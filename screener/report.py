"""알림 메시지 생성."""
from . import config as C


def _group(model_name):
    for i, name in enumerate(C.MODEL_ORDER):
        if name in (model_name or ""):
            return i
    return len(C.MODEL_ORDER)


def sort_cars(cars):
    """차급 순(아반떼→쏘나타→그랜저), 그 안에서 가격 낮은 순."""
    return sorted(cars, key=lambda c: (_group(c.get("model")), c.get("price") or 0))


def _age_phrase(days):
    if days is None:
        return "등록일 불명"
    if days == 0:
        return "오늘 등록"
    if days < 14:
        return f"등록 {days}일 전"
    return f"등록 {days // 7}주 전"


# 탈락 사유는 "경과 99일"처럼 값이 섞여 있어 그대로 세면 1건짜리 항목만 늘어난다.
_DROP_CATEGORIES = [
    ("사고이력", "사고이력"),
    ("렌트이력", "렌트이력"),
    ("장기렌트", "렌트이력"),
    ("경과", "등록 2개월 초과"),
    ("피해", "피해금액 500만 초과"),
    ("보험공백", "보험이력 공백"),
    ("이력시작", "이력시작 지연"),
    ("차량이력 미표시", "차량이력 미표시"),
    ("확인불가", "데이터 확인불가"),
]


def summarize_drops(dropped):
    """탈락 사유를 카테고리로 묶어 센다. 매물당 첫 번째 사유만 집계한다."""
    counts = {}
    for _, fails in dropped.values():
        label = "기타"
        for prefix, category in _DROP_CATEGORIES:
            if fails[0].startswith(prefix) or prefix in fails[0]:
                label = category
                break
        counts[label] = counts.get(label, 0) + 1
    return counts


def render(cars, ccc_only=None, dropped=None):
    if not cars:
        return "이번 주는 조건에 맞는 새 매물 없음"

    lines = [f"## 조건 통과 매물 {len(cars)}대", ""]
    current = None
    for car in sort_cars(cars):
        group = C.MODEL_ORDER[_group(car["model"])] if _group(car["model"]) < len(C.MODEL_ORDER) else "기타"
        if group != current:
            current = group
            lines += [f"### {group}", ""]

        title = f"{car['model']} {car.get('badge') or ''}".strip()
        lines.append(f"**{title}** · {car['year_label']} · "
                     f"{car['mileage']:,}km · **{car['price']:,}만원** · {car['region']}")
        lines.append(f"- 사고이력 없음 / 렌트이력 없음 확인됨")

        if car.get("outer_repairs"):
            lines.append(f"- 경미수리: {', '.join(car['outer_repairs'])}")
        dmg = car.get("damage_won")
        if dmg:
            lines.append(f"- 보험 피해 {dmg:,}원 "
                         f"(내차 {car.get('own_damage_won', 0):,} + 타차 {car.get('other_damage_won', 0):,})")
        if car.get("battery_years_left") is not None:
            lines.append(f"- 배터리 보증 잔여 약 {car['battery_years_left']:.1f}년 "
                         f"({car['battery_binding']} 기준, 차대번호 확인 필요)")
        lines.append(f"- {_age_phrase(car.get('listing_age_days'))}"
                     + (" · 재등록 매물" if car.get("re_registered") else ""))
        lines.append(f"- {car['url']}")
        lines.append("")

    if ccc_only:
        lines += ["---", "",
                  f"### 차차차 전용 {len(ccc_only)}대 — 검증 불가",
                  "",
                  "엔카에 없어 사고이력·피해금액·보험공백을 확인할 수 없습니다. "
                  "렌트이력과 경과일만 통과한 상태입니다.", ""]
        for car in sort_cars(ccc_only):
            lines.append(f"- {car.get('title') or car['model']} · {car['year_label']} · "
                         f"{car['mileage']:,}km · {car['price']:,}만원 · {car['region']} · "
                         f"{_age_phrase(car.get('listing_age_days'))} · {car['url']}")
        lines.append("")

    if dropped:
        lines += ["---", "", "### 탈락 요약", ""]
        for reason, count in sorted(summarize_drops(dropped).items(), key=lambda x: -x[1]):
            lines.append(f"- {reason}: {count}건")

    return "\n".join(lines)
