"""알림 메시지 생성."""
import datetime

from . import config as C

GROUP_ICON = {"아반떼": "🚙", "쏘나타": "🚗", "그랜저": "🚘"}


def _group_index(model_name):
    for i, name in enumerate(C.MODEL_ORDER):
        if name in (model_name or ""):
            return i
    return len(C.MODEL_ORDER)


def _group_name(model_name):
    i = _group_index(model_name)
    return C.MODEL_ORDER[i] if i < len(C.MODEL_ORDER) else "기타"


def sort_cars(cars):
    """차급 순(아반떼→쏘나타→그랜저), 그 안에서 가격 낮은 순."""
    return sorted(cars, key=lambda c: (_group_index(c.get("model")), c.get("price") or 0))


def _age_phrase(days):
    if days is None:
        return "등록일 불명"
    if days == 0:
        return "오늘 등록"
    if days == 1:
        return "어제 등록"
    if days < 14:
        return f"{days}일 전 등록"
    return f"{days // 7}주 전 등록"


def _trim(car):
    return f"{car['model']} {car.get('badge') or ''}".strip()


def pick_recommendation(cars):
    """배터리 보증 잔여가 가장 긴 매물. 동률이면 주행거리가 적은 쪽."""
    scored = [c for c in cars if c.get("battery_years_left") is not None]
    if not scored:
        return None
    return max(scored, key=lambda c: (round(c["battery_years_left"], 1), -c["mileage"]))


def warnings_for(car):
    """매물별 주의점. 탈락 사유는 아니지만 알고 사야 하는 것들."""
    notes = []
    if car.get("price", 0) >= C.MAX_PRICE_MANWON - 20:
        notes.append(f"예산 상한({C.MAX_PRICE_MANWON}만) 근접 — 이전비 100~150만원 별도")
    if car.get("mileage", 0) >= C.MAX_MILEAGE_KM - 5000:
        notes.append("주행거리 10만km 근접")
    owner = car.get("owner_changes")
    if isinstance(owner, int) and owner >= 3:
        notes.append(f"명의변경 {owner}회로 많음")
    if (car.get("battery_years_left") or 0) < 2:
        notes.append(f"배터리 보증 잔여 {car['battery_years_left']:.1f}년 — 교체비 수백만원대 리스크")
    if car.get("re_registered"):
        notes.append("재등록 매물 — 실제 체류 기간이 표기보다 길 수 있음")
    avg = car.get("avg_km_per_year") or 0
    if avg >= C.SHORT_TERM_MIN_AVG_KM:
        notes.append(f"연평균 {avg:,}km로 주행량 많음 — 렌트 이력은 없으나 사용 강도 확인 필요")
    return notes


