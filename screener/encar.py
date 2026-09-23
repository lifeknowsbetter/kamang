"""엔카 수집기. 비공개 검색/진단/카히스토리 API를 사용한다."""
import datetime

from . import config as C
from . import rules
from .http import get_json, map_parallel, quote

SEARCH = "https://api.encar.com/search/car/list/general"
INSPECTION = "https://api.encar.com/v1/readside/inspection/vehicle/{}"
RECORD = "https://api.encar.com/v1/readside/record/vehicle/{}/open"
VEHICLE = "https://api.encar.com/v1/readside/vehicle/{}"
REFERER = "https://www.encar.com/"
DETAIL_URL = "https://www.encar.com/dc/dc_cardetailview.do?carid={}"

PAGE_SIZE = 50  # 20으로 고정하면 모델당 20건에서 잘린다 (과거 누락 원인)


def _query(group, model):
    return (f"(And.Hidden.N._.GreenType.Y._.(C.CarType.A._."
            f"(C.Manufacturer.{C.ENCAR_MANUFACTURER}._."
            f"(C.ModelGroup.{group}._.Model.{model}.)))"
            f"_.Mileage.range(..{C.MAX_MILEAGE_KM})._."
            f"Price.range(..{C.MAX_PRICE_MANWON}).)")


def search(group, model):
    """한 모델의 매물을 끝까지 페이지네이션해 가져온다."""
    out, offset = [], 0
    while True:
        sr = f"|ModifiedDate|{offset}|{PAGE_SIZE}"
        url = f"{SEARCH}?count=true&q={quote(_query(group, model))}&sr={quote(sr)}"
        data = get_json(url, referer=REFERER)
        if not data:
            break
        hits = data.get("SearchResults") or []
        out.extend(hits)
        offset += PAGE_SIZE
        if len(hits) < PAGE_SIZE or offset >= (data.get("Count") or 0):
            break
    return out


def search_all():
    """5개 모델 전체. 리스/렌트 판매건과 중복 Id는 제외."""
    seen = {}
    for group, model in C.ENCAR_MODELS:
        for row in search(group, model):
            if row.get("SellType") in ("리스", "렌트"):
                continue
            car_id = str(row.get("Id"))
            seen.setdefault(car_id, row)
    return seen


def _days_since(iso, today):
    if not iso:
        return None
    return (today - datetime.date.fromisoformat(str(iso)[:10])).days


def enrich(car_id, listing, today=None):
    """진단 + 카히스토리 + 매물정보를 합쳐 판정용 dict를 만든다.

    진단 API가 빈 응답이면 중복 등록 Id이므로 None을 반환한다.
    """
    today = today or datetime.date.today()
    insp = get_json(INSPECTION.format(car_id), referer=REFERER)
    if not insp:
        return None
    master = insp.get("master") or {}

    # 진단 API만으로 탈락이 확정되면 나머지 두 호출을 아낀다.
    # 실질 경과일은 max(점검, 광고)이므로 점검일만으로 이미 초과면 광고일은 볼 필요가 없다.
    insp_age = _days_since(master.get("registrationDate"), today)
    if master.get("accdient") is not False or (insp_age is not None and insp_age > C.MAX_LISTING_AGE_DAYS):
        return {
            "source": "encar", "id": car_id, "url": DETAIL_URL.format(car_id),
            "model": listing.get("Model"), "badge": listing.get("Badge"),
            "price": int(listing["Price"]), "mileage": int(listing["Mileage"]),
            "accident_free": master.get("accdient") is False,
            "listing_age_days": insp_age, "early_exit": True,
        }

    rec = get_json(RECORD.format(car_id), referer=REFERER) or {}
    manage = (get_json(VEHICLE.format(car_id), referer=REFERER) or {}).get("manage") or {}

    year = str(int(listing["Year"]))
    model_yyyymm = year[:6]
    mileage = int(listing["Mileage"])

    ad_age = _days_since(manage.get("firstAdvertisedDateTime"), today)
    ages = [a for a in (insp_age, ad_age) if a is not None]
    # 재등록 시 두 날짜가 따로 리셋되므로 세탁되지 않은 쪽(더 오래된 값)을 쓴다.
    listing_age = max(ages) if ages else None

    first_date = rec.get("firstDate")
    driven_years = None
    if first_date:
        driven_years = max((today - datetime.date.fromisoformat(first_date)).days / 365.25, 0.1)
    avg_km = int(mileage / driven_years) if driven_years else 0

    not_join = [rec.get(f"notJoinDate{i}") for i in range(1, 6)]
    gap = rules.insurance_gap_months([p for p in not_join if p])

    has_rent = bool(rec.get("loan"))
    car = {
        "source": "encar",
        "id": car_id,
        "url": DETAIL_URL.format(car_id),
        "model": listing.get("Model"),
        "badge": listing.get("Badge"),
        "model_yyyymm": model_yyyymm,
        "year_label": f"{year[:4]}.{year[4:6]}",
        "mileage": mileage,
        "price": int(listing["Price"]),
        "region": listing.get("OfficeCityState"),
        "plate": rec.get("carNo"),
        "accident_free": master.get("accdient") is False,
        "listing_age_days": listing_age,
        "inspection_age_days": insp_age,
        "ad_age_days": ad_age,
        "re_registered": bool(manage.get("reRegistered")),
        "history_available": bool(rec.get("openData")),
        "has_rent_history": has_rent,
        "rent_kind": (rules.classify_rent(rec.get("use"), avg_km, rec.get("ownerChangeCnt") or 0)
                      if has_rent else None),
        "damage_won": (rec.get("myAccidentCost") or 0) + (rec.get("otherAccidentCost") or 0),
        "own_damage_won": rec.get("myAccidentCost") or 0,
        "other_damage_won": rec.get("otherAccidentCost") or 0,
        "insurance_gap_months": gap,
        "history_lag_months": rules.history_lag_months(model_yyyymm, first_date),
        "owner_changes": rec.get("ownerChangeCnt"),
        "avg_km_per_year": avg_km,
        "first_registration": first_date,
        "outer_repairs": [
            f"{(o.get('type') or {}).get('title')} "
            f"{'/'.join(s.get('title', '') for s in (o.get('statusTypes') or []))}".strip()
            for o in (insp.get("outers") or [])
        ],
    }
    if first_date:
        left, binding = rules.battery_warranty_left(first_date, mileage, today,
                                                    model_name=listing.get("Model"))
        car["battery_years_left"], car["battery_binding"] = left, binding
    return car


def collect(today=None, progress=None, workers=5):
    """검색 → 상세 검증까지 수행해 (통과 목록, 탈락 사유 dict)를 반환."""
    listings = search_all()
    items = list(listings.items())
    done = [0]

    def work(item):
        car_id, listing = item
        car = enrich(car_id, listing, today)
        done[0] += 1
        if progress:
            progress(done[0], len(items), car_id)
        return car_id, car

    passed, dropped = [], {}
    for car_id, car in map_parallel(work, items, workers=workers):
        if car is None:
            continue  # 중복 등록 Id
        if car.get("early_exit"):
            # 나머지 API를 부르지 않았으므로 확정된 사유만 기록한다.
            dropped[car_id] = (car, ["사고이력" if not car["accident_free"]
                                     else f"경과 {car['listing_age_days']}일"])
            continue
        fails = rules.evaluate(car, today)
        if fails:
            dropped[car_id] = (car, fails)
        else:
            passed.append(car)
    return passed, dropped
