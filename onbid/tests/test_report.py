"""영역 4(리포트 작성·실행기·추적 상태·지원금) 단위 시험.

구성
- *Ok 클래스: 현재 코드에서 통과하는 시험(회귀 방지).
- *Bugs 클래스: 발견한 문제를 드러내는 시험. '기대하는 올바른 동작'을 단언하므로 현재 코드에서는 실패한다.

실행: cd /home/user/kamang && python3 -m unittest -v <이 파일의 경로>  (또는 python3 이 파일)
저장소 파일은 수정하지 않는다. 임시 파일은 SCRATCH 아래에만 만든다.
"""
import os as _os
REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
FIXTURES = _os.environ.get("ONBID_FIXTURES", "/nonexistent-onbid-fixtures")
FIXTURES_PARENT = _os.path.dirname(FIXTURES)
import datetime
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, REPO_ROOT)

SCRATCH = tempfile.mkdtemp(prefix="onbid_test_")
os.makedirs(SCRATCH, exist_ok=True)
TEST5 = FIXTURES

from onbid import analyze as A  # noqa: E402
from onbid import report, run, subsidy, track  # noqa: E402

TODAY = datetime.date(2026, 10, 18)


# ───────────────────────── 합성 재료 ─────────────────────────

def basis(**kw):
    b = {"공유자수": 0, "공유자_법인": 0, "공유자_등록일": [], "공유자_장기": False, "공유자_등록일미상": 0, "기타등기권리": [],
         "인수권리": [], "지상권개요": [], "점유": 0, "임대차": 0, "명세서점유행": [], "명세서임차행": [], "명세서공개": False, "등기행수": 0}
    b.update(kw)
    return b


def item_a(**kw):
    it = dict(mng="M-1", name="경기도 군포시 산본동 1", link="http://x", link_ok=True, basis=basis(), land_class="우선", grade="낮음",
              area={}, kv={}, statement={"available": False}, row={"sidoSgkEmd": "경기도 군포시 산본동"}, round="001", price=None,
              appraisal=None, fails=0, notes=[], schedule=[], period=None)
    it.update(kw)
    return it


def item_b(**kw):
    it = dict(mng="B-1", name="명", display="명", link="http://x/?a=1&b=2", price=100000, appraisal=200000, org="기관", place="보관소",
              flags=[], period="2026-10-10 10:00 ~ 2026-10-21 17:00", row={"sidoSgkEmd": "경기도 군포시"}, link_ok=True)
    it.update(kw)
    return it


def sched(*prices):
    return [dict(no=f"{i + 1:03d}", start=f"2026-10-{5 + 7 * i:02d} 10:00", end="x", price=p, open="x", decide="y")
            for i, p in enumerate(prices)]


# ───────────────────────── report: 통과하는 시험 ─────────────────────────

