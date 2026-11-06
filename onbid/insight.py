"""부동산(A 지분·D 단독)과 자동차(C)의 예상 낙찰가, 입찰 판정 근거, 지난 낙찰의 이유 추정. 동산(B)은 다루지 않는다.

리포트가 "입찰 비권고"만 되풀이하지 않도록, 코드가 숫자로 근거를 만든다.
- 예상 낙찰가: 같은 시·군의 최근 90일 토지/건물 낙찰(온비드 물건입찰결과) → 없으면 우리 추적 이력(tracked.json history)의
  '최저가 대비 낙찰가율' 중앙값 × 이번 최저가. 사분위 범위와 표본 수를 함께 낸다.
- 판정: 판정(⛔ 비권고 / ⏳ 회차 대기 / 🔍 조건부 검토)과 그 이유(숫자 포함), 그리고 '입찰할 수 있게 되는 조건'.
- 낙찰 이유 추정: 응찰자 수·낙찰가율·감정가 대비·당시 물건 특징(스냅숏)으로 가장 그럴듯한 낙찰자 유형과 근거.
  모두 '추정'이며 낙찰자가 누구인지는 공개되지 않는다.

숫자는 코드가 계산하고 리포트 모델은 그대로 옮긴다(손계산 오류 방지, ROUTINE_PROMPT 3-2).
"""
import re
import statistics

from . import analyze

TAX = 1.046                 # 토지 취득세 등(KNOWLEDGE 4-A)
REG_COST = 50_000           # 등기 실비
TRIP_COST = 30_000          # 우편·교통
TARGET = 300_000            # 목표이익
MIN_N = 3                   # 중앙값을 내는 최소 표본
SOLO_NEAR = 105.0           # 단독 응찰 + 최저가의 105% 이하 = '최저가 근처'
DUMP_RATIO = 30.0           # 감정가의 30% 이하 = 지분 매입업체 매입선(감정가 20~30%, KNOWLEDGE 6-A 4항 (미확인) 가정)


def _money(s):
    if s in (None, "", "-"):
        return None
    m = re.sub(r"[^\d]", "", str(s))
    return int(m) if m else None


def _f(v):
    try:
        x = float(v)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def won(n):
    return f"{int(n):,}원" if isinstance(n, (int, float)) else "-"


def _q(xs):
    """(1사분위, 중앙값, 3사분위). 3건 미만이면 None."""
    xs = sorted(x for x in xs if x)
    if len(xs) < MIN_N:
        return None
    if len(xs) < 4:
        return xs[0], statistics.median(xs), xs[-1]
    q = statistics.quantiles(xs, n=4, method="inclusive")
    return q[0], q[1], q[2]


def fails_of(it):
    m = re.search(r"\d+", str(it.get("fails") or ""))
    if m:
        return int(m.group())
    try:
        return int((it.get("row") or {}).get("uscbdCnt") or 0)
    except (TypeError, ValueError):
        return 0


# ───────────────────────── 같은 시·군 부동산 낙찰 사례 ─────────────────────────

def region_key(it):
    """물건명 앞 두 어절('경기도 남양주시')을 키워드로 쓴다. 온비드 결과 검색은 물건명 부분 일치다.
    '중구'·'동구'처럼 여러 시에 있는 구 이름 하나만으로는 다른 도시가 섞이므로 시·도 어절을 붙인다."""
    toks = (it.get("name") or "").split()
    if len(toks) >= 2 and re.search(r"(도|시)$", toks[0]) and re.fullmatch(r"[가-힣]+(시|군|구)", toks[1]):
        return f"{toks[0]} {toks[1]}"
    return None


def is_land(it_or_cat):
    cat = it_or_cat if isinstance(it_or_cat, str) else ((it_or_cat.get("row") or {}).get("ctgrFullNm") or "")
    return cat.startswith("토지")


