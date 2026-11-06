#!/usr/bin/env python3
"""온비드 스카우팅 실행기(평일 저녁 루틴이 쓴다).

  python3 -m onbid.run --out out/onbid            # 전체(검색→상세→사진·감정평가서→초안)
  python3 -m onbid.run --out out/onbid --skip-search   # 검색 결과 재사용

결과물
  <out>/candidates.json   후보별 전체 데이터(등급·근거·회차표·지원금 추정·사진 경로)
  <out>/report_draft.md   리포트 초안. ⟪…⟫ 자리는 모델이 사진·감정평가서를 보고 채운다.
  <out>/media/<물건관리번호>/photos_sheet.jpg, appraisal_sheet*.jpg, apsl-pNN.png
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request

try:
    import PIL  # noqa: F401  (media.py가 쓴다)
except ImportError:
    sys.exit("이 파이썬에는 Pillow(PIL)가 없습니다. 루틴 컨테이너는 기본 python3(3.11)에 Pillow가 없을 수 있으니 "
             "Pillow가 든 /usr/bin/python3 로 다시 실행하세요: /usr/bin/python3 -m onbid.run --out out/onbid  (pip 설치는 막혀 있습니다)")

from . import analyze as A
from . import config as C
from . import devzone, media, parse, report, track

HERE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(HERE, "js")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def node(script, *args, timeout=3600):
    return subprocess.run(["node", os.path.join(JS, script), *map(str, args)], timeout=timeout)


def drop_closed(search, cutoff):
    """검색 결과 행 중 마감(pbctDdlnDt)이 cutoff(KST, tz 없는 datetime)보다 이른 것을 뺀다. 마감 시각을 못 읽는 행은 남긴다. 뺀 행 수를 돌려준다."""
    n = 0
    for k in list(search):
        rows = (search[k] or {}).get("rows") or []
        keep = []
        for r in rows:
            try:
                dl = datetime.datetime.strptime((r.get("pbctDdlnDt") or r.get("pbctLastDdlnDt") or "")[:16], "%Y-%m-%d %H:%M")
            except ValueError:
                dl = None
            if dl is not None and dl < cutoff:
                n += 1
            else:
                keep.append(r)
        search[k] = {**search[k], "rows": keep}
    return n


def run_details(rows, items_dir, workers):
    """상세 수집을 여러 브라우저로 나눠 돌린다. 끝나지 않은 물건은 한 번 더 시도한다."""
    for attempt in range(2):
        todo = [r for r in rows if not os.path.exists(os.path.join(items_dir, r["scrnIndctCltrMngNo"] + ".done"))]
        if not todo:
            return
        n = max(1, min(workers if attempt == 0 else 2, len(todo)))
        log(f"상세 수집 {len(todo)}건 / 브라우저 {n}개 (시도 {attempt + 1})")
        procs = []
        for i in range(n):
            pool = os.path.join(items_dir, f"_pool{i}.json")
            with open(pool, "w") as f:
                json.dump(todo[i::n], f)
            lf = open(os.path.join(items_dir, f"_worker{i}.log"), "a")
            procs.append(subprocess.Popen(["node", os.path.join(JS, "details.js"), pool, items_dir], stdout=lf, stderr=lf))
        deadline = time.time() + 3600
        for p in procs:
            try:
                p.wait(timeout=max(1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                p.kill()


def verify_link(url, mng):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": media.UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status == 200 and mng in r.read().decode("utf-8", "ignore")
        except Exception:
            time.sleep(2 * (i + 1))
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/onbid")
    ap.add_argument("--skip-search", action="store_true")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--today", help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--no-media", action="store_true")
    ap.add_argument("--no-results", action="store_true", help="낙찰 결과·동종 낙찰 사례 조회 생략")
    ap.add_argument("--no-state", action="store_true", help="추적 상태 파일을 저장하지 않음(시험용)")
    args = ap.parse_args()
    kst = datetime.timezone(datetime.timedelta(hours=9))
    today = datetime.date.fromisoformat(args.today) if args.today else datetime.datetime.now(kst).date()
    out = args.out
    items_dir, media_dir = os.path.join(out, "items"), os.path.join(out, "media")
    os.makedirs(items_dir, exist_ok=True)

    # 1. 검색
    if not (args.skip_search and all(os.path.exists(os.path.join(out, f"search_{k}.json")) for k in "ABC")):
        log("온비드 조건검색 중...")
        try:
            rc = node("search.js", out, C.BUDGET_RLST, C.BUDGET_MVAST, C.CAR_MAX, timeout=1800).returncode
        except (subprocess.TimeoutExpired, OSError) as e:      # 시간 초과, node 없음
            log(f"검색 실행 오류: {type(e).__name__} {e}")
            rc = -1
        if rc != 0:
            report.write_failure(out, today, "온비드 조건검색 접속 실패")
            log("검색 실패 — 실패 리포트만 작성")
            return 2
    try:
        search = {k: json.load(open(os.path.join(out, f"search_{k}.json"))) for k in "ABC"}
    except (OSError, ValueError) as e:
        report.write_failure(out, today, f"검색 결과 파일을 읽지 못함({type(e).__name__})")
        log(f"검색 결과 파일 오류 — 실패 리포트만 작성: {e}")
        return 2
    if not any(search[k].get("rows") for k in "ABC"):
        report.write_failure(out, today, "검색 결과 0건(빈 데이터)")
        log("검색 결과가 비어 있음 — 실패 리포트만 작성")
        return 2

    # 1-1. 리포트가 닿기 전에 마감하는 물건은 뺀다. --today 로 날짜를 지정한 시험 실행은 그날 18:48(평일 루틴 시각)을 기준으로 본다.
    base = (datetime.datetime.combine(today, datetime.time(18, 48)) if args.today
            else datetime.datetime.now(kst).replace(tzinfo=None))
    closed_dropped = drop_closed(search, base + datetime.timedelta(minutes=C.CLOSE_MARGIN_MIN))
    if closed_dropped:
        log(f"마감이 {base + datetime.timedelta(minutes=C.CLOSE_MARGIN_MIN):%m/%d %H:%M} 이전인 물건 {closed_dropped}건 제외")

    # 2. 1차 선별
    pool_a, stats_a = A.select_A(search["A"])
    pool_d, stats_d = A.select_D(search["A"])
    pool_b, stats_b, all_b = A.select_B(search["B"])
    pool_c, stats_c, all_c = A.select_C(search["C"])
    log(f"선별: A {len(pool_a)}건, D {len(pool_d)}건, B {len(pool_b)}건, C {len(pool_c)}건 (자동차 실효없음 제외 {sum(stats_c['실효없음_제외'].values())}건)")

    # 3. 상세 수집
    rows = [v["row"] for v in pool_a + pool_d + pool_b + pool_c]
    run_details(rows, items_dir, args.workers)

    # 4. 파싱
    def load(pool):
        got = []
        for v in pool:
            mng = v["row"]["scrnIndctCltrMngNo"]
            if not os.path.exists(os.path.join(items_dir, mng + ".done")):
                log(f"  상세 없음: {mng}")
                continue
            try:
                it = parse.parse_item(mng, items_dir)
            except Exception as e:       # 한 물건의 손상된 원자료가 전체 실행을 멈추지 않게(missing_details에 집계된다)
                log(f"  상세 파싱 실패: {mng} ({type(e).__name__}: {e})")
                continue
            it.update(row=v["row"], rounds=v["rounds"], link=A.link(v["row"]),
                      land_class=v.get("land_class"), score=v.get("score"), prescore=v.get("prescore"), dup=v.get("dup", 0))
            # 일부 공고(불용품 등)는 상세 화면 배치가 달라 가격을 못 읽는다 — 검색 목록 값으로 채운다
            if not it.get("price"):
                it["price"] = v["row"].get("lowstBidPrc")
            if not it.get("appraisal") and v["row"].get("cltrApslEvlAvgAmt"):
                it["appraisal"] = v["row"]["cltrApslEvlAvgAmt"]
            got.append(it)
        return got

    ta = A.build_A(load(pool_a), today)
    td = A.build_D(load(pool_d), today)
    tb = A.build_B(load(pool_b))
    tc = A.build_C(load(pool_c))
    missing = {"A": len(pool_a) - len(ta), "D": len(pool_d) - len(td), "B": len(pool_b) - len(tb), "C": len(pool_c) - len(tc)}
    if (pool_a or pool_d or pool_b or pool_c) and not (ta or td or tb or tc):
        report.write_failure(out, today, "상세 화면 수집 실패(상세를 하나도 받지 못함)")
        log("상세 수집이 전부 실패 — 실패 리포트만 작성")
        return 2

    # 5. 사진·감정평가서 + 링크 확인 (리포트에 오를 만한 후보만)
    shortlist = ta[:C.MEDIA_A] + td[:C.MEDIA_D] + tb[:C.MEDIA_B] + tc[:C.MEDIA_C]
    for it in shortlist:
        it["link_ok"] = True if args.no_media else verify_link(it["link"], it["mng"])      # --no-media는 오프라인 시험 실행용: 링크 확인 생략
        if not args.no_media:
            log(f"사진·감정평가서: {it['mng']}")
            try:
                it["media"] = media.collect(it, media_dir)
            except Exception as e:           # 한 건의 사진·PDF 처리 실패가 전체 실행을 멈추지 않게 한다
                log(f"  사진·감정평가서 처리 오류 {it['mng']}: {type(e).__name__} {e}")
                it["media"] = {"dir": os.path.join(media_dir, it["mng"]),
                               "photos": {"count": 0, "downloaded": 0, "sheet": None},
                               "appraisal": {"status": f"오류({type(e).__name__})"}}
    # 감정평가서 본문(맹지·급경사·현황 농지·분묘)을 읽어 등급을 다시 매기고, 사진을 본 뒤의 순서로 정렬한다
    for kind, items in (("A", ta[:C.MEDIA_A]), ("D", td[:C.MEDIA_D])):
        for it in items:
            try:
                A.apply_appraisal(it, kind)
            except Exception as e:
                log(f"  감정평가서 신호 추출 오류 {it['mng']}: {type(e).__name__} {e}")
    ta = A.sort_A(ta[:C.MEDIA_A]) + ta[C.MEDIA_A:]
    td = A.sort_D(td[:C.MEDIA_D]) + td[C.MEDIA_D:]

    # 6. 추적: 지난 후보의 낙찰 결과 + 오늘 후보와 같은 종류의 최근 낙찰 사례
    st = track.load()
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    due_items = track.due(st, now)
    keywords = {}
    for t, items in (("B", tb[:C.MEDIA_B]), ("C", tc[:C.MEDIA_C])):
        for it in items:
            kw = track.comp_keyword(t, it)
            if kw:
                it["comp_key"] = f"{t}:{kw}"
                keywords[it["comp_key"]] = {"key": it["comp_key"], "kw": kw, "type": track.TYPE[t],
                                            "from": (today - datetime.timedelta(days=90)).isoformat()}
    res, changed = None, []
    if not args.no_results and (due_items or keywords):
        log(f"입찰결과 조회: 지난 후보 {len(due_items)}건, 동종 키워드 {len(keywords)}개")
        res = track.run_results(JS, out, due_items, list(keywords.values()))
        if res is None:
            log("입찰결과 조회 실패 — 이번 리포트는 결과 없이 진행")
    if res:
        changed = track.apply_results(st, res.get("items"), today.isoformat())
        for it in tb[:C.MEDIA_B] + tc[:C.MEDIA_C]:
            if it.get("comp_key"):
                it["comps"] = track.comps_summary((res.get("keywords") or {}).get(it["comp_key"]), exclude=it["mng"],
                                                  price=it.get("price"), window=1.7 if it["comp_key"].startswith("C:") else 5)
    elif keywords and not args.no_results:       # 조회 자체가 실패했으면 '낙찰 사례 없음'이 아니라 '조회 실패'로 표시한다
        for it in tb[:C.MEDIA_B] + tc[:C.MEDIA_C]:
            if it.get("comp_key"):
                it["comps"] = track.comps_summary(None)
    tracking = report.tracking_data(st, changed, due_items, res is not None)
    for it in ta + td + tb + tc:
        e = st["items"].get(it["mng"])
        it["seen"] = ({"first_seen": e.get("first_seen"), "reported": e.get("reported") or [], "prev_price": e.get("price"),
                       "prev_deadline": e.get("deadline"), "prev_seen": e.get("last_seen")} if e else None)
    track.add_candidates(st, today.isoformat(), {"A": ta[:C.MEDIA_A], "D": td[:C.MEDIA_D], "B": tb[:C.MEDIA_B], "C": tc[:C.MEDIA_C]})
    track.prune(st, today.isoformat())

    # 개발 사업 연관: 상세를 열지 않은 전체 압류 부동산 목록을 개발 사업 데이터와 맞춘다
    try:
        dz = devzone.load()
        devscan = devzone.scan(search["A"]["rows"], dz)
        for h in devscan["shown"]:
            h["link"] = A.link(h.pop("row"))
        devscan.update(entries=len(dz.get("entries") or []), built=dz.get("built"),
                       counts={str(k): v for k, v in devscan["counts"].items()})
    except Exception as e:                       # 개발 데이터가 깨져도 나머지 리포트는 낸다
        log(f"개발 사업 연관 집계 오류: {type(e).__name__} {e}")
        devscan = {"total": 0, "hits": 0, "counts": {"1": 0, "2": 0, "3": 0}, "shown": [], "entries": 0, "built": None}
    data = {"today": today.isoformat(), "bid_window": search["A"].get("bidWindow"), "devscan": devscan, "closed_dropped": closed_dropped,
            "stats": {"A": stats_a, "B": stats_b, "C": stats_c, "D": stats_d}, "missing_details": missing,
            "tracking": tracking, "A": ta, "D": td, "B": tb, "C": tc}
    with open(os.path.join(out, "candidates.json"), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, default=str)
    report.write_draft(out, data)
    log(f"완료: {out}/report_draft.md")
    if not args.no_state:                        # 초안을 쓴 뒤에 저장한다(상태 저장 실패가 초안을 막지 않게)
        try:
            track.save(st)
        except OSError as e:
            log(f"경고: 추적 상태 저장 실패 — {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
