"""검토·추천 물건 추적과 낙찰 결과·동종 낙찰 사례.

상태 파일(onbid/state/tracked.json)은 저장소에 커밋한다. 루틴은 매번 새 컨테이너에서 돌기 때문에
커밋하지 않으면 어제 무엇을 추천했는지 잊는다.

  python3 -m onbid.track mark <out> <물건관리번호>...   # 오늘 리포트에 실은 물건 표시
  python3 -m onbid.track show                           # 추적 현황
"""
import datetime
import json
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("ONBID_STATE") or os.path.join(HERE, "state", "tracked.json")
TYPE = {"A": "0001", "B": "0003", "C": "0002"}
FINAL = ("낙찰", "낙찰(낙찰후취소)", "취소")
OPEN_STATES = ("입찰마감", "개찰중", "개찰미진행", "입찰진행중", "입찰준비중")
KEEP_DAYS = 45          # 마지막으로 본 날부터 이만큼 지나면 추적을 끝낸다


def load():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"items": {}, "history": []}


def save(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1, sort_keys=True)


def _money(s):
    if s in (None, "", "-"):
        return None
    m = re.sub(r"[^\d]", "", str(s))
    return int(m) if m else None


def _deadline(it):
    m = re.findall(r"\d{4}-\d\d-\d\d \d\d:\d\d", it.get("period") or "")
    return m[-1] if m else (it.get("row") or {}).get("pbctDdlnDt")


def add_candidates(st, today, tracks):
    """오늘 사진까지 본 후보를 추적 목록에 넣는다. 이미 있으면 마지막 확인 정보만 갱신."""
    for track, items in tracks.items():
        for it in items:
            e = st["items"].setdefault(it["mng"], {"track": track, "first_seen": today, "reported": []})
            e.update(track=track, name=(it.get("display") or it.get("name") or "")[:60], link=it.get("link"),
                     last_seen=today, price=it.get("price"), appraisal=it.get("appraisal"),
                     deadline=_deadline(it), open_dt=(it.get("row") or {}).get("pbctExctDt"), type=TYPE[track])


def mark_reported(st, today, mngs):
    for m in mngs:
        if m in st["items"]:
            r = st["items"][m].setdefault("reported", [])
            if today not in r:
                r.append(today)


def due(st, now):
    """개찰일이 지났는데 결과가 확정되지 않은 물건.
    유찰된 물건은 다음 회차로 다시 검색되면 개찰일이 갱신된다. 그 전에는 매일 대신 일주일에 한 번만 다시 본다."""
    week_ago = (datetime.date.fromisoformat(now[:10]) - datetime.timedelta(days=7)).isoformat()
    out = []
    for m, e in st["items"].items():
        if e.get("final"):
            continue
        dl = e.get("open_dt") or e.get("deadline") or ""
        if not dl or dl[:16] > now:
            continue
        r = e.get("result") or {}
        if (r.get("opened") or "")[:16] >= dl[:16] and (e.get("result_checked") or "") > week_ago:
            continue
        out.append({"mng": m, "type": e.get("type", "0001")})
    return out


def apply_results(st, results, today):
    """조회 결과로 상태를 갱신하고, 이번에 새로 확정되거나 바뀐 것을 돌려준다."""
    changed = []
    for m, rows in (results or {}).items():
        e = st["items"].get(m)
        if e is None or rows is None:
            continue
        e["result_checked"] = today
        since = (e.get("first_seen") or "0000")[:10]
        rows = [r for r in rows if (r.get("pbctExctDt") or "")[:10] >= since]
        done = [r for r in rows if r.get("pbctStatNm") not in OPEN_STATES]
        if not done:
            continue
        last = max(done, key=lambda r: r.get("pbctExctDt") or "")
        res = {"status": last.get("pbctStatNm"), "round": last.get("pbctNsq"), "opened": last.get("pbctExctDt"),
               "lowest": last.get("lowstBidPrc"), "bid": _money(last.get("onbidBidAmt")),
               "rate": last.get("rateRow1"), "bidders": _money(last.get("totalBid"))}
        if res != e.get("result"):
            e["result"] = res
            changed.append(m)
        if res["status"] in FINAL:
            e["final"] = True
            st["history"].append({"mng": m, "track": e["track"], "name": e.get("name"), "reported": bool(e.get("reported")),
                                  "appraisal": e.get("appraisal"), **res})
    return changed