def rlst_comps(rows, it, window=5):
    """같은 시·군 최근 90일 부동산 결과에서 이 물건과 비교할 만한 것(같은 토지/건물 구분, 최저가 1/5~5배)만 요약.
    rows 가 None 이면 조회 실패. 유찰 행도 세어 '개찰된 것 중 팔린 비율'을 낸다."""
    if rows is None:
        return {"failed": True}
    price = it.get("price") or 0
    land = is_land(it)
    mine = it.get("mng")

    def ok(r):
        if r.get("scrnIndctCltrMngNo") == mine:
            return False
        if is_land(r.get("ctgrFullNm") or "") != land:
            return False
        low = _money(r.get("lowstBidPrc"))
        return bool(low) and (not price or price / window <= low <= price * window)
    rel = [r for r in rows if ok(r)]
    sold = [r for r in rel if r.get("pbctStatNm") == "낙찰" and _money(r.get("onbidBidAmt"))]
    unsold = [r for r in rel if r.get("pbctStatNm") == "유찰"]
    rates, apprs, bidders = [], [], []
    for r in sold:
        bid, low, ap = _money(r.get("onbidBidAmt")), _money(r.get("lowstBidPrc")), _money(r.get("cltrApslEvlAvgAmt"))
        rate = _f(r.get("rateRow1")) or (round(bid / low * 100, 2) if bid and low else None)
        if rate:
            rates.append(rate)
        if bid and ap:
            apprs.append(bid / ap * 100)
        b = _money(r.get("totalBid"))
        if b:
            bidders.append(b)
    sold.sort(key=lambda r: r.get("pbctExctDt") or "", reverse=True)
    return {
        "n_sold": len(sold), "n_unsold": len(unsold), "rate_q": _q(rates), "appr_q": _q(apprs),
        "solo": sum(1 for b in bidders if b == 1), "n_bidders": len(bidders),
        "bidders_med": statistics.median(bidders) if bidders else None,
        "truncated": len(rows) >= 100, "kind": "토지" if land else "건물",
        "examples": [{"date": (r.get("pbctExctDt") or "")[:10], "name": (r.get("onbidCltrNm") or "")[:30],
                      "lowest": _money(r.get("lowstBidPrc")), "bid": _money(r.get("onbidBidAmt")),
                      "appr": _money(r.get("cltrApslEvlAvgAmt")), "bidders": _money(r.get("totalBid"))} for r in sold[:3]],
    }


# ───────────────────────── 우리 추적 이력 ─────────────────────────

def hist_stats(st, track):
    """tracked.json 의 낙찰 이력(history)과 결과가 난 추적 물건으로 트랙별 기준선을 만든다."""
    hs = [h for h in (st or {}).get("history") or [] if h.get("track") == track and h.get("status") == "낙찰"]
    rates = [_f(h.get("rate")) or (h["bid"] / h["lowest"] * 100 if h.get("bid") and _money(h.get("lowest")) else None) for h in hs]
    apprs = [h["bid"] / h["appraisal"] * 100 for h in hs if h.get("bid") and h.get("appraisal")]
    bidders = [h.get("bidders") for h in hs if h.get("bidders")]
    res = [(e.get("result") or {}).get("status") for e in ((st or {}).get("items") or {}).values() if e.get("track") == track]
    n_sold_items, n_unsold_items = sum(1 for s in res if s == "낙찰"), sum(1 for s in res if s == "유찰")
    errs = []
    for h in hs:                       # 예측 오차(예측을 남긴 이력만): 실제 낙찰가 ÷ 예측 낙찰가
        p = (h.get("feat") or {}).get("exp")
        if p and h.get("bid"):
            errs.append(h["bid"] / p * 100)
    return {"n": len(hs), "rate_q": _q([r for r in rates if r]), "appr_q": _q(apprs),
            "solo": sum(1 for b in bidders if b == 1), "n_bidders": len(bidders),
            "bidders_med": statistics.median(bidders) if bidders else None,
            "sold_items": n_sold_items, "unsold_items": n_unsold_items, "calib_q": _q(errs), "n_calib": len(errs)}


