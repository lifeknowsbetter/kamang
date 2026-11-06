"""영역 appr 시험: 감정평가서 신호(appraisal_signals·apply_appraisal)·출구 계산(exit_numbers)·상세 파싱(parse.py)·media.py.

실행: cd /tmp && python3 -I -m unittest -v <이 파일의 디렉터리>.test_appr   (또는 python3 test_appr.py)

구성
  TestCurrent*  현재 코드에서 통과하는 시험(의도된 동작이 맞는지 고정)
  TestBug*      버그를 드러내는 시험. 기대 동작을 단언하므로 현재 코드에서는 실패한다.
저장소 파일은 건드리지 않는다. 임시 파일은 scratch 아래에만 만든다.
"""
import os as _os
REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
FIXTURES = _os.environ.get("ONBID_FIXTURES", "/nonexistent-onbid-fixtures")
FIXTURES_PARENT = _os.path.dirname(FIXTURES)
import base64
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from fractions import Fraction as F

sys.path.insert(0, REPO_ROOT)

from onbid import analyze, config as C, media, parse, report  # noqa: E402

SCRATCH = FIXTURES
WORK = tempfile.mkdtemp(prefix="onbid_test_")
T5 = FIXTURES
os.makedirs(WORK, exist_ok=True)


# ───────────────────────── 도우미 ─────────────────────────

def tmp_text(text):
    fd, p = tempfile.mkstemp(suffix=".txt", dir=WORK)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def sig(text):
    """감정평가서 본문 text → appraisal_signals의 (flags)."""
    p = tmp_text(text)
    try:
        return analyze.appraisal_signals(p)[0]
    finally:
        os.unlink(p)


def msgs(flags):
    return {m for _, m in flags}


