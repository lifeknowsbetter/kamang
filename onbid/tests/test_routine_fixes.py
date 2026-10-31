"""2026-10-18 평일 루틴 시험 실행(월요일 가정)에서 드러난 문제의 재발 방지."""
import datetime
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from onbid import config as C  # noqa: E402
from onbid import media, report  # noqa: E402
from onbid import run as R  # noqa: E402


def row(mng, deadline):
    return {"scrnIndctCltrMngNo": mng, "pbctDdlnDt": deadline}


class TestDropClosed(unittest.TestCase):
    def test_drops_rows_closing_before_cutoff(self):
        s = {"A": {"rows": [row("a1", "2026-10-19 16:00"), row("a2", "2026-10-19 18:00"), row("a3", "2026-10-19 20:00"), row("a4", "2026-10-21 17:00")]},
             "B": {"rows": [row("b1", "2026-10-19 19:20")]}, "C": {"rows": []}}
        cutoff = datetime.datetime(2026, 10, 19, 18, 48) + datetime.timedelta(minutes=C.CLOSE_MARGIN_MIN)       # 19:28
        n = R.drop_closed(s, cutoff)
        self.assertEqual(n, 3)
        self.assertEqual([r["scrnIndctCltrMngNo"] for r in s["A"]["rows"]], ["a3", "a4"])
        self.assertEqual(s["B"]["rows"], [])

    def test_keeps_rows_without_readable_deadline_and_other_keys(self):
        s = {"A": {"rows": [{"scrnIndctCltrMngNo": "x"}, row("y", ""), row("z", "미정")], "totalCount": 3}}
        n = R.drop_closed(s, datetime.datetime(2030, 1, 1))
        self.assertEqual(n, 0)
        self.assertEqual(len(s["A"]["rows"]), 3)
        self.assertEqual(s["A"]["totalCount"], 3)

    def test_falls_back_to_last_deadline_field(self):
        s = {"A": {"rows": [{"scrnIndctCltrMngNo": "x", "pbctLastDdlnDt": "2026-10-19 10:00"}]}}
        self.assertEqual(R.drop_closed(s, datetime.datetime(2026, 10, 19, 12, 0)), 1)


class TestPipelineDropsClosed(unittest.TestCase):
    def test_draft_excludes_closed_and_says_so(self):
        import json
        import tempfile
        from onbid.tests.test_e2e import a_row, run_main, write_search
        closed = dict(a_row("2026-00001-001"), pbctDdlnDt="2026-10-19 16:00")
        open_ = dict(a_row("2026-00002-001"), pbctDdlnDt="2026-10-21 17:00")
        with tempfile.TemporaryDirectory() as tmp:
            write_search(tmp, [closed, open_])
            with run_main(tmp, ["--no-media", "--today", "2026-10-19"]) as (rc, _):
                pass
            self.assertEqual(rc, 0)
            data = json.load(open(os.path.join(tmp, "candidates.json"), encoding="utf-8"))
            draft = open(os.path.join(tmp, "report_draft.md"), encoding="utf-8").read()
        self.assertEqual(data["closed_dropped"], 1)
        self.assertEqual([x["mng"] for x in data["A"]], ["2026-00002-001"])
        self.assertIn("마감하는 물건 1건은 목록에서 뺐다", draft)


class TestPickPages(unittest.TestCase):
    def test_short_documents_are_kept_whole(self):
        self.assertEqual(media._pick_pages([3, 1, 2]), [3, 1, 2])
        self.assertEqual(media._pick_pages(list(range(1, media.MAX_PDF_PAGES + 1))), list(range(1, media.MAX_PDF_PAGES + 1)))

    def test_long_documents_keep_head_and_tail(self):
        got = media._pick_pages(list(range(1, 31)))
        self.assertEqual(len(got), media.MAX_PDF_PAGES)
        self.assertEqual(got[0], 1)
        self.assertEqual(got[-1], 30)
        self.assertTrue(set(range(23, 31)) <= set(got), got)       # 28쪽 스캔본의 요항표(22~28쪽)가 빠지던 문제


class TestPushStepInPrompt(unittest.TestCase):
    def test_routine_prompt_requires_push_summary(self):
        s = open(os.path.join(REPO_ROOT, "onbid", "ROUTINE_PROMPT.md"), encoding="utf-8").read()
        i = s.index("## 6. 푸시 알림")
        sec = s[i:]
        for must in ("PushNotification", "반드시", "select:PushNotification", "<routine_summary>", "proactive", "푸시 요약 전송 실패"):
            self.assertIn(must, sec)
        self.assertGreater(i, s.index("## 5. 추적 표시와 저장"))          # 저장 뒤, 최종 응답 직전


if __name__ == "__main__":
    unittest.main()
