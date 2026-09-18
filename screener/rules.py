"""매물 판정 규칙. 플랫폼과 무관하게 Listing 하나를 받아 통과/탈락을 정한다."""
import datetime

from . import config as C


def _months_between(start_yyyymm, end_yyyymm):
    return ((int(end_yyyymm[:4]) - int(start_yyyymm[:4])) * 12
            + (int(end_yyyymm[4:6]) - int(start_yyyymm[4:6])))


def insurance_gap_months(not_join_periods):
    """카히스토리 '보험 미가입기간' 목록(예: ['202207~202606'])의 누적 개월 수.

    무보험 운행이 아니라 개인용 자동차보험 이력이 조회되지 않는 구간이다.
    렌트/법인 차량은 공제조합에 가입돼 이 구간이 길게 잡히며,
    그 기간의 사고는 카히스토리에 남지 않아 무사고를 검증할 수 없다.
    """
    total = 0
    for period in not_join_periods:
        if not period or "~" not in period:
            continue
        start, end = period.split("~")
        total += _months_between(start, end)
    return total


def history_lag_months(model_yyyymm, first_history_date):
    """연식 대비 이력 시작 지연(개월). 크면 말소 후 재등록 등 레코드 세탁 의심."""
    if not first_history_date:
        return 0
    return _months_between(model_yyyymm, first_history_date.replace("-", "")[:6])


def classify_rent(current_use_code, avg_km_per_year, owner_changes):
    """렌트 이력 매물을 단기렌터카 / 장기렌트 / 판단보류로 나눈다."""
    if current_use_code == "3" or avg_km_per_year >= C.SHORT_TERM_MIN_AVG_KM:
        return "short_term"
    if owner_changes >= 1 and avg_km_per_year < C.LONG_TERM_MAX_AVG_KM:
        return "long_term"
    return "unknown"


def battery_warranty_left(first_registration, mileage_km, today=None):
    """고전압 배터리 보증 잔여를 (년, 제약요인)으로 반환. 기간/주행거리 중 먼저 닿는 쪽."""
    today = today or datetime.date.today()
    first = datetime.date.fromisoformat(first_registration)
    years_left = (first.replace(year=first.year + C.BATTERY_WARRANTY_YEARS) - today).days / 365.25
    driven_years = max((today - first).days / 365.25, 0.1)
    avg = mileage_km / driven_years
    km_years_left = (C.BATTERY_WARRANTY_KM - mileage_km) / avg if avg > 0 else 99.0
    if years_left <= km_years_left:
        return years_left, "기간"
    return km_years_left, "주행거리"


def evaluate(car, today=None):
    """car dict를 판정해 탈락 사유 목록을 반환한다. 빈 리스트면 통과.

    필수 키: price, mileage, accident_free, listing_age_days, has_rent_history,
             damage_won, insurance_gap_months, history_lag_months, history_available
    """
    today = today or datetime.date.today()
    fails = []

    if car.get("price") is None or car["price"] > C.MAX_PRICE_MANWON:
        fails.append(f"가격 {car.get('price')}만")
    if car.get("mileage") is None or car["mileage"] > C.MAX_MILEAGE_KM:
        fails.append(f"주행 {car.get('mileage')}km")

    if car.get("accident_free") is False:
        fails.append("사고이력")
    elif car.get("accident_free") is not True:
        # 차차차 단독 수집처럼 골격 사고 여부를 못 읽은 경우
        fails.append("사고이력 확인불가")

    age = car.get("listing_age_days")
    if age is None:
        fails.append("등록일 불명")
    elif age > C.MAX_LISTING_AGE_DAYS:
        fails.append(f"경과 {age}일")

    if not car.get("history_available", True):
        fails.append("차량이력 미표시")

    if car.get("has_rent_history"):
        kind = car.get("rent_kind")
        if not (C.INCLUDE_LONG_TERM_RENT and kind == "long_term"):
            fails.append("렌트이력" if kind != "long_term" else "장기렌트")

    dmg = car.get("damage_won")
    if dmg is None:
        fails.append("피해금액 확인불가")
    elif dmg > C.MAX_DAMAGE_WON:
        fails.append(f"피해 {dmg // 10000}만")

    gap = car.get("insurance_gap_months")
    if gap is None:
        fails.append("보험공백 확인불가")
    elif gap > C.MAX_INSURANCE_GAP_MONTHS:
        fails.append(f"보험공백 {gap}개월")

    lag = car.get("history_lag_months") or 0
    if lag > C.MAX_HISTORY_LAG_MONTHS:
        fails.append(f"이력시작 {lag}개월 지연")

    return fails