def clip_raw(lines, pages=1):
    """합성 ClipReport 응답(parse.clip_lines가 읽는 형식)."""
    def item(t):
        ch = [urllib.parse.quote_plus(c) for c in t]
        return [ch, [0] * len(ch)]
    per = max(1, (len(lines) + pages - 1) // pages)
    pg = [[item(t) for t in lines[i:i + per]] for i in range(0, len(lines), per)]
    vd = {"pageNumList": list(range(1, len(pg) + 1)), "pageList": [[p] for p in pg]}
    body = json.dumps({"id": 1, "resValue": {"viewData": base64.b64encode(json.dumps(vd).encode()).decode()}})
    return "fn_pbctPrptDstmtReport('2026','1');\n=========\nClipType=x\n----\n" + body


def mk_item_dir(html, xhr=None, img=None, stmt=None):
    d = tempfile.mkdtemp(dir=WORK)
    open(d + "/M.html", "w", encoding="utf-8").write(html)
    for ext, v in (("xhr", xhr), ("img", img), ("stmt", stmt)):
        if v is not None:
            open(f"{d}/M.{ext}", "w", encoding="utf-8").write(v)
    return d


def text_pdf(path, text):
    """글자 층이 있는 1쪽 PDF(Helvetica, ASCII). xref는 poppler가 복구한다."""
    rows = [text[i:i + 70] for i in range(0, len(text), 70)]            # 쪽 밖으로 나간 글자는 pdftotext가 버리므로 줄바꿈한다
    stream = ("BT /F1 10 Tf 40 750 Td 12 TL " + " ".join(f"({r}) Tj T*" for r in rows) + " ET").encode()
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            b"<</Length %d>>\nstream\n" % len(stream) + stream + b"\nendstream", b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out = b"%PDF-1.4\n%" + b"x" * 1200 + b"\n"          # media.appraisal은 1,000바이트 이하 캐시를 무시하고 내려받으려 하므로 채운다
    for i, o in enumerate(objs, 1):
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    out += b"trailer\n<</Root 1 0 R/Size 6>>\n%%EOF\n"
    open(path, "wb").write(out)


def image_pdf(path, n, size=(800, 1100)):
    from PIL import Image
    ims = [Image.effect_noise(size, 60).convert("RGB") for _ in range(n)]
    ims[0].save(path, "PDF", save_all=True, append_images=ims[1:], resolution=100)


# ───────────────────────── 현재 통과하는 시험 ─────────────────────────

class TestCurrentExit(unittest.TestCase):
    def test_budget_cap_formula(self):
        # (1,000만 − 5만) ÷ 1.046 = 9,512,428.3…
        self.assertEqual(analyze.exit_numbers({})["budget_cap"], 9_512_428)
        self.assertEqual(analyze.exit_numbers({})["budget_cap"], int(F(10_000_000 - 50_000) / F("1.046")))

    def test_exit_cap_and_loss_hand_calc(self):
        # 감정가 2,000만, 현재가 600만: 출구 상한 (1,400만−38만)/1.046 = 13,021,032.5
        e = analyze.exit_numbers({"appraisal": 20_000_000, "price": 6_000_000})
        self.assertEqual(e["exit_cap"], 13_021_032)
        # 손실 = 600만×1.046 + 5만 − 2,000만×0.2 = 627.6만+5만−400만 = 2,326,000
        self.assertEqual(e["loss"], 2_326_000)

    def test_exit_cap_matches_exact_within_1won(self):
        for a in (1_000_000, 3_816_000, 7_695_000, 29_820_000, 60_000_000):
            e = analyze.exit_numbers({"appraisal": a})
            exact = (F(a) * F(7, 10) - 380_000) / F("1.046")
            self.assertLessEqual(abs(e["exit_cap"] - int(exact)), 1, a)

    def test_none_and_zero_inputs(self):
        self.assertEqual(set(analyze.exit_numbers({"appraisal": None, "price": None})), {"budget_cap"})
        self.assertEqual(set(analyze.exit_numbers({"appraisal": 0, "price": 5})), {"budget_cap", "over_budget"})
        e = analyze.exit_numbers({"appraisal": 10_000_000, "price": None})
        self.assertIn("exit_cap", e)
        self.assertNotIn("loss", e)

    def test_negative_cap_has_no_first_under(self):
        e = analyze.exit_numbers({"appraisal": 300_000, "price": 100_000, "round": "1",
                                  "schedule": [{"no": "1", "price": 100_000}]})
        self.assertLess(e["exit_cap"], 0)
        self.assertNotIn("first_under", e)

    def test_first_under_starts_at_current_round_not_before(self):
        sched = [{"no": "030", "price": 1_000_000}, {"no": "031", "price": 900_000}, {"no": "032", "price": 5_000_000},
                 {"no": "033", "price": 800_000}]
        # 감정가 1,000만 → 출구 상한 6,3xx,xxx. 지난 회차(030,031)가 상한 이하여도 현재(032) 이후만 본다.
        e = analyze.exit_numbers({"appraisal": 10_000_000, "price": 5_000_000, "round": "032", "schedule": sched})
        self.assertEqual(e["first_under"]["no"], "032")
        e = analyze.exit_numbers({"appraisal": 8_000_000, "price": 5_000_000, "round": "032", "schedule": sched})
        # 상한 = (560만−38만)/1.046 = 4,990,439 → 032(500만)은 초과, 033(80만)이 첫 회차
        self.assertEqual(e["first_under"]["no"], "033")

    def test_first_under_none_when_no_round_qualifies(self):
        sched = [{"no": "1", "price": 9_000_000}, {"no": "2", "price": 8_000_000}]
        e = analyze.exit_numbers({"appraisal": 1_000_000, "price": 9_000_000, "round": "1", "schedule": sched})
        self.assertIsNone(e["first_under"])

    def test_combined_round_number_matches_first_part(self):
        sched = [{"no": "028/001", "price": 2_000_000}, {"no": "029", "price": 1_000_000}]
        e = analyze.exit_numbers({"appraisal": 10_000_000, "price": 2_000_000, "round": "028", "schedule": sched})
        self.assertEqual(e["first_under"]["no"], "028/001")


class TestCurrentApplyAppraisal(unittest.TestCase):
    def a_item(self, text, grade="낮음", notes=None):
        return {"grade": grade, "notes": notes or [], "media": {"appraisal": {"text": tmp_text(text)}}}

    def d_item(self, text, flags=None, grade="낮음"):
        return {"grade": grade, "risk_flags": list(flags or []), "media": {"appraisal": {"text": tmp_text(text)}}}

    def test_A_landlocked_is_high_and_bad_exit(self):
        it = analyze.apply_appraisal(self.a_item("지적도상 맹지임."), "A")
        self.assertEqual(it["grade"], "높음")
        self.assertTrue(it["bad_exit"])
        self.assertIn(("R", "맹지"), it["appr_flags"])

    def test_A_yellow_raises_only_low_to_mid(self):
        it = analyze.apply_appraisal(self.a_item("본건은 급경사지임."), "A")
        self.assertEqual(it["grade"], "중간")
        self.assertFalse(it["bad_exit"])
        it = analyze.apply_appraisal(self.a_item("본건은 급경사지임.", grade="중간"), "A")
        self.assertEqual(it["grade"], "중간")

    def test_A_info_flag_changes_nothing(self):
        it = analyze.apply_appraisal(self.a_item("분묘의 소재 가능성이 있으니 유의하시기 바람."), "A")
        self.assertEqual(it["grade"], "낮음")
        self.assertFalse(it["bad_exit"])
        self.assertEqual(it["appr_flags"], [("I", "분묘 소재 가능성(유의 문구)")])

    def test_A_field_flag_maps_to_R(self):
        it = analyze.apply_appraisal(self.a_item("공부상 지목은 대지이나 현황은 전으로 이용 중임."), "A")
        self.assertEqual(it["grade"], "높음")
        self.assertEqual(it["appr_flags"][0][0], "R")
        self.assertFalse(it["bad_exit"])          # 현황 농지는 bad_exit(맹지·분묘)가 아니다

    def test_A_bad_exit_from_notes_only(self):
        it = analyze.apply_appraisal({"grade": "낮음", "notes": ["지상에 분묘 3기 소재"], "media": {}}, "A")
        self.assertTrue(it["bad_exit"])
        it = analyze.apply_appraisal({"grade": "낮음", "notes": ["분묘 소재 가능성이 있음"], "media": {}}, "A")
        self.assertFalse(it["bad_exit"])
        it = analyze.apply_appraisal({"grade": "낮음", "notes": ["본건은 맹지가 아님"], "media": {}}, "A")
        self.assertFalse(it["bad_exit"])

    def test_A_no_media_leaves_grade(self):
        it = analyze.apply_appraisal({"grade": "중간", "notes": [], "media": {"appraisal": {"status": "없음"}}}, "A")
        self.assertEqual(it["grade"], "중간")
        self.assertEqual(it["appr_flags"], [])
        self.assertEqual(it["appr_excerpt"], [])

    def test_D_landlocked_is_yellow_not_red(self):
        it = analyze.apply_appraisal(self.d_item("접면도로상황 기호1,2 공히 맹지임."), "D")
        self.assertEqual(it["grade"], "중간")
        self.assertIn(("Y", "감정평가서: 맹지"), it["risk_flags"])

    def test_D_field_flag_is_red(self):
        it = analyze.apply_appraisal(self.d_item("공부상 지목은 대지이나 현황은 전으로 이용 중임."), "D")
        self.assertEqual(it["grade"], "높음")
        self.assertTrue(any(s == "R" and m.startswith("감정평가서: ") for s, m in it["risk_flags"]))

    def test_D_info_flag_becomes_green_and_keeps_grade_low(self):
        it = analyze.apply_appraisal(self.d_item("분묘의 소재 가능성이 있으니 유의하시기 바람."), "D")
        self.assertEqual(it["grade"], "낮음")
        self.assertEqual(it["risk_flags"], [("G", "감정평가서: 분묘 소재 가능성(유의 문구)")])

    def test_D_no_duplicate_when_flag_already_present(self):
        it = analyze.apply_appraisal(self.d_item("접면도로상황 맹지임.", flags=[("Y", "맹지")], grade="중간"), "D")
        self.assertEqual([m for _, m in it["risk_flags"]].count("맹지"), 1)
        self.assertNotIn("감정평가서: 맹지", msgs(it["risk_flags"]))

    def test_D_idempotent(self):
        it = self.d_item("접면도로상황 맹지임. 급경사지임.")
        analyze.apply_appraisal(it, "D")
        first = list(it["risk_flags"])
        analyze.apply_appraisal(it, "D")
        self.assertEqual(it["risk_flags"], first)

    def test_A_idempotent(self):
        it = self.a_item("접면도로상황 맹지임.")
        analyze.apply_appraisal(it, "A")
        flags, grade = list(it["appr_flags"]), it["grade"]
        analyze.apply_appraisal(it, "A")
        self.assertEqual((it["appr_flags"], it["grade"]), (flags, grade))


class TestCurrentSignals(unittest.TestCase):
    def test_basic_positive(self):
        self.assertEqual(sig("본건은 맹지임."), [("R", "맹지")])
        self.assertEqual(sig("본건은 급경사지로 이용에 제한이 있음"), [("Y", "급경사")])
        self.assertEqual(sig("본건까지 차량 접근이 불가능함."), [("Y", "차량 접근 불가")])
        self.assertEqual(sig("지상에 분묘 3기가 소재함"), [("Y", "분묘")])
        self.assertEqual(sig("본건 지상 일부에 제시외 건물이 소재함"), [("Y", "제시외 건물·수목")])

    def test_documented_negations(self):
        for t in ("본건은 맹지가 아님.", "본건은 맹지 아님", "본건은 맹지가 아니며 포장도로에 접함.",
                  "분묘 없음", "분묘가 없으며", "분묘 등은 없음"):
            self.assertEqual(sig(t), [], t)

    def test_grave_maybe_is_info(self):
        for t in ("분묘의 소재 가능성이 있으니 유의", "분묘가 소재할 가능성이 있음"):
            self.assertEqual(sig(t), [("I", "분묘 소재 가능성(유의 문구)")], t)

    def test_field_pattern_positive(self):
        for t in ("공부상 지목은 대지이나 현황은 전으로 이용 중임.", "공부상 지목은 임야이나 현황은 과수원으로 이용 중임.",
                  "지목은 임야이나, 현황 밭으로 이용중", "공부상 지목은 대지이나 현황은 '전'으로 이용 중임."):
            self.assertEqual([s for s, _ in sig(t)], ["F"], t)

    def test_table_lines_ending_with_number_are_skipped(self):
        self.assertEqual(sig("A 목현동 30,248 임 자연림 개발제한 맹지 5,760"), [])
        self.assertEqual(sig("기타규제(고압선, 분묘 등)"), [])

    def test_no_mention_no_flag(self):
        self.assertEqual(sig("본건은 포장도로에 접하며 완경사지임.\n차량 접근이 가능함."), [])

    def test_excerpt_limits(self):
        p = tmp_text("\n".join(f"본건은 맹지임 {i}호" for i in range(20)) + "\n맹지임")
        flags, lines = analyze.appraisal_signals(p)
        self.assertLessEqual(len(lines), 8)
        self.assertEqual(flags, [("R", "맹지")])

    def test_missing_path(self):
        self.assertEqual(analyze.appraisal_signals("/nonexistent/x.txt"), ([], []))
        self.assertEqual(analyze.appraisal_signals(None), ([], []))


class TestCurrentParse(unittest.TestCase):
    def test_money(self):
        self.assertEqual(parse._money("29,820,000"), 29_820_000)
        self.assertEqual(parse._money("7,362,700원"), 7_362_700)
        self.assertIsNone(parse._money("하단참조"))
        self.assertIsNone(parse._money(None))

    def test_empty_files_no_exception(self):
        r = parse.parse_item("M", mk_item_dir(""))
        self.assertIsNone(r["name"])
        self.assertEqual(r["schedule"], [])
        self.assertEqual(r["reg"], [])
        self.assertEqual(r["statement"], {"available": False})

    def test_frag_rows(self):
        html = ('<span>(총 <span class="p">2</span>건)</span><table><thead><tr><th>번호</th></tr></thead><tbody>'
                '<tr><td><span>1</span></td><td><span>공유자</span></td><td><span>김**</span></td><td><span>2010-01-01</span></td></tr>'
                '<tr><td>2</td><td>압류</td><td>국</td><td>2020-01-01</td></tr></tbody></table><script>x=총 9</script>')
        cnt, rows = parse.frag_rows(html)
        self.assertEqual(cnt, 2)
        self.assertEqual(rows[0], ["1", "공유자", "김**", "2010-01-01"])
        self.assertEqual(parse.frag_rows("ERR timeout"), (None, []))
        self.assertEqual(parse.frag_rows(None), (None, []))
        empty = '<span>총 <b>0</b>건</span><table><tbody><tr><td>조회된 결과가 없습니다.</td></tr></tbody></table>'
        self.assertEqual(parse.frag_rows(empty), (0, []))

    def test_schedule_and_price_from_html(self):
        rows = ["입찰일정 및 장소 정보 테이블", "입찰관리번호", "회차", "입찰구분", "입찰기간", "공매예정가격(원)", "개찰일시", "매각결정일시",
                "0081", "030", "전자입찰", "2026-08-18 14:00", "~", "2026-08-19 17:00", "29,820,000", "2026-08-20 11:00", "2026-08-31 14:00",
                "전자자산처분시스템", "-",
                "0081", "028/001", "현장입찰", "2026-08-25 14:00", "~", "2026-08-26 17:00", "26,838,000", "2026-08-27 11:00", "2026-09-07 14:00",
                "납부기한 안내"]
        html = "".join(f"<div>{r}</div>" for r in
                       ["공고보기", "경기도 안산시 X", "감정평가금액(원)", "29,820,000", "회차", "030", "유찰횟수", "2회", "공매예정가격(원)", "29,820,000"] + rows)
        r = parse.parse_item("M", mk_item_dir(html))
        self.assertEqual(r["name"], "경기도 안산시 X")
        self.assertEqual((r["appraisal"], r["price"], r["round"], r["fails"]), (29_820_000, 29_820_000, "030", "2회"))
        self.assertEqual([(s["no"], s["price"]) for s in r["schedule"]], [("030", 29_820_000), ("028/001", 26_838_000)])

    def test_statement_sections(self):
        lines = ["압류재산 공매재산 명세서", "▣ 공매재산 이용 및 점유현황", "공매재산의 현황", "점유", "관계", "성명", "비고", "임차인", "홍**", "미상", "350,000,000",
                 "▣ 임차인 배분 요구 및 채권신고 현황", "임대차", "구분", "비고",
                 "▣ 배분요구 및 채권신고 현황", "번호",
                 "▣ 공매재산에 대하여 등기된 권리 또는 가처분으로서 매각으로 그 효력을 잃지 아니하는 것", "전세권",
                 "▣ 매각에 따라 설정된 것으로 보게 되는 지상권의 개요",
                 "▣ 기타 유의 사항", "- 가등기 있음", "2026.10.15", "한국자산관리공사 경기지역본부"]
        st = parse.statement(clip_raw(lines, pages=2))
        self.assertTrue(st["available"])
        self.assertEqual(st["keep"], ["전세권"])
        self.assertEqual(st["surface"], [])
        self.assertEqual(st["occupancy_rows"][:2], ["임차인", "홍**"])
        self.assertEqual(st["lease_rows"], [])
        self.assertEqual(st["note"], ["- 가등기 있음"])
        self.assertEqual(st["base_date"], "2026.10.15")

    def test_statement_no_button(self):
        self.assertEqual(parse.statement("NO_BUTTON"), {"available": False})
        self.assertEqual(parse.statement(None), {"available": False})

    def test_photos_unique_and_sorted(self):
        raw = ("dnldImgFile.do?atchFileLstNo=1&atchSn=3&thnImgDownloadFlag=false&downloadImageKind=ELGM_FILE_NM "
               "dnldImgFile.do?atchFileLstNo=1&amp;atchSn=2&amp;thnImgDownloadFlag=false&amp;downloadImageKind=ELGM_FILE_NM "
               "dnldImgFile.do?atchFileLstNo=1&atchSn=3&thnImgDownloadFlag=false&downloadImageKind=ELGM_FILE_NM")
        self.assertEqual([p["atchSn"] for p in parse._photos(raw)], ["2", "3"])
        self.assertEqual(parse._photos(None), [])

    def test_pdf_ref(self):
        raw = "<a onclick=\"fn_chkPdfRead('17034230','1','','p22026.pdf','HASH')\">"
        self.assertEqual(parse._pdf(raw), {"atchFileLstNo": "17034230", "atchSn": "1", "name": "p22026.pdf", "hash": "HASH"})
        self.assertIsNone(parse._pdf("없음"))


@unittest.skipUnless(os.path.isdir(T5 + "/items"), "scratch 시험 재료 없음")
class TestCurrentRealData(unittest.TestCase):
    """이전 전체 실행 결과(test5)에 돌려 보는 시험."""

    @classmethod
    def setUpClass(cls):
        cls.c = json.load(open(T5 + "/candidates.json"))

    def test_all_177_items_parse_without_exception(self):
        d = T5 + "/items"
        mngs = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".html"))
        self.assertGreater(len(mngs), 100)
        for m in mngs:
            parse.parse_item(m, d)

    def test_price_and_appraisal_match_search_rows(self):
        d = T5 + "/items"
        for t in "ADBC":
            for it in self.c[t]:
                r = parse.parse_item(it["mng"], d)
                self.assertEqual(r["price"], it["row"]["lowstBidPrc"], it["mng"])
                if r["appraisal"] is not None:                 # 일괄 입찰물건은 '하단참조'라 None(run.py가 목록 값으로 채운다)
                    self.assertEqual(r["appraisal"], it["row"]["cltrApslEvlAvgAmt"], it["mng"])

    def test_schedule_complete_for_seized_realestate(self):
        d = T5 + "/items"
        for t in "AD":
            for it in self.c[t]:
                r = parse.parse_item(it["mng"], d)
                cur = r["round"].split("/")[0]
                self.assertTrue(any(s["no"].split("/")[0] == cur for s in r["schedule"]), it["mng"])

    def test_exit_numbers_real_items_against_exact(self):
        for it in self.c["A"]:
            e = analyze.exit_numbers(it)
            exact = (F(it["appraisal"]) * F(7, 10) - 380_000) / F("1.046")
            self.assertLessEqual(abs(e["exit_cap"] - int(exact)), 1, it["mng"])
            cur = it["round"].split("/")[0]
            idx = [i for i, s in enumerate(it["schedule"]) if s["no"].split("/")[0] == cur][0]
            want = next((s for s in it["schedule"][idx:] if s["price"] <= exact), None)
            self.assertEqual(e.get("first_under"), want, it["mng"])

    def test_signal_true_positives_on_real_texts(self):
        def flags(m):
            return msgs(analyze.appraisal_signals(f"{T5}/media/{m}/appraisal.txt")[0])
        self.assertIn("맹지", flags("2025-14353-001"))          # '기호1,2 공히 맹지임.'
        self.assertIn("맹지", flags("2025-17973-001"))          # '지적도상 맹지임.'
        self.assertIn("차량 접근 불가", flags("2025-17973-001"))
        self.assertIn("분묘 소재 가능성(유의 문구)", flags("2025-17973-001"))
        self.assertIn("분묘", flags("2026-00505-001"))          # '분묘 약 10여기가 소재'
        self.assertIn("제시외 건물·수목", flags("2026-12232-001"))
        self.assertEqual(flags("2026-05933-001"), set())

    def test_media_appraisal_on_real_pdfs_without_network(self):
        called = []
        orig = media._get
        media._get = lambda url, path, tries=4: called.append(url) or False
        try:
            for m, scanned in (("2026-16401-001", True), ("2026-00505-001", False)):
                d = f"{WORK}/real_{m}"
                shutil.rmtree(d, ignore_errors=True)
                os.makedirs(d)
                shutil.copy(f"{T5}/media/{m}/appraisal.pdf", d + "/appraisal.pdf")
                r = media.appraisal({"pdf": {"atchFileLstNo": "1", "atchSn": "1", "name": "a.pdf", "hash": "h"}}, d)
                self.assertEqual(r["status"], "ok")
                self.assertEqual(r["scanned"], scanned)
                self.assertTrue(r["sheets"])
            self.assertEqual(called, [])
        finally:
            media._get = orig


