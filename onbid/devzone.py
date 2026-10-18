"""개발 사업 연관 표시.

온비드 부동산 물건의 소재지(시도·시군구·읍면동 문자열)를 onbid/data/devzones.json의 개발 사업(반도체·대기업 투자,
공공택지·신도시, 산업단지, 교통, 신공항 등)과 맞춰 리포트에 '이 물건이 어떤 개발 사업과 가까운가'를 사실로만 보여 준다.

원칙
- 개발 연관은 위치가 가깝다는 사실이지 수익이 아니다. 개발이익은 시세와 감정가에 이미 반영됐거나(발표 선반영),
  공익사업 보상에서는 배제된다. 순위 보조 신호로만 쓰고 위험 등급은 바꾸지 않는다.
- 온비드 행에는 좌표가 없고 읍면동 문자열만 있다. 그래서 단계 1(읍면동 일치) → 2(같은 시·구인데 사업 위치가 읍면동까지 특정되지 않음)
  → 3(같은 시·구 안 다른 읍면동, 인접 시군구, 노선·광역 사업 통과)으로 맞춘다. 사업 읍면동이 특정돼 있는데 물건이 다른 읍면동이면
  같은 시라도 3단계다(큰 시에서 '같은 시'는 가깝다는 뜻이 아니다). 구역 경계는 지번 단위로 알 수 없으니 '구역 내 가능성'은 고시 도면(토지이음)으로 확인하라고 안내한다.
- 모든 항목에는 출처 URL과 기준일이 있어야 한다(validate가 검사). 데이터가 낡으면(기준일 1년 초과) 경고한다.

  python3 -m onbid.devzone validate                 # 데이터 검사
  python3 -m onbid.devzone match "경기도 용인시 처인구 원삼면"
  python3 -m onbid.devzone scan <search_A.json>     # 검색 결과 전체에서 연관 건수 집계
"""
import datetime
import json
import os
import re
import sys

from . import geo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("ONBID_DEVZONES") or os.path.join(HERE, "data", "devzones.json")

KINDS = ("반도체·첨단산업", "대기업 투자·신설 부지", "산업단지", "신도시·공공주택지구", "도시개발·재정비", "교통", "신공항·항만", "기타")
STAGES = ("계획", "구역지정", "승인·착공", "조성·건설중", "준공·가동", "보류·취소")
STAGE_RANK = {"승인·착공": 0, "조성·건설중": 0, "구역지정": 1, "준공·가동": 1, "계획": 2, "보류·취소": 3}
TIER_WHY = {1: "읍면동 일치", 2: "같은 시·구(읍면동 미특정)", 3: "같은 시·구 다른 읍면동 · 인접 시군구 · 노선 통과"}
STALE_DAYS = 400
_cache = {}


def load(path=None):
    path = path or DATA
    if path not in _cache:
        try:
            with open(path, encoding="utf-8") as f:
                _cache[path] = json.load(f)
        except (OSError, ValueError):
            _cache[path] = {"entries": []}
    return _cache[path]


# ───────────────────────── 위치 문자열 정규화 ─────────────────────────

def _split_loc(loc):
    """'경기도 화성시 만세구 장안면' → ('경기도', '화성시', '만세구', '장안면'). 구가 없으면 gu=None."""
    p = (loc or "").split()
    if not p:
        return "", "", None, ""
    sido, rest = p[0], p[1:]
    if not rest:
        return sido, "", None, ""
    city, gu = rest[0], None
    rest = rest[1:]
    if rest and city.endswith("시") and rest[0].endswith("구"):
        gu, rest = rest[0], rest[1:]
    return sido, city, gu, (rest[0] if rest else "")


def _norm_emd(s):
    s = re.sub(r"\(.*?\)", "", s or "")
    s = re.sub(r"\s+", "", s)
    return re.sub(r"\d+가$", "", re.sub(r"\d+$", "", s))


def _emds(entry):
    out = set()
    for e in entry.get("emd") or []:
        for part in re.split(r"[,/·]", e):
            n = _norm_emd(part)
            if n:
                out.add(n)
    return out


def _entry_places(entry):
    """항목의 (시, 구|None) 목록."""
    out = []
    for s in entry.get("sgg") or []:
        p = s.split()
        if p and re.search(r"(도|특별시|광역시|특별자치시|특별자치도)$", p[0]):
            p = p[1:]
        if not p:
            continue
        if len(p) >= 2 and p[0].endswith("시") and p[1].endswith("구"):
            out.append((p[0], p[1]))
        else:
            out.append((p[0], None))
    return out


def _neighbor_cities(entry):
    out = set()
    for s in entry.get("neighbors_sgg") or []:
        p = s.split()
        if p and re.search(r"(도|특별시|광역시|특별자치시|특별자치도)$", p[0]):
            p = p[1:]
        if p:
            out.add(p[0])
    return out


