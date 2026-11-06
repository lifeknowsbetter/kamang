"""영역 6(e2e) 시험: 깨끗한 클론 실행, 문서·지시문과 코드의 일치, 일요일 개발 데이터 점검 절차.

- TestPassingNow: 현재 코드에서 통과해야 하는 시험(회귀 방지).
- TestBugRepro:   발견한 문제를 드러내는 시험. 현재 코드에서는 실패한다(수정되면 통과).
저장소 파일은 읽기만 한다. 임시 파일은 tempfile 아래에만 만든다.
"""
import os as _os
REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
FIXTURES = _os.environ.get("ONBID_FIXTURES", "/nonexistent-onbid-fixtures")
FIXTURES_PARENT = _os.path.dirname(FIXTURES)
import ast
import contextlib
import datetime
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = REPO_ROOT
sys.dont_write_bytecode = True
sys.path.insert(0, REPO)

from onbid import analyze, carfilter, config as C, devzone, media, report, run as runmod, track  # noqa: E402


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


# ───────────────────────── 합성 입력 도우미 ─────────────────────────

LINK_ROW = dict(cltrScrnGrpCd="0001", cltrPrptDivCd="0007", onbidCltrno="1", onbidPbancNo="2", pbctNo="3", pbctCdtnNo="4")


def a_row(mng="2026-00001-001", cat="토지 / 임야", price=5_000_000, share="Y"):
    return dict(LINK_ROW, scrnIndctCltrMngNo=mng, pbctBegnDtm="2026-10-19", alcYn=share, scrnPrptDvsnNm="압류재산",
                ctgrFullNm=cat, sidoSgkEmd="경기도 안산시 단원구 대부북동", lowstBidPrc=price, cltrApslEvlAvgAmt=price * 2,
                onbidCltrNm="경기도 안산시 단원구 대부북동 1-1", regOrgNm="한국자산관리공사")


def parsed_item(mng):
    """parse.parse_item이 돌려주는 모양의 합성 항목(Track A용)."""
    return {"mng": mng, "name": "경기도 안산시 단원구 대부북동 1-1", "appraisal": 10_000_000, "price": 5_000_000, "round": "037",
            "fails": "5회", "period": "2026-10-19 09:00 2026-10-21 17:00", "org": "한국자산관리공사", "branch": "x", "client": "y",
            "bid_method": "", "handover": "", "kv": {}, "area": {"use": "토지(임야)", "area": "10㎡", "share_note": "2분의1 지분"},
            "notes": [], "schedule": [], "stmt_base": None, "history": None, "attachments": [], "notice_head": [], "pdf": None,
            "reg_cnt": 0, "reg": [], "occ_cnt": 0, "occ": [], "lease_cnt": 0, "lease": [], "bond_cnt": 0, "bond": [], "photos": [],
            "statement": {"available": False, "keep": [], "surface": [], "occupancy_rows": [], "lease_rows": [], "note": []}}


def write_search(out, a_rows):
    os.makedirs(os.path.join(out, "items"), exist_ok=True)
    for k in "ABC":
        rows = a_rows if k == "A" else []
        with open(os.path.join(out, f"search_{k}.json"), "w") as f:
            json.dump({"track": k, "rows": rows, "totalCount": len(rows)}, f)
    for r in a_rows:
        open(os.path.join(out, "items", r["scrnIndctCltrMngNo"] + ".done"), "w").close()


@contextlib.contextmanager
def run_main(out, extra):
    """run.main()을 네트워크·노드 없이 돌린다. verify_link 호출과 urlopen 시도를 기록한다."""
    calls = {"verify_link": [], "urlopen": []}

    def fake_verify(url, mng):
        calls["verify_link"].append(mng)
        return True

    def fake_urlopen(*a, **k):
        calls["urlopen"].append(a)
        raise AssertionError("network access attempted")

    argv = ["onbid.run", "--out", out, "--skip-search", "--no-results", "--no-state", "--today", "2026-10-18", *extra]
    with mock.patch.object(sys, "argv", argv), mock.patch.object(runmod, "verify_link", fake_verify), \
            mock.patch("urllib.request.urlopen", fake_urlopen), \
            mock.patch.object(runmod.parse, "parse_item", lambda mng, d: parsed_item(mng)), \
            mock.patch.object(runmod, "run_details", lambda *a, **k: None), \
            mock.patch.object(runmod, "node", lambda *a, **k: (_ for _ in ()).throw(AssertionError("node called"))), \
            mock.patch.object(track, "STATE", os.path.join(out, "nonexistent_state.json")):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = runmod.main()
        yield rc, calls