class TestCurrentMedia(unittest.TestCase):
    def setUp(self):
        self.orig_get = media._get
        media._get = lambda url, path, tries=4, **kw: False

    def tearDown(self):
        media._get = self.orig_get

    def test_non_pdf_and_missing(self):
        self.assertEqual(media.appraisal({}, WORK)["status"], "없음")
        self.assertEqual(media.appraisal({"pdf": {"name": "a.hwpx"}}, WORK)["status"], "PDF 아님(hwpx)")

    def test_html_error_page_detected(self):
        d = tempfile.mkdtemp(dir=WORK)
        open(d + "/appraisal.pdf", "wb").write(b"<html>" + b"x" * 3000)
        r = media.appraisal({"pdf": {"atchFileLstNo": "1", "atchSn": "1", "name": "a.pdf", "hash": "h"}}, d)
        # 받은 파일이 PDF가 아니면 지우고 다시 받는다(다시 받기 실패를 모의했으니 '다운로드 실패'이고 오류 페이지는 남지 않는다)
        self.assertEqual(r["status"], "다운로드 실패")
        self.assertFalse(os.path.exists(d + "/appraisal.pdf"))

    def test_image_only_pdf_is_scanned(self):
        d = tempfile.mkdtemp(dir=WORK)
        image_pdf(d + "/appraisal.pdf", 3)
        r = media.appraisal({"pdf": {"atchFileLstNo": "1", "atchSn": "1", "name": "a.pdf", "hash": "h"}}, d)
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["scanned"])
        self.assertIsNone(r["text"])
        self.assertEqual(r["pages"], [1, 2, 3])
        self.assertEqual(len(r["page_images"]), 3)

    def test_text_pdf_has_text(self):
        d = tempfile.mkdtemp(dir=WORK)
        text_pdf(d + "/appraisal.pdf", "Land appraisal report " * 20)
        r = media.appraisal({"pdf": {"atchFileLstNo": "1", "atchSn": "1", "name": "a.pdf", "hash": "h"}}, d)
        self.assertFalse(r["scanned"])
        self.assertTrue(r["text"])

    def test_contact_sheet_grid_and_skip_unreadable(self):
        from PIL import Image
        d = tempfile.mkdtemp(dir=WORK)
        ps = []
        for i, col in enumerate(("red", "green", "blue", "yellow", "gray")):
            p = f"{d}/{i}.png"
            Image.new("RGB", (400, 300), col).save(p)
            ps.append(p)
        out = media.contact_sheet(ps, d + "/s.jpg", cols=4, width=100)
        im = Image.open(out)
        self.assertEqual(im.width, 400)
        self.assertEqual(im.height, 2 * (75 + 22))
        self.assertIsNone(media.contact_sheet([d + "/nope.png"], d + "/n.jpg"))

    def test_photos_download_skipped_when_file_exists(self):
        from PIL import Image
        d = tempfile.mkdtemp(dir=WORK)
        Image.new("RGB", (640, 480), "red").save(d + "/photo01.jpg")
        r = media.photos({"photos": [{"atchFileLstNo": "1", "atchSn": "1"}]}, d)
        self.assertEqual((r["count"], r["downloaded"]), (1, 1))
        self.assertTrue(r["sheet"])

    def test_max_photos_cap(self):
        from PIL import Image
        d = tempfile.mkdtemp(dir=WORK)
        for i in range(1, 21):
            Image.new("RGB", (64, 48), "red").save(f"{d}/photo{i:02d}.jpg")
        r = media.photos({"photos": [{"atchFileLstNo": "1", "atchSn": str(i)} for i in range(1, 21)]}, d)
        self.assertEqual((r["count"], r["downloaded"]), (20, media.MAX_PHOTOS))


