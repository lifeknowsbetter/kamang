#!/usr/bin/env python3
"""온비드 주간 스카우팅 실행기.

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

from . import analyze as A
from . import config as C
from . import media, parse, report

HERE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(HERE, "js")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def node(script, *args, timeout=3600):
    return subprocess.run(["node", os.path.join(JS, script), *map(str, args)], timeout=timeout)


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
    args = ap.parse_args()
    today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    out = args.out
    items_dir, media_dir = os.path.join(out, "items"), os.path.join(out, "media")
    os.makedirs(items_dir, exist_ok=True)

    # 1. 검색
    if not (args.skip_search and all(os.path.exists(os.path.join(out, f"search_{k}.json")) for k in "ABC")):
        log("온비드 조건검색 중...")
        if node("search.js", out, C.BUDGET_RLST, C.BUDGET_MVAST, C.CAR_MAX, timeout=1800).returncode != 0:
            report.write_failure(out, today, "온비드 조건검색 접속 실패")
            log("검색 실패 — 실패 리포트만 작성")
            return 2
    search = {k: json.load(open(os.path.join(out, f"search_{k}.json"))) for k in "ABC"}

    # 2. 1차 선별
    pool_a, stats_a = A.select_A(search["A"])
    pool_b, stats_b, all_b = A.select_B(search["B"])
    pool_c, stats_c, all_c = A.select_C(search["C"])
    log(f"선별: A {len(pool_a)}건, B {len(pool_b)}건, C {len(pool_c)}건")

    # 3. 상세 수집
    rows = [v["row"] for v in pool_a + pool_b + pool_c]
    run_details(rows, items_dir, args.workers)

    # 4. 파싱
    def load(pool):
        got = []
        for v in pool:
            mng = v["row"]["scrnIndctCltrMngNo"]
            if not os.path.exists(os.path.join(items_dir, mng + ".done")):
                log(f"  상세 없음: {mng}")
                continue
            it = parse.parse_item(mng, items_dir)
            it.update(row=v["row"], rounds=v["rounds"], link=A.link(v["row"]),
                      land_class=v.get("land_class"), score=v.get("score"), prescore=v.get("prescore"))
            # 일부 공고(불용품 등)는 상세 화면 배치가 달라 가격을 못 읽는다 — 검색 목록 값으로 채운다
            if not it.get("price"):
                it["price"] = v["row"].get("lowstBidPrc")
            if not it.get("appraisal") and v["row"].get("cltrApslEvlAvgAmt"):
                it["appraisal"] = v["row"]["cltrApslEvlAvgAmt"]
            got.append(it)
        return got

    ta = A.build_A(load(pool_a), today)
    tb = A.build_B(load(pool_b))
    tc = A.build_C(load(pool_c))
    missing = {"A": len(pool_a) - len(ta), "B": len(pool_b) - len(tb), "C": len(pool_c) - len(tc)}

    # 5. 사진·감정평가서 + 링크 확인 (리포트에 오를 만한 후보만)
    shortlist = ta[:C.MEDIA_A] + tb[:C.MEDIA_B] + tc[:C.MEDIA_C]
    for it in shortlist:
        it["link_ok"] = verify_link(it["link"], it["mng"])
        if not args.no_media:
            log(f"사진·감정평가서: {it['mng']}")
            it["media"] = media.collect(it, media_dir)

    data = {"today": today.isoformat(), "bid_window": search["A"].get("bidWindow"),
            "stats": {"A": stats_a, "B": stats_b, "C": stats_c}, "missing_details": missing,
            "A": ta, "B": tb, "C": tc}
    with open(os.path.join(out, "candidates.json"), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, default=str)
    report.write_draft(out, data)
    log(f"완료: {out}/report_draft.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