class ReportOk(unittest.TestCase):
    def test_won_pct(self):
        self.assertEqual(report.won(1234567), "1,234,567원")
        self.assertEqual(report.won(None), "-")
        self.assertEqual(report.pct(30, 100), "30%")
        self.assertEqual(report.pct(30, 0), "-")
        self.assertEqual(report.pct(30, None), "-")

    def test_dday_boundaries(self):
        mk = lambda p: {"period": p}
        self.assertIn("(D-0)", report.dday(mk("2026-10-10 10:00 ~ 2026-10-18 17:00"), TODAY))
        self.assertIn("(마감)", report.dday(mk("2026-10-10 10:00 ~ 2026-10-17 17:00"), TODAY))
        self.assertEqual(report.dday({"period": None, "row": {}}, TODAY), "-")
        # 기간이 없으면 검색 행의 마감 시각을 쓴다
        self.assertIn("(D-3)", report.dday({"period": None, "row": {"pbctDdlnDt": "2026-10-21 17:00"}}, TODAY))

    def test_block_A_minimal_has_required_markers(self):
        out = report.block_A(0, item_a(), TODAY)
        for m in ("🔗", "📍", "농지여부", "공유자 현황", "인수권리", "점유자", "📷 사진·도면 판단", "종합 리스크", "한줄평"):
            self.assertIn(m, out)
        self.assertEqual(out.count("⟪"), out.count("⟫"))

    def test_block_A_exit_lines_present_when_exit_given(self):
        it = item_a(price=1_008_000, appraisal=2_015_920, schedule=sched(2_016_000, 1_008_000, 807_000), round="002")
        it["exit"] = A.exit_numbers(it)
        it["next_round"] = A.next_round(it["schedule"], it["round"])
        out = report.block_A(0, it, TODAY)
        self.assertIn("🧮", out)
        self.assertIn("예산 상한 **9,512,428원**", out)
        self.assertIn("손실 약", out)
        self.assertIn("다음 회차: 003회", out)

    def test_exit_numbers_first_under(self):
        it = dict(appraisal=2_000_000, price=1_400_000, round="001", schedule=sched(1_400_000, 1_200_000, 800_000))
        e = A.exit_numbers(it)
        self.assertEqual(e["exit_cap"], int((2_000_000 * 0.7 - 380_000) / 1.046))   # 975,... 원
        self.assertEqual(e["first_under"]["no"], "003")

    def test_sched_table_marks_current_round(self):
        t = report._sched_table(dict(schedule=sched(1000, 900, 800), round="002", appraisal=1000))
        self.assertIn("| 001 | 10/05 | 1,000 | 100% | 유찰 |", "\n".join(t))
        self.assertIn("**이번 회차**", t[3])
        self.assertIn("예정(등록됨)", t[4])

    def test_block_D_total_burden(self):
        it = dict(mng="D-1", name="n", link="http://x", link_ok=True, land_class="건물", grade="높음", area=None, kv={},
                  row={"sidoSgkEmd": "서울특별시 구로구 개봉동", "ctgrFullNm": "건물 / 아파트"}, round="010", price=8_820_000, appraisal=88_000_000,
                  fails=9, notes=[], schedule=[], period=None, risk_flags=[("R", "임차인 신고")], dup=2, ratio=10, deposit_sum=135_000_000,
                  next_round=None, statement={"available": True, "note": []})
        out = report.block_D(0, it, TODAY)
        self.assertIn("143,820,000원", out)
        self.assertIn("같은 건물·가격 호실 2개 더 있음", out)

    def test_block_C_minimal_no_exception(self):
        it = dict(mng="C-1", name="차", link="http://x", link_ok=False, kv={}, row={"sidoSgkEmd": "경기도 안양시"}, year=2012, fuel="경유", cc=2000,
                  km=1000, plate="12가3456", price=3_000_000, appraisal=3_000_000, round="001", fails=0, period=None, place="보관소",
                  handover="낙찰자", org="o", branch="b", flags=[], notes=[], subsidy=subsidy.estimate(fuel="경유", year=2012), assess=None)
        out = report.block_C(0, it, TODAY)
        self.assertIn("링크 확인 실패", out)
        self.assertIn("조기폐차 지원금", out)

    def test_seen_tag_variants(self):
        self.assertEqual(report.seen_tag({"seen": None}, TODAY), "🆕")
        self.assertEqual(report.seen_tag({"seen": {"first_seen": "2026-10-11", "reported": ["2026-10-11"]}}, TODAY), "↻ 10/11 보고")
        self.assertEqual(report.seen_tag({"seen": {"first_seen": "2026-10-11", "reported": []}}, TODAY), "검토 10/11~")

    def test_tracking_section_variants(self):
        self.assertEqual(report.tracking_section(None), [])
        self.assertIn("(개찰이 지난 추적 물건 없음)", "\n".join(report.tracking_section({"queried": False, "due": 0})))
        self.assertIn("(이번에는 입찰결과를 조회하지 못함)", "\n".join(report.tracking_section({"queried": False, "due": 2})))
        txt = "\n".join(report.tracking_section({"queried": True, "due": 1, "pending_reported": 3, "changed": [
            {"mng": "m1", "track": "A", "name": "n1", "link": "L", "appraisal": 1000, "reported": ["2026-10-11"], "status": "낙찰",
             "bid": 120, "rate": "120", "bidders": 2, "opened": "2026-10-15 11:00"}]}))
        self.assertIn("**낙찰 120원** (최저가 대비 120%, 감정가 대비 12%, 응찰 2명)", txt)

    def test_comps_line_normal(self):
        rows = [{"pbctStatNm": "낙찰", "onbidBidAmt": f"{110_000 + i}", "lowstBidPrc": 100_000, "onbidCltrNm": f"캐논 EOS {i}", "ctgrFullNm": "x",
                 "dspsMthodCdNm": "매각", "scrnIndctCltrMngNo": f"a{i}", "pbctExctDt": f"2026-10-0{i + 1} 10:00", "totalBid": "2", "rateRow1": "110",
                 "sidoEmd": "서울"} for i in range(3)]
        c = track.comps_summary(rows, price=100_000, window=5)
        line = report.comps_line({"comp_key": "B:캐논", "comps": c})
        self.assertIn("낙찰 3건, 낙찰가율 중앙값 110.0%", line)

    @unittest.skipUnless(os.path.exists(TEST5 + "/candidates.json"), "test5 재료 없음")
    def test_write_draft_on_test5_candidates(self):
        data = json.load(open(TEST5 + "/candidates.json", encoding="utf-8"))
        out = tempfile.mkdtemp(dir=SCRATCH)
        report.write_draft(out, data)
        md = open(out + "/report_draft.md", encoding="utf-8").read()
        self.assertEqual(md.count("⟪"), md.count("⟫"))
        self.assertGreaterEqual(md.count("🧮"), 8)          # A 8건 모두 출구 계산 줄
        self.assertGreaterEqual(md.count("📄"), 1)
        self.assertNotIn("None", md)
        self.assertIn(report.C.FOOTER, md)

    def test_write_failure(self):
        out = tempfile.mkdtemp(dir=SCRATCH)
        report.write_failure(out, TODAY, "사유")
        md = open(out + "/report_draft.md", encoding="utf-8").read()
        self.assertIn("사유", md)
        self.assertIn(report.C.FOOTER, md)


# ───────────────────────── report: 문제를 드러내는 시험(현재 실패) ─────────────────────────