# ───────────────────────── 버그를 드러내는 시험(현재 코드에서 실패) ─────────────────────────

class TestBugSignalFalseNegatives(unittest.TestCase):
    """appr-2(진입 불가 표현 누락), appr-15(묘지·봉분). 실제 2026-05268-001 감정평가서에 '도로휀스 및 고저 차이로 출입이 불가한 상태임.'"""

    def test_access_impossible_without_word_vehicle(self):
        self.assertTrue(sig("본건 북서측으로 소로에 접하나 현황 저지상태이고, 도로휀스 및 고저 차이로 출입이 불가한 상태임."),
                        "출입 불가가 신호로 안 잡힘")

    def test_access_variants(self):
        for t in ("본건까지 차량의 접근이 불가능함.", "본건까지 차량이 접근하기 어려움.", "차량 진출입이 곤란함",
                  "본건은 도로에 접하지 않은 토지임.", "접근도로가 없어 진입이 불가능함"):
            self.assertTrue(sig(t), t)

    @unittest.skipUnless(os.path.exists(T5 + "/media/2026-05268-001/appraisal.txt"), "실자료 없음")
    def test_real_2026_05268_001_access_impossible(self):
        flags, _ = analyze.appraisal_signals(T5 + "/media/2026-05268-001/appraisal.txt")
        self.assertTrue(flags, "실제 '출입이 불가한 상태' 물건이 신호 없음(report_draft에 '문구 없음'으로 출력됨)")

    def test_grave_synonyms(self):
        for t in ("지상에 묘지 3기가 소재함", "현황 묘지 및 자연림"):
            self.assertTrue(sig(t), t)


