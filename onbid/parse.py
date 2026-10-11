"""온비드 상세 화면·XHR 조각·공매재산명세서(ClipReport) 원자료를 구조화한다."""
import base64
import html as htmlmod
import json
import os
import re
import urllib.parse

# 세부정보 '기본정보' 블록의 항목명. 값은 다음 항목명이 나올 때까지 이어진 줄들이다.
KV_KEYS = (
    "제조사", "차종", "물품명", "모델명", "수량", "연식", "제조년도", "차량번호", "주행거리", "배기량/배터리",
    "변속기", "연료", "색상", "생산지/원산지", "사용기간", "크기(가로 x 세로 x 너비)", "무게", "기타사항",
    "보관장소", "지번", "도로명", "보관장소상세", "이용 현황", "위치 및 주위환경", "이용상태", "감정평가정보",
)
KAMCO_NOTE_HEADS = (
    "공매재산에 대하여 등기된 권리 또는 가처분으로서 매각으로 효력을 잃지 아니하는 것",
    "공매재산의 매수인으로서 일정한 자격을 필요로 하는 경우 그 사실",
    "유의사항",
)


def html_lines(raw):
    t = re.sub(r"(?s)<script.*?</script>|<style.*?</style>|<!--.*?-->", "", raw)
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"</(tr|p|div|li|h\d|dt|dd|table|caption|t[dh])>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = htmlmod.unescape(t)
    lines = (re.sub(r"\s+", " ", l).strip() for l in t.split("\n"))
    return [l for l in lines if l and l != "|"]


def _idx(lines, key, start=0):
    for i in range(start, len(lines)):
        if lines[i] == key:
            return i
    return -1


def _after(lines, key, start=0):
    i = _idx(lines, key, start)
    return lines[i + 1] if 0 <= i < len(lines) - 1 else None


def frag_rows(frag):
    """XHR 조각(PC 표 형식)에서 (총건수, 행 목록)."""
    if not frag or frag.startswith("ERR"):
        return None, []
    b = re.sub(r"(?s)<script.*?</script>", "", frag)
    cnt = re.search(r"총\s*(?:<[^>]+>\s*)*(\d+)", b)
    rows = []
    body = re.search(r"(?s)<tbody[^>]*>(.*?)</tbody>", b)
    if body:
        for tr in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", body.group(1)):
            cells = [htmlmod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))).strip()
                     for c in re.findall(r"(?s)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
            if cells and not (len(cells) == 1 and "조회된 결과가 없습니다" in cells[0]):
                rows.append(cells)
    return (int(cnt.group(1)) if cnt else None), rows


def clip_lines(raw):
    """ClipReport 리포트 서버 응답(viewData: base64 JSON, 글자 단위 URL 인코딩)을 줄 단위 텍스트로."""
    if not raw or raw.startswith("NO_BUTTON"):
        return None

    def walk(o, acc):
        if isinstance(o, list):
            if (len(o) == 2 and isinstance(o[0], list) and isinstance(o[1], list) and o[0]
                    and len(o[0]) == len(o[1]) and all(isinstance(c, str) for c in o[0])
                    and all(isinstance(c, (int, float)) for c in o[1])):
                acc.append(urllib.parse.unquote_plus("".join(o[0])))
                return
            for e in o:
                walk(e, acc)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v, acc)

    pages = {}
    for part in raw.split("\n=========\n"):
        _, _, body = part.partition("\n----\n")
        try:
            vd = json.loads(body).get("resValue", {}).get("viewData")
        except ValueError:
            continue
        if not vd:
            continue
        d = json.loads(base64.b64decode(vd))
        for num, pg in zip(d.get("pageNumList", []), d.get("pageList", [])):
            acc = []
            walk(pg, acc)
            pages[num] = acc
    return [l for k in sorted(pages) for l in pages[k]] if pages else []