class ReportBugs(unittest.TestCase):
    def test_rep3_exit_lines_nonpositive_message_matches_formula(self):
        """cap<=0 문구가 '35만원'인데 식은 5만+3만+30만=38만원을 뺀다."""
        it = item_a(price=100_000, appraisal=400_000)
        it["exit"] = A.exit_numbers(it)
        text = "\n".join(report.exit_lines(it))
        self.assertNotIn("35만원", text)
        self.assertIn("38만원", text)

    def test_rep4_block_B_row_escapes_pipe_and_newline(self):
        row = report.block_B_row(item_b(display="A|B 노트북\n맥북", place="창고|2층", org="기관|부서"), TODAY)
        self.assertEqual(row.count("\n"), 0)
        unescaped = row.replace("\\|", "")
        self.assertEqual(unescaped.count("|"), 7, row)       # 6열 표 → 구분자 7개

    def test_rep5_block_A_lease_rows_are_shown(self):
        b = basis(명세서공개=True, 명세서점유행=[], 명세서임차행=["임차인 김철수", "보증금 3000만원"])
        out = report.block_A(0, item_a(basis=b, statement={"available": True, "base_date": "2026.10.15", "note": []}), TODAY)
        line = next(l for l in out.split("\n") if "점유자" in l)
        self.assertIn("김철수", line)                         # 임차 행이 빠지고 [] 만 찍힌다

    def test_rep6_block_A_occupancy_not_python_list_repr(self):
        b = basis(점유=1, 명세서공개=True, 명세서점유행=["전입세", "대주", "김**", "미상"])
        out = report.block_A(0, item_a(basis=b, statement={"available": True, "base_date": "2026.10.15", "note": []}), TODAY)
        line = next(l for l in out.split("\n") if "점유자" in l)
        self.assertNotIn("['", line)

    def test_rep7_comps_line_failed_query_is_not_reported_as_no_cases(self):
        """results.js가 키워드 조회에 실패하면 null → comps_summary(None) → '낙찰 사례 없음'으로 찍힌다."""
        failed = report.comps_line({"comp_key": "B:카메라", "comps": track.comps_summary(None, price=1_000_000)})
        self.assertFalse(failed is not None and "사례 없음" in failed, failed)

    def test_rep8_comps_line_has_no_None_text(self):
        rows = [{"pbctStatNm": "낙찰", "onbidBidAmt": "110,000", "lowstBidPrc": 100000, "onbidCltrNm": "캐논 EOS", "ctgrFullNm": "x",
                 "dspsMthodCdNm": "매각", "scrnIndctCltrMngNo": "a", "pbctExctDt": "2026-10-01 10:00", "rateRow1": "110"}]
        line = report.comps_line({"comp_key": "B:캐논", "comps": track.comps_summary(rows, price=100000, window=5)})
        self.assertNotIn("None", line)

    def test_rep9_block_C_shows_next_round_and_schedule(self):
        """ROUTINE_PROMPT 4절 Track C: '감정가 → 현재 가격, 다음 회차 가격, 입찰 마감(D-n)'. 초안 C 블록에는 다음 회차가 없다."""
        raw = dict(mng="C-2", name="기아 모하비", price=3_000_000, appraisal=3_000_000, round="001", fails="0회", period="2026-10-20 10:00 ~ 2026-10-28 17:00",
                   kv={"모델명": "모하비", "연료": "경유"}, notes=[], notice_head=[], schedule=sched(3_000_000, 2_700_000, 2_400_000),
                   row={"sidoSgkEmd": "경기도 광주시 도척면", "onbidCltrNm": "기아 모하비 2010년식", "ctgrFullNm": "자동차 / 승용", "lowstBidPrc": 3_000_000},
                   link="http://x", link_ok=True)
        built = A.build_C([raw])[0]
        out = report.block_C(0, built, TODAY)
        self.assertIn("다음 회차", out)

    def test_rep10_block_B_row_reports_link_failure(self):
        row = report.block_B_row(item_b(link_ok=False), TODAY)
        self.assertIn("링크", row)

    def test_rep11_seen_tag_first_seen_today_is_new(self):
        """같은 날 재실행(--skip-search)하면 어제까지 안 본 물건도 '검토 10/18~'로 바뀐다. 사용자에게 보이는 첫 리포트면 🆕여야 한다."""
        tag = report.seen_tag({"seen": {"first_seen": "2026-10-18", "reported": []}}, TODAY)
        self.assertEqual(tag, "🆕")

    def test_rep12_write_failure_mentions_all_four_tracks(self):
        out = tempfile.mkdtemp(dir=SCRATCH)
        report.write_failure(out, TODAY, "사유")
        md = open(out + "/report_draft.md", encoding="utf-8").read()
        self.assertIn("Track D", md)


# ───────────────────────── 다른 영역 원인이지만 초안(⛔·실행)에 드러나는 문제 ─────────────────────────

class CrossAreaBugs(unittest.TestCase):
    def test_x1_bad_exit_not_triggered_by_possibility_or_boilerplate_notes(self):
        """analyze.GRAVE_REAL이 '분묘가 소재할 수 있으므로'·'분묘기지권 성립여부' 같은 가능성/법률용어 문구에도 걸려 초안에 ⛔(입찰 비권고)가 붙는다."""
        for note in ("- 본건 육안으로 확인되지 않은 분묘가 소재할 수 있으므로 사전조사 후 입찰바람.",
                     "ㅇ현황 자연림으로 지상에 \"분묘\"가 소재할 가능성이 있으므로 분묘기지권 성립여부 등에 관하여는 사전 현장조사 후 입찰바람",
                     "- 본 건 정확한 지적관련 사항, 분묘소재여부, 경계 등의 확인이 필요한 경우에는 측량등을 통한 재확인이 필요하므로 사전조사 후 입찰바람"):
            it = {"notes": [note], "grade": "낮음", "media": None}
            A.apply_appraisal(it, "A")
            self.assertFalse(it["bad_exit"], note[:40])

    def test_x2_select_C_survives_zero_price_row(self):
        row = {"scrnIndctCltrMngNo": "C-0", "pbctBegnDtm": "2026-10-10 10:00", "onbidCltrNm": "아반떼", "ctgrFullNm": "자동차 / 승용",
               "lowstBidPrc": 0, "sidoEmd": "경기", "sidoSgkEmd": "경기도 군포시", "cptnMtdNm": "일반경쟁"}
        try:
            A.select_C({"rows": [row]})
        except ZeroDivisionError:
            self.fail("lowstBidPrc 0인 자동차 행 하나가 carfilter.assess의 0 나누기로 run 전체를 중단시킨다")


# ───────────────────────── track: 통과하는 시험 ─────────────────────────

def state(**items):
    return {"items": items, "history": []}