# 2026년 행정구역 통합: 온비드는 '전남광주통합특별시'로 표기한다. 옛 이름으로 적힌 항목도 같은 곳으로 본다.
SIDO_ALIAS = {"전라남도": "전남광주통합특별시", "광주광역시": "전남광주통합특별시"}


def _canon_sido(s):
    s = SIDO_ALIAS.get(s or "", s or "")
    return re.sub(r"(특별자치도|특별자치시|특별시|광역시|도)$", "", s)


def _same_sido(a, b):
    return _canon_sido(a) == _canon_sido(b) or not b


def _is_broad(entry):
    """읍면동 없이 여러 시군구에 걸친 노선·광역 사업은 시군구가 같아도 위치가 가깝다고 보기 어렵다."""
    return not (entry.get("emd") or []) and (entry.get("kind") == "교통" or len(entry.get("sgg") or []) >= 3)


def _item_center(sido, city):
    c = geo.C.get(sido, {}).get(city)
    return c


# ───────────────────────── 매칭 ─────────────────────────

def match_entry(entry, loc):
    """한 항목과 위치 문자열의 연관 단계(1 읍면동 일치 / 2 같은 시·구 / 3 인접 시군구) 또는 None."""
    sido, city, gu, emd = _split_loc(loc)
    if not city or not _same_sido(sido, entry.get("sido")):
        return None
    places = _entry_places(entry)
    in_city = [(c, g) for c, g in places if c == city]
    if in_city:
        gu_ok = any(g is None or gu is None or g == gu for _, g in in_city)
        if gu_ok:
            if emd and _norm_emd(emd) in _emds(entry):
                return 1, "읍면동 일치"
            if _is_broad(entry):
                return 3, "노선·광역 사업 통과 시군구"
            if not _emds(entry):                  # 사업 위치가 읍면동 단위로 특정되지 않은 항목
                return 2, "같은 시·구(읍면동 미특정)"
            return 3, "같은 시·구 안 다른 읍면동"     # 사업 읍면동이 특정돼 있는데 이 물건은 거기가 아님
        return 3, "같은 시 다른 구"
    if city in _neighbor_cities(entry):
        return 3, "인접 시군구"
    lat, lng = entry.get("lat"), entry.get("lng")
    if lat is not None and lng is not None:
        c = _item_center(sido, city)
        if c:
            d = geo.km((lat, lng), c)
            if d <= 12:
                return 3, f"직선 약 {round(d)}km(시군구 중심 기준)"
    return None


def match(loc, data=None):
    """위치 문자열 하나에 대한 연관 항목 목록(가까운 순). 각 원소: 항목 요약 + tier + why."""
    data = data or load()
    out = []
    for e in data.get("entries") or []:
        m = match_entry(e, loc)
        if not m:
            continue
        tier, why = m
        out.append({"tier": tier, "why": why, "id": e.get("id"), "name": e.get("name"), "kind": e.get("kind"), "stage": e.get("stage"),
                    "place": " ".join(filter(None, [" ".join((e.get("sgg") or [])[:2]), "·".join((e.get("emd") or [])[:3])])),
                    "investor": e.get("investor"), "scale": e.get("scale"), "schedule": e.get("schedule"), "land_rules": e.get("land_rules"),
                    "summary": e.get("summary"), "asof": e.get("asof"), "sources": (e.get("sources") or [])[:2], "confidence": e.get("confidence")})
    out.sort(key=lambda x: (x["tier"], STAGE_RANK.get(x["stage"], 2), {"high": 0, "medium": 1}.get(x["confidence"], 2)))
    return out


def best_tier(dev):
    """정렬 보조: 0 구역 내·같은 시(취소 아님), 1 인접, 2 없음(또는 취소만)."""
    live = [d for d in dev or [] if d["stage"] != "보류·취소"]
    if not live:
        return 2
    t = min(d["tier"] for d in live)
    return 0 if t <= 2 else 1


# ───────────────────────── 전체 목록 집계 ─────────────────────────

def scan(rows, data=None, limit=15):
    """검색 결과 행 전체(중복 제거 후)를 개발 사업과 맞춰 집계한다. 상세를 열지 않은 1차 정보라 권리·위험은 따로 확인해야 한다."""
    data = data or load()
    seen, hits, counts = set(), [], {1: 0, 2: 0, 3: 0}
    total = 0
    for r in rows:
        k = r.get("scrnIndctCltrMngNo")
        if k in seen:
            continue
        seen.add(k)
        if r.get("scrnPrptDvsnNm") != "압류재산":
            continue
        total += 1
        dev = [d for d in match(r.get("sidoSgkEmd"), data) if d["stage"] != "보류·취소"]
        if not dev:
            continue
        d = dev[0]
        counts[d["tier"]] += 1
        km_, _ = geo.dist_from_sanbon(r.get("sidoSgkEmd"))
        hits.append({"mng": k, "name": r.get("onbidCltrNm"), "price": r.get("lowstBidPrc"), "appraisal": r.get("cltrApslEvlAvgAmt"),
                     "share": r.get("alcYn") == "Y", "cat": (r.get("ctgrFullNm") or "").split(" / ")[-1], "dist": km_,
                     "loc": r.get("sidoSgkEmd"), "dev": d, "row": r})
    hits.sort(key=lambda h: (h["dev"]["tier"], geo.band_idx(h["dist"]), h["price"] or 0))
    strong = [h for h in hits if h["dev"]["tier"] <= 2]
    shown = strong[:limit]
    if len(shown) < 8:                      # 강한 연관이 적으면 인접 시군구(약한 연관)로 8건까지 채운다
        shown += [h for h in hits if h["dev"]["tier"] == 3][:8 - len(shown)]
    return {"total": total, "counts": counts, "shown": shown, "hits": len(hits)}