# ───────────────────────── 예상 낙찰가 ─────────────────────────

def expect(it, local=None, hist=None):
    """이번 최저가 × 낙찰가율(중앙값, 사분위). 같은 시·군 사례 3건 이상 → 우리 추적 이력 3건 이상 순으로 쓴다."""
    price = it.get("price") or 0
    if not price:
        return None
    for src, s in (("local", local), ("hist", hist)):
        if s and not s.get("failed") and s.get("rate_q"):
            q1, med, q3 = s["rate_q"]
            n = s.get("n_sold") if src == "local" else s.get("n")
            return {"src": src, "n": n, "lo": int(price * q1 / 100), "mid": int(price * med / 100),
                    "hi": int(price * q3 / 100), "rate": round(med, 1), "rate_lo": round(q1, 1), "rate_hi": round(q3, 1)}
    return None


def need_sell(bid):
    """이 값에 낙찰받았을 때 본전 + 목표이익(30만)을 남기려면 받아야 할 매도가."""
    return int(bid * TAX + REG_COST + TRIP_COST + TARGET)


def _first_round_under(it, cap):
    sched = it.get("schedule") or []
    cur = (it.get("round") or "").split("/")[0]
    after = not any(r["no"].split("/")[0] == cur for r in sched)
    for r in sched:
        if r["no"].split("/")[0] == cur:
            after = True
        if after and r["price"] <= cap:
            return r
    return None


# ───────────────────────── 판정 ─────────────────────────