class TestBugSignalFalsePositives(unittest.TestCase):
    """appr-3, 5, 6, 7: 비교 사례표·범례·부정문을 이 물건의 상태로 읽음."""

    def test_comparable_table_multiline_cell_landlocked(self):
        # 실제 2026-01223-001: pdftotext -layout이 비교표준지 한 칸을 여러 줄로 쪼개 숫자로 끝나지 않는 줄이 남음
        text = ("                        면적       이용       용도      도로교통        형상       공시지가\n"
                "       양주시\n"
                "       광적면                                보전        맹지        부정형\n"
                " 가                임야   1,785.0   자연림                                     21,600        -\n"
                "       우고리                                관리       남동향        완경사\n"
                "5. 접면도로상황\n      북측으로 노폭 3~4미터의 포장도로와 접하고 있습니다.\n")
        self.assertNotIn("맹지", msgs(sig(text)))

    def test_trade_case_row_ending_with_text(self):
        # 실제 2026-11939-001 거래사례표 줄 '1 임 맹지 부정형 완경사 2025-07-10 91,000 법원경매'
        text = "   1                      임    맹지   부정형   완경사   2025-07-10   91,000   법원경매\n"
        self.assertNotIn("맹지", msgs(sig(text)))

    def test_nearby_price_level_table(self):
        # 실제 2026-00505-001 '(나) 인근 토지의 가격수준' 표
        text = "        -        순수 산림지대          맹지            10,000-20,000     개발제한\n"
        self.assertNotIn("맹지", msgs(sig(text)))

    def test_slope_in_comparable_cell(self):
        # 실제 2025-14353-001 비교표준지 '가'의 지세 칸
        text = ("                                                  교통       지세 (원/㎡)\n"
                "    삼봉리 임야 12,893 자연림 농림지역\n"
                "  가 산9-23                                         맹지       부정형 2,310\n"
                "                                                           급경사\n")
        self.assertNotIn("급경사", msgs(sig(text)))

    def test_map_legend_is_not_unlisted_building(self):
        # 실제 2026-14446-003 지적도 범례
        text = "범 례            도로                   평가건물1층                  제시외건물\n"
        self.assertNotIn("제시외 건물·수목", msgs(sig(text)))

    def test_no_unlisted_building_statement(self):
        for t in ("제시외 건물은 없음", "제시외건물 없음", "제시외 건물이 소재하지 않음"):
            self.assertEqual(sig(t), [], t)

    def test_grave_not_found_is_not_grave(self):
        # 실제 2026-00185-001 문장
        t = ("- 본건 토지는 현장조사 및 위성사진 등을 검토할 때 분묘가 발견되지 않았으나, 현황 우거진 입목 등으\n"
             "로 인해 분묘 확인이 용이하지 않은바, 입찰시 분묘소재 여부 등에 대하여 재확인하시기 바랍니다.\n")
        self.assertNotIn("분묘", msgs(sig(t)))

    def test_grave_negation_variants(self):
        for t in ("분묘는 확인되지 않음", "분묘가 소재하지 않음", "분묘 등 제한사항은 없음", "분묘로 보이는 시설은 없음"):
            self.assertNotIn("분묘", msgs(sig(t)), t)

    def test_A_not_found_grave_must_not_be_bad_exit(self):
        it = {"grade": "낮음", "notes": [], "media": {"appraisal": {"text": tmp_text("현장조사 결과 분묘가 발견되지 않았음.")}}}
        analyze.apply_appraisal(it, "A")
        self.assertFalse(it["bad_exit"])
        self.assertEqual(it["grade"], "낮음")

    def test_landlocked_negation_variants(self):
        for t in ("본건은 맹지는 아니며 도로에 접함.", "본건은 맹지가 아닌 토지임.", "본건은 맹지로 보기 어려움.",
                  "본건은 맹지에 해당하지 않음.", "비맹지 토지임"):
            self.assertNotIn("맹지", msgs(sig(t)), t)

    def test_landlocked_negation_across_line_break(self):
        self.assertNotIn("맹지", msgs(sig("도로에 접하고 있어 맹지가\n아님")))

    def test_slope_negation(self):
        for t in ("급경사가 아님", "완경사지로서 급경사는 아님"):
            self.assertNotIn("급경사", msgs(sig(t)), t)

    @unittest.skipUnless(os.path.isdir(T5 + "/media"), "실자료 없음")
    def test_real_texts_have_no_false_landlocked(self):
        # 위 세 문서의 이 물건(대상)은 도로에 접한다: 01223 '노폭 3~4미터의 포장도로', 11939 '노폭 약 2미터 비포장', 00505 '소로한면'
        for m in ("2026-01223-001", "2026-11939-001", "2026-00505-001"):
            flags, _ = analyze.appraisal_signals(f"{T5}/media/{m}/appraisal.txt")
            self.assertNotIn("맹지", msgs(flags), m)


