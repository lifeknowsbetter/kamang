"""KB차차차 수집기.

차차차는 보험 피해금액을 공개하지 않고(건수만 표기), 성능점검기록부 원본은
autocafe/carmodoo/m-park 같은 외부 호스트로 연결된다. 따라서 이 모듈만으로는
피해금액·보험공백·골격 사고를 판정할 수 없고, 엔카와 교차 대조해야 한다.

대신 렌트 이력은 '용도이력 있음/없음'으로 직접 표기돼 추론이 필요 없다.
"""
import datetime
import re

from . import config as C
from .http import get

LIST = "https://www.kbchachacha.com/public/search/list.empty"
DETAIL = "https://www.kbchachacha.com/public/car/detail.kbc?carSeq={}"
REFERER = "https://www.kbchachacha.com/public/search/list.kbc"

# 봇 감지 페이지는 3KB 남짓으로 돌아온다.
MIN_DETAIL_BYTES = 50_000


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def search(class_code, car_code, max_pages=5):
    """모델 하나의 매물 목록. 가격/주행거리는 서버 필터로 건다."""
    out = {}
    for page in range(1, max_pages + 1):
        url = (f"{LIST}?makerCode={C.CCC_MAKER_CODE}&classCode={class_code}"
               f"&carCode={car_code}&sellAmt=,{C.MAX_PRICE_MANWON}"
               f"&km=,{C.MAX_MILEAGE_KM}&page={page}")
        html = get(url, referer=REFERER)
        marks = list(re.finditer(r'data-car-seq="(\d+)"', html))
        found = 0
        for cur, nxt in zip(marks, marks[1:] + [None]):
            end = nxt.start() if nxt else cur.start() + 7000
            block = html[cur.start():end]
            text = _text(block)
            ym = re.search(r"(\d{2})/(\d{2})식", text)
            km = re.search(r"([\d,]+)km", text)
            price = re.search(r"([\d,]+)\s*만원", text)
            if not (ym and km and price):
                continue
            seq = cur.group(1)
            if seq in out:
                continue
            tail = text[km.end():km.end() + 30].strip().split(" ")
            title = re.search(r'vehicle_info\\?":\\?"([^"\\]+)', block)
            out[seq] = {
                "seq": seq,
                "title": title.group(1).strip() if title else "",
                "year_label": f"20{ym.group(1)}.{ym.group(2)}",
                "mileage": int(km.group(1).replace(",", "")),
                "price": int(price.group(1).replace(",", "")),
                "region": tail[0] if tail else "",
            }
            found += 1
        if found == 0:
            break
    return out


def search_all():
    seen = {}
    for class_code, car_code, name in C.CCC_MODELS:
        for seq, row in search(class_code, car_code).items():
            row["model"] = name
            seen.setdefault(seq, row)
    return seen


def enrich(seq, listing, today=None):
    """상세페이지에서 렌트(용도이력)·조회일자·차량번호를 읽는다.

    차차차가 주지 않는 값(피해금액, 보험공백)은 None으로 남겨 rules가
    '확인불가'로 탈락시키도록 한다. 엔카와 대조되면 그쪽 값으로 채운다.
    """
    today = today or datetime.date.today()
    html = get(DETAIL.format(seq), referer=REFERER, delay=1.2)
    if len(html) < MIN_DETAIL_BYTES:
        html = get(DETAIL.format(seq), referer=REFERER, delay=2.5)  # 봇 감지 재시도
    text = _text(html)

    def grab(pattern, default=None):
        m = re.search(pattern, text)
        return m.group(1).strip() if m else default

    checked = grab(r"보험사고정보 조회일자 : ([\d.]+)")
    age = None
    if checked:
        try:
            age = (today - datetime.date(*map(int, checked.split(".")))).days
        except ValueError:
            age = None

    use_hist = grab(r"용도이력 (\S+)")
    ins_cnt = grab(r"보험이력 (\d+)건")
    encar_id = grab(r"inspectionViewNew&carid=(\d+)")

    car = dict(listing)
    car.update({
        "source": "chachacha",
        "id": seq,
        "url": DETAIL.format(seq),
        "plate": grab(r"\[ ([0-9]{2,3}[가-힣][0-9]{4}) \]"),
        "model_yyyymm": listing["year_label"].replace(".", ""),
        # 차차차는 골격 사고 여부를 직접 주지 않는다. KB진단 배지는 프로그램
        # 참여 여부일 뿐이므로 무사고 근거로 쓰지 않는다.
        "accident_free": None,
        "listing_age_days": age,
        "has_rent_history": (use_hist != "없음") if use_hist else None,
        "rent_kind": None,
        "damage_won": None,          # 차차차 미공개
        "insurance_gap_months": None,  # 차차차 미공개
        "history_lag_months": 0,
        "history_available": True,
        "insurance_claim_count": int(ins_cnt) if ins_cnt else None,
        "owner_changes": grab(r"소유자변경 (\S+)"),
        "encar_carid": encar_id,
        "inspection_report_url": grab(r'data-link-url="([^"]+)"'),
    })
    return car


def collect(progress=None, today=None):
    listings = search_all()
    out = []
    for i, (seq, listing) in enumerate(listings.items(), 1):
        if progress:
            progress(i, len(listings), seq)
        out.append(enrich(seq, listing, today))
    return out


def match_to_encar(ccc_cars, encar_cars, km_tolerance=150):
    """차차차 매물을 엔카 매물과 대조한다. 차량번호 우선, 없으면 주행거리 근사."""
    by_plate = {c["plate"]: c for c in encar_cars if c.get("plate")}
    for car in ccc_cars:
        match = by_plate.get(car.get("plate"))
        if match is None:
            for enc in encar_cars:
                if abs(enc["mileage"] - car["mileage"]) <= km_tolerance:
                    match = enc
                    break
        car["encar_match"] = match["id"] if match else None
    return ccc_cars
