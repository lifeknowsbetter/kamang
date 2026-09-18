#!/usr/bin/env python3
"""주간 스크리닝 실행기.

  python run.py                      # 엔카만 (기본)
  python run.py --source both        # 엔카 + 차차차 교차대조
  python run.py --out report.md      # 파일로 저장
  python run.py --json out.json      # 원자료 저장
"""
import argparse
import datetime
import json
import sys

from screener import chachacha, encar, report, rules


def _progress(label):
    def show(i, total, car_id):
        print(f"\r  {label} {i}/{total} ({car_id})   ", end="", file=sys.stderr)
        if i == total:
            print(file=sys.stderr)
    return show


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["encar", "ccc", "both"], default="encar")
    ap.add_argument("--out", help="알림 메시지를 저장할 파일")
    ap.add_argument("--json", dest="json_out", help="통과 매물 원자료를 저장할 파일")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    today = datetime.date.today()
    passed, dropped, ccc_only = [], {}, []

    if args.source in ("encar", "both"):
        print("엔카 수집 중...", file=sys.stderr)
        passed, dropped = encar.collect(today, progress=None if args.quiet else _progress("검증"))
        print(f"엔카: {len(passed)}대 통과 / {len(dropped)}대 탈락", file=sys.stderr)

    if args.source in ("ccc", "both"):
        print("차차차 수집 중...", file=sys.stderr)
        ccc = chachacha.collect(progress=None if args.quiet else _progress("상세"), today=today)
        chachacha.match_to_encar(ccc, passed + [c for c, _ in dropped.values()])
        # 엔카에 없고, 렌트 없고, 경과일 통과한 것만 참고용으로 남긴다.
        ccc_only = [c for c in ccc
                    if not c.get("encar_match")
                    and c.get("has_rent_history") is False
                    and c.get("listing_age_days") is not None
                    and c["listing_age_days"] <= rules.C.MAX_LISTING_AGE_DAYS]
        print(f"차차차: {len(ccc)}건 수집 / 전용 후보 {len(ccc_only)}건", file=sys.stderr)

    message = report.render(passed, ccc_only=ccc_only, dropped=dropped)
    print(message)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(message + "\n")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"date": today.isoformat(), "passed": passed,
                       "ccc_only": ccc_only}, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