def prune(st, today):
    cut = (datetime.date.fromisoformat(today) - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    for m in [m for m, e in st["items"].items() if (e.get("last_seen") or e.get("first_seen")) < cut]:
        del st["items"][m]
    st["history"] = st["history"][-2000:]


# ───────────────────────── 동종 낙찰 사례 ─────────────────────────

def comp_keyword(track, it):
    kv = it.get("kv", {})
    good = lambda v: v and v not in ("-", "미상")
    if track == "C":
        for k in ("모델명", "차종"):
            if good(kv.get(k)):
                return re.sub(r"\s+", "", kv[k])[:10]
        m = re.search(r"(모닝|스파크|레이|아반떼|쏘나타|그랜저|투싼|스포티지|싼타페|쏘렌토|카니발|스타렉스|포터|봉고|모하비|코란도|티볼리|K3|K5|K7)", it.get("name") or "")
        return m.group(1) if m else None
    nm = (it.get("display") or it.get("name") or "")
    for pat, kw in ((r"순금|24K", "순금"), (r"18K", "18K"), (r"14K", "14K"), (r"금거북|거북", "거북"), (r"금두꺼비|두꺼비", "두꺼비"),
                    (r"노트북", "노트북"), (r"소니|SONY", "소니"), (r"캐논|Canon", "캐논"), (r"니콘|Nikon", "니콘"),
                    (r"카메라|미러리스|DSLR", "디지털카메라")):
        if re.search(pat, nm, re.I):
            return kw
    if good(kv.get("모델명")):
        return kv["모델명"][:10]
    return None


def _rate(r):
    """최저가 대비 낙찰가율(%). 응답에 비어 있으면 낙찰가/최저가로 계산."""
    v = r.get("rateRow1")
    try:
        if v not in (None, "", "-") and float(v) > 0:
            return float(v)
    except ValueError:
        pass
    bid, low = _money(r.get("onbidBidAmt")), _money(r.get("lowstBidPrc"))
    return round(bid / low * 100, 2) if bid and low else None


NOISE = re.compile(r"안저|감마|의료|내시경|초음파|CCTV|블랙박스|산업용|측정|실험|방송|CCU|중계")
# 여러 물건을 한 번에 파는 묶음은 단품 시세와 비교가 안 된다
LOT = re.compile(r"등\s*\d+\s*(점|종|대|개|건)|외\s*\d*\s*(점|종|대|개|건)|일괄|[^,]+,[^,]+,")


def comps_summary(rows, exclude=None, limit=5, price=None):
    """낙찰 건만 골라 최근순 요약 + 낙찰가율 중앙값.
    의료·방송 장비, 여러 물건 묶음, 이번 물건과 최저가가 5배 넘게 차이 나는 건은 뺀다. 낙찰가율이 3건 미만이면 중앙값을 내지 않는다."""
    def comparable(r):
        low = _money(r.get("lowstBidPrc"))
        return not (price and low and not price / 5 <= low <= price * 5)
    sold = [r for r in rows or [] if r.get("pbctStatNm") == "낙찰" and _money(r.get("onbidBidAmt"))
            and r.get("scrnIndctCltrMngNo") != exclude and r.get("dspsMthodCdNm") in (None, "매각")
            and not NOISE.search((r.get("onbidCltrNm") or "") + (r.get("ctgrFullNm") or ""))
            and not LOT.search(r.get("onbidCltrNm") or "") and comparable(r)]
    sold.sort(key=lambda r: r.get("pbctExctDt") or "", reverse=True)
    rates = [x for x in (_rate(r) for r in sold) if x]
    return {
        "n_sold": len(sold), "n_all": len(rows or []), "n_rates": len(rates),
        "median_rate": round(statistics.median(rates), 1) if len(rates) >= 3 else None,
        "examples": [{"date": (r.get("pbctExctDt") or "")[:10], "name": (r.get("onbidCltrNm") or "")[:40],
                      "lowest": _money(r.get("lowstBidPrc")), "bid": _money(r.get("onbidBidAmt")), "rate": _rate(r),
                      "bidders": _money(r.get("totalBid")), "region": r.get("sidoEmd")} for r in sold[:limit]],
    }


def run_results(js_dir, work, items, keywords):
    """results.js를 한 번 돌려 물건별·키워드별 결과를 받는다. 실패하면 None."""
    inp, outp = os.path.join(work, "_results_in.json"), os.path.join(work, "_results_out.json")
    with open(inp, "w") as f:
        json.dump({"items": items, "keywords": keywords}, f, ensure_ascii=False)
    try:
        r = subprocess.run(["node", os.path.join(js_dir, "results.js"), inp, outp], timeout=1800)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0 or not os.path.exists(outp):
        return None
    with open(outp) as f:
        return json.load(f)


def main():
    args = sys.argv[1:]
    st = load()
    today = datetime.date.today().isoformat()
    if args[:1] == ["mark"]:
        # 사진 검토 범위 밖에서 대체 후보를 골랐을 수도 있으니, 추적 목록에 없으면 candidates.json에서 넣는다.
        mngs = args[2:]
        cand = os.path.join(args[1], "candidates.json") if len(args) > 1 else ""
        if os.path.exists(cand):
            with open(cand, encoding="utf-8") as f:
                data = json.load(f)
            today = data.get("today") or today
            missing = [m for m in mngs if m not in st["items"]]
            add_candidates(st, today, {t: [it for it in data.get(t, []) if it["mng"] in missing] for t in TYPE})
        mark_reported(st, today, mngs)
        save(st)
        unknown = [m for m in mngs if m not in st["items"]]
        print(f"표시 {len(mngs) - len(unknown)}건" + (f", 후보 목록에 없음: {' '.join(unknown)}" if unknown else ""))
    elif args[:1] == ["show"]:
        items = st["items"]
        print(f"추적 {len(items)}건, 리포트 실린 것 {sum(1 for e in items.values() if e.get('reported'))}건, "
              f"결과 확정 {sum(1 for e in items.values() if e.get('final'))}건, 이력 {len(st['history'])}건")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