def verdict_land(it, track, ex, local=None, hist=None):
    """A·D 판정. 반환 {call, reasons:[(기호, 글)], unlock:[글]}. 기호 ⛔ 막는 이유 / ⚠ 감점 / ✅ 유리 / ℹ 참고."""
    appr, price = it.get("appraisal") or 0, it.get("price") or 0
    e = it.get("exit") or analyze.exit_numbers(it)
    cap, bcap, loss = e.get("exit_cap"), e.get("budget_cap"), e.get("loss")
    R, unlock, stop = [], [], []
    b = it.get("basis") or {}
    if track == "A":
        if it.get("bad_exit"):
            stop.append("맹지·분묘 문구가 감정평가서·유의사항에 있음 → 지분을 살 사람이 공유자 말고는 거의 없다")
        if it.get("land_class") == "농지":
            R.append(("⚠", "농지 — 농지취득자격증명이 필요하고, 지분 농지는 발급이 까다롭다"))
        for sev, m in it.get("appr_flags") or []:
            if sev == "R" and m != "맹지":
                stop.append(f"감정평가서: {m}")
        if b.get("인수권리") or b.get("지상권개요") or b.get("존속권리"):
            stop.append("매수인이 인수할 권리가 명세서·등기에 있음: " + " / ".join((b.get("인수권리") or []) + (b.get("지상권개요") or []) + (b.get("존속권리") or []))[:120])
        if b.get("점유") or b.get("임대차") or b.get("명세서점유행") or b.get("명세서임차행"):
            R.append(("⚠", f"점유 {b.get('점유') or 0}건·임대차 {b.get('임대차') or 0}건 — 명도 책임이 생길 수 있다"))
        n_co = b.get("공유자수") or 0
        if n_co:
            R.append(("⚠", f"공유자 {n_co}명: 공유자는 최고가와 같은 값에 우선매수할 수 있어(국세징수법 제79조) 이겨도 뺏길 수 있다. "
                           "반대로 이 공유자가 가장 유력한 출구 상대다"))
        elif b.get("정보부족"):
            R.append(("ℹ", "등기 주요정보가 0건이라 공유자 이름·인원을 볼 수 없다"))
        if it.get("natural_hint"):
            R.append(("⚠", "감정평가서 이용상태가 자연림·임야 — 쓰는 사람이 없는 산이라 인접지주 매수 동기가 약하다"))
        if it.get("caution_flags"):
            R.append(("⚠", f"현황도로 표기({', '.join(it['caution_flags'])}) — 지자체 보상·부당이득 청구는 어렵다(KNOWLEDGE 2-6)"))
        unlock.append("공유자·인접지주 이름을 등기 주요정보에서 특정하고, 아래 '필요한 매도가' 이상에 사겠다는 의사를 입찰 전에 확인")
    else:
        for sev, m in it.get("risk_flags") or []:
            if sev == "R":
                stop.append(m)
        ys = [m for sev, m in it.get("risk_flags") or [] if sev == "Y"]
        if ys:
            R.append(("⚠", "확인 필요: " + ", ".join(ys[:4])))
        if it.get("deposit_sum"):
            R.append(("⚠", f"보증금 {won(it['deposit_sum'])}을 인수하면 총부담 {won(price + it['deposit_sum'])}"))
        if it.get("ratio") is not None and it["ratio"] <= 15 and it.get("land_class") == "건물":
            R.append(("⚠", f"최저가가 감정가의 {it['ratio']}% — 건물이 이 정도로 싸면 인수금·점유가 값에 들어 있는 경우가 많다"))
    if e.get("over_budget"):
        stop.append(f"최저가가 예산 상한 {won(bcap)}을 넘는다(취득세·등기비까지 1,000만원 초과)")
    if cap is not None and cap <= 0:
        stop.append(f"감정가 {won(appr)}의 70%에서 실비·목표이익 38만원을 빼면 남는 돈이 없다 — 어떤 값에 사도 이익 구조가 아니다")

    fails = fails_of(it)
    if appr and price:
        R.append(("ℹ", f"유찰 {fails}회로 감정가의 {price / appr * 100:.0f}%까지 내려왔다"
                       + (" — 이만큼 안 팔린 데는 이유(진입로·경사·분묘·쓸모)가 있다" if fails >= 5 else "")))
    if ex:
        src = "같은 시·군 최근 90일" if ex["src"] == "local" else "우리 추적 이력"
        R.append(("ℹ", f"예상 낙찰가 {won(ex['mid'])}(범위 {won(ex['lo'])}~{won(ex['hi'])}) — {src} 낙찰 {ex['n']}건의 최저가 대비 {ex['rate']}%"
                       f"(사분위 {ex['rate_lo']}~{ex['rate_hi']}%)"))
    s = local if local and local.get("n_sold") else hist
    if s and s.get("n_bidders"):
        R.append(("ℹ", f"{'같은 시·군' if s is local else '추적 이력'} 낙찰 {s['n_bidders']}건 중 {s['solo']}건이 응찰 1명"
                       + (" — 경쟁은 약하지만 그만큼 사려는 사람도 적다는 뜻(되팔 상대가 얕다)" if s["solo"] * 2 >= s["n_bidders"] else " — 경쟁이 붙는 지역")))
    if local and not local.get("failed") and local.get("n_sold", 0) + local.get("n_unsold", 0) >= 5:
        tot = local["n_sold"] + local["n_unsold"]
        R.append(("ℹ", f"같은 시·군 비슷한 가격대 {local['kind']} 개찰 {tot}회 중 낙찰 {local['n_sold']}회({local['n_sold'] / tot * 100:.0f}%)"))

    mid = ex["mid"] if ex else price
    sell = need_sell(mid)
    if appr:
        R.append(("ℹ", f"{'예상 낙찰가' if ex else '최저가'} {won(mid)}에 사면 본전+목표이익 30만에 필요한 매도가 {won(sell)}(감정가의 {sell / appr * 100:.0f}%)"))
    if cap and cap > 0 and ex:
        lim = min(cap, bcap or cap)
        if ex["mid"] > lim:
            R.append(("⛔", f"예상 낙찰가 {won(ex['mid'])} > 출구 상한 {won(lim)} — 이기려면 상한보다 {won(ex['mid'] - lim)} 더 써야 한다"))
            stop.append("경쟁선이 출구 상한 위")
        else:
            R.append(("✅", f"예상 낙찰가가 출구 상한 {won(lim)} 이하(여유 {won(lim - ex['mid'])}, 상한은 감정가로 잡은 위쪽 한계)"))
    if loss is not None:
        R.append(("⚠" if loss > 0 else "ℹ", f"못 팔고 감정가의 20%(미확인 가정)로 넘기면 손실 약 {won(max(loss, 0))}"
                                            + (f" — 최저가의 {loss / price * 100:.0f}%" if loss > 0 and price else "")))

    if stop:
        call = "⛔ 입찰 비권고"
    elif cap and cap > 0:
        fu = _first_round_under(it, min(cap, bcap or cap))
        cur = (it.get("round") or "").split("/")[0]
        if fu and fu["no"].split("/")[0] != cur:
            call = f"⏳ 회차 대기 — {fu['no']}회({fu['start'][:10]}) {won(fu['price'])}부터 상한 이하"
            unlock.append(f"{fu['no']}회 {won(fu['price'])}까지 유찰되기를 기다리기")
        elif fu or price <= min(cap, bcap or cap):
            call = "🔍 조건부 검토 — 출구 상대를 특정할 때만" if track == "A" else "🔍 조건부 검토 — 위험 신호·현장 확인 후"
        else:
            call = "⛔ 입찰 비권고"
            stop.append("등록된 회차표에 출구 상한 이하 회차가 없다")
    else:
        call = "🔍 판단 보류 — 감정가 정보 없음"
    return {"call": call, "stop": stop, "reasons": R, "unlock": unlock, "need_sell": sell, "exp": ex}


