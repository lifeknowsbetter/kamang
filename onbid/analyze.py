"""검색 원자료 → 상세분석 후보 선별 → 권리분석 등급·순위 → 리포트 초안 데이터.

규칙은 사용자 지침을 그대로 옮긴 것이다(README 참고). 사진 판단처럼 사람이 봐야 하는 부분은
리포트를 쓰는 모델이 media 폴더를 보고 채운다.
"""
import datetime
import re

from . import carfilter
from . import config as C
from . import geo
from . import subsidy

LINK_KEYS = ("cltrScrnGrpCd", "cltrPrptDivCd", "onbidCltrno", "onbidPbancNo", "pbctNo", "pbctCdtnNo")


def link(row):
    q = "&".join(f"{k}={row[k]}" for k in LINK_KEYS)
    return f"https://www.onbid.co.kr/op/cltrpbancinf/cltrdtl/CltrDtlController/mvmnCltrDtl.do?{q}"


def dedupe(rows):
    """물건관리번호별로 묶는다. 대표 행은 가장 이른 회차(입찰 시작이 빠른 것)."""
    g = {}
    for r in sorted(rows, key=lambda x: x.get("pbctBegnDtm") or ""):
        g.setdefault(r["scrnIndctCltrMngNo"], []).append(r)
    return {k: {"row": v[0], "rounds": v} for k, v in g.items()}


def sido(row):
    s = (row.get("sidoSgkEmd") or row.get("onbidCltrNm") or "").split(" ")
    return s[0] if s else ""


def land_class(row):
    sub = (row.get("ctgrFullNm") or "").split(" / ")[-1]
    if sub in C.FARMLAND:
        return "농지", sub
    if sub in C.LAND_PREFERRED:
        return "우선", sub
    if (row.get("ctgrFullNm") or "").startswith("토지"):
        return "기타토지", sub
    return "건물", sub


# ───────────────────────── 1차 선별(상세 화면 열기 전) ─────────────────────────

def _dist(row):
    d, _ = geo.dist_from_sanbon(row.get("sidoSgkEmd"))
    return d


def _cls_order(cls):
    return {"우선": 0, "기타토지": 1, "건물": 1, "농지": 3}.get(cls, 2)


def select_A(search):
    """Track A — 지분 부동산(압류재산). 전국에서 고르되 산본에 가까운 순으로 상세를 연다."""
    g = dedupe(search["rows"])
    share = {k: v for k, v in g.items() if v["row"].get("alcYn") == "Y"}
    stats = {"검색행": len(search["rows"]), "부동산물건": len(g), "지분물건": len(share)}
    by_type, pool = {}, []
    for k, v in share.items():
        r = v["row"]
        by_type[r["scrnPrptDvsnNm"]] = by_type.get(r["scrnPrptDvsnNm"], 0) + 1
        if r["scrnPrptDvsnNm"] != "압류재산":
            continue
        cls, sub = land_class(r)
        v.update(land_class=cls, dist=_dist(r))
        pool.append(v)
    stats["재산유형별"] = by_type
    stats["압류재산_지분"] = len(pool)
    stats["산본_50km_이내"] = sum(1 for v in pool if v["dist"] is not None and v["dist"] <= C.NEAR_KM)
    stats["지목별"] = {}
    for v in pool:
        sub = land_class(v["row"])[1]
        stats["지목별"][sub] = stats["지목별"].get(sub, 0) + 1
    non_farm = [v for v in pool if v["land_class"] != "농지"]
    non_farm.sort(key=lambda v: (geo.band_idx(v["dist"]), _cls_order(v["land_class"]), v["row"].get("lowstBidPrc") or 0))
    detail = non_farm[:C.DETAIL_A]
    stats["상세분석"] = len(detail)
    return detail, stats