# ───────────────────────── 검사 ─────────────────────────

def validate(path=None, today=None):
    """데이터 검사. (오류 목록, 경고 목록)"""
    data = load(path)
    today = today or datetime.date.today()
    errs, warns, ids = [], [], set()
    for i, e in enumerate(data.get("entries") or []):
        tag = f"[{i}] {e.get('id') or e.get('name')}"
        for k in ("id", "name", "kind", "stage", "sido", "sgg", "summary", "asof", "sources", "confidence"):
            if not e.get(k):
                errs.append(f"{tag}: '{k}' 없음")
        if e.get("id") in ids:
            errs.append(f"{tag}: id 중복")
        ids.add(e.get("id"))
        if e.get("kind") not in KINDS:
            errs.append(f"{tag}: kind '{e.get('kind')}'가 목록에 없음")
        if e.get("stage") not in STAGES:
            errs.append(f"{tag}: stage '{e.get('stage')}'가 목록에 없음")
        if e.get("confidence") not in ("high", "medium", "low"):
            errs.append(f"{tag}: confidence 값 오류")
        srcs = e.get("sources") or []
        if not srcs or not all(isinstance(s, str) and s.startswith("http") for s in srcs):
            errs.append(f"{tag}: 출처 URL(http…)이 필요함")
        m = re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", e.get("asof") or "")
        if not m:
            errs.append(f"{tag}: asof 형식 오류(YYYY-MM 또는 YYYY-MM-DD)")
        else:
            try:
                d = datetime.date(int(m[1]), int(m[2]), int(m[3] or 1))
                if (today - d).days > STALE_DAYS:
                    warns.append(f"{tag}: 기준일 {e['asof']}이 {STALE_DAYS}일보다 오래됨")
                if d > today + datetime.timedelta(days=1):
                    errs.append(f"{tag}: 기준일이 미래")
            except ValueError:
                errs.append(f"{tag}: asof 날짜 오류")
        lat, lng = e.get("lat"), e.get("lng")
        if (lat is None) != (lng is None):
            errs.append(f"{tag}: lat/lng는 함께 있어야 함")
        elif lat is not None and not (33 <= lat <= 39 and 124 <= lng <= 132):
            errs.append(f"{tag}: 좌표가 한국 범위 밖")
        sido = e.get("sido") or ""
        for city, _gu in _entry_places(e):
            known = any(city in v for v in geo.C.values())
            if not known:
                warns.append(f"{tag}: 시군구 '{city}'가 geo.py 목록에 없음(행정구역 개편이면 geo.C에 추가)")
        if not (e.get("emd") or e.get("neighbors_sgg") or lat is not None):
            warns.append(f"{tag}: emd·neighbors_sgg·좌표가 모두 없어 시·구 단위로만 맞춰짐")
        if not any(_canon_sido(k) == _canon_sido(sido) for k in geo.C):
            errs.append(f"{tag}: sido '{sido}'를 geo.C에서 찾지 못함")
    return errs, warns


def main():
    a = sys.argv[1:]
    if a[:1] == ["validate"]:
        errs, warns = validate()
        data = load()
        print(f"항목 {len(data.get('entries') or [])}개 / 오류 {len(errs)} / 경고 {len(warns)}")
        for x in errs:
            print("오류:", x)
        for x in warns[:40]:
            print("경고:", x)
        sys.exit(1 if errs else 0)
    elif a[:1] == ["match"] and len(a) > 1:
        for d in match(a[1]):
            print(f"[{d['tier']}·{d['why']}] {d['name']} — {d['stage']} ({d['asof']}) {d['summary']}")
    elif a[:1] == ["scan"] and len(a) > 1:
        with open(a[1], encoding="utf-8") as f:
            rows = json.load(f)["rows"]
        r = scan(rows)
        print(f"압류재산 {r['total']}건 중 개발 연관 {r['hits']}건 (읍면동 일치 {r['counts'][1]}, 읍면동 미특정 {r['counts'][2]}, 약한 연관 {r['counts'][3]})")
        for h in r["shown"]:
            print(f"  [{h['dev']['tier']}] {h['loc']} {h['cat']} {h['price']:,}원 — {h['dev']['name']}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
