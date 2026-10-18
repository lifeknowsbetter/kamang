"""R1(KNOWLEDGE 7절): 현황도로는 유리한 신호(FAVOR)가 아니라 경고(CAUTION)로 표시한다."""
import datetime
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from onbid import analyze, report  # noqa: E402
from onbid.tests.test_e2e import a_row, parsed_item  # noqa: E402

TODAY = datetime.date(2026, 10, 18)


def build(notes=(), use=""):
    it = {**parsed_item("2026-00001-001"), "row": a_row(), "land_class": "우선", "link": "https://x", "notes": list(notes)}
    it["kv"] = {"이용상태": use}
    return analyze.build_A([it], TODAY)[0]


class TestR1(unittest.TestCase):
    def test_constants_do_not_overlap(self):
        for w in analyze.CAUTION:
            self.assertNotIn(w, analyze.FAVOR)
            self.assertFalse(any(w in f for f in analyze.FAVOR), w)

    def test_hyeonhwang_doro_is_caution_not_favor(self):
        for t in ("- 본건은 현황도로로 사용 중임", "- 본건은 현황 도로 부분임", "ㅇ 지상은 마을 진입로 도로로 이용 중"):
            a = build(notes=[t])
            self.assertEqual(a["favor_flags"], [], t)
            self.assertTrue(a["caution_flags"], t)

    def test_other_favor_words_unchanged(self):
        a = build(notes=["- 인접 아파트 옹벽이 일부 침범하고 있음", "- 담장 설치됨"])
        self.assertEqual(set(a["favor_flags"]), {"아파트 옹벽", "옹벽", "침범", "담장"})
        self.assertEqual(a["caution_flags"], [])

    def test_report_shows_warning_line_without_favor_phrase(self):
        a = build(notes=["- 본건은 현황도로로 사용 중임"])
        a["media"] = {}
        txt = report.block_A(0, a, TODAY)
        self.assertIn("⚠ 현황도로 표기", txt)
        self.assertIn("2016다264556", txt)
        self.assertNotIn("지분 되팔기 전략에 유리한 신호", txt)

    def test_report_keeps_favor_line_for_other_words(self):
        a = build(notes=["- 아파트 옹벽 일부 침범"])
        a["media"] = {}
        txt = report.block_A(0, a, TODAY)
        self.assertIn("지분 되팔기 전략에 유리한 신호", txt)
        self.assertNotIn("⚠ 현황도로 표기", txt)

    def test_grade_is_not_changed_by_caution(self):
        self.assertEqual(build(notes=["- 현황도로"])["grade"], build(notes=[])["grade"])


if __name__ == "__main__":
    unittest.main()