class TestBugFieldPattern(unittest.TestCase):
    """appr-8: 지목/현황 전·답 정규식 경계."""

    def test_field_prefix_words_are_not_farmland(self):
        for t in ("공부상 지목은 대이나 현황은 전원주택 부지임.", "공부상 지목은 대이나 현황은 전혀 이용하지 않는 나지임.",
                  "공부상 지목은 대이나 현황은 전체가 포장된 주차장임.", "공부상 지목은 임야이나 현황은 답사 당시 자연림 상태임."):
            self.assertEqual(sig(t), [], t)

    def test_field_with_curly_quotes(self):
        self.assertEqual([s for s, _ in sig("공부상 지목은 ‘대’이나 현황은 ‘전’으로 이용 중임.")], ["F"])

    def test_field_wrapped_line(self):
        self.assertEqual([s for s, _ in sig("지목은 임야이나\n현황은 전으로 이용 중임.")], ["F"])

    def test_field_paddy_and_garden(self):
        for t in ("공부상 지목은 임야이나 현황은 논으로 이용 중임.", "공부상 지목은 대이나 현황은 경작지로 이용 중임."):
            self.assertEqual([s for s, _ in sig(t)], ["F"], t)


class TestBugSkipPattern(unittest.TestCase):
    """appr-4: APPR_SKIP이 이 물건을 설명하는 실제 문장·표 줄도 버린다."""

    def test_subject_table_row_ending_with_share_fraction(self):
        # 실제 2025-14430-031: '대상 토지 현황' 표의 기호4(=이 물건, 지분 1488분의36) 줄. 도로교통 칸이 맹지인데 줄이 '…분의36'으로 끝나 숫자 줄로 버려진다.
        self.assertIn("맹지", msgs(sig("  4   감북동      임야   1,488               일부     맹지            1488분의36")))

    @unittest.skipUnless(os.path.exists(T5 + "/media/2025-14430-031/appraisal.txt"), "실자료 없음")
    def test_real_2025_14430_031_subject_is_landlocked(self):
        flags, _ = analyze.appraisal_signals(T5 + "/media/2025-14430-031/appraisal.txt")
        self.assertIn("맹지", msgs(flags), "대상 토지 표 기호4 도로교통=맹지인데 신호에 없다(등급 중간으로 남음)")

    def test_subject_statement_with_skip_words(self):
        for t in ("본건은 맹지로서 접근조건이 불량함", "접근조건이 불량한 맹지임", "접근성 및 이용편의 측면에서 맹지임", "본건은 맹지로서 산 74"):
            self.assertIn("맹지", msgs(sig(t)), t)