def verdict_car(it, ex):
    """C 판정. 시세를 모르므로 '본전 시세'를 내고, 동종 낙찰의 경쟁 정도와 차 상태 문구로 근거를 만든다."""
    a = it.get("assess") or {}
    c = it.get("comps") or {}
    price = it.get("price") or 0
    R, stop, unlock = [], [], []
    flags = " ".join(it.get("flags") or []) + " " + " ".join(it.get("notes") or [])
    if re.search(r"운행\s*불가|시동\s*불가|시동\s*불량|엔진\s*(고장|불량)|부품\s*(탈거|적출)|침수|폐차", flags):
        stop.append("공고에 운행·시동 불가, 침수·폐차 같은 문구 — 바닥가(폐차·수출가) 이하로만 의미가 있다(KNOWLEDGE 3-C)")
    if it.get("year") and isinstance(it["year"], int) and it["year"] <= 2009 and "경유" in str(it.get("fuel") or ""):
        R.append(("ℹ", "2009년 이전 경유차 — 조기폐차 지원금 대상일 수 있으나 조건부(6개월 소유 등), 수출 시장은 2026년 약세"))
    if it.get("km") and it["km"] >= 200_000:
        R.append(("⚠", f"주행 {it['km']:,}km — 내차팔기 견적이 크게 깎이는 구간"))
    clear = a.get("clear")
    if ex and clear:
        tax_r = (a.get("tax") or 0) / clear
        fixed = (a.get("extra") or 0) - (a.get("tax") or 0) - 0.10 * clear
        be = int(ex["mid"] * (1 + tax_r + 0.10) + fixed)
        R.append(("ℹ", f"예상 낙찰가 {won(ex['mid'])}(동종 {ex['n']}건 최저가 대비 {ex['rate']}%, 범위 {won(ex['lo'])}~{won(ex['hi'])}) → "
                       f"본전 시세 약 {won(round(be, -4))}(취득세·탁송·상품화·예비비 포함, 가정치)"))
    elif clear:
        be = int(a.get("breakeven") or 0)
        R.append(("ℹ", f"동종 사례가 부족해 구간표(최저가 {won(price)} 구간 {clear / price * 100:.0f}%)로 예상 낙찰가 {won(round(clear, -3))}, "
                       f"본전 시세 약 {won(round(be, -4))}"))
    else:
        be = None
    if c and c.get("n_sold"):
        exs = c.get("examples") or []
        solo = sum(1 for x in exs if x.get("bidders") == 1)
        bmed = statistics.median([x["bidders"] for x in exs if x.get("bidders")]) if any(x.get("bidders") for x in exs) else None
        if c.get("median_rate") and c["median_rate"] >= 150:
            R.append(("⚠", f"동종 낙찰가율 중앙값 {c['median_rate']}% — 업자·수출상이 시세 근처까지 써 낸다. 최저가 근처 입찰은 거의 지고, 이기면 시세에 산 것"))
        if bmed:
            R.append(("ℹ", f"최근 사례 응찰자 중앙값 {bmed:g}명" + (f"(단독 응찰 {solo}건)" if solo else "")))
    unlock.append("엔카·헤이딜러에서 같은 연식·주행 시세가 본전 시세보다 확실히 높은지 확인" + (f"(본전 약 {won(round(be, -4))})" if be else ""))
    unlock.append("감정평가표의 시동·운행 판정과 사고이력이 깨끗할 것")
    call = "⛔ 입찰 비권고" if stop else "🔍 시세 비교 후 판단"
    return {"call": call, "stop": stop, "reasons": R, "unlock": unlock, "exp": ex, "breakeven": be}