class TrackOk(unittest.TestCase):
    def test_due_boundaries(self):
        st = state(
            a={"open_dt": "2026-10-15 11:00:00", "type": "0001"},                                   # 개찰 지남, 결과 없음 → 대상
            b={"open_dt": "2026-10-22 11:00:00", "type": "0001"},                                   # 개찰 전
            c={"open_dt": "2026-10-15 11:00:00", "final": True},                                    # 확정
            d={"open_dt": "2026-10-15 11:00:00", "result": {"opened": "2026-10-15 11:00"}, "result_checked": "2026-10-17"},   # 최근 확인
            e={"open_dt": "2026-10-15 11:00:00", "result": {"opened": "2026-10-15 11:00"}, "result_checked": "2026-10-10"},   # 일주일 지남
            f={"open_dt": "2026-10-20 11:00:00", "result": {"opened": "2026-10-15 11:00"}, "result_checked": "2026-10-17"},   # 재공고로 개찰일 갱신
            g={"deadline": "2026-10-14 17:00"},                                                      # open_dt 없으면 마감일
            h={},
        )
        got = {x["mng"] for x in track.due(st, "2026-10-18 18:48")}
        self.assertEqual(got, {"a", "e", "g"})
        # 개찰 시각 정각: 포함
        self.assertEqual([x["mng"] for x in track.due(state(a={"open_dt": "2026-10-18 18:48:00"}), "2026-10-18 18:48")], ["a"])

    def test_apply_results_sold_is_final_and_in_history(self):
        st = state(m={"track": "C", "first_seen": "2026-10-11", "name": "n", "appraisal": 1000, "reported": ["2026-10-11"]})
        rows = {"m": [{"pbctStatNm": "낙찰", "pbctNsq": "1", "pbctExctDt": "2026-10-15 11:00", "lowstBidPrc": 1000, "onbidBidAmt": "1,500",
                       "rateRow1": "150", "totalBid": "7"}]}
        self.assertEqual(track.apply_results(st, rows, "2026-10-18"), ["m"])
        self.assertTrue(st["items"]["m"]["final"])
        self.assertEqual(st["items"]["m"]["result"]["bid"], 1500)
        self.assertEqual(st["history"][0]["bidders"], 7)
        self.assertEqual(len(st["history"]), 1)
        self.assertEqual(track.due(st, "2026-10-19 18:48"), [])          # 확정 물건은 다시 조회하지 않는다

    def test_apply_results_ignores_rounds_before_first_seen_and_open_states(self):
        st = state(m={"track": "A", "first_seen": "2026-10-11"})
        rows = {"m": [{"pbctStatNm": "유찰", "pbctExctDt": "2026-10-08 11:00"},            # first_seen 이전
                      {"pbctStatNm": "개찰중", "pbctExctDt": "2026-10-15 11:00"}]}           # 아직 진행
        self.assertEqual(track.apply_results(st, rows, "2026-10-18"), [])
        self.assertEqual(st["items"]["m"]["result_checked"], "2026-10-18")
        self.assertNotIn("result", st["items"]["m"])

    def test_apply_results_unfinished_yuchal_not_final_and_reported_once(self):
        st = state(m={"track": "A", "first_seen": "2026-10-11"})
        rows = {"m": [{"pbctStatNm": "유찰", "pbctNsq": "036", "pbctExctDt": "2026-10-15 11:00", "lowstBidPrc": 100}]}
        self.assertEqual(track.apply_results(st, rows, "2026-10-16"), ["m"])
        self.assertNotIn("final", st["items"]["m"])
        self.assertEqual(track.apply_results(st, rows, "2026-10-23"), [])      # 같은 결과는 다시 알리지 않는다

    def test_apply_results_none_rows_and_unknown_mng_skipped(self):
        st = state(m={"track": "A", "first_seen": "2026-10-11"})
        self.assertEqual(track.apply_results(st, {"m": None, "zzz": []}, "2026-10-18"), [])
        self.assertNotIn("result_checked", st["items"]["m"])

    def test_prune_and_history_cap(self):
        st = state(old={"last_seen": "2026-08-01"}, fresh={"last_seen": "2026-10-10"}, nols={"first_seen": "2026-10-01"})
        st["history"] = list(range(2500))
        track.prune(st, "2026-10-18")
        self.assertEqual(set(st["items"]), {"fresh", "nols"})
        self.assertEqual(len(st["history"]), 2000)

    def test_mark_reported_idempotent_and_unknown_skipped(self):
        st = state(m={"reported": []})
        track.mark_reported(st, "2026-10-18", ["m", "unknown"])
        track.mark_reported(st, "2026-10-18", ["m"])
        self.assertEqual(st["items"]["m"]["reported"], ["2026-10-18"])
        self.assertNotIn("unknown", st["items"])

    def test_add_candidates_updates_existing_and_keeps_reported(self):
        st = state(m={"track": "A", "first_seen": "2026-10-11", "reported": ["2026-10-11"]})
        it = {"mng": "m", "name": "n", "link": "L", "price": 5, "appraisal": 9, "period": "2026-10-19 10:00 ~ 2026-10-26 17:00",
              "row": {"pbctExctDt": "2026-10-27 11:00:00"}}
        track.add_candidates(st, "2026-10-18", {"D": [it]})                  # 같은 물건이 다른 트랙으로 들어옴
        e = st["items"]["m"]
        self.assertEqual((e["track"], e["type"], e["first_seen"], e["last_seen"]), ("D", "0001", "2026-10-11", "2026-10-18"))
        self.assertEqual(e["reported"], ["2026-10-11"])
        self.assertEqual((e["deadline"], e["open_dt"]), ("2026-10-26 17:00", "2026-10-27 11:00:00"))

    def test_save_load_roundtrip_sorted_keys(self):
        p = os.path.join(tempfile.mkdtemp(dir=SCRATCH), "sub", "t.json")
        with mock.patch.object(track, "STATE", p):
            track.save({"items": {"b": {"z": 1, "a": 2}, "a": {}}, "history": []})
            txt = open(p, encoding="utf-8").read()
            self.assertLess(txt.index('"a"'), txt.index('"b"'))
            self.assertEqual(track.load()["items"]["b"], {"a": 2, "z": 1})
        with mock.patch.object(track, "STATE", p + ".none"):
            self.assertEqual(track.load(), {"items": {}, "history": []})

    def test_comps_summary_median_needs_three_and_filters(self):
        mk = lambda i, nm="캐논 EOS", st="낙찰", low=100_000: {"pbctStatNm": st, "onbidBidAmt": "150,000", "lowstBidPrc": low, "onbidCltrNm": nm,
                                                           "ctgrFullNm": "x", "dspsMthodCdNm": "매각", "scrnIndctCltrMngNo": f"m{i}",
                                                           "pbctExctDt": f"2026-10-0{i + 1} 10:00", "totalBid": "2", "rateRow1": "150", "sidoEmd": "서울"}
        c = track.comps_summary([mk(0), mk(1)], price=100_000)
        self.assertIsNone(c["median_rate"])
        c = track.comps_summary([mk(0), mk(1), mk(2), mk(3, st="유찰"), mk(4, nm="안저카메라"), mk(5, nm="캐논 외 3점"), mk(6, low=900_000), mk(7)],
                                exclude="m7", price=100_000)
        self.assertEqual((c["n_sold"], c["median_rate"]), (3, 150.0))

    def test_tracking_data_counts_pending(self):
        st = state(a={"reported": ["2026-10-11"]}, b={"reported": ["2026-10-11"], "final": True}, c={"reported": []})
        td = report.tracking_data(st, [], [{"mng": "a"}], True)
        self.assertEqual((td["pending_reported"], td["due"], td["queried"]), (1, 1, True))

    def test_comp_keyword_normal_cases(self):
        self.assertEqual(track.comp_keyword("C", {"kv": {"모델명": "모하비"}}), "모하비")
        self.assertEqual(track.comp_keyword("B", {"name": "순금팔찌 1점", "kv": {}}), "순금")
        self.assertEqual(track.comp_keyword("B", {"name": "레노버 노트북", "kv": {}}), "노트북")
        self.assertIsNone(track.comp_keyword("B", {"name": "고압멸균기 1대", "kv": {"모델명": "-"}}))