class TestBugScannedPartialText(unittest.TestCase):
    """appr-1: 전자서명 증명서 1쪽만 글자 층이 있고 본문은 스캔 — has_text가 True가 돼 '신호 없음'으로 보고된다."""

    def make_partial(self):
        d = tempfile.mkdtemp(dir=WORK)
        text_pdf(d + "/t.pdf", "Electronic signature certificate of appraisal report " * 6)      # >200자
        image_pdf(d + "/i.pdf", 6)
        subprocess.run(["pdfunite", d + "/t.pdf", d + "/i.pdf", d + "/appraisal.pdf"], check=True)
        return d

    def test_synthetic_partial_text_is_scanned(self):
        orig = media._get
        media._get = lambda *a, **k: False
        try:
            d = self.make_partial()
            r = media.appraisal({"pdf": {"atchFileLstNo": "1", "atchSn": "1", "name": "a.pdf", "hash": "h"}}, d)
        finally:
            media._get = orig
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["scanned"], "7쪽 중 1쪽만 글자인데 scanned=False")

    @unittest.skipUnless(os.path.exists(T5 + "/media/2026-15825-002/appraisal.pdf"), "실자료 없음")
    def test_real_2026_15825_002(self):
        d = f"{WORK}/real_15825"
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        shutil.copy(T5 + "/media/2026-15825-002/appraisal.pdf", d + "/appraisal.pdf")
        orig = media._get
        media._get = lambda *a, **k: False
        try:
            r = media.appraisal({"pdf": {"atchFileLstNo": "1", "atchSn": "1", "name": "a.pdf", "hash": "h"}}, d)
        finally:
            media._get = orig
        self.assertTrue(r["scanned"], "28쪽 중 1쪽(전자서명 증명서)만 글자 — 본문은 스캔")


class TestBugStatementUnfetched(unittest.TestCase):
    """appr-9: 명세서 뷰어가 viewData를 못 받은 경우(실제 2025-14353-001)에도 available=True."""

    RAW = ("fn_pbctPrptDstmtReport('2026', '037');|fn_pbctPrptDstmtReport('2026', '037');\n=========\n"
           "ClipType=pageCheck&ClipData=%7B%22cnt%22%3A1%7D\n----\n"
           '{"id":2,"resValue":{"is_s":false,"status":true,"event":200,"count":2,"endReport":true}}')

    def test_unfetched_statement_is_not_available(self):
        st = parse.statement(self.RAW)
        self.assertFalse(st["available"], "본문을 못 받았는데 available=True")

    def test_flags_D_warns_unfetched_statement(self):
        it = {"statement": parse.statement(self.RAW), "kv": {}, "notes": []}
        self.assertIn("공매재산명세서 미공개(입찰 임박 시 재확인)", msgs(analyze.flags_D(it)))