def car_expect(it):
    c = it.get("comps") or {}
    price = it.get("price") or 0
    rates = []
    if c.get("median_rate") and price:
        # comps_summary 는 중앙값만 남기므로 사례 낙찰가율로 범위를 만든다(사례 3~5건)
        rates = [x["rate"] for x in c.get("examples") or [] if x.get("rate")]
        q = _q(rates) or (c["median_rate"], c["median_rate"], c["median_rate"])
        return {"src": "comps", "n": c.get("n_rates") or c.get("n_sold"), "mid": int(price * c["median_rate"] / 100),
                "lo": int(price * q[0] / 100), "hi": int(price * q[2] / 100), "rate": c["median_rate"],
                "rate_lo": round(q[0], 1), "rate_hi": round(q[2], 1)}
    return None


def build(track, it, local=None, hist=None):
    """후보 하나의 인사이트. it['insight'] 에 넣는다."""
    if track in ("A", "D"):
        ex = expect(it, local, hist)
        v = verdict_land(it, track, ex, local, hist)
        v["local"] = local
    elif track == "C":
        v = verdict_car(it, car_expect(it))
    else:
        return None
    return v


def lines(it):
    """초안에 넣을 줄. 숫자는 코드 산출 — 리포트에 그대로 옮긴다."""
    v = it.get("insight")
    if not v:
        return []
    L = [f"- 🧭 판정(코드 산출 — 그대로 옮기고 이유를 빼지 말 것): **{v['call']}**"]
    for s in v.get("stop") or []:
        L.append(f"  - ⛔ {s}")
    for sym, t in v.get("reasons") or []:
        if sym == "⛔" and any(t.startswith("예상 낙찰가") for t in v.get("stop") or []):
            continue
        L.append(f"  - {sym} {t}")
    if v.get("unlock"):
        L.append("  - 🔓 입찰할 수 있게 되는 조건: " + " / ".join(v["unlock"]))
    loc = v.get("local")
    if loc and loc.get("failed"):
        L.append("  - (같은 시·군 낙찰 사례 조회 실패 — 추적 이력으로 대신 계산)")
    elif loc and loc.get("examples"):
        ex = "; ".join(f"{x['date'][5:]} {x['name'][:20]} 최저 {x['lowest']:,}→{x['bid']:,}원"
                       + (f"(감정가의 {x['bid'] / x['appr'] * 100:.0f}%" if x.get("appr") else "(")
                       + (f", {x['bidders']}명)" if x.get("bidders") else ")") for x in loc["examples"] if x.get("lowest") and x.get("bid"))
        if ex:
            L.append(f"  - 같은 시·군 최근 낙찰: {ex}" + (" ※ 조회 상한 100건에 걸림" if loc.get("truncated") else ""))
    return L