def _section(lines, head, tail):
    a = next((i for i, l in enumerate(lines) if head in l), None)
    if a is None:
        return None
    b = next((i for i in range(a + 1, len(lines)) if tail in lines[i]), None)
    return lines[a + 1:b] if b else lines[a + 1:]


def _rows_after_header(sec):
    """명세서 표 영역에서 머리글('비고'로 끝남) 이후 실제 데이터 줄만."""
    if not sec:
        return []
    k = [i for i, l in enumerate(sec) if l == "비고"]
    return sec[k[0] + 1:] if k else []


def statement(raw):
    st = clip_lines(raw)
    if st is None:
        return {"available": False}
    keep = _section(st, "효력을 잃지 아니하는 것", "지상권의 개요") or []
    surf = _section(st, "지상권의 개요", "기타 유의 사항") or []
    note = _section(st, "기타 유의 사항", "한국자산관리공사") or []
    note = [l for l in note if not re.fullmatch(r"\d{4}\.\d\d\.\d\d", l.strip())]
    return {
        "available": True,
        "keep": [l for l in keep if l.strip()],
        "surface": [l for l in surf if l.strip()],
        "note": note,
        "occupancy_rows": _rows_after_header(_section(st, "▣ 공매재산 이용 및 점유현황", "▣ 임차인 배분")),
        "lease_rows": _rows_after_header(_section(st, "▣ 임차인 배분 요구 및 채권신고 현황", "▣ 배분요구 및 채권신고")),
        "base_date": next((l for l in reversed(st) if re.fullmatch(r"\d{4}\.\d\d\.\d\d", l.strip())), None),
        "lines": st,
    }


def _kv_block(lines):
    s = _idx(lines, "세부정보")
    if s < 0:
        return {}
    e = next((i for i in range(s, len(lines)) if lines[i] in ("인도/인수 책임 및 부대조건", "입찰정보", "압류재산정보")), len(lines))
    out, cur = {}, None
    for l in lines[s + 1:e]:
        if l in KV_KEYS:
            cur = l
            out.setdefault(cur, [])
        elif cur:
            out[cur].append(l)
    return {k: " ".join(v).strip() for k, v in out.items()}


def _schedule(lines):
    j = _idx(lines, "입찰일정 및 장소 정보 테이블")
    if j < 0:
        return [], None
    k = _idx(lines, "납부기한 안내", j)
    seg = "\n".join(lines[j:k if k > 0 else len(lines)])
    rows = [dict(no=m[1], start=m[3], end=m[4], price=int(m[5].replace(",", "")), open=m[6], decide=m[7])
            for m in re.finditer(r"\n\d{4}\n(\d{3}(?:/\d{3})?)\n(전자입찰|현장입찰)\n(\d{4}-\d\d-\d\d \d\d:\d\d)\n~\n"
                                 r"(\d{4}-\d\d-\d\d \d\d:\d\d)\n([\d,]+)\n(\d{4}-\d\d-\d\d \d\d:\d\d)\n(\d{4}-\d\d-\d\d \d\d:\d\d)", seg)]
    base = re.search(r"기준일 : (\S+)", seg)
    return rows, (base.group(1) if base else None)


def _area(lines):
    j = _idx(lines, "면적정보 테이블")
    if j < 0:
        return None
    k = _idx(lines, "지역", j)
    cells = lines[j + 5:k] if k > 0 else []
    return {"use": cells[0], "area": cells[1], "share_note": cells[3] if len(cells) > 3 else ""} if len(cells) >= 2 else None


def _notes(lines):
    """물건별 유의사항. 한국자산관리공사 압류재산은 '입찰 전 알아야 할 주요사항' 블록, 그 외는 기본정보의 기타사항."""
    j = _idx(lines, "입찰 전 알아야 할 주요사항")
    if j >= 0:
        ends = [x for x in (_idx(lines, "임대차 정보(감정평가서 및 배분요구서 기준)", j), _idx(lines, "입찰정보", j),
                            _idx(lines, "등기사항증명서 주요정보", j)) if x > 0]
        block = lines[j + 1:min(ends)] if ends else lines[j + 1:j + 30]
        return [l for l in block if l not in KAMCO_NOTE_HEADS]
    return []


