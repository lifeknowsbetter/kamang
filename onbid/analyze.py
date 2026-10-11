"""검색 원자료 → 상세분석 후보 선별 → 권리분석 등급·순위 → 리포트 초안 데이터.

규칙은 사용자 지침을 그대로 옮긴 것이다(README 참고). 사진 판단처럼 사람이 봐야 하는 부분은
리포트를 쓰는 모델이 media 폴더를 보고 채운다.
"""
import datetime
import re

from . import config as C
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

def select_A(search):
    g = dedupe(search["rows"])
    share = {k: v for k, v in g.items() if v["row"].get("alcYn") == "Y"}
    stats = {"검색행": len(search["rows"]), "지분물건": len(share)}
    by_type, in_region, pool = {}, {}, []
    for k, v in share.items():
        r = v["row"]
        by_type[r["scrnPrptDvsnNm"]] = by_type.get(r["scrnPrptDvsnNm"], 0) + 1
        if sido(r) not in C.RLST_REGIONS:
            continue
        in_region[k] = v
        if r["scrnPrptDvsnNm"] != "압류재산":
            continue
        cls, _ = land_class(r)
        v["land_class"] = cls
        pool.append(v)
    stats["재산유형별"] = by_type
    stats["권역내(수도권·강원·충청)"] = len(in_region)
    stats["권역내_압류재산"] = len(pool)
    stats["권역내_압류재산_지목별"] = {}
    for v in pool:
        sub = land_class(v["row"])[1]
        stats["권역내_압류재산_지목별"][sub] = stats["권역내_압류재산_지목별"].get(sub, 0) + 1
    non_farm = [v for v in pool if v["land_class"] in ("우선", "기타토지")]
    detail = non_farm if len(non_farm) >= C.TOP_A * 2 else non_farm + [v for v in pool if v["land_class"] == "농지"]
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
    return s


def select_B(search):
    g = dedupe(search["rows"])
    hits = []
    for k, v in g.items():
        r = v["row"]
        nm = r.get("onbidCltrNm") or ""
        cat_hit = any(h in (r.get("ctgrFullNm") or "") for h in C.MVAST_CATEGORY_ONLY)
        kw_hit = re.search(C.MVAST_KEYWORDS, nm, re.I) and not re.search(C.MVAST_EXCLUDE, nm)
        if (cat_hit and not re.search(C.MVAST_EXCLUDE, nm)) or kw_hit:
            v["score"] = _mvast_score(r)
            hits.append(v)
    hits.sort(key=lambda v: -v["score"])
    stats = {"검색행": len(search["rows"]), "동산물건": len(g), "키워드충족": len(hits),
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
    g = dedupe(search["rows"])
    cars = list(g.values())
    for v in cars:
        v["prescore"] = _car_prescore(v)
    cars.sort(key=lambda v: (-v["prescore"], v["row"].get("lowstBidPrc") or 0))
    stats = {"검색행": len(search["rows"]), "차량": len(cars), "연료별": {}, "상세분석": min(len(cars), C.DETAIL_C)}
    for v in cars:
        f = car_fuel(v["row"])
        stats["연료별"][f] = stats["연료별"].get(f, 0) + 1
    stats["경유_2009년이전"] = sum(1 for v in cars if car_fuel(v["row"]) == "경유" and (car_year(v["row"]) or 9999) <= 2009)
    stats["폐차조건부"] = sum(1 for v in cars if "폐차" in (v["row"].get("onbidCltrNm") or ""))
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
            "budget_entry": next((s for s in sched if s["price"] <= C.BUDGET_RLST), None),
        })
    order = {"낮음": 0, "중간": 1, "높음": 2}
    cls = {"우선": 0, "기타토지": 1, "농지": 2, "건물": 3}
    # 리스크 → (같은 등급 안에서) 실제 이용 중인 땅 먼저 → 지목 → 가격
    out.sort(key=lambda x: (order[x["grade"]], x["natural_hint"], cls.get(x["land_class"], 9), x.get("price") or 0))
    return out


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
        out.append({**it, "fuel": fuel, "year": year, "km": km, "cc": cc, "flags": flags, "subsidy": sub,
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
        near = sido(row) in C.RLST_REGIONS
        restricted = row.get("cptnMtdNm") == "제한경쟁"
        return (blocked, not subsidy_cand, warn, restricted, not passenger, not near, x.get("price") or 0)
    out.sort(key=key)
    return out
