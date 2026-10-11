"""경유차 조기폐차 지원금 추정.

근거: 2026년 조기폐차 보조금 업무처리지침(기후에너지환경부, 2026-02-10 발표)·한국자동차환경협회(aea.or.kr)
안내·2026년 지자체 공고(서울·인천·대전·용인·공주 등). 2026-10 조사는 공고 원문을 직접 열지 못하고 검색 발췌로
교차확인한 것이라 금액·요건은 신청 전에 해당 지자체 공고로 다시 확인해야 한다. README에 출처를 정리했다.
해마다 바뀌므로 RULES를 해마다 갱신한다.

공매 차량에 적용할 때 가장 중요한 점
- 신청일 기준 6개월 이상 소유 + 해당 지역 6개월 이상 연속 등록이 필요하다(2026년부터 전 차종 적용).
  → 낙찰받고 이전등록한 날부터 최소 6개월을 들고 있어야 신청할 수 있다.
- 5등급 지원은 2026년이 마지막이다 → 지금 낙찰받는 5등급 차량은 요건을 채울 시간이 없다.
- 4등급은 2027년 이후 사업 지속 여부가 미확정이다.
- 차량기준가액(보험개발원, 당해연도 1분기)은 온비드 감정가와 다르다. 여기서는 감정가를 대용값으로 쓴다.
"""

RULES = {
    "year": 2026,
    # 경유차 제작연도로 추정한 배출가스 등급(형식승인 기준에 따라 경계 연식은 차량별로 다르다)
    # 등급은 연식이 아니라 제작 당시 인증 배출허용기준으로 정해진다. 아래는 경험칙일 뿐이고 확정은 차량번호 조회.
    "grade_by_year": [
        (2005, "5등급"),          # 유로3 이하(2002.7.1 이후 유로3 포함), 통상 2005년 이전 제작
        (2007, "4·5등급 혼재"),   # 2006~2007년은 유예기간이라 두 등급이 함께 생산됨
        (2009, "4등급"),          # 유로4(2006 기준), 통상 ~2009.8 제작
        (2011, "3~4등급 경계"),   # 유로4 엔진이 2009.9 이후에도 쓰임(2010 쏘렌토R 일부, 2008~2011 포터2 126마력 등)
        (9999, "3등급 이하"),     # 유로5·6 — 조기폐차 대상 아님
    ],
    "under_3_5t": {
        "4등급": {"cap": 8_000_000, "first_rate": 0.70, "second_rate": 0.30,
                 "second_cond": "2차 30%는 전기·수소·하이브리드(경유 하이브리드 제외) 신차 구매 시에만"},
        "5등급": {"cap": 3_000_000, "first_rate": 1.00, "second_rate": 0.0, "second_cond": ""},
    },
    "low_income_bonus": 1_000_000,
    "own_months": 6,
    "reg_months": 6,
    "grade5_last_year": 2026,     # 5등급 지원 종료(건설기계 일부 예외)
    "grade4_after_2026": "미확정(인천시만 '내년에도 지속 예정' 언급)",
    "one_per_person": True,       # 서울·인천·수원·용인 등 다수 지자체 1인 1대
}

HEAVY = ("화물차", "버스", "특수자동차", "트레일러", "덤프", "중기")


def grade_from_year(year):
    if not year:
        return "연식 미상"
    for upto, g in RULES["grade_by_year"]:
        if year <= upto:
            return g
    return "3등급 이하"


def estimate(fuel, year, cc=None, category="", km=None, flags=(), name="", value_proxy=None):
    """반환: grade_est, eligible(가능/불가/확인필요/대상아님), amount_lo/hi/mid, basis, caveats."""
    out = {"grade_est": None, "eligible": "대상아님", "amount_lo": None, "amount_hi": None, "amount_mid": None,
           "basis": "", "caveats": []}
    if fuel != "경유":
        out["grade_est"] = f"{fuel}(경유 아님)"
        out["basis"] = "조기폐차 4등급 지원은 경유차 대상. 휘발유·LPG는 1987~2003년 이전 제작 5등급만 해당돼 사실상 없음"
        return out
    g = grade_from_year(year)
    out["grade_est"] = f"{g} 추정({year}년식)" if year else g
    heavy = any(h in (category or "") or h in (name or "") for h in HEAVY) or (cc and cc >= 3500)
    if heavy:
        out["caveats"].append("3.5톤 이상 가능성(화물·버스·특수 또는 대배기량) — 배기량 구간별 상한표 적용, 총중량 확인 필요")
    blocked = [f for f in flags if "폐차 조건부" in f]
    if blocked:
        out["eligible"] = "불가"
        out["basis"] = "폐차 조건부 매각 — 낙찰자가 직접 조기폐차 신청할 수 없음"
        return out
    if g == "3등급 이하":
        out["eligible"] = "대상아님"
        out["basis"] = "유로5 이후(3등급 이하 추정) — 조기폐차 지원 대상 아님"
        return out
    if g == "5등급" or g == "4·5등급 혼재":
        if g == "4·5등급 혼재":
            out["caveats"].append("2006~2007년식은 4·5등급 혼재 — 차량번호로 등급 조회. 4등급이면 아래 4등급 조건 적용")
        out["eligible"] = "불가"
        out["basis"] = (f"5등급 지원은 {RULES['grade5_last_year']}년 종료 + 낙찰 후 {RULES['own_months']}개월 소유·등록 요건"
                        " → 지금 낙찰받으면 기한 내 신청 불가")
        if g == "5등급":
            return out
        out["eligible"] = "확인필요"
    # 4등급 또는 경계 연식
    out["eligible"] = "확인필요"
    rule = RULES["under_3_5t"]["4등급"]
    v = value_proxy
    if v and not heavy:
        r10k = lambda x: int(round(x / 10_000) * 10_000)
        lo, hi = r10k(v * 0.8 * rule["first_rate"]), r10k(min(v * 1.5 * rule["first_rate"], rule["cap"] * rule["first_rate"]))
        out.update(amount_lo=lo, amount_hi=hi, amount_mid=(lo + hi) // 2)
    out["basis"] = (f"4등급 3.5톤 미만: 차량기준가액(보험개발원)×{int(rule['first_rate'] * 100)}%(1차), 상한 {rule['cap']:,}원. "
                    f"{rule['second_cond']}. 금액은 온비드 감정가로 차량기준가액을 대신 추정한 범위")
    out["caveats"] += [
        f"낙찰·이전등록 후 {RULES['own_months']}개월 이상 소유 + 같은 지역 {RULES['reg_months']}개월 연속 등록해야 신청 가능 → 빨라야 2027년 신청",
        f"2027년 4등급 지원사업 지속 여부 {RULES['grade4_after_2026']} — 사업 공고 확인 전에는 수익 계산에 넣지 말 것",
        "관능검사 적합 + 대상차량확인 '정상가동' 판정 필요(시동불가·사고·침수 차량 탈락), 정부지원 DPF·저공해조치 이력 있으면 제외",
        "보유 6개월 동안 의무보험·자동차세·정기검사 비용 발생, 취득세 과세표준이 낙찰가가 아닌 시가표준액일 수 있음",
        "다수 지자체가 1인 1대·선착순·예산소진 마감 — 2026년 접수는 대부분 마감(서울 10/16)",
    ]
    if g == "3~4등급 경계":
        out["caveats"].insert(0, "연식 경계(2010~2011년식) — 대부분 3등급(유로5)이라 대상 아님, 일부 모델만 4등급. "
                                 "차량번호로 배출가스 등급 조회(emissiongrade.mecar.or.kr, 1833-7435) 후 판단")
    return out