def _pdf(raw):
    m = re.search(r"fn_chkPdfRead\('(\d+)','(\d+)','[^']*','([^']*)','([^']*)'\)", raw)
    if not m:
        return None
    return {"atchFileLstNo": m[1], "atchSn": m[2], "name": m[3], "hash": m[4]}


def _photos(img_raw):
    urls = re.findall(r"dnldImgFile\.do\?atchFileLstNo=(\d+)&(?:amp;)?atchSn=(\d+)&(?:amp;)?thnImgDownloadFlag=false&(?:amp;)?downloadImageKind=ELGM_FILE_NM", img_raw or "")
    seen, out = set(), []
    for lst, sn in urls:
        if (lst, sn) not in seen:
            seen.add((lst, sn))
            out.append({"atchFileLstNo": lst, "atchSn": sn})
    out.sort(key=lambda p: int(p["atchSn"]))
    return out


def _money(s):
    if not s:
        return None
    m = re.search(r"[\d,]{2,}", s)
    return int(m.group(0).replace(",", "")) if m else None


def parse_item(mng, d):
    """<d>/<mng>.{html,xhr,img,stmt}를 읽어 하나의 dict로."""
    raw = open(os.path.join(d, mng + ".html"), encoding="utf-8").read()
    L = html_lines(raw)
    r = {"mng": mng}
    j = _idx(L, "공고보기")
    r["name"] = L[j + 1] if 0 <= j < len(L) - 1 else None
    if r["name"] == "공고보기":
        r["name"] = L[j + 2]
    r["appraisal"] = _money(_after(L, "감정평가금액(원)"))
    r["price"] = _money(_after(L, "공매예정가격(원)") or _after(L, "최저입찰가격(원)"))
    r["round"] = _after(L, "회차")
    r["fails"] = _after(L, "유찰횟수")
    j = _idx(L, "입찰기간")
    r["period"] = " ".join(L[j + 1:j + 4]) if j >= 0 else None
    r["org"] = _after(L, "공고기관")
    j = _idx(L, "담당부점")
    r["branch"] = " ".join(L[j + 1:j + 3]).replace(" /", "/") if j >= 0 else None
    r["client"] = _after(L, "공매대행의뢰기관")
    r["bid_method"] = _after(L, "입찰방식")
    r["handover"] = _after(L, "인도/인수 책임")
    r["kv"] = _kv_block(L)
    r["area"] = _area(L)
    r["notes"] = _notes(L)
    r["schedule"], r["stmt_base"] = _schedule(L)
    j = _idx(L, "전체 입찰내역")
    r["history"] = L[j + 2] if j >= 0 and j + 2 < len(L) else None
    r["attachments"] = sorted(set(l for l in L if re.search(r"\.(hwpx?|pdf|xlsx?|docx?)$", l, re.I)))
    j = _idx(L, "공고문")
    r["notice_head"] = L[j + 1:j + 30] if j >= 0 else []
    r["pdf"] = _pdf(raw)

    for ext, key in (("xhr", "frag"), ("img", "img"), ("stmt", "stmt")):
        p = os.path.join(d, f"{mng}.{ext}")
        r[key] = open(p, encoding="utf-8").read() if os.path.exists(p) else None
    frags = json.loads(r.pop("frag")) if r.get("frag") else {}
    r["reg_cnt"], r["reg"] = frag_rows(frags.get("inqRgstMtrsCrtiClg"))
    r["occ_cnt"], r["occ"] = frag_rows(frags.get("inqOcpyRelClg"))
    r["lease_cnt"], r["lease"] = frag_rows(frags.get("inqLeasInfClg"))
    r["bond_cnt"], r["bond"] = frag_rows(frags.get("inqBondDclrPscdClg"))
    r["photos"] = _photos(r.pop("img"))
    r["statement"] = statement(r.pop("stmt"))
    return r