def render(cars, ccc_only=None, dropped=None, previous_ids=None, today=None):
    today = today or datetime.date.today()
    stamp = today.strftime("%Y년 %m월 %d일")
    previous_ids = set(previous_ids or [])

    if not cars:
        msg = f"**{stamp} 스크리닝** — 이번 주는 조건에 맞는 새 매물 없음"
        if dropped:
            total = len(dropped)
            msg += f"\n\n검토한 {total}건은 모두 조건에서 탈락했습니다."
        return msg

    ordered = sort_cars(cars)
    new_ids = [c["id"] for c in ordered if previous_ids and c["id"] not in previous_ids]
    prices = [c["price"] for c in ordered]

    lines = [f"# 🚗 {stamp} 중고 하이브리드 스크리닝", ""]
    headline = f"**조건 통과 {len(ordered)}대** · {min(prices):,}만 ~ {max(prices):,}만원"
    if previous_ids:
        headline += f" · 지난주 대비 신규 {len(new_ids)}대"
    lines += [headline, ""]

    counts = {}
    for car in ordered:
        counts[_group_name(car["model"])] = counts.get(_group_name(car["model"]), 0) + 1
    lines.append(" · ".join(f"{GROUP_ICON.get(g, '')} {g} {n}대"
                            for g, n in sorted(counts.items(), key=lambda x: C.MODEL_ORDER.index(x[0])
                                               if x[0] in C.MODEL_ORDER else 99)))
    lines.append("")

    pick = pick_recommendation(ordered)
    if pick:
        lines += ["---", "", "## 🏆 이번 주 추천", "",
                  f"**{_trim(pick)}** · {pick['year_label']} · {pick['mileage']:,}km · "
                  f"**{pick['price']:,}만원** · {pick['region']}", "",
                  f"통과 매물 중 배터리 보증 잔여가 **{pick['battery_years_left']:.1f}년**으로 가장 깁니다"
                  f"({pick['battery_binding']} 기준). "
                  f"연평균 {pick.get('avg_km_per_year', 0):,}km 주행, "
                  f"명의변경 {pick.get('owner_changes')}회.", ""]
        pick_notes = warnings_for(pick)
        if pick_notes:
            lines += ["다만 아래는 확인하고 보세요:", ""]
            lines += [f"- ⚠️ {note}" for note in pick_notes]
            lines.append("")
        lines += [f"👉 {pick['url']}", ""]

    lines += ["---", "", "## 전체 목록", ""]
    current = None
    for car in ordered:
        group = _group_name(car["model"])
        if group != current:
            current = group
            lines += [f"### {GROUP_ICON.get(group, '')} {group}", ""]

        flag = " 🆕" if car["id"] in new_ids else ""
        lines.append(f"**{_trim(car)}**{flag}")
        lines.append(f"{car['year_label']} · {car['mileage']:,}km "
                     f"(연평균 {car.get('avg_km_per_year', 0):,}km) · "
                     f"**{car['price']:,}만원** · {car['region']}")
        lines.append("")

        checks = ["사고이력 없음", "렌트이력 없음"]
        gap = car.get("insurance_gap_months")
        checks.append("보험이력 연속" if not gap else f"보험공백 {gap}개월")
        lines.append("- ✅ " + " / ".join(checks))

        dmg = car.get("damage_won") or 0
        if dmg:
            lines.append(f"- 보험 피해 **{dmg:,}원** "
                         f"(내차 {car.get('own_damage_won', 0):,} + 타차 {car.get('other_damage_won', 0):,})")
        else:
            lines.append("- 보험 피해 이력 없음")

        if car.get("outer_repairs"):
            lines.append(f"- 경미수리: {', '.join(car['outer_repairs'])} (외판, 골격 무관)")
        else:
            lines.append("- 외판 교환·판금 이력 없음")

        if car.get("battery_years_left") is not None:
            lines.append(f"- 🔋 배터리 보증 잔여 **{car['battery_years_left']:.1f}년** "
                         f"({car['battery_binding']} 기준)")
        lines.append(f"- 명의변경 {car.get('owner_changes')}회 · {_age_phrase(car.get('listing_age_days'))}")

        for note in warnings_for(car):
            lines.append(f"- ⚠️ {note}")

        lines.append(f"- {car['url']}")
        lines.append("")

    if ccc_only:
        lines += ["---", "", f"## 📋 차차차 전용 {len(ccc_only)}대 — 검증 불가", "",
                  "엔카에 없어 **사고이력·보험 피해금액·보험이력 공백을 확인할 수 없습니다.** "
                  "렌트이력과 등록 경과일만 통과한 상태이므로 위 후보와 같은 기준으로 "
                  "비교하지 마세요. 관심 있으면 링크에서 성능점검기록부를 직접 확인하세요.", ""]
        for car in sort_cars(ccc_only):
            claims = car.get("insurance_claim_count")
            extra = f" · 보험이력 {claims}건" if claims is not None else ""
            lines.append(f"- **{car.get('title') or car['model']}** · {car['year_label']} · "
                         f"{car['mileage']:,}km · {car['price']:,}만원 · {car['region']}"
                         f"{extra} · {_age_phrase(car.get('listing_age_days'))}")
            lines.append(f"  {car['url']}")
        lines.append("")

    if dropped:
        counts = summarize_drops(dropped)
        lines += ["---", "", f"## 탈락 {sum(counts.values())}건", "",
                  " · ".join(f"{reason} {n}" for reason, n in
                             sorted(counts.items(), key=lambda x: -x[1])), ""]

    lines += ["---",
              "",
              f"_조건: 현대 하이브리드 · {C.MAX_PRICE_MANWON:,}만원 이하 · "
              f"{C.MAX_MILEAGE_KM:,}km 이하 · 등록 2개월 이내 · 사고/렌트 이력 없음 · "
              f"보험 피해 {C.MAX_DAMAGE_WON // 10000:,}만원 이하_",
              "",
              "_배터리 보증은 10년/20만km 가정입니다. 실제 조건과 중고 승계 여부는 "
              "차대번호로 제조사 서비스센터 확인이 필요합니다._"]
    return "\n".join(lines)


# 탈락 사유는 "경과 99일"처럼 값이 섞여 있어 그대로 세면 1건짜리 항목만 늘어난다.
_DROP_CATEGORIES = [
    ("사고이력", "사고이력"),
    ("렌트이력", "렌트이력"),
    ("장기렌트", "렌트이력"),
    ("경과", "등록 2개월 초과"),
    ("피해", "피해금액 초과"),
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