# ───────────────────────── track: 문제를 드러내는 시험(현재 실패) ─────────────────────────

class TrackBugs(unittest.TestCase):
    def test_trk1_cancel_round_is_not_terminal(self):
        """실제 결과(2025-17736-001): 030·031회 '취소' 뒤에도 033~036회가 이어졌다. 취소를 확정으로 보면 이후 결과를 영영 못 받는다."""
        st = state(m={"track": "A", "first_seen": "2026-08-01", "name": "n", "reported": ["2026-08-01"]})
        rows = {"m": [{"pbctStatNm": "취소", "pbctNsq": "030", "pbctExctDt": "2026-08-20 11:00"},
                      {"pbctStatNm": "취소", "pbctNsq": "031", "pbctExctDt": "2026-08-27 11:00"}]}
        track.apply_results(st, rows, "2026-08-28")
        self.assertFalse(st["items"]["m"].get("final"), "취소 회차가 확정으로 처리되어 이후 회차 결과 추적이 끊긴다")

    def test_trk2_load_survives_corrupt_state(self):
        for content in ('{"items": {', "", '<<<<<<< HEAD\n{"items": {}, "history": []}\n=======\n{}\n>>>>>>> x\n'):
            p = os.path.join(tempfile.mkdtemp(dir=SCRATCH), "t.json")
            open(p, "w", encoding="utf-8").write(content)
            with mock.patch.object(track, "STATE", p):
                try:
                    st = track.load()
                except Exception as e:  # noqa: BLE001
                    self.fail(f"깨진 상태 파일({content[:12]!r})에서 load()가 {type(e).__name__}으로 죽는다")
                self.assertIn("items", st)

    def test_trk3_save_with_bare_filename(self):
        d = tempfile.mkdtemp(dir=SCRATCH)
        old = os.getcwd()
        os.chdir(d)
        try:
            with mock.patch.object(track, "STATE", "st_bare.json"):
                try:
                    track.save({"items": {}, "history": []})
                except Exception as e:  # noqa: BLE001
                    self.fail(f"디렉터리 없는 ONBID_STATE에서 save()가 {type(e).__name__}: {e}")
        finally:
            os.chdir(old)
        self.assertTrue(os.path.exists(os.path.join(d, "st_bare.json")))

    def test_trk4_comp_keyword_does_not_use_class_label(self):
        it = {"name": "현대 중형차 쏘나타 1998cc", "kv": {"차종": "중형차"}}
        self.assertEqual(track.comp_keyword("C", it), "쏘나타")        # 현재는 '중형차'(전 차종과 비교)

    def test_trk5_comp_keyword_matches_spaced_and_unspaced_names(self):
        """키워드에서 공백을 지우면 '그랜드 스타렉스'로 적힌 공고가 검색에서 빠진다(실제 100행 중 51행이 공백형)."""
        kw = track.comp_keyword("C", {"name": "그랜드 스타렉스", "kv": {"모델명": "그랜드 스타렉스"}})
        self.assertIn(kw, "현대자동차 중형 승합 그랜드 스타렉스 2,497cc")
        self.assertIn(kw, "현대 중형차 그랜드스타렉스 2497cc")

    def test_trk6_comp_keyword_for_gold_ring(self):
        self.assertIsNotNone(track.comp_keyword("B", {"name": "금반지 2점", "kv": {"모델명": "-"}}))

    def test_trk7_lot_filter_keeps_single_vehicle_with_commas(self):
        r = {"pbctStatNm": "낙찰", "onbidBidAmt": "7,200,000", "lowstBidPrc": 4_000_000, "ctgrFullNm": "자동차 / 승용", "dspsMthodCdNm": "매각",
             "onbidCltrNm": "대전광역시 유성구 복용동 579-15  [36라2672, 아반떼, 2017년식]", "scrnIndctCltrMngNo": "a", "pbctExctDt": "2026-10-01 10:00",
             "totalBid": "3", "rateRow1": "180"}
        self.assertEqual(track.comps_summary([r], price=4_000_000, window=1.7)["n_sold"], 1)

    def test_trk9_mark_without_outdir_does_not_drop_first_id(self):
        p = os.path.join(tempfile.mkdtemp(dir=SCRATCH), "t.json")
        json.dump({"items": {"M-1": {"reported": []}, "M-2": {"reported": []}}, "history": []}, open(p, "w"))
        with mock.patch.object(track, "STATE", p), mock.patch.object(sys, "argv", ["track", "mark", "M-1", "M-2"]), \
                mock.patch("builtins.print"):
            track.main()
        st = json.load(open(p))
        self.assertTrue(st["items"]["M-1"]["reported"], "첫 물건관리번호가 out 폴더 인자로 먹혀 조용히 빠진다")

    def test_trk8_comps_summary_flags_truncated_100_rows(self):
        """results.js는 첫 100행만 받는다. 초안은 '최근 90일'이라 쓰지만 100행이 차면 실제로는 그보다 짧은 기간이다."""
        rows = [{"pbctStatNm": "유찰", "pbctExctDt": f"2026-10-{1 + i % 16:02d} 10:00"} for i in range(100)]
        c = track.comps_summary(rows, price=1_000_000)
        self.assertTrue(c.get("truncated"), "100행이 차도 잘렸다는 표시가 없다")


