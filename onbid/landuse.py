"""감정평가서 본문(appraisal.txt)의 '토지이용계획사항 등'을 뽑아 개발·규제 지정을 가려낸다.

토지이음(eum.go.kr)은 이 실행 환경의 네트워크 정책으로 막혀 있어(프록시 CONNECT 403) 직접 조회할 수 없다.
감정평가서 6번 항목 '토지이용계획사항 등'은 토지이용계획확인서 내용을 감정평가 기준시점에 옮겨 적은 것이라,
토지이음과 같은 종류의 정보(용도지역·지구단위계획구역·도로 저촉·개발제한구역·토지거래허가구역 등)를 담는다.
단 기준시점의 사실이므로 이후 지정·해제는 반영되지 않는다 — 리포트에도 기준시점을 함께 적는다.
"""
import re

# 개발·규제 판단에 쓰는 지정. (패턴, 표시 이름, 분류)  분류: dev 개발·사업 / reg 규제 / zone 용도지역
KEYS = [
    (r"개발제한구역", "개발제한구역(그린벨트)", "reg"),
    (r"토지거래\s*계약에\s*관한\s*허가구역", "토지거래허가구역(세부는 원문 참조)", "reg"),
    (r"공공주택(?:지구|특별법)|공공주택지구", "공공주택지구", "dev"),
    (r"택지개발(?:지구|예정지구)", "택지개발지구", "dev"),
    (r"(?:국가|일반|도시첨단|농공)산업단지", "산업단지", "dev"),
    (r"도시개발(?:구역|사업)", "도시개발구역", "dev"),
    (r"정비구역|재개발|재건축|재정비촉진", "정비(재개발·재건축)구역", "dev"),
    (r"지구단위계획구역", "지구단위계획구역", "dev"),
    (r"개발행위허가제한", "개발행위허가제한지역", "reg"),
    (r"(?:소|중|대)로\s*\d류[^,]{0,40}?\(\s*저촉\s*\)|(?:도로|공원|녹지|학교|하천)\s*\(\s*저촉\s*\)", "도로 등 도시계획시설 저촉", "dev"),
    (r"도시계획시설|도시·군계획시설", "도시·군계획시설", "dev"),
    (r"(?:군사)?시설보호구역|제한보호구역|통제보호구역", "군사시설보호구역", "reg"),
    (r"상수원보호구역", "상수원보호구역", "reg"),
    (r"수변구역", "수변구역", "reg"),
    (r"특별대책지역", "특별대책지역", "reg"),
    (r"문화재보호구역|역사문화환경", "문화재 관련 구역", "reg"),
    (r"공익용산지|보전산지|준보전산지", None, "reg"),
    (r"농업진흥구역|농업보호구역", None, "reg"),
]
ZONE = re.compile(r"((?:제\s*\d\s*종)?(?:전용|일반)?(?:주거|상업|공업|녹지)지역|자연녹지지역|생산녹지지역|보전녹지지역|"
                  r"생산관리지역|보전관리지역|계획관리지역|농림지역|자연환경보전지역)")


HEAD = re.compile(r"^\s*(?:\(\d\)|\d\.)\s*토지이용계획(?:사항\s*등|관계\s*및\s*공법상\s*제한상태|\s*및\s*공법상\s*제한상태)\s*$")
NEXT_HEAD = re.compile(r"^\s*(?:\(\d\)|\d{1,2}\.)\s+\S")
TOC = re.compile(r"4\.\s*이용상황.*5\.\s*접면도로|7\.\s*제시목록외의 물건\s+8\.")


def _block(text):
    """토지이용계획 항목(감정사무소마다 제목이 조금씩 다르다)의 본문을 다음 번호 제목 전까지 이어 붙인다.
    쪽 머리의 목차 줄('4. 이용상황 5. 접면도로상황 6. 토지이용계획사항 등')은 제외한다."""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        if HEAD.match(lines[i]):
            j, chunk = i + 1, []
            while j < len(lines) and len(chunk) < 40:
                t = lines[j].strip()
                if t and NEXT_HEAD.match(t) and not TOC.search(t):
                    break
                if t and not TOC.search(t):
                    chunk.append(t)
                j += 1
            out.append(" ".join(chunk))
            i = j
        else:
            i += 1
    return " ".join(x for x in out if x)


def _notes(text):
    """제목을 못 찾은 감정서용 보조: '토지이용계획확인서'를 언급하는 문장을 최대 2줄."""
    L = []
    for ln in text.split("\n"):
        t = re.sub(r"\s+", " ", ln).strip()
        if "토지이용계획확인서" in t and len(t) > 12 and t not in L:
            L.append(t[:200])
        if len(L) >= 2:
            break
    return L


def _asof(text):
    """기준시점(가격조사 완료일) 'YYYY-MM-DD'를 찾는다. 못 찾으면 None."""
    m = re.search(r"기준시점[^\n]{0,80}?(?:\n[^\n]{0,80}?){0,3}?(20\d\d)\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    if not m:
        m = re.search(r"(20\d\d)\s*년\s*\n?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일을?\s*기준시점", text)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def parse_landuse(path):
    """감정평가서 텍스트 파일에서 토지이용계획 정보를 뽑는다.
    반환: {"raw": 원문, "zone": 용도지역|None, "marks": [(분류, 표시)], "asof": 기준시점|None}
    텍스트가 없거나 항목을 못 찾으면 None."""
    try:
        text = open(path, encoding="utf-8", errors="ignore").read()
    except (OSError, TypeError):
        return None
    raw = re.sub(r"\s+", " ", _block(text)).strip()
    if not raw:
        notes = _notes(text)
        if not notes:
            return None
        return {"raw": "(항목 제목을 못 찾아 본문 언급만 옮김) " + " / ".join(notes), "zone": None, "marks": [], "asof": _asof(text)}
    zm = ZONE.search(raw)
    marks, seen = [], set()
    for pat, label, cls in KEYS:
        for m in re.finditer(pat, raw):
            name = label or re.sub(r"\s+", " ", m.group(0)).strip(" ,")[:80]
            if name not in seen:
                seen.add(name)
                marks.append((cls, name))
    return {"raw": raw[:600], "zone": zm.group(1) if zm else None, "marks": marks, "asof": _asof(text)}


def landuse_lines(info):
    """리포트 초안에 넣을 줄. info가 None이면 '항목을 못 찾음'을 밝힌다(추측 금지)."""
    if not info:
        return ["- 🗺 토지이용계획: 감정평가서에서 '토지이용계획사항' 항목을 찾지 못함 — 토지이음은 이 환경에서 접속 불가(네트워크 정책 차단)"]
    asof = f"감정 기준시점 {info['asof']}" if info.get("asof") else "감정 기준시점 미상"
    L = [f"- 🗺 토지이용계획({asof}, 감정평가서에 옮겨 적힌 토지이용계획확인 내용): {info['raw']}"]
    dev = [n for c, n in info["marks"] if c == "dev"]
    reg = [n for c, n in info["marks"] if c == "reg"]
    if dev or reg:
        L.append("  - 개발·규제 지정(원문 대조): " + " / ".join(
            ([f"개발·계획 {', '.join(dev)}"] if dev else []) + ([f"규제 {', '.join(reg)}"] if reg else [])))
    else:
        L.append("  - 개발사업 구역·개발제한구역·토지거래허가구역 등 지정은 이 항목에 없음(기준시점 이후 변경은 반영되지 않음)")
    return L
