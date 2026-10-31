"""자동차 실효 판정.

온비드 자동차 공매는 낙찰가가 시세 가까이 올라가서, 최저가가 싸 보여도 되판 돈이 비용을 못 넘기는 경우가 대부분이다.
시세를 몰라도 결론이 같은 물건(구조적 실효 없음)은 리포트에서 빼고, 나머지에는 '본전에 필요한 되팔 시세'를 붙여
사용자가 엔카·헤이딜러 시세와 바로 비교하게 한다.

근거 (2026-10-18 조사)
- 낙찰가율: 온비드 최근 90일 낙찰 404건(20개 차종 키워드, 특수차 제외)의 최저가 구간별 중앙값.
  100만 미만 209%, 100~200만 170%, 200~300만 161%, 300~500만 131%, 500만 이상 109%.
  → 낙찰 기록이 쌓이면 RATE_BANDS를 다시 잰다(공부 루틴 과제).
- 비용(모두 보수적 가정치): 취득세 승용 7%·그 밖 5%·경차 0, 전기차는 140만 감면, 탁송 6만+0.1만×직선km(제주 +60만),
  상품화 15만, 이전·보험 5만, 예비비 낙찰가의 10%. 실제로는 더 들 가능성이 크다.
"""
import re

RATE_BANDS = ((0, 1_000_000, 2.09), (1_000_000, 2_000_000, 1.70), (2_000_000, 3_000_000, 1.61),
              (3_000_000, 5_000_000, 1.31), (5_000_000, 10 ** 12, 1.09))

# 되팔 상대가 좁고 운반·등록이 어려운 차량
SPECIAL = re.compile(r"진개|소방|구급|엠블런스|앰블런스|앰뷸런스|응급|레커|구난|압축|덤프|펌프|청소|음식물|폐차|유니버스|BH090|유니시티|트레일러|살수|고소작업|지게차|"
                     r"버스|에어로타운|저상|슬로프|특장|크레인|굴삭|트랙터|암롤|순찰|견인|수거")
SPECIAL_CAT = ("특수", "덤프", "버스", "트레일러", "소방")
PASSENGER = re.compile(r"쏘나타|아반떼|그랜져|그랜저|K[3579]|투싼|싼타페|스포티지|쏘렌토|쏘울|니로|모닝|레이|스파크|프라이드|SM[3567]|렉서스|체어맨|코란도|"
                       r"모하비|아이오닉|말리부|캠리|제네시스|G[78]0|티볼리|QM[356]")
VAN = re.compile(r"스타렉스|카니발|승합")
EV = re.compile(r"일렉트릭|(?<![A-Za-z])EV\d?(?![A-Za-z])|전기차|전기\s*(?:승용|자동차)|아이오닉\s*[56](?!\d)")
ASK_RATIO_MAX = 0.20      # 본전에 필요한 시세 상승률 상한(경험칙) — 참고용 표시에만 쓰고 제외 기준으로는 쓰지 않는다


def rate(price):
    return next(r for a, b, r in RATE_BANDS if a <= price < b)


def _cc(name):
    m = re.search(r"(\d{1,2},?\d{3}|\d{2,3})\s*cc", name or "")
    return int(m.group(1).replace(",", "")) if m else None


def _km(name):
    m = re.search(r"(\d{2,3},\d{3})\s*k?m", name or "", re.I)
    return int(m.group(1).replace(",", "")) if m else None


def assess(name, cat, price, sido, dist_km, fuel=None, km=None):
    """반환: dict(verdict '제외'|'확인', reasons[], clear, extra, breakeven, need_pct, tow)
    fuel·km는 검색 행의 연료·주행거리 필드(있으면 물건명 정규식보다 먼저 믿는다)."""
    name, cat = name or "", cat or ""
    cc = _cc(name)
    ev = bool(EV.search(name)) or (cc is not None and cc < 200) or fuel == "전기"
    hyb = "하이브리드" in name or fuel == "하이브리드"
    kind = "기타" if "화물" in cat else "승합" if (VAN.search(name) or "승합" in cat) else "승용" if (PASSENGER.search(name) or re.search(r"승용|SUV", cat)) else "기타"
    light = cc is not None and cc <= 1000 and not ev and kind in ("승용", "승합")
    clear = price * rate(price)
    tax = 0.0 if light else clear * (0.07 if kind == "승용" else 0.05)
    if ev:
        tax = max(0.0, tax - 1_400_000)
    tow = 150_000 if dist_km is None else 60_000 + 1_000 * dist_km + (600_000 if (sido or "").startswith("제주") else 0)
    extra = tax + tow + 150_000 + 50_000 + 0.10 * clear
    special = bool(SPECIAL.search(name)) or any(k in cat for k in SPECIAL_CAT)
    reasons = []
    if special:
        reasons.append("특수·대형·폐차조건부(되팔 상대가 좁고 운반·등록이 어렵다)")
    elif price < 3_000_000:
        reasons.append(f"최저가 300만 미만 구간은 낙찰가율 중앙값이 {int(rate(price) * 100)}%(시세에 붙는다)")
    if not special and 3_000_000 <= price < 5_000_000 and dist_km is not None and dist_km >= 200:
        reasons.append(f"산본에서 {dist_km}km(탁송 약 {int(tow // 10000)}만원)")
    km = km or _km(name)
    if (ev or hyb) and (km or 0) >= 200_000:
        reasons.append("EV·하이브리드 20만km 이상(배터리)")
    return dict(verdict="제외" if reasons else "확인", reasons=reasons, clear=clear, extra=extra, tax=tax, tow=tow,
                breakeven=clear + extra, need_pct=extra / clear * 100 if clear else 0.0, kind=kind)