# ───────────────────────── subsidy ─────────────────────────

class SubsidyOk(unittest.TestCase):
    def test_grade_boundaries(self):
        g = subsidy.grade_from_year
        self.assertEqual([g(y) for y in (2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012)],
                         ["5등급", "4·5등급 혼재", "4·5등급 혼재", "4등급", "4등급", "3~4등급 경계", "3~4등급 경계", "3등급 이하"])
        self.assertEqual(g(None), "연식 미상")

    def test_eligibility_rules(self):
        e = subsidy.estimate
        self.assertEqual(e(fuel="휘발유", year=2008)["eligible"], "대상아님")
        self.assertEqual(e(fuel="경유", year=2005)["eligible"], "불가")
        self.assertEqual(e(fuel="경유", year=2012)["eligible"], "대상아님")
        self.assertEqual(e(fuel="경유", year=2008, flags=["폐차 조건부 매각"])["eligible"], "불가")
        r = e(fuel="경유", year=2008, cc=2000, category="자동차 / 승용", value_proxy=3_000_000)
        self.assertEqual((r["eligible"], r["amount_lo"], r["amount_hi"]), ("확인필요", 1_680_000, 3_150_000))
        self.assertIsNone(e(fuel="경유", year=2008, cc=3500, value_proxy=3_000_000)["amount_hi"])     # 3.5톤 이상 가능성 → 금액 생략

    def test_no_amount_without_value(self):
        r = subsidy.estimate(fuel="경유", year=2008, cc=2000, value_proxy=None)
        self.assertIsNone(r["amount_lo"])


class SubsidyBugs(unittest.TestCase):
    def test_sub1_amount_range_not_inverted(self):
        r = subsidy.estimate(fuel="경유", year=2009, cc=2000, category="자동차 / 승용", value_proxy=15_000_000)
        self.assertLessEqual(r["amount_lo"], r["amount_hi"])           # 현재 8,400,000 > 5,600,000

    def test_sub2_amount_never_exceeds_cap(self):
        r = subsidy.estimate(fuel="경유", year=2009, cc=2000, category="자동차 / 승용", value_proxy=30_000_000)
        cap = subsidy.RULES["under_3_5t"]["4등급"]["cap"]
        self.assertLessEqual(r["amount_lo"], cap)                       # 현재 lo=16,800,000 (상한 800만 초과)
        self.assertLessEqual(r["amount_hi"], cap)


# ───────────────────────── run.main 흐름(네트워크는 전부 대체) ─────────────────────────

ROW_KEYS = dict(cltrScrnGrpCd="0001", cltrPrptDivCd="0007", onbidCltrno="1", onbidPbancNo="2", pbctNo="3", pbctCdtnNo="4")


def stats():
    return {
        "A": {"부동산물건": 2, "지분물건": 2, "압류재산_지분": 2, "산본_50km_이내": 2, "상세분석": 2, "재산유형별": {}, "지목별": {}},
        "D": {"단독·미표시": 0, "압류재산": 0, "산본_50km_이내": 0, "유형별": {}, "상세분석": 0},
        "B": {"동산물건": 0, "후보": 0, "산본_50km_이내": 0, "상세분석": 0, "권리형·폐기물 등 제외": {}, "공고기관별": {}},
        "C": {"차량": 0, "실효없음_제외": {}, "남은_차량": 0, "상세분석": 0, "연료별": {}, "경유_2009년이전": 0, "폐차조건부": 0},
    }


def a_row(mng, price=1_000_000):
    return {**ROW_KEYS, "scrnIndctCltrMngNo": mng, "sidoSgkEmd": "경기도 군포시 산본동", "lowstBidPrc": price, "cltrApslEvlAvgAmt": 2_000_000,
            "pbctDdlnDt": "2026-10-21 17:00", "pbctExctDt": "2026-10-22 11:00:00", "scrnPrptDvsnNm": "압류재산", "alcYn": "Y", "onbidCltrNm": mng}


def parsed_a(mng, **kw):
    it = dict(mng=mng, name=f"경기도 군포시 산본동 {mng}", appraisal=2_000_000, price=1_000_000, round="001", fails="0회",
              period="2026-10-14 10:00 ~ 2026-10-21 17:00", org="기관", branch="b", client="c", kv={}, area={"use": "토지(대)", "area": "1㎡", "share_note": ""},
              notes=[], schedule=[], reg=[], reg_cnt=1, occ=[], occ_cnt=0, lease=[], lease_cnt=0, statement={"available": True, "keep": [], "surface": [],
              "note": [], "occupancy_rows": [], "lease_rows": []}, photos=[], pdf=None)
    it.update(kw)
    return it