def select_D(search):
    """Track D — 지분이 아닌 소액 부동산(단독 토지·건물 호실, 압류재산). 같은 건물의 비슷한 호실은 하나로 묶는다."""
    g = dedupe(search["rows"])
    solo = {k: v for k, v in g.items() if v["row"].get("alcYn") != "Y"}
    stats = {"단독·미표시": len(solo)}
    pool, seen = [], {}
    for k, v in sorted(solo.items(), key=lambda kv: kv[1]["row"].get("lowstBidPrc") or 0):
        r = v["row"]
        if r["scrnPrptDvsnNm"] != "압류재산":
            continue
        cls, sub = land_class(r)
        v.update(land_class=cls, dist=_dist(r), dup=0)
        key = ((r.get("onbidCltrNm") or "")[:22], r.get("lowstBidPrc"))
        if key in seen:                       # 같은 건물·같은 가격의 다른 호실
            seen[key]["dup"] += 1
            continue
        seen[key] = v
        pool.append(v)
    stats["압류재산"] = len(pool)
    stats["산본_50km_이내"] = sum(1 for v in pool if v["dist"] is not None and v["dist"] <= C.NEAR_KM)
    stats["유형별"] = {"토지": sum(1 for v in pool if v["land_class"] in ("우선", "기타토지")),
                    "건물": sum(1 for v in pool if v["land_class"] == "건물"), "농지(제외)": sum(1 for v in pool if v["land_class"] == "농지")}
    live = [v for v in pool if v["land_class"] != "농지"]
    key = lambda v: (geo.band_idx(v["dist"]), _cls_order(v["land_class"]), v["row"].get("lowstBidPrc") or 0)
    bld = sorted([v for v in live if v["land_class"] == "건물"], key=key)[:C.DETAIL_D // 2]
    lnd = sorted([v for v in live if v["land_class"] != "건물"], key=key)[:C.DETAIL_D - len(bld)]
    detail = bld + lnd
    stats["상세분석"] = len(detail)
    return detail, stats


def _mvast_score(row):
    nm = row.get("onbidCltrNm") or ""
    s = sum(w for pat, w in C.MVAST_SCORE if re.search(pat, nm, re.I))
    if row.get("ctgrFullNm", "").startswith("시계/귀금속") and s == 0:
        s = 1
    price, appr = row.get("lowstBidPrc") or 0, row.get("cltrApslEvlAvgAmt") or 0
    if appr and price < appr:
        s += min(2, (appr - price) / appr * 4)       # 유찰로 감정가보다 싸진 만큼 가산
    if price < 50_000:
        s -= 1                                        # 소액 액세서리는 수고 대비 남는 게 적다
    # 자차가 없으니 직접 가지러 갈 수 있는 곳이 낫다
    d = _dist(row)
    s += 2 if d is not None and d <= C.NEAR_KM else 1 if d is not None and d <= 100 else -1 if d is not None and d >= 200 else 0
    return s


def select_B(search):
    """Track B — 동산. 귀금속·시계·카메라·컴퓨터·명품 가방 + 감정가 대비 70% 이하로 내려온 장비류.
    유가증권·특허·회원권 같은 권리형 자산과 폐기물·식료품은 기본 제외한다(되팔 상대·자격 문제)."""
    g = dedupe(search["rows"])
    hits, skipped, seen = [], {}, set()
    for k, v in g.items():
        r = v["row"]
        nm = r.get("onbidCltrNm") or ""
        cat = r.get("ctgrFullNm") or ""
        top = cat.split(" / ")[0]
        if top in C.MVAST_SKIP_CATS:
            skipped[top] = skipped.get(top, 0) + 1
            continue
        price, appr = r.get("lowstBidPrc") or 0, r.get("cltrApslEvlAvgAmt") or 0
        cat_hit = any(h in cat for h in C.MVAST_CATEGORY_ONLY)
        kw_hit = re.search(C.MVAST_KEYWORDS, nm, re.I) and not re.search(C.MVAST_EXCLUDE, nm)
        bag_hit = "가방" in cat and re.search(C.MVAST_BRAND_BAG, nm)
        equip_hit = top in C.MVAST_EQUIP_CATS and appr and price <= appr * 0.7 and price >= 200_000
        if not ((cat_hit and not re.search(C.MVAST_EXCLUDE, nm)) or kw_hit or bag_hit or equip_hit):
            continue
        key = (nm[:24], price)
        if key in seen:                       # 같은 이름·같은 가격의 묶음 행
            continue
        seen.add(key)
        v["score"] = _mvast_score(r) + (1 if equip_hit else 0)
        v["dist"] = _dist(r)
        hits.append(v)
    hits.sort(key=lambda v: -v["score"])
    per_org, spread, rest = {}, [], []
    for v in hits:
        o = v["row"].get("regOrgNm", "").strip()
        per_org[o] = per_org.get(o, 0) + 1
        (spread if per_org[o] <= C.MAX_PER_ORG_B else rest).append(v)
    hits = spread + rest
    stats = {"검색행": len(search["rows"]), "동산물건": len(g), "후보": len(hits), "권리형·폐기물 등 제외": skipped,
             "산본_50km_이내": sum(1 for v in hits if v["dist"] is not None and v["dist"] <= C.NEAR_KM),
             "공고기관별": {}, "상세분석": min(len(hits), C.DETAIL_B)}
    for v in hits:
        o = v["row"]["regOrgNm"].strip()
        stats["공고기관별"][o] = stats["공고기관별"].get(o, 0) + 1
    return hits[:C.DETAIL_B], stats, hits


FUELS = (("가솔린+전기", "하이브리드"), ("하이브리드", "하이브리드"), ("경유", "경유"), ("디젤", "경유"),
         ("휘발유", "휘발유"), ("가솔린", "휘발유"), ("LPG", "LPG"), ("수소", "수소"), ("전기", "전기"))


def car_fuel(row, kv=None):
    """상세 화면 연료 → 목록 연료코드 → 배기량 문구 → 물건명 순으로 믿는다."""
    for s in ((kv or {}).get("연료"), row.get("carFuelKindCd"), row.get("fuelContDsvlmNm"), row.get("onbidCltrNm")):
        for k, v in FUELS:
            if s and k in s:
                return v
    return "미상"


def car_year(row, kv=None):
    for s in ((kv or {}).get("연식"), row.get("nrtpNm"), row.get("onbidCltrNm")):
        m = re.search(r"(19[89]\d|20[0-3]\d)", s or "")
        if m:
            return int(m.group(1))
    return None


def _car_prescore(v):
    r = v["row"]
    fuel, year, price = car_fuel(r), car_year(r), r.get("lowstBidPrc") or 0
    nm = r.get("onbidCltrNm") or ""
    s = 0.0
    if fuel == "경유" and year and year <= 2009:
        s += 6                                    # 조기폐차 지원 대상 가능성(4·5등급)
    elif fuel == "경유" and year and year <= 2011:
        s += 3                                    # 연식 경계 — 등급 조회로 확인 필요
    if "폐차" in nm:
        s -= 5                                    # 폐차 조건부 매각은 되팔기·지원금 모두 불가
    if r.get("cptnMtdNm") == "제한경쟁":
        s -= 1
    if price <= 3_000_000:
        s += 1
    if not (r.get("ctgrFullNm") or "").startswith("자동차"):
        s -= 3                                    # 지게차·굴삭기 등 중기
    return s


def select_C(search):
    """Track C — 자동차. 구조적으로 실효 없는 물건(carfilter)은 상세 전에 빼고, 남은 것을 산본 가까운 순으로 본다."""
    g = dedupe(search["rows"])
    cars, dropped = [], {}
    for v in g.values():
        r = v["row"]
        d = _dist(r)
        a = carfilter.assess(r.get("onbidCltrNm"), r.get("ctgrFullNm"), r.get("lowstBidPrc") or 0, r.get("sidoEmd"), d)
        v.update(prescore=_car_prescore(v), dist=d, assess=a)
        if a["verdict"] == "제외":
            key = a["reasons"][0].split("(")[0].strip()
            key = "최저가 300만 미만" if key.startswith("최저가 300만") else "산본에서 200km 이상" if key.startswith("산본에서") else key
            dropped[key] = dropped.get(key, 0) + 1
            continue
        cars.append(v)
    cars.sort(key=lambda v: (geo.band_idx(v["dist"]), -v["prescore"], v["row"].get("lowstBidPrc") or 0))
    stats = {"검색행": len(search["rows"]), "차량": len(g), "실효없음_제외": dropped, "남은_차량": len(cars), "연료별": {},
             "상세분석": min(len(cars), C.DETAIL_C)}
    for v in cars:
        f = car_fuel(v["row"])
        stats["연료별"][f] = stats["연료별"].get(f, 0) + 1
    stats["경유_2009년이전"] = sum(1 for v in cars if car_fuel(v["row"]) == "경유" and (car_year(v["row"]) or 9999) <= 2009)
    stats["폐차조건부"] = sum(1 for v in g.values() if "폐차" in (v["row"].get("onbidCltrNm") or ""))
    return cars[:C.DETAIL_C], stats, cars


# ───────────────────────── 상세 분석(상세 화면 파싱 후) ─────────────────────────

CORP = re.compile(r"\(주\)|주식|\(유\)|\(사\)|\(재\)|법인|조합|공사|공단|종중|교회|^국|시청|군청|구청|도청|회사")
FAVOR = ("아파트 옹벽", "옹벽", "통행로", "경계 확인", "경계확인", "현황도로", "현황 도로", "도로로 이용", "침범", "담장")


def _share_ratio(note):
    m = re.search(r"([\d.]+)\s*분의\s*([\d.]+)", note or "")
    if m:
        den, num = float(m.group(1)), float(m.group(2))
        return num / den if den else None
    return None


def next_round(sched, current_no):
    """현재 회차 다음에 이미 등록된 회차. 없으면 None."""
    after = False
    for s in sched:
        if after:
            return s
        if s["no"].split("/")[0] == (current_no or "").split("/")[0]:
            after = True
    return None


def grade_A(item, today):
    """사용자 3단계 리스크 규칙. 반환: (등급, 근거 dict)."""
    reg = item.get("reg") or []
    co = [x for x in reg if len(x) >= 4 and x[1] == "공유자"]
    cutoff = (today - datetime.timedelta(days=365 * C.LONG_TERM_YEARS)).isoformat()
    dates = [x[3] for x in co if re.match(r"\d{4}-", x[3])]
    old = [d for d in dates if d <= cutoff]
    other_rights = [x for x in reg if len(x) >= 4 and x[1] not in ("공유자", "위임기관", "압류", "가압류", "교부청구", "물건지지방자치단체")]
    st = item.get("statement") or {}
    keep, surf = st.get("keep") or [], st.get("surface") or []
    occ_rows, lease_rows = st.get("occupancy_rows") or [], st.get("lease_rows") or []
    occ, lease = item.get("occ_cnt") or 0, item.get("lease_cnt") or 0
    farm = item["land_class"] == "농지"
    basis = {
        "공유자수": len(co), "공유자_법인": sum(1 for x in co if CORP.search(x[2])),
        "공유자_등록일": sorted(set(x[3] for x in co)), "공유자_장기": bool(dates) and len(old) == len(co),
        "공유자_등록일미상": len(co) - len(dates), "기타등기권리": ["/".join(x[1:4]) for x in other_rights],
        "인수권리": keep, "지상권개요": surf, "점유": occ, "임대차": lease,
        "명세서점유행": occ_rows, "명세서임차행": lease_rows, "명세서공개": st.get("available", False),
        "등기행수": item.get("reg_cnt"),
    }
    if farm or keep or surf or occ or lease or occ_rows or lease_rows:
        g = "높음"
    elif item.get("reg_cnt") in (0, None):
        g = "중간"           # 등기 주요정보 미제공 — 지분물건인데 공유자를 확인할 수 없다
        basis["정보부족"] = True
    elif not co or basis["공유자_장기"]:
        g = "낮음"
    else:
        g = "중간"
    return g, basis


def build_A(items, today):
    out = []
    for it in items:
        g, b = grade_A(it, today)
        notes = it.get("notes") or []
        text = " ".join(notes + (it.get("statement") or {}).get("note", []) + [it["kv"].get("이용상태", ""), it["kv"].get("위치 및 주위환경", "")])
        sched = it.get("schedule") or []
        cur = next((s for s in sched if s["no"].split("/")[0] == (it.get("round") or "").split("/")[0]), None)
        nxt = next_round(sched, it.get("round"))
        ratio = _share_ratio((it.get("area") or {}).get("share_note"))
        # 감정평가서 '이용상태'가 자연림·임야 상태면 그냥 산일 가능성이 크다(사진 판단 전 1차 힌트)
        natural = bool(re.search(r"자연림|자염림|임야\s*상태|임야상태|토지임야|잡목|산림|^\s*임야\.?\s*$",
                                 it["kv"].get("이용상태", "")))
        out.append({
            **it, "grade": g, "basis": b, "natural_hint": natural,
            "favor_flags": [f for f in FAVOR if f in text],
            "share_ratio": ratio,
            "current_round": cur, "next_round": nxt,
            "dist": _dist(it["row"]) if it.get("row") else None,
        })
        out[-1]["exit"] = exit_numbers(out[-1])
    # 위험 높음은 뒤로 → 산본에서 가까운 구간 → 리스크 → 실제 이용 중인 땅 먼저 → 지목 → 가격
    return sort_A(out)


def _text_of(it):
    st = it.get("statement") or {}
    kv = it.get("kv") or {}
    parts = (it.get("notes") or []) + (st.get("note") or []) + (st.get("keep") or []) + (st.get("surface") or [])
    parts += [kv.get(k, "") for k in ("이용 현황", "이용상태", "기타사항", "위치 및 주위환경")]
    return " ".join(parts)


def _deposits(it):
    """임대차 신고 행에서 보증금 숫자(원)를 모은다."""
    out = []
    for r in it.get("lease") or []:
        if r and r[0] == "임차인":
            for c in r[2:4]:
                m = re.fullmatch(r"[\d,]{4,}", c or "")
                if m:
                    out.append(int(c.replace(",", "")))
                    break
    return out


def flags_D(it):
    """단독 토지·건물의 위험 신호. [(심각도 'R'위험/'Y'확인/'G'참고, 설명)]."""
    t = _text_of(it)
    st = it.get("statement") or {}
    f = []
    dep = _deposits(it)
    movein = [r for r in (it.get("occ") or []) if r and r[0] == "전입세대주"]
    if dep:
        f.append(("R", f"임차인 신고(보증금 합계 {sum(dep):,}원) — 대항력 있으면 낙찰자가 인수"))
    if movein:
        f.append(("R", f"전입세대 {len(movein)}명(명도·인수 확인)"))
    if not dep and not movein and (st.get("occupancy_rows") or st.get("lease_rows")):
        f.append(("R", "명세서에 점유·임차 기재"))
    if st.get("keep"):
        f.append(("R", "명세서 인수권리: " + " / ".join(st["keep"])[:80]))
    if st.get("surface"):
        f.append(("R", "지상권 개요 기재"))
    for pat, msg, sev in ((r"건물만의 매각|건물만 매각", "건물만 매각(대지는 제3자 소유)", "R"), (r"대지권미등기|대지사용권", "대지권 문제", "R"),
                          (r"유치권", "유치권 신고", "R"), (r"법정지상권", "법정지상권", "R"), (r"가처분|가등기|전세권", "가처분·가등기·전세권", "R"),
                          (r"위반건축물", "위반건축물", "Y"), (r"관리비", "관리비 체납 확인 필요", "Y"), (NOT_LANDLOCKED, "맹지", "Y"), (GRAVE_REAL, "분묘", "Y"), (GRAVE_MAYBE, "분묘 소재 가능성(유의 문구)", "G"),
                          (r"농지취득자격", "농지취득자격증명 필요", "Y"), (r"인수부담", "매수인 인수부담 가능 문구", "Y"), (r"신탁", "신탁 압류재산", "Y"),
                          (r"구분점포.{0,20}요건|경계표지", "구분점포 요건 미비 문구", "Y"), (r"제시외", "제시외 건물·수목", "Y"),
                          (r"현황\s*[\"“]?(도로|구거)", "현황이 도로·구거(사용수익 제한)", "Y"), (r"지분", "지분 문구", "Y")):
        if re.search(pat, t):
            f.append((sev, msg))
    for r in it.get("reg") or []:
        if r and r[1] in ("가등기", "가처분", "전세권", "지상권", "임차권등기", "지역권"):
            f.append(("R", f"등기: {r[1]}"))
    if (it.get("kv") or {}).get("이용상태", "") and re.search(r"이용중|영업|매장", (it.get("kv") or {}).get("이용상태", "")) and not dep:
        f.append(("Y", "사용 중으로 기재 — 점유자·임차 여부 확인"))
    if not st.get("available"):
        f.append(("Y", "공매재산명세서 미공개(입찰 임박 시 재확인)"))
    seen, out = set(), []
    for sev, msg in f:
        if msg not in seen:
            seen.add(msg)
            out.append((sev, msg))
    return out


def build_D(items, today):
    out = []
    for it in items:
        fl = flags_D(it)
        grade = "높음" if any(s == "R" for s, _ in fl) else "중간" if any(s == "Y" for s, _ in fl) else "낮음"
        sched = it.get("schedule") or []
        cur = next((s for s in sched if s["no"].split("/")[0] == (it.get("round") or "").split("/")[0]), None)
        appr, price = it.get("appraisal") or 0, it.get("price") or 0
        row = it.get("row") or {}
        dep = _deposits(it)
        out.append({**it, "grade": grade, "risk_flags": fl, "dist": _dist(row), "current_round": cur,
                    "next_round": next_round(sched, it.get("round")),
                    "ratio": round(price / appr * 100) if appr and price else None,
                    "fails_n": int(row.get("uscbdCnt") or 0), "deposit_sum": sum(dep) if dep else 0,
                    "dup": it.get("dup", 0)})
    order = {"낮음": 0, "중간": 1, "높음": 2}
    out.sort(key=lambda x: (x["grade"] == "높음", geo.band_idx(x["dist"]), order[x["grade"]], x.get("price") or 0))
    return out


GRAVE_REAL = r"분묘(?![^.\n]{0,14}가능성)(?![^.\n]{0,6}없)"
GRAVE_MAYBE = r"분묘[^.\n]{0,14}가능성"
NOT_LANDLOCKED = r"맹지(?!\s*(가\s*)?(아니|아님))"
APPR_SIGNALS = (
    (NOT_LANDLOCKED, "맹지", "R"),
    (r"급경사", "급경사", "Y"),
    (r"(차량|자동차)\s*(접근|진입|출입)[^.\n]{0,8}(불가|곤란|어려)", "차량 접근 불가", "Y"),
    (r"(지목은|지목상)[^\n]{0,30}현황은?\s*[「\"“'\[]?\s*(전|답|과수원|밭)", "지목은 대지 등이나 현황은 전·답(경작 중)", "F"),
    (GRAVE_REAL, "분묘", "Y"),
    (GRAVE_MAYBE, "분묘 소재 가능성(유의 문구)", "I"),
    (r"제시외", "제시외 건물·수목", "Y"),
)
# 인근 사례 지가표 줄('… 맹지 26,700')은 이 물건의 상태가 아니다
APPR_SKIP = re.compile(r"기타규제|접근성\s*및|접근조건|가로조건|접근\s*환경|획지|격차율|요인비교|\d{2,3}(,\d{3})*\s*$")


def appraisal_signals(path):
    """감정평가서 본문(appraisal.txt)에서 맹지·급경사·접근불가·현황 농지·분묘 줄을 뽑는다.
    루틴 모델이 사진만 보고 지형을 잘못 쓰는 일(2026-10-11 검증에서 확인)을 막으려고 코드가 먼저 보여 준다."""
    try:
        text = open(path, encoding="utf-8", errors="ignore").read()
    except (OSError, TypeError):
        return [], []
    flags, lines, seen = [], [], set()
    for ln in text.split("\n"):
        t = re.sub(r"\s+", " ", ln).strip()
        if not t or APPR_SKIP.search(t):
            continue
        for pat, msg, sev in APPR_SIGNALS:
            if re.search(pat, t):
                if msg not in seen:
                    seen.add(msg)
                    flags.append((sev, msg))
                if len(lines) < 8 and t not in lines:
                    lines.append(t[:170])
    return flags, lines


def exit_numbers(it):
    """KNOWLEDGE 6-A 숫자를 코드로 계산해 모델이 어림하다 틀리지 않게 한다. 감정가는 이미 지분 감정가라 지분비율을 다시 곱하지 않는다.
    출구 상한은 시세 대신 감정가를 넣은 '위쪽 한계'다(감정평가서의 낮은 지가 자료가 있으면 더 낮아질 수 있다)."""
    appr, price = it.get("appraisal") or 0, it.get("price") or 0
    out = {"budget_cap": int((C.BUDGET_RLST - 50_000) / 1.046)}
    if appr:
        out["exit_cap"] = int((appr * 0.7 - 50_000 - 30_000 - 300_000) / 1.046)
    if appr and price:
        out["loss"] = int(price * 1.046 + 50_000 - appr * 0.2)          # 못 팔고 지분 매입업체에 감정가의 20%로 넘길 때
    cap = out.get("exit_cap")
    if cap and cap > 0:
        sched = it.get("schedule") or []
        cur = (it.get("round") or "").split("/")[0]
        after, first = False, None
        for r in sched:
            if r["no"].split("/")[0] == cur:
                after = True
            if after and r["price"] <= cap:
                first = r
                break
        out["first_under"] = first
    return out


def apply_appraisal(it, kind):
    """사진·감정평가서를 받은 뒤 감정평가서 본문 신호를 등급과 위험 신호에 반영한다. kind: 'A'(지분) | 'D'(단독).
    신호 심각도: R 위험 / Y 확인 / I 참고(일반 유의 문구, 등급 영향 없음) / F 현황 농지(위험 처리)."""
    path = ((it.get("media") or {}).get("appraisal") or {}).get("text")
    flags, lines = appraisal_signals(path) if path else ([], [])
    it["appr_excerpt"] = lines
    if kind == "A":
        fl = [("R" if sv == "F" else sv, m) for sv, m in flags]
        it["appr_flags"] = fl
        if any(sv == "R" for sv, _ in fl):
            it["grade"] = "높음"
        elif any(sv == "Y" for sv, _ in fl) and it.get("grade") == "낮음":
            it["grade"] = "중간"
        it["bad_exit"] = any(m in ("맹지", "분묘") for _, m in fl) or any(
            re.search(NOT_LANDLOCKED + "|" + GRAVE_REAL, f) for f in (it.get("notes") or []))
    else:
        rf = list(it.get("risk_flags") or [])
        have = {m for _, m in rf}
        for sv, m in flags:
            sv = "R" if sv == "F" else "Y" if (m == "맹지") else sv     # 단독 소유 맹지는 인접지주에게 팔 길이 있어 확인 수준
            if sv == "I":
                sv = "G"
            if "감정평가서: " + m not in have and m not in have:
                rf.append((sv, "감정평가서: " + m))
        it["risk_flags"] = rf
        it["grade"] = "높음" if any(sv == "R" for sv, _ in rf) else "중간" if any(sv == "Y" for sv, _ in rf) else "낮음"
    return it


def sort_A(items):
    order = {"낮음": 0, "중간": 1, "높음": 2}
    cls = {"우선": 0, "기타토지": 1, "농지": 2, "건물": 3}
    return sorted(items, key=lambda x: (x["grade"] == "높음", geo.band_idx(x.get("dist")), order[x["grade"]], x.get("natural_hint", False),
                                        cls.get(x.get("land_class"), 9), x.get("price") or 0))


def sort_D(items):
    order = {"낮음": 0, "중간": 1, "높음": 2}
    return sorted(items, key=lambda x: (x["grade"] == "높음", geo.band_idx(x.get("dist")), order[x["grade"]], x.get("price") or 0))


def display_name_B(it):
    """동산 표시 이름. 한국자산관리공사 물건은 이름 앞에 보관 주소가 붙어 있어 떼어 낸다."""
    kv = it.get("kv", {})
    good = lambda v: v and v not in ("-", "미상")
    name = kv.get("물품명") if good(kv.get("물품명")) else (it.get("name") or "")
    m = re.search(r"보관\s+(.+)$", name)
    if m:
        name = m.group(1)
    name = re.sub(r"\S+(국세청|세무서|시청|군청|구청)\s*(\S+\s*)?보관\s*", "", name)   # 묶음 안의 반복된 보관 문구
    model = kv.get("모델명")
    if good(model) and model not in name:
        name = f"{model} {name}"
    return name.strip()


def build_B(items):
    out = []
    for it in items:
        kv = it.get("kv", {})
        text = " ".join([it.get("name") or "", kv.get("물품명", ""), kv.get("기타사항", ""), " ".join(it.get("notes") or [])])
        flags = []
        if re.search(r"배우자|부부공유", text):
            flags.append("배우자 우선매수 시 매각결정 취소 가능")
        if re.search(r"시간정지|시계정지|작동 ?불|고장|파손|수선|정지", text):
            flags.append("작동/상태 이상 표기")
        if re.search(r"보증서\s*(없|무)|케이스\s*(없|무)", text):
            flags.append("보증서·케이스 없음")
        if "일괄" in text or sum(int(n) for n in re.findall(r"(\d+)\s*점", text)) > 1:
            flags.append("여러 점 일괄")
        if re.search(C.MVAST_BRAND_BAG + r"|롤렉스|오메가|위블로|태그호이어|IWC|파텍|예거", text):
            flags.append("명품: 정품 감정서·위조품 보상 조항이 공고에 없으면 입찰 금지(KNOWLEDGE 2-11)")
        place = kv.get("보관장소상세") or kv.get("지번") or ""
        if place in ("", "-"):
            m = re.search(r"^(.*?보관)", it.get("name") or "")
            place = m.group(1) if m else ""
        appr, price = it.get("appraisal") or 0, it.get("price") or 0
        out.append({**it, "flags": flags, "place": place, "display": display_name_B(it),
                    "discount": round(1 - price / appr, 3) if appr and price else None})
    return out


def build_C(items):
    out = []
    for it in items:
        kv = it.get("kv", {})
        row = it.get("row", {})
        fuel = car_fuel(row, kv)
        year = car_year(row, kv)
        km = None
        m = re.search(r"([\d,]+)\s*km", kv.get("주행거리") or row.get("drvDstcNm") or "", re.I)
        if m:
            km = int(m.group(1).replace(",", ""))
        cc = None
        m = re.search(r"([\d,]+)\s*cc", kv.get("배기량/배터리") or row.get("fuelContDsvlmNm") or "", re.I)
        if m:
            cc = int(m.group(1).replace(",", ""))
        own = " ".join([it.get("name") or "", kv.get("기타사항", ""), " ".join(it.get("notes") or [])])
        notice = " ".join(it.get("notice_head") or [])
        text = own + " " + notice
        flags = []
        if "폐차" in (it.get("name") or "") or re.search(r"폐차\s*조건", text):
            flags.append("폐차 조건부 매각(되팔기·지원금 불가)")
        # 물건 자체 설명에서는 '견인'까지, 공고문 본문에서는 상투 문구(견인비 낙찰자 부담 등)를 피해 고장 표현만 본다
        warn = (re.search(r"[^.。\n]{0,60}(시동\s*(불|안|이 꺼)|운행\s*불|견인\s*필요|엔진\s*고장|모터.{0,10}고장|부동차|수리견적)[^.。\n]{0,60}", own)
                or re.search(r"[^.。\n]{0,60}(시동\s*(불가|안\s*됨|이 꺼)|운행\s*불가|엔진\s*고장|모터.{0,10}고장|부동차|수리견적)[^.。\n]{0,60}", notice))
        if warn:
            flags.append(f"상태 경고 원문: 「{warn.group(0).strip()}」")
        if row.get("cptnMtdNm") == "제한경쟁":
            flags.append("제한경쟁(참가자격 확인 필요)")
        if re.search(r"번호판\s*(없|무|영치)|열쇠\s*(없|무)|키\s*(없|무)", text):
            flags.append("번호판/열쇠 없음")
        sub = subsidy.estimate(fuel=fuel, year=year, cc=cc, category=row.get("ctgrFullNm") or "", km=km,
                               flags=flags, name=it.get("name") or "",
                               value_proxy=it.get("appraisal") or it.get("price"))
        d = _dist(row)
        out.append({**it, "fuel": fuel, "year": year, "km": km, "cc": cc, "flags": flags, "subsidy": sub, "dist": d,
                    "assess": carfilter.assess(row.get("onbidCltrNm"), row.get("ctgrFullNm"), it.get("price") or row.get("lowstBidPrc") or 0,
                                               row.get("sidoEmd"), d),
                    "place": kv.get("보관장소상세") or kv.get("지번") or row.get("sidoSgkEmd"),
                    "plate": kv.get("차량번호")})
    def key(x):
        s = x["subsidy"]
        row = x.get("row", {})
        blocked = any("폐차 조건부" in f for f in x["flags"])
        warn = any(f.startswith("상태 경고") for f in x["flags"])
        subsidy_cand = s.get("eligible") in ("가능", "확인필요")
        cat = row.get("ctgrFullNm") or ""
        passenger = any(k in cat for k in ("승용", "SUV", "승합"))
        restricted = row.get("cptnMtdNm") == "제한경쟁"
        return (blocked, geo.band_idx(x.get("dist")), not subsidy_cand, warn, restricted, not passenger, x.get("price") or 0)
    out.sort(key=key)
    return out