class TestBugParseRobustness(unittest.TestCase):
    """appr-13(예외가 run.py의 load()를 통과해 전체 실행을 멈춘다), appr-14(유의사항 잘림·구역 폴백)."""

    def test_duplicated_gonggobogi_at_tail(self):
        parse.parse_item("M", mk_item_dir("<div>공고보기</div><div>공고보기</div>"))

    def test_truncated_xhr_json(self):
        parse.parse_item("M", mk_item_dir("<div>x</div>", xhr='{"inqRgstMtrsCrtiClg": "abc'))

    def test_xhr_non_dict_or_non_string(self):
        parse.parse_item("M", mk_item_dir("<div>x</div>", xhr="[]"))
        parse.parse_item("M", mk_item_dir("<div>x</div>", xhr='{"inqRgstMtrsCrtiClg": 5}'))

    def test_statement_resvalue_null(self):
        parse.statement('btn\n=========\nhdr\n----\n{"resValue":null}')

    def test_note_not_cut_by_org_name_inside_note(self):
        lines = ["▣ 기타 유의 사항", "- 자세한 사항은 한국자산관리공사에 문의 바람", "- 가등기 있음", "2026.10.15", "한국자산관리공사 서울"]
        st = parse.statement(clip_raw(lines))
        self.assertEqual(st["note"], ["- 자세한 사항은 한국자산관리공사에 문의 바람", "- 가등기 있음"])

    def test_occupancy_section_without_lease_header(self):
        lines = ["▣ 공매재산 이용 및 점유현황", "점유", "관계", "비고", "▣ 배분요구 및 채권신고 현황", "번호", "권리관계", "압류", "국"]
        st = parse.statement(clip_raw(lines))
        self.assertEqual(st["occupancy_rows"], [], "점유 표가 비었는데 뒤의 배분요구 표가 점유 행으로 읽힘")


class TestBugExitNumbers(unittest.TestCase):
    """appr-10, appr-11."""

    def test_first_under_respects_budget_cap(self):
        # 현재가 980만 > 예산 상한 9,512,428. 출구 상한만 보면 이번 회차가 '첫 회차'가 되지만 980만×1.046+5만 > 1,000만.
        sched = [{"no": "037", "price": 9_800_000}, {"no": "038", "price": 8_820_000}]
        e = analyze.exit_numbers({"appraisal": 30_000_000, "price": 9_800_000, "round": "037", "schedule": sched})
        self.assertGreater(e["exit_cap"], 9_800_000)
        self.assertLessEqual(e["first_under"]["price"], e["budget_cap"])

    def test_report_text_matches_constants(self):
        it = {"exit": {"budget_cap": 9_512_428, "exit_cap": -1}, "round": "1"}
        text = "\n".join(report.exit_lines(it))
        # 코드는 5만+3만+30만 = 38만원을 뺀다
        self.assertIn("38만원", text)
        self.assertNotIn("35만원", text)

    def test_unknown_current_round_is_not_reported_as_no_round(self):
        # 현재 회차가 회차표에 없으면 first_under=None → 리포트가 '출구 상한 이하 회차가 없다'고 단정한다
        e = analyze.exit_numbers({"appraisal": 10_000_000, "price": 1_000_000, "round": None,
                                  "schedule": [{"no": "1", "price": 1_000_000}]})
        self.assertIsNotNone(e.get("first_under"), "현재 회차를 못 찾았으면 None 대신 처음 상한 이하 회차를 보여 줘야 한다")


class TestBugMediaRobustness(unittest.TestCase):
    """appr-12."""

    def setUp(self):
        self.orig_get = media._get
        media._get = lambda url, path, tries=4, **kw: False

    def tearDown(self):
        media._get = self.orig_get

    def test_subprocess_timeout_is_contained(self):
        d = tempfile.mkdtemp(dir=WORK)
        image_pdf(d + "/appraisal.pdf", 2)
        real = subprocess.run

        def fake(cmd, *a, **k):
            if cmd[0] == "pdftotext":
                raise subprocess.TimeoutExpired(cmd, 180)
            return real(cmd, *a, **k)
        media.subprocess.run = fake
        try:
            r = media.appraisal({"pdf": {"atchFileLstNo": "1", "atchSn": "1", "name": "a.pdf", "hash": "h"}}, d)
        finally:
            media.subprocess.run = real
        self.assertIn("status", r)

    def test_contact_sheet_labels_follow_images(self):
        from PIL import Image, ImageDraw
        d = tempfile.mkdtemp(dir=WORK)
        ps = []
        for i in (1, 2, 3, 4):
            p = f"{d}/apsl-p{i:02d}.png"
            if i == 2:
                open(p, "wb").write(b"broken")
            else:
                Image.new("RGB", (400, 300), "white").save(p)
            ps.append(p)
        drawn = []
        orig = ImageDraw.ImageDraw.text
        ImageDraw.ImageDraw.text = lambda self, xy, text, *a, **k: drawn.append(text)
        try:
            media.contact_sheet(ps, d + "/s.jpg", cols=4, width=100, labels=["p1", "p2", "p3", "p4"])
        finally:
            ImageDraw.ImageDraw.text = orig
        self.assertEqual(drawn, ["p1", "p3", "p4"], "깨진 p2를 건너뛰면 라벨이 한 칸씩 밀린다")

    def test_contact_sheet_very_tall_image(self):
        from PIL import Image
        d = tempfile.mkdtemp(dir=WORK)
        Image.new("RGB", (100, 20000), "gray").save(d + "/t.jpg")
        Image.new("RGB", (800, 600), "red").save(d + "/n.jpg")
        media.contact_sheet([d + "/n.jpg", d + "/t.jpg"], d + "/s.jpg")

    def test_corrupt_pdf_not_reported_ok(self):
        d = tempfile.mkdtemp(dir=WORK)
        open(d + "/appraisal.pdf", "wb").write(b"%PDF-1.4\n" + b"garbage" * 500)
        r = media.appraisal({"pdf": {"atchFileLstNo": "1", "atchSn": "1", "name": "a.pdf", "hash": "h"}}, d)
        self.assertNotEqual(r["status"], "ok")

    def test_photos_count_only_images(self):
        from PIL import Image
        d = tempfile.mkdtemp(dir=WORK)
        Image.new("RGB", (400, 300), "red").save(d + "/photo01.jpg")
        open(d + "/photo02.jpg", "wb").write(b"<html>error page</html>")
        r = media.photos({"photos": [{"atchFileLstNo": "1", "atchSn": "1"}, {"atchFileLstNo": "1", "atchSn": "2"}]}, d)
        self.assertEqual(r["downloaded"], 1, "HTML 오류 페이지가 사진 1장으로 집계됨")


if __name__ == "__main__":
    unittest.main(verbosity=2)