class RunFlow(unittest.TestCase):
    """search/select/parse/media/results를 모두 가짜로 바꿔 run.main의 흐름만 시험한다."""

    def setUp(self):
        self.out = tempfile.mkdtemp(dir=SCRATCH)
        self.state_path = os.path.join(tempfile.mkdtemp(dir=SCRATCH), "tracked.json")
        self.addCleanup(mock.patch.stopall)

    def write_search(self, rows_a=(), rows_b=(), rows_c=()):
        for k, rows in (("A", rows_a), ("B", rows_b), ("C", rows_c)):
            json.dump({"track": k, "rows": list(rows), "bidWindow": ["2026-10-18", "2026-11-18"]}, open(f"{self.out}/search_{k}.json", "w"))

    def patch_common(self, pool_a=(), parse=None, collect=None, state=True):
        P = mock.patch
        pa = [{"row": r, "rounds": [r], "land_class": "우선", "dist": 10} for r in pool_a]
        P.object(run.A, "select_A", return_value=(pa, stats()["A"])).start()
        P.object(run.A, "select_D", return_value=([], stats()["D"])).start()
        P.object(run.A, "select_B", return_value=([], stats()["B"], [])).start()
        P.object(run.A, "select_C", return_value=([], stats()["C"], [])).start()
        P.object(run, "run_details", lambda *a, **k: None).start()
        P.object(run, "verify_link", lambda url, mng: True).start()
        P.object(run.parse, "parse_item", side_effect=parse or (lambda mng, d: parsed_a(mng))).start()
        if collect is not None:
            P.object(run.media, "collect", side_effect=collect).start()
        if state:
            P.object(track, "STATE", self.state_path).start()
        # 상세가 있다고 표시
        os.makedirs(f"{self.out}/items", exist_ok=True)
        for r in pool_a:
            open(f"{self.out}/items/{r['scrnIndctCltrMngNo']}.done", "w").close()

    def main(self, *extra):
        argv = ["run", "--out", self.out, "--skip-search", "--no-results", "--today", "2026-10-18", *extra]
        with mock.patch.object(sys, "argv", argv):
            return run.main()


class RunFlowOk(RunFlow):
    def test_normal_flow_sorted_after_appraisal_and_tracked(self):
        """감정평가서 본문 신호(맹지)로 1번 후보가 '높음'이 되면 정렬이 바뀌고, 추적 목록과 candidates.json·초안이 같은 순서/집합이다."""
        rows = [a_row("M-1", 900_000), a_row("M-2", 1_100_000)]
        self.write_search(rows)
        txt = os.path.join(self.out, "appraisal.txt")
        open(txt, "w", encoding="utf-8").write("본건은 맹지로서 차량 접근이 불가하다.\n")

        def collect(it, root):
            ap = {"status": "ok", "text": txt if it["mng"] == "M-1" else None, "pages": [1], "sheets": []}
            return {"dir": root, "photos": {"count": 0, "downloaded": 0, "sheet": None}, "appraisal": ap}

        self.patch_common(rows, collect=collect)
        self.assertEqual(self.main(), 0)
        data = json.load(open(self.out + "/candidates.json", encoding="utf-8"))
        self.assertEqual([x["mng"] for x in data["A"]], ["M-2", "M-1"])          # 높음으로 바뀐 M-1이 뒤로
        self.assertEqual(data["A"][1]["grade"], "높음")
        md = open(self.out + "/report_draft.md", encoding="utf-8").read()
        self.assertLess(md.index("M-2"), md.index("물건관리번호 M-1"))
        self.assertIn("⛔", md)
        st = json.load(open(self.state_path, encoding="utf-8"))
        self.assertEqual(set(st["items"]), {"M-1", "M-2"})
        self.assertEqual({e["track"] for e in st["items"].values()}, {"A"})

    def test_no_state_flag_does_not_write_state(self):
        rows = [a_row("M-1")]
        self.write_search(rows)
        self.patch_common(rows, collect=lambda it, root: {})
        self.assertEqual(self.main("--no-state"), 0)
        self.assertFalse(os.path.exists(self.state_path))
        self.assertTrue(os.path.exists(self.out + "/report_draft.md"))

    def test_search_failure_writes_failure_report(self):
        self.patch_common()
        with mock.patch.object(run, "node", return_value=types.SimpleNamespace(returncode=1)):
            argv = ["run", "--out", self.out, "--today", "2026-10-18"]
            with mock.patch.object(sys, "argv", argv):
                self.assertEqual(run.main(), 2)
        md = open(self.out + "/report_draft.md", encoding="utf-8").read()
        self.assertIn("수집 실패", md)

    def test_missing_details_counted_and_noted(self):
        rows = [a_row("M-1"), a_row("M-2")]
        self.write_search(rows)
        self.patch_common(rows, collect=lambda it, root: {})
        os.remove(self.out + "/items/M-2.done")
        self.assertEqual(self.main(), 0)
        data = json.load(open(self.out + "/candidates.json", encoding="utf-8"))
        self.assertEqual(data["missing_details"]["A"], 1)
        self.assertIn("상세 수집 실패", open(self.out + "/report_draft.md", encoding="utf-8").read())

    def test_results_none_still_produces_report(self):
        rows = [a_row("M-1")]
        self.write_search(rows)
        self.patch_common(rows, collect=lambda it, root: {})
        # 추적 상태에 개찰 지난 물건이 있으면 결과 조회를 시도한다
        json.dump({"items": {"OLD": {"track": "A", "first_seen": "2026-10-01", "open_dt": "2026-10-10 11:00:00", "type": "0001", "reported": []}},
                   "history": []}, open(self.state_path, "w"))
        with mock.patch.object(run.track, "run_results", return_value=None):
            argv = ["run", "--out", self.out, "--skip-search", "--today", "2026-10-18"]
            with mock.patch.object(sys, "argv", argv):
                self.assertEqual(run.main(), 0)
        md = open(self.out + "/report_draft.md", encoding="utf-8").read()
        self.assertIn("(이번에는 입찰결과를 조회하지 못함)", md)