# ───────────────────────── 추적 스냅숏과 낙찰 이유 추정 ─────────────────────────

def snapshot(track, it):
    """추적 목록에 남길 당시 특징. 낙찰 뒤 '왜 팔렸나'를 근거로 쓰기 위해 저장한다."""
    v = it.get("insight") or {}
    ex = v.get("exp") or {}
    s = {"fails": fails_of(it), "dist": it.get("dist"), "call": v.get("call"), "exp": ex.get("mid"),
         "need_sell": v.get("need_sell"), "cat": (it.get("row") or {}).get("ctgrFullNm")}
    if track in ("A", "D"):
        b = it.get("basis") or {}
        e = it.get("exit") or {}
        s.update(grade=it.get("grade"), co=b.get("공유자수"), share=it.get("share_ratio"), natural=it.get("natural_hint"),
                 bad_exit=it.get("bad_exit"), road=bool(it.get("caution_flags")), favor=it.get("favor_flags") or None,
                 dev=min((d["tier"] for d in it.get("dev") or []), default=None), exit_cap=e.get("exit_cap"),
                 risk=[m for sv, m in it.get("risk_flags") or [] if sv == "R"][:3] or None)
    elif track == "C":
        s.update(year=it.get("year"), km=it.get("km"), fuel=it.get("fuel"), comp_rate=(it.get("comps") or {}).get("median_rate"),
                 breakeven=v.get("breakeven"))
    return {k: x for k, x in s.items() if x not in (None, [], "")}