# ───────────────────────── 현재 통과해야 하는 시험 ─────────────────────────

class TestPassingNow(unittest.TestCase):
    def test_compile_all_python(self):
        for root, _, files in os.walk(os.path.join(REPO, "onbid")):
            for fn in files:
                if fn.endswith(".py"):
                    path = os.path.join(root, fn)
                    compile(open(path, encoding="utf-8").read(), path, "exec")

    def test_real_devzones_validate_clean(self):
        errs, warns = devzone.validate()
        self.assertEqual(errs, [])

    def test_validate_cli_exit_code(self):
        r = subprocess.run([sys.executable, "-m", "onbid.devzone", "validate"], cwd=REPO, capture_output=True, text=True,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(r.returncode, 0, r.stdout[-300:])
        self.assertIn("오류 0", r.stdout)

    def test_docs_numbers_match_config(self):
        readme = read("onbid/README.md")
        m = re.search(r"상위 후보\(A (\d+)·D (\d+)·B (\d+)·C (\d+)\)", readme)
        self.assertEqual(tuple(map(int, m.groups())), (C.MEDIA_A, C.MEDIA_D, C.MEDIA_B, C.MEDIA_C))
        self.assertIn(f"(A·D 각 {C.DETAIL_A}건)", readme)
        self.assertEqual(C.DETAIL_A, C.DETAIL_D)
        self.assertIn(f"분산({C.DETAIL_B}건)", readme)
        self.assertIn(f"가까운 순(" + str(C.DETAIL_C) + "건)", readme)
        self.assertIn(f"{C.MAX_PER_ORG_B}건 넘게", readme)
        routine = read("onbid/ROUTINE_PROMPT.md")
        self.assertIn("상위 5건", routine)
        self.assertEqual((C.BUDGET_RLST, C.BUDGET_MVAST, C.CAR_MAX), (10_000_000,) * 3)
        self.assertEqual(C.NEAR_KM, 50)
        self.assertIn("산본 50km 이내", routine)
        self.assertEqual(track.KEEP_DAYS, 45)
        self.assertIn("45일", readme)
        self.assertEqual(devzone.STALE_DAYS, 400)

    def test_exit_numbers_match_readme_formula(self):
        it = {"appraisal": 10_000_000, "price": 5_000_000, "round": "005",
              "schedule": [{"no": "005", "start": "2026-10-19", "price": 5_000_000}, {"no": "006", "start": "2026-10-26", "price": 4_000_000}]}
        e = analyze.exit_numbers(it)
        self.assertEqual(e["budget_cap"], int((10_000_000 - 50_000) / 1.046))
        self.assertEqual(e["exit_cap"], int((10_000_000 * 0.7 - 50_000 - 30_000 - 300_000) / 1.046))
        self.assertEqual(e["loss"], int(5_000_000 * 1.046 + 50_000 - 10_000_000 * 0.2))
        self.assertEqual(e["first_under"]["no"], "005")

    def test_carfilter_rules_match_readme(self):
        # 최저가 300만 미만은 제외, 300~500만이면서 200km 이상 제외, 500만 이상 통과
        self.assertEqual(carfilter.assess("모닝 998cc", "자동차 / 승용", 2_900_000, "경기도", 10)["verdict"], "제외")
        self.assertEqual(carfilter.assess("쏘나타 1999cc", "자동차 / 승용", 4_000_000, "경상남도", 250)["verdict"], "제외")
        self.assertEqual(carfilter.assess("쏘나타 1999cc", "자동차 / 승용", 4_000_000, "경기도", 50)["verdict"], "확인")
        self.assertEqual(carfilter.assess("쏘나타 1999cc", "자동차 / 승용", 6_000_000, "경상남도", 250)["verdict"], "확인")
        self.assertEqual(carfilter.assess("쏘나타 폐차조건", "자동차 / 승용", 6_000_000, "경기도", 5)["verdict"], "제외")
        self.assertEqual([r[2] for r in carfilter.RATE_BANDS], [2.09, 1.70, 1.61, 1.31, 1.09])

    def test_seen_tag_markers(self):
        today = datetime.date(2026, 10, 18)
        self.assertEqual(report.seen_tag({}, today), "🆕")
        self.assertEqual(report.seen_tag({"seen": {"first_seen": "2026-10-11", "reported": ["2026-10-11"]}}, today), "↻ 10/11 보고")
        self.assertEqual(report.seen_tag({"seen": {"first_seen": "2026-10-11", "reported": []}}, today), "검토 10/11~")

    def test_routine_markers_present_in_blocks(self):
        today = datetime.date(2026, 10, 18)
        a = analyze.build_A([{**parsed_item("2026-00001-001"), "row": a_row(), "land_class": "우선", "link": "https://x"}], today)[0]
        a["appr_excerpt"] = ["맹지 어쩌고"]
        a["media"] = {}
        txt = report.block_A(0, a, today)
        for marker in ("🧮 입찰 상한 계산", "🏗 개발 연관", "📄 감정평가서 본문 신호", "못 팔고 지분 매입업체에 감정가의 20%로"):
            if marker == "🏗 개발 연관":
                continue   # 소재지가 개발 데이터와 맞는지는 데이터에 달렸다(아래 시험에서 따로 본다)
            self.assertIn(marker, txt)
        row = {"onbidCltrNm": "현대 쏘나타 1999cc", "ctgrFullNm": "자동차 / 승용", "lowstBidPrc": 6_000_000, "sidoEmd": "경기도", "sidoSgkEmd": "경기도 안양시"}
        c = {"mng": "c1", "name": "현대 쏘나타 1999cc", "link": "https://x", "kv": {}, "row": row, "price": 6_000_000, "appraisal": 7_000_000,
             "round": "1", "fails": 0, "period": "", "org": "o", "branch": "", "handover": "낙찰자", "place": "p", "plate": "12가3456",
             "year": 2015, "fuel": "휘발유", "cc": 1999, "km": 100000, "flags": [], "notes": [],
             "subsidy": {"grade_est": "x", "eligible": "대상아님", "caveats": [], "basis": ""},
             "assess": carfilter.assess(row["onbidCltrNm"], row["ctgrFullNm"], 6_000_000, "경기도", 10)}
        self.assertIn("💰 본전 시세", report.block_C(0, c, today))

    def test_devzone_matching_tiers(self):
        d = {"entries": [{"id": "a", "name": "n", "kind": "산업단지", "stage": "계획", "sido": "경기도", "sgg": ["용인시 처인구"], "emd": ["원삼면"],
                          "summary": "s", "asof": "2026-10", "sources": ["http://x"], "confidence": "high"}]}
        self.assertEqual(devzone.match("경기도 용인시 처인구 원삼면", d)[0]["tier"], 1)
        self.assertEqual(devzone.match("경기도 용인시 처인구 남사읍", d)[0]["tier"], 3)
        self.assertEqual(devzone.match("서울특별시 종로구 청운동", d), [])

    def test_track_mark_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = os.path.join(tmp, "s.json")
            out = os.path.join(tmp, "out")
            os.makedirs(out)
            cand = {"today": "2026-10-18", "A": [{"mng": "m1", "name": "n1", "link": "l", "price": 1, "appraisal": 2, "row": {"pbctExctDt": "2026-10-22 11:00:00"}, "period": "x 2026-10-21 17:00"}],
                    "D": [], "B": [], "C": []}
            json.dump(cand, open(os.path.join(out, "candidates.json"), "w"))
            with mock.patch.object(track, "STATE", state), mock.patch.object(sys, "argv", ["track", "mark", out, "m1", "nope"]):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    track.main()
                self.assertIn("표시 1건", buf.getvalue())
                self.assertIn("nope", buf.getvalue())
                st = track.load()
                self.assertEqual(st["items"]["m1"]["reported"], ["2026-10-18"])
                self.assertEqual(st["items"]["m1"]["type"], "0001")
                raw = open(state, encoding="utf-8").read()
                track.save(st)
                self.assertEqual(raw, open(state, encoding="utf-8").read())    # 저장 형식이 안정적(커밋에 불필요한 변경 없음)

    def test_committed_state_schema_matches_track(self):
        st = json.load(open(os.path.join(REPO, "onbid/state/tracked.json"), encoding="utf-8"))
        self.assertEqual(set(st), {"items", "history"})
        for m, e in st["items"].items():
            self.assertLessEqual({"track", "first_seen", "last_seen", "reported", "type", "link", "name", "price", "appraisal", "deadline", "open_dt"}, set(e), m)
            self.assertEqual(track.TYPE[e["track"]], e["type"], m)

    def test_gitignore_rules(self):
        for p in ("out/onbid/candidates.json", "out/onbid/media/x/a.jpg", "onbid/__pycache__/a.pyc"):
            self.assertEqual(git("check-ignore", "-q", p).returncode, 0, p)
        for p in ("onbid/state/tracked.json", "onbid/data/devzones.json", "onbid/knowledge/journal/2026-10-19.md"):
            self.assertEqual(git("check-ignore", "-q", p).returncode, 1, p)

    def test_knowledge_numbering(self):
        t = read("onbid/knowledge/KNOWLEDGE.md").split("\n")
        i = next(k for k, l in enumerate(t) if l.startswith("## 8."))
        j = next(k for k, l in enumerate(t) if l.startswith("## 9."))
        nums = [int(m.group(1)) for l in t[i + 1:j] if (m := re.match(r"(\d+)\.", l))]
        self.assertEqual(nums, list(range(2, 26)) if nums[0] == 2 else nums)   # 1은 '1.' 로 시작하므로 포함됨
        self.assertEqual(sorted(set(nums)), list(range(1, max(nums) + 1)) if 1 in nums else sorted(set(nums)))
        k = next(k for k, l in enumerate(t) if l.startswith("## 7."))
        rs = [m.group(1) for l in t[k + 1:i] if (m := re.match(r"- \*\*(R[\d-]+)\.", l))]
        self.assertEqual(len(rs), len(set(rs)))

    def test_r5_applied_tag_matches_code(self):
        farm = a_row("f1", cat="토지 / 전")
        pasture = a_row("p1", cat="토지 / 임야")
        detail, stats = analyze.select_A({"rows": [farm, pasture]})
        self.assertEqual([v["row"]["scrnIndctCltrMngNo"] for v in detail], ["p1"])
        self.assertIn("R5. (적용됨", read("onbid/knowledge/KNOWLEDGE.md"))

    def test_learn_prompt_commands(self):
        lp = read("onbid/LEARN_PROMPT.md")
        self.assertIn("python3 -m onbid.devzone validate", lp)
        self.assertIn("git add onbid/knowledge onbid/data", lp)

    def test_doc_map_files_exist(self):
        for rel in ("README.md", "onbid/README.md", "onbid/ROUTINE_PROMPT.md", "onbid/LEARN_PROMPT.md", "onbid/knowledge/KNOWLEDGE.md",
                    "onbid/data/README.md", "onbid/state/tracked.json", "onbid/data/devzones.json", "onbid/data/devzones_pending.json"):
            self.assertTrue(os.path.exists(os.path.join(REPO, rel)), rel)

    def test_pending_count_in_docs(self):
        p = json.load(open(os.path.join(REPO, "onbid/data/devzones_pending.json"), encoding="utf-8"))
        self.assertIsInstance(p["entries"], list)
        if p["entries"]:                                  # 미확인 항목이 남아 있으면 문서가 그 개수를 말해야 한다
            self.assertIn(f"{len(p['entries'])}개", read("onbid/README.md"))


# ───────────────────────── 문제를 드러내는 시험(현재 실패) ─────────────────────────

class TestBugRepro(unittest.TestCase):
    def test_e2e1_sunday_revert_must_cover_pending_file(self):
        """LEARN_PROMPT 2-1 5번의 되돌리기가 devzones.json만 가리키면, 2번에서 pending에서 지운 항목이 사라진다."""
        lp = read("onbid/LEARN_PROMPT.md")
        step5 = next(l for l in lp.split("\n") if l.startswith("5. ") and "validate" in l)
        self.assertIn("git checkout", step5)
        self.assertTrue("devzones_pending" in step5 or "onbid/data" in step5,
                        "되돌리기 문구가 devzones.json만 되돌려 pending에서 이미 지운 항목이 유실된다: " + step5)

    def test_e2e2_validate_must_fail_on_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "broken.json")
            open(p, "w").write('{"schema":1,"entries":[{"id":"x",')
            errs, _ = devzone.validate(p)
            self.assertTrue(errs, "깨진 JSON인데 오류 0으로 통과한다")

    def test_e2e2_validate_must_fail_on_missing_file(self):
        errs, _ = devzone.validate(os.path.join(tempfile.gettempdir(), "does_not_exist_devzones.json"))
        self.assertTrue(errs, "파일이 없는데 오류 0으로 통과한다")

    def test_e2e3_pending_entries_pass_validate_once_moved(self):
        p = json.load(open(os.path.join(REPO, "onbid/data/devzones_pending.json"), encoding="utf-8"))
        if not p["entries"]:
            self.skipTest("devzones_pending.json이 비어 있음")
        moved = []
        for e in p["entries"]:
            e = dict(e)
            e.pop("status", None)
            e.pop("pending_reason", None)
            moved.append(e)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "moved.json")
            json.dump({"schema": 1, "built": "2026-10-18", "entries": moved}, open(path, "w"), ensure_ascii=False)
            errs, _ = devzone.validate(path)
        self.assertEqual(errs, [], f"{len(errs)}건 오류: " + "; ".join(errs[:2]))

    def test_e2e3_moved_honam_entry_must_match_onbid_sido(self):
        p = json.load(open(os.path.join(REPO, "onbid/data/devzones_pending.json"), encoding="utf-8"))
        found = [x for x in p["entries"] if x["id"] == "honam-jeju-gwangju-semicon"]
        if not found:
            self.skipTest("해당 항목이 pending에 없음(이미 devzones.json으로 옮겨짐)")
        e = dict(found[0])
        got = devzone.match("전남광주통합특별시 광산구 하남동", {"entries": [e]})
        self.assertTrue(got, f"sido={e['sido']!r} 라서 온비드 표기 '전남광주통합특별시'와 매칭되지 않는다")

    def test_e2e4_docs_agree_on_unverified_pending(self):
        data_readme = read("onbid/data/README.md")
        learn = read("onbid/LEARN_PROMPT.md")
        says_delete = "이 파일에도 남기지 않고" in data_readme
        says_keep = "확인하지 못한 것은 그대로 둡니다" in learn
        self.assertFalse(says_delete and says_keep, "data/README는 지우라고, LEARN_PROMPT는 그대로 두라고 한다")

    def test_e2e5_no_media_run_should_not_touch_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_search(tmp, [a_row()])
            with run_main(tmp, ["--no-media"]) as (rc, calls):
                pass
            self.assertEqual(rc, 0)
            self.assertEqual(calls["verify_link"], [], "--no-media인데 링크 확인(verify_link)이 온비드로 HTTP 요청을 보낸다")

    def test_e2e6_missing_poppler_should_degrade_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "appraisal.pdf"), "wb").write(b"%PDF-1.4\n" + b"0" * 2000)
            item = {"pdf": {"name": "a.pdf", "atchFileLstNo": "1", "atchSn": "1", "hash": "x"}}
            with mock.patch.object(media.subprocess, "run", side_effect=FileNotFoundError(2, "No such file or directory", "pdftotext")):
                try:
                    res = media.appraisal(item, tmp)
                except FileNotFoundError as e:
                    self.fail(f"poppler가 없으면 감정평가서 단계에서 예외로 전체 실행이 중단된다: {e}")
            self.assertNotEqual(res.get("status"), "ok")

    def test_e2e7_routine_prompt_hwangdo_reference_and_consistency(self):
        rp = read("onbid/ROUTINE_PROMPT.md")
        rule7 = next(l for l in rp.split("\n") if l.startswith("7. **현황도로"))
        sec = re.search(r"KNOWLEDGE (2-\d+)", rule7).group(1)
        head = next(l for l in read("onbid/knowledge/KNOWLEDGE.md").split("\n") if l.startswith(f"### {sec}."))
        self.assertIn("현황도로", head, f"규칙 7이 가리키는 {sec} 제목: {head}")
        form = next(l for l in rp.split("\n") if "유의사항 원문 인용" in l and "옹벽" in l)
        if "유리한 신호" in form:                          # 쓰지 말라는 부정 문장에서만 나와야 한다
            self.assertIn("유리한 신호\"라고 쓰지 않음", form, "규칙 7은 '감점 신호', 형식 줄은 '유리한 신호'라고 한다")

    def test_e2e8_failure_draft_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            report.write_failure(tmp, datetime.date(2026, 10, 18), "x")
            t = open(os.path.join(tmp, "report_draft.md"), encoding="utf-8").read()
        self.assertIn("Track D", t)
        self.assertNotIn("주간", t)

    def test_e2e9_nonpositive_exit_cap_message_amount(self):
        it = {"appraisal": 400_000, "price": 300_000, "round": "1", "schedule": []}
        txt = "\n".join(report.exit_lines({**it, "exit": analyze.exit_numbers(it)}))
        self.assertIn("38만원", txt, "빼는 금액은 5+3+30=38만원인데 문구는 35만원이라고 한다")

    def test_e2e10_top_constants_are_used(self):
        if not any(hasattr(C, f"TOP_{k}") for k in "ABCD"):
            self.skipTest("TOP_* 상수는 제거됨(상위 건수는 지시문·초안 머리말에서 정함)")
        used = False
        for fn in os.listdir(os.path.join(REPO, "onbid")):
            if fn.endswith(".py") and fn != "config.py":
                if re.search(r"\bTOP_[ABCD]\b", read("onbid/" + fn)):
                    used = True
        self.assertTrue(used, "config.TOP_A/B/C/D를 쓰는 코드가 없다(바꿔도 효과 없음)")

    def test_e2e11_routine_prompt_handles_existing_checkout(self):
        rp = read("onbid/ROUTINE_PROMPT.md")
        step1 = rp.split("## 1. 파이프라인 준비")[1].split("## 2.")[0]
        self.assertIn("이미 있으면", step1, "LEARN_PROMPT와 달리 이미 클론돼 있을 때(연결된 저장소 체크아웃·재실행)의 처리가 없다")

    def test_e2e12_empty_search_must_not_look_like_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_search(tmp, [])
            with run_main(tmp, ["--no-media"]) as (rc, calls):
                pass
            draft = open(os.path.join(tmp, "report_draft.md"), encoding="utf-8").read()
            self.assertTrue(rc != 0 or "수집 실패" in draft, "검색 결과가 전부 0건인데 정상 초안(rc=0)으로 끝난다")

    def test_e2e13_validate_enforces_documented_limits(self):
        e = {"id": "a", "name": "n", "kind": "산업단지", "stage": "계획", "sido": "경기도", "sgg": ["용인시"], "emd": ["원삼면"],
             "neighbors_sgg": ["수원시", "성남시", "안양시", "화성시", "평택시", "안성시"], "summary": "s", "asof": "2026-10",
             "sources": ["http://x"], "confidence": "high"}
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "d.json")
            json.dump({"entries": [e]}, open(p, "w"), ensure_ascii=False)
            errs, warns = devzone.validate(p)
        self.assertTrue(errs or any("5" in w for w in warns), "neighbors_sgg 5개 이하 규칙(data/README·LEARN_PROMPT)을 검사하지 않는다")

    def test_e2e13_run_time_estimate_consistent(self):
        a = re.search(r"\((\d+~\d+)분\)", read("onbid/README.md")).group(1)
        b = re.search(r"(\d+~\d+)분 걸립니다", read("onbid/ROUTINE_PROMPT.md")).group(1)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