class RunFlowBugs(RunFlow):
    def test_run1_corrupt_state_does_not_abort_run(self):
        """깨진 tracked.json(예: git rebase 충돌 표식)이 있으면 상세 수집이 다 끝난 뒤 JSONDecodeError로 죽고 초안이 하나도 남지 않는다."""
        rows = [a_row("M-1")]
        self.write_search(rows)
        self.patch_common(rows, collect=lambda it, root: {})
        open(self.state_path, "w").write('<<<<<<< HEAD\n{"items": {}, "history": []}\n=======\n')
        try:
            self.main()
        except Exception as e:  # noqa: BLE001
            self.fail(f"run.main이 {type(e).__name__}로 중단됨")
        self.assertTrue(os.path.exists(self.out + "/report_draft.md"))

    def test_run2_media_exception_is_isolated_per_item(self):
        rows = [a_row("M-1"), a_row("M-2")]
        self.write_search(rows)

        def collect(it, root):
            if it["mng"] == "M-1":
                raise subprocess.TimeoutExpired(cmd="pdftotext", timeout=180)
            return {}

        self.patch_common(rows, collect=collect)
        try:
            self.main()
        except subprocess.TimeoutExpired:
            self.fail("후보 하나의 pdftotext 시간 초과가 run 전체를 중단시킨다")
        self.assertTrue(os.path.exists(self.out + "/report_draft.md"))

    def test_run3_search_timeout_writes_failure_report(self):
        self.patch_common()
        with mock.patch.object(run.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="node", timeout=1800)):
            argv = ["run", "--out", self.out, "--today", "2026-10-18"]
            with mock.patch.object(sys, "argv", argv):
                try:
                    rc = run.main()
                except subprocess.TimeoutExpired:
                    self.fail("search.js 시간 초과가 실패 리포트 없이 예외로 끝난다")
        self.assertEqual(rc, 2)

    def test_run4_empty_search_is_reported_as_collection_failure(self):
        """세 검색이 모두 0건이어도 search.js는 경고만 하고 종료코드 0 → 정상 초안(전부 0건)이 나온다. 지시문은 '빈 데이터 = 수집 실패'."""
        self.write_search()
        self.patch_common()
        rc = self.main()
        md = open(self.out + "/report_draft.md", encoding="utf-8").read()
        self.assertTrue(rc != 0 or "수집 실패" in md[:600], "0건 검색이 정상 리포트로 나온다")

    def test_run5_all_details_missing_is_flagged_near_top(self):
        rows = [a_row("M-1"), a_row("M-2")]
        self.write_search(rows)
        self.patch_common(rows, collect=lambda it, root: {})
        for r in rows:
            os.remove(f"{self.out}/items/{r['scrnIndctCltrMngNo']}.done")
        rc = self.main()
        md = open(self.out + "/report_draft.md", encoding="utf-8").read()
        self.assertTrue(rc != 0 or "상세 수집 실패" in md[:800], "상세를 하나도 못 받았는데 맨 아래 한 줄로만 알린다")

    def test_run7_seen_exposes_previous_price_and_deadline_for_repeat_items(self):
        """ROUTINE_PROMPT: ↻ 물건은 '가격·회차·마감이 바뀌지 않았으면' 한 줄로 줄인다 → 이전 보고 때 가격·마감이 초안에 있어야 비교할 수 있다."""
        rows = [a_row("M-1", 900_000)]
        self.write_search(rows)
        self.patch_common(rows, collect=lambda it, root: {})
        json.dump({"items": {"M-1": {"track": "A", "first_seen": "2026-10-11", "last_seen": "2026-10-11", "reported": ["2026-10-11"],
                                     "price": 1_200_000, "deadline": "2026-10-14 17:00"}}, "history": []}, open(self.state_path, "w"))
        self.assertEqual(self.main(), 0)
        md = open(self.out + "/report_draft.md", encoding="utf-8").read()
        self.assertIn("↻ 10/11 보고", md)
        self.assertIn("1,200,000", md, "이전 보고 때 가격(1,200,000원)이 초안 어디에도 없다")

    def test_run6_comps_not_claimed_when_keyword_query_failed(self):
        """results.js가 키워드 조회에 실패해 null을 주면 초안은 '낙찰 사례 없음'이라고 쓴다."""
        row = {**a_row("B-1"), "scrnPrptDvsnNm": "동산", "alcYn": "N", "onbidCltrNm": "순금팔찌 1점", "ctgrFullNm": "시계/귀금속 / 귀금속"}
        self.write_search((), (row,))
        P = mock.patch
        P.object(run.A, "select_A", return_value=([], stats()["A"])).start()
        P.object(run.A, "select_D", return_value=([], stats()["D"])).start()
        P.object(run.A, "select_B", return_value=([{"row": row, "rounds": [row], "score": 5}], stats()["B"], [])).start()
        P.object(run.A, "select_C", return_value=([], stats()["C"], [])).start()
        P.object(run, "run_details", lambda *a, **k: None).start()
        P.object(run, "verify_link", lambda url, mng: True).start()
        P.object(run.media, "collect", return_value={}).start()
        P.object(track, "STATE", self.state_path).start()
        P.object(run.parse, "parse_item", side_effect=lambda mng, d: dict(parsed_a(mng), name="순금팔찌 1점", kv={"물품명": "순금팔찌 1점"})).start()
        os.makedirs(f"{self.out}/items", exist_ok=True)
        open(f"{self.out}/items/B-1.done", "w").close()
        P.object(run.track, "run_results", return_value={"items": {}, "keywords": {"B:순금": None}}).start()
        argv = ["run", "--out", self.out, "--skip-search", "--today", "2026-10-18"]
        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(run.main(), 0)
        md = open(self.out + "/report_draft.md", encoding="utf-8").read()
        self.assertNotIn("낙찰 사례 없음", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