def explain(r, feat=None):
    """낙찰·유찰 결과 한 건의 이유 추정. r: 결과(bid, rate, bidders, lowest, appraisal, track, status). 반환: 글 목록."""
    feat = feat or {}
    tr, st = r.get("track"), r.get("status")
    if tr not in ("A", "C", "D"):
        return []
    bid, appr, low = r.get("bid"), r.get("appraisal"), _money(r.get("lowest"))
    rate = _f(r.get("rate")) or (bid / low * 100 if bid and low else None)
    n = r.get("bidders") or 0
    ap = bid / appr * 100 if bid and appr else None
    out = []
    if st == "유찰":
        out.append(f"응찰 {n}명 — 최저가 {won(low)}" + (f"(감정가의 {low / appr * 100:.0f}%)" if low and appr else "")
                   + "에도 사려는 사람이 없었다. 이 값도 비싸다고 본 것이고 다음 회차에서 10%p씩 더 내려간다")
        if feat.get("bad_exit") or feat.get("natural"):
            out.append("당시 맹지·분묘 또는 자연림 신호가 있었다 — 쓸 사람이 없는 땅은 유찰이 길어진다")
        return out
    if st not in ("낙찰", "낙찰(낙찰후취소)") or not bid:
        return []
    if tr in ("A", "D"):
        if n == 1 and rate and rate <= SOLO_NEAR:
            who = "공유자·인접지주(쓸모가 있는 사람)나 지분 매입업체" if tr == "A" else "인접지주·실수요자나 토지 매입업자"
            out.append(f"단독 응찰·최저가의 {rate:.1f}% — 경쟁자 없이 '이 값이면 산다'는 한 사람이 산 패턴. {who}로 추정")
        elif n >= 2 and rate and rate > 110:
            out.append(f"{n}명 경쟁·최저가의 {rate:.1f}% — 이 땅을 원하는 사람이 여럿이었다(진입로·지목·위치 등 쓸모가 보였을 가능성)")
        else:
            out.append(f"응찰 {n}명·최저가의 {rate:.1f}% — 경쟁이 약했고 최저가를 조금 넘겨 써 낸 정도" if rate else f"응찰 {n}명")
        if ap is not None:
            if ap <= DUMP_RATIO:
                out.append(f"감정가의 {ap:.0f}%에 팔림 — 지분 매입업체 매입선(감정가 20~30%, 미확인 가정)에 닿은 가격이라 업체 매입 가능성")
            elif ap >= 70:
                out.append(f"감정가의 {ap:.0f}%에 팔림 — 감정가 근처를 써 낸 것은 직접 쓸 사람(공유자·인접지주·실수요)일 가능성이 높다")
            else:
                out.append(f"감정가의 {ap:.0f}%에 팔림")
        if feat.get("co"):
            out.append(f"당시 공유자 {feat['co']}명 — 공유자 우선매수였는지는 공개되지 않는다")
        if feat.get("fails") is not None:
            out.append(f"당시 유찰 {feat['fails']}회 뒤")
        if feat.get("exit_cap"):
            cap = feat["exit_cap"]
            out.append(f"우리 출구 상한 {won(cap)} 대비 낙찰가 {won(bid)}"
                       + (" — 상한보다 높게 샀다: 낙찰자는 우리보다 높은 출구(직접 사용·공유자 지위)를 봤을 것" if bid > cap
                          else " — 상한 이하에서 팔렸다: 출구 상대를 특정할 수 있었다면 기회였을 수 있다(복기 대상)"))
    else:
        if n >= 5 and rate and rate >= 130:
            out.append(f"{n}명 경쟁·최저가의 {rate:.0f}% — 저가 차량은 중고상·수출업자가 되팔 시세 근처까지 써 낸다")
        elif n == 1 and rate and rate >= 130:
            out.append(f"단독 응찰인데 최저가의 {rate:.0f}% — 다른 응찰자를 의식하지 않고 자기 매입 상한을 쓴 것(차 상태·시세를 아는 업자 추정)")
        elif n <= 2 and rate and rate <= SOLO_NEAR + 5:
            out.append(f"응찰 {n}명·최저가의 {rate:.0f}% — 수요가 얕았다(상태·연식·차종 문제 가능)")
        else:
            out.append(f"응찰 {n}명·최저가의 {rate:.0f}%" if rate else f"응찰 {n}명")
        if feat.get("comp_rate"):
            out.append(f"당시 동종 중앙값 {feat['comp_rate']}%")
        if feat.get("breakeven"):
            out.append(f"당시 계산한 본전 시세 {won(feat['breakeven'])}")
        if st == "낙찰(낙찰후취소)":
            out.append("낙찰 후 취소 — 낙찰자가 대금을 안 냈거나 취소됐다(보증금 몰수 가능성, 다음 회차 재공매 확인)")
    if feat.get("exp"):
        out.append(f"예측 {won(feat['exp'])} → 실제 {won(bid)}(예측의 {bid / feat['exp'] * 100:.0f}%)")
    return out


def lessons(st):
    """트랙별 누적 낙찰 기준선 한 줄씩(동산 제외)."""
    out = []
    for tr, nm in (("A", "지분"), ("D", "단독 부동산"), ("C", "자동차")):
        h = hist_stats(st, tr)
        if not h["n"]:
            continue
        rq = h["rate_q"]
        aq = h["appr_q"]
        t = f"{nm}({tr}) 낙찰 {h['n']}건"
        if rq:
            t += f": 최저가 대비 중앙값 {rq[1]:.1f}%(사분위 {rq[0]:.1f}~{rq[2]:.1f}%)"
        if aq:
            t += f", 감정가 대비 중앙값 {aq[1]:.0f}%"
        if h["n_bidders"]:
            t += f", 응찰 1명 {h['solo']}/{h['n_bidders']}건"
        if h["sold_items"] + h["unsold_items"]:
            t += f" · 추적 물건 최근 결과 낙찰 {h['sold_items']}·유찰 {h['unsold_items']}"
        if h["calib_q"]:
            t += f" · 예측 대비 실제 중앙값 {h['calib_q'][1]:.0f}%({h['n_calib']}건)"
        out.append(t)
    return out
