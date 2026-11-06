"""영역 appr 검증 시험(재현 검증자 작성). 검토자의 test_appr.py와 별개로, 합성 입력을 인라인으로 두고 직접 만든 시험이다.

실행(저장소 현재 코드):  cd <이 디렉터리> && NODE_PATH=/opt/node22/lib/node_modules python3 -m unittest test_appr_verify -v
실행(수정안을 적용한 scratch 복사본):  ONBID_ROOT=<scratch>/codereview/appr/verify/patched python3 -m unittest test_appr_verify

구성
  TestPassNow_*  현재 코드에서 통과 — 의도된 동작(고정)과 수정안이 깨면 안 되는 동작
  TestBug_*      확인된 결함을 드러내는 시험 — 기대 동작을 단언하므로 현재 코드에서는 실패, 수정안 적용 후 통과
  TestOpen_*     수정안으로도 닫히지 않는 알려진 한계(실패 유지) — 판단 근거를 남기려는 시험
저장소 파일은 건드리지 않는다. 임시 파일은 scratch 아래에만 만든다.
"""
import os as _os
REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
FIXTURES = _os.environ.get("ONBID_FIXTURES", "/nonexistent-onbid-fixtures")
FIXTURES_PARENT = _os.path.dirname(FIXTURES)
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse

ROOT = os.environ.get("ONBID_ROOT", "/home/user/kamang")
sys.path.insert(0, ROOT)
from onbid import analyze, media, parse, report  # noqa: E402

SCRATCH = FIXTURES
WORK = tempfile.mkdtemp(prefix="onbid_test_")
T5 = FIXTURES
os.makedirs(WORK, exist_ok=True)


def sig(text):
    """본문 text → appraisal_signals의 (flags, lines)"""
    d = tempfile.mkdtemp(dir=WORK)
    p = os.path.join(d, "a.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return analyze.appraisal_signals(p)


def msgs(text):
    return {m for _, m in sig(text)[0]}


def real_signals(mng):
    return analyze.appraisal_signals(f"{T5}/media/{mng}/appraisal.txt")


def have_real(mng):
    return os.path.exists(f"{T5}/media/{mng}/appraisal.txt")


def clip_raw(lines):
    """합성 ClipReport 응답. walk()는 [[글자 문자열들],[숫자들]] 쌍을 한 줄로 읽는다."""
    pg = [[[urllib.parse.quote_plus(l)], [1]] for l in lines]
    vd = base64.b64encode(json.dumps({"pageNumList": [1], "pageList": [pg]}).encode()).decode()
    return "btn\n=========\nClipType=x\n----\n" + json.dumps({"id": 1, "resValue": {"viewData": vd}})


def item_dir(html, **ext):
    d = tempfile.mkdtemp(dir=WORK)
    with open(d + "/X.html", "w", encoding="utf-8") as f:
        f.write(html)
    for e, v in ext.items():
        with open(f"{d}/X.{e}", "w", encoding="utf-8") as f:
            f.write(v)
    return d


# ───────────────────────── 현재 통과 ─────────────────────────

class TestPassNow_Intended(unittest.TestCase):
    def test_landlocked_negation_basic(self):
        for t in ("본건은 맹지가 아님.", "본건은 맹지 아님", "본건은 맹지가 아니며 도로에 접함"):
            self.assertNotIn("맹지", msgs(t), t)

    def test_landlocked_sentence_positive(self):
        self.assertIn("맹지", msgs("도로 상태 맹지임."))
        self.assertIn("맹지", msgs("기호1,2 공히 맹지임."))

    def test_grave_none_and_maybe(self):
        self.assertNotIn("분묘", msgs("분묘가 없음"))
        self.assertEqual(sig("분묘 소재 가능성이 있음")[0], [("I", "분묘 소재 가능성(유의 문구)")])
        self.assertIn("분묘", msgs("본건 지상에 연고자 미상의 분묘 약 10여기가 소재함."))

    def test_number_ending_comparable_line_skipped(self):
        self.assertEqual(sig("임야 1,956.00 자연림 맹지 93,100")[0], [])

    def test_vehicle_access(self):
        self.assertEqual(sig("본건까지 차량 접근이 불가능함.")[0], [("Y", "차량 접근 불가")])

    def test_field_pattern_basic(self):
        self.assertEqual({s for s, _ in sig("공부상 지목은 임야이나 현황은 전으로 이용 중임.")[0]}, {"F"})

    def test_apply_appraisal_grades(self):
        d = tempfile.mkdtemp(dir=WORK)
        p = d + "/a.txt"
        open(p, "w", encoding="utf-8").write("본건은 맹지임.")
        it = analyze.apply_appraisal({"grade": "낮음", "notes": [], "media": {"appraisal": {"text": p}}}, "A")
        self.assertEqual((it["grade"], it["bad_exit"]), ("높음", True))
        it = analyze.apply_appraisal({"grade": "낮음", "notes": [], "media": {"appraisal": {"text": p}}, "risk_flags": []}, "D")
        self.assertEqual(it["grade"], "중간")      # D에서 단독 소유 맹지는 Y

    def test_exit_numbers_formula(self):
        e = analyze.exit_numbers({"appraisal": 30_000_000, "price": 9_800_000, "round": "037",
                                  "schedule": [{"no": "037", "price": 9_800_000}, {"no": "038", "price": 8_820_000}]})
        self.assertEqual(e["budget_cap"], 9_512_428)
        self.assertEqual(e["exit_cap"], int((30_000_000 * 0.7 - 380_000) / 1.046))
        self.assertEqual(e["loss"], int(9_800_000 * 1.046 + 50_000 - 30_000_000 * 0.2))

    def test_statement_no_button(self):
        self.assertEqual(parse.statement("NO_BUTTON"), {"available": False})

    def test_statement_sections_real_shape(self):
        st = parse.statement(clip_raw(["▣ 기타 유의 사항", "- 가등기 있음", "2026.10.15", "한국자산관리공사 서울"]))
        self.assertTrue(st["available"])
        self.assertEqual(st["note"], ["- 가등기 있음"])
        self.assertEqual(st["base_date"], "2026.10.15")

    def test_real_corpus_true_positives(self):
        if not have_real("2025-14353-001"):
            self.skipTest("실자료 없음")
        self.assertIn("맹지", {m for _, m in real_signals("2025-14353-001")[0]})        # '기호1,2 공히 맹지임.'
        self.assertIn("맹지", {m for _, m in real_signals("2026-00185-001")[0]})        # '도로 상태 맹지임.'
        self.assertIn("차량 접근 불가", {m for _, m in real_signals("2025-17973-001")[0]})
        self.assertIn("분묘", {m for _, m in real_signals("2026-00505-001")[0]})


# ───────────────────────── 결함 확인 ─────────────────────────

class FakeRun:
    """media.subprocess.run 대체: pdftotext는 지정 텍스트를 쓰고, pdfimages는 빈 목록, pdftoppm은 작은 PNG를 쓴다."""

    def __init__(self, text, png=True):
        self.text, self.png = text, png

    def __call__(self, cmd, *a, **k):
        from PIL import Image
        if cmd[0] == "pdftotext":
            open(cmd[-1], "w", encoding="utf-8").write(self.text)
        elif cmd[0] == "pdftoppm" and self.png:
            Image.new("RGB", (50, 50), "white").save(cmd[-1] + ".png")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def appraisal_with(text, png=True):
    d = tempfile.mkdtemp(dir=WORK)
    with open(d + "/appraisal.pdf", "wb") as f:
        f.write(b"%PDF-1.4\n" + b"x" * 2000)
    orig_run, orig_get = media.subprocess.run, media._get
    media.subprocess.run, media._get = FakeRun(text, png), lambda *a, **k: False
    try:
        return media.appraisal({"pdf": {"atchFileLstNo": "1", "atchSn": "1", "name": "a.pdf", "hash": "h"}}, d)
    finally:
        media.subprocess.run, media._get = orig_run, orig_get


CERT = "감정평가서 전자서명(원본) 증명서\n" + "서명자 정보 평가금액 43,560,000 원 " * 20


class TestBug_Media(unittest.TestCase):
    def test_appr_1_cert_page_only_text_is_scanned(self):
        # 28쪽 중 1쪽(전자서명 증명서)만 글자: pdftotext 출력은 쪽마다 form feed
        text = CERT + "\f" + "\f" * 27
        r = appraisal_with(text)
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["scanned"], "증명서 1쪽만 글자인데 scanned=False")
        self.assertIsNone(r["text"])

    def test_appr_1_real_pdf(self):
        pdf = T5 + "/media/2026-15825-002/appraisal.pdf"
        if not os.path.exists(pdf):
            self.skipTest("실자료 없음")
        d = tempfile.mkdtemp(dir=WORK)
        shutil.copy(pdf, d + "/appraisal.pdf")
        orig = media._get
        media._get = lambda *a, **k: False
        try:
            r = media.appraisal({"pdf": {"atchFileLstNo": "1", "atchSn": "1", "name": "a.pdf", "hash": "h"}}, d)
        finally:
            media._get = orig
        self.assertTrue(r["scanned"])

    def test_appr_1_normal_text_pdf_not_scanned(self):
        # 수정안이 정상 글자 PDF를 스캔으로 오판하면 안 된다(실데이터 45개 중 최소 글자 쪽 비율 54%)
        body = "본건은 임야로서 …" * 30
        text = CERT + "\f" + "\f".join([body] * 10 + [""] * 8)       # 19쪽 중 11쪽 글자
        r = appraisal_with(text)
        self.assertFalse(r["scanned"])
        self.assertTrue(r["text"])

    def test_appr_16_cert_page_still_first(self):
        # 전자서명 증명서(1쪽) 대신 감정평가표가 있는 쪽을 먼저 본다
        r = appraisal_with(CERT + "\f" + "감정평가표 …" * 30)
        self.assertEqual(r["pages"][0], 2)

    def test_appr_12_timeout_contained(self):
        d = tempfile.mkdtemp(dir=WORK)
        with open(d + "/appraisal.pdf", "wb") as f:
            f.write(b"%PDF-1.4\n" + b"x" * 2000)
        orig_run, orig_get = media.subprocess.run, media._get

        def boom(cmd, *a, **k):
            if cmd[0] == "pdftotext":
                raise subprocess.TimeoutExpired(cmd, 180)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        media.subprocess.run, media._get = boom, lambda *a, **k: False
        try:
            r = media.appraisal({"pdf": {"atchFileLstNo": "1", "atchSn": "1", "name": "a.pdf", "hash": "h"}}, d)
        finally:
            media.subprocess.run, media._get = orig_run, orig_get
        self.assertNotEqual(r.get("status"), "ok")

    def test_appr_12_tall_image(self):
        from PIL import Image
        d = tempfile.mkdtemp(dir=WORK)
        Image.new("RGB", (100, 20000), "red").save(d + "/tall.png")
        Image.new("RGB", (800, 600), "blue").save(d + "/w.png")
        out = media.contact_sheet([d + "/tall.png", d + "/w.png"], d + "/o.jpg")
        self.assertEqual(out, d + "/o.jpg")

    def test_appr_12_labels_follow_images(self):
        from PIL import Image, ImageDraw
        d = tempfile.mkdtemp(dir=WORK)
        for i in (1, 3, 4):
            Image.new("RGB", (200, 100), (i * 50, 0, 0)).save(f"{d}/p{i}.png")
        open(d + "/p2.png", "wb").write(b"garbage")
        drawn, orig = [], ImageDraw.ImageDraw.text

        def spy(self, xy, text, *a, **k):
            drawn.append(text)
            return orig(self, xy, text, *a, **k)
        ImageDraw.ImageDraw.text = spy
        try:
            media.contact_sheet([f"{d}/p{i}.png" for i in (1, 2, 3, 4)], d + "/o.jpg", labels=["p1", "p2", "p3", "p4"])
        finally:
            ImageDraw.ImageDraw.text = orig
        self.assertEqual(drawn, ["p1", "p3", "p4"])

    def test_appr_12_corrupt_pdf_not_ok(self):
        r = appraisal_with("", png=False)       # 글자도 쪽 이미지도 못 얻은 PDF
        self.assertNotEqual(r.get("status"), "ok")

    def test_appr_12_error_html_photo_not_counted(self):
        from PIL import Image
        d = tempfile.mkdtemp(dir=WORK)
        open(d + "/photo01.jpg", "w").write("<html>error</html>")
        Image.new("RGB", (100, 100), "blue").save(d + "/photo02.jpg")
        r = media.photos({"photos": [{"atchFileLstNo": "1", "atchSn": "1"}, {"atchFileLstNo": "1", "atchSn": "2"}]}, d)
        self.assertEqual(r["downloaded"], 1)


class TestBug_Signals(unittest.TestCase):
    def test_appr_2_access_impossible_real_sentence(self):
        t = "본건 북서측으로 소로에 접하나 현황 저지상태이고, 도로휀스 및 고저 차이로 출입이 불가한 상태임."
        self.assertTrue(sig(t)[0], "출입 불가 문장이 신호 0건")

    def test_appr_2_access_variants(self):
        for t in ("차량의 접근이 불가능", "차량이 접근하기 어려움", "차량 진출입이 곤란", "도로에 접하지 않은 토지", "접근도로가 없어 진입이 불가능"):
            self.assertTrue(sig(t)[0], t)

    def test_appr_2_no_duplicate_with_vehicle_pattern(self):
        flags = sig("본건까지 차량 출입이 불가하며")[0]
        self.assertEqual(len(flags), 1, flags)

    def test_appr_2_real_05268(self):
        if not have_real("2026-05268-001"):
            self.skipTest("실자료 없음")
        self.assertTrue(real_signals("2026-05268-001")[0])

    def test_appr_3_comparable_cells(self):
        rows = [
            "       광적면                                보전        맹지        부정형",
            "  1                      임    맹지   부정형   완경사   2025-07-10   91,000   법원경매",
            "        -        순수 산림지대          맹지            10,000-20,000     개발제한",
        ]
        for r in rows:
            self.assertNotIn("맹지", msgs(r), r)

    def test_appr_3_prose_with_single_gap_still_flagged(self):
        self.assertIn("맹지", msgs("  도로 상태       맹지임."))

    def test_appr_3_real_docs(self):
        for m in ("2026-01223-001", "2026-11939-001", "2026-00505-001"):
            if not have_real(m):
                self.skipTest("실자료 없음")
            self.assertNotIn("맹지", {x for _, x in real_signals(m)[0]}, m)

    def test_appr_4_subject_row_ends_with_share_fraction(self):
        self.assertIn("맹지", msgs("  4   감북동      임야   1,488               일부     맹지            1488분의36"))

    def test_appr_4_real_14430_031(self):
        if not have_real("2025-14430-031"):
            self.skipTest("실자료 없음")
        self.assertIn("맹지", {x for _, x in real_signals("2025-14430-031")[0]})

    def test_appr_5_grave_not_found(self):
        t = ("현장조사 및 위성사진 등을 검토할 때 분묘가 발견되지 않았으나, 현황 우거진 입목 등으로 인해 분묘 확인이 용이하지 않은바, "
             "입찰시 분묘소재 여부 등에 대하여 재확인하시기 바랍니다.")
        self.assertNotIn("분묘", msgs(t))
        for v in ("분묘는 확인되지 않음", "분묘가 소재하지 않음", "분묘 등 제한사항은 없음", "분묘로 보이는 시설은 없음"):
            self.assertNotIn("분묘", msgs(v), v)

    def test_appr_5_A_not_found_is_not_bad_exit(self):
        d = tempfile.mkdtemp(dir=WORK)
        p = d + "/a.txt"
        open(p, "w", encoding="utf-8").write("현장조사 결과 분묘가 발견되지 않았음.")
        it = analyze.apply_appraisal({"grade": "낮음", "notes": [], "media": {"appraisal": {"text": p}}}, "A")
        self.assertFalse(it["bad_exit"])

    def test_appr_5_real_grave_still_flagged(self):
        for t in ("본건 지상에 연고자 미상의 분묘 약 10여기가 소재함.", "지상에 분묘가 소재하므로 사전조사 후 입찰바람",
                  "본건 지상에 후첨 사진과 같이 분묘 등이 소재하는 묘역이 조성되어 있음"):
            self.assertIn("분묘", msgs(t), t)

    def test_appr_6_landlocked_negation_variants(self):
        for t in ("본건은 맹지는 아니며 도로에 접함.", "본건은 맹지가 아닌 토지임.", "본건은 맹지로 보기 어려움.",
                  "본건은 맹지에 해당하지 않음.", "비맹지 토지임"):
            self.assertNotIn("맹지", msgs(t), t)

    def test_appr_7_slope_and_unlisted(self):
        self.assertNotIn("급경사", msgs("급경사"))                                    # 비교표준지 지세 칸이 줄로 쪼개진 한 단어
        self.assertNotIn("급경사", msgs("급경사가 아님"))
        self.assertNotIn("제시외 건물·수목", msgs("제시외 건물은 없음"))
        self.assertNotIn("제시외 건물·수목", msgs("제시외건물 없음"))
        self.assertNotIn("제시외 건물·수목", msgs("범 례            도로                   평가건물1층                  제시외건물"))
        self.assertIn("급경사", msgs("본건은 급경사지로서 접근이 어려움"))
        self.assertIn("제시외 건물·수목", msgs("제시외 건물(창고 15㎡)이 있으나 평가에서 제외함"))

    def test_appr_8_field_pattern(self):
        F = "지목은 대지 등이나 현황은 전·답(경작 중)"
        for t in ("공부상 지목은 대이나 현황은 전원주택 부지임.", "공부상 지목은 대이나 현황은 전혀 이용하지 않는 나지임.",
                  "공부상 지목은 대이나 현황은 전체가 포장된 주차장임.", "공부상 지목은 대이나 현황은 답사 당시 주차장임."):
            self.assertNotIn(F, msgs(t), t)
        for t in ("공부상 지목은 ‘대’이나 현황은 ‘전’으로 이용 중임.", "공부상 지목은 임야이나 현황은 논으로 이용 중임.",
                  "공부상 지목은 임야이나 현황은 경작지로 이용 중임.", "공부상 지목은 임야이나 현황은 전으로 이용 중임.",
                  "공부상 지목은 임야이나 현황은 밭으로 이용 중임."):
            self.assertIn(F, msgs(t), t)

    def test_appr_15_grave_synonyms(self):
        for t in ("지상에 묘지 3기가 소재함", "현황 자연림,묘지로 이용중임.", "봉분 다수 소재", "묘 3기가 소재함"):
            self.assertIn("분묘", msgs(t), t)
        for t in ("주위는 임야, 묘지 및 전 등으로 형성된 임야지대임.", "공동묘지에 접함", "‘감북동 공원묘지(일자산 묘지)’ 남측 인근에 위치"):
            self.assertNotIn("분묘", msgs(t), t)

    def test_extra_1_boilerplate_grave_caution_not_bad_exit(self):
        # KAMCO 유의사항 상투 문구가 A에서 bad_exit(⛔ 입찰 비권장)을 켠다
        for n in ("- 현황 자연림으로 미확인 분묘가 소재할 수 있사오니 사전조사 후 입찰바람.",
                  "- 본 건 정확한 지적관련 사항, 분묘소재여부, 경계 등의 확인이 필요한 경우에는 측량등을 통한 재확인이 필요하므로 사전조사 후 입찰바람",
                  "ㅇ현황 자연림으로 지상에 \"분묘\"가 소재할 가능성이 있으므로 분묘기지권 성립여부 등에 관하여는 매수신청인의 책임하에 사전 현장조사 후 입찰바람",
                  "- 본건 육안으로 확인되지 않은 분묘가 소재할 수 있으므로 사전조사 후 입찰바람."):
            it = analyze.apply_appraisal({"grade": "낮음", "notes": [n], "media": {}}, "A")
            self.assertFalse(it["bad_exit"], n)

    def test_extra_1_real_grave_in_notes_still_bad_exit(self):
        for n in ("지상에 \"분묘\"가 소재하므로 분묘기지권 성립여부 등에 관하여 사전조사 후 입찰바람",
                  "- 본건은 공유지분 매각건으로 필지 전체에 80여기가 넘는 분묘가 전체에 산재됨.",
                  "ㅇ 본건 지목 임야로 지상에 소유자미상의 분묘 소재하오니 분묘기지권 성립여부 등 입찰자의 책임하에 사전조사 후 입찰바람"):
            it = analyze.apply_appraisal({"grade": "낮음", "notes": [n], "media": {}}, "A")
            self.assertTrue(it["bad_exit"], n)


class TestBug_Parse(unittest.TestCase):
    def test_appr_9_unfetched_viewer_is_not_available(self):
        raw = ("fn_pbctPrptDstmtReport('2026', '037');\n=========\nClipType=pageCheck&ClipData=x\n----\n"
               '{"id":2,"resValue":{"is_s":false,"status":true,"event":200,"count":2,"endReport":true}}')
        self.assertFalse(parse.statement(raw)["available"])

    def test_appr_9_flags_D_warns(self):
        raw = "x\n=========\nClipType=pageCheck\n----\n" + '{"id":2,"resValue":{"status":true}}'
        st = parse.statement(raw)
        fl = analyze.flags_D({"statement": st, "kv": {}, "notes": []})
        self.assertIn("공매재산명세서 미공개(입찰 임박 시 재확인)", [m for _, m in fl])

    def test_appr_9_grade_A_does_not_claim_clean(self):
        import datetime
        raw = "x\n=========\nClipType=pageCheck\n----\n" + '{"id":2,"resValue":{"status":true}}'
        it = {"reg": [["1", "공유자", "홍길동", "2005-01-01"]], "reg_cnt": 1, "land_class": "우선", "occ_cnt": 0, "lease_cnt": 0,
              "statement": parse.statement(raw)}
        g, basis = analyze.grade_A(it, datetime.date(2026, 10, 18))
        self.assertFalse(basis["명세서공개"])

    def test_appr_13_duplicate_gonggobogi(self):
        d = item_dir("<html><body><p>공고보기</p><p>공고보기</p></body></html>")
        parse.parse_item("X", d)

    def test_appr_13_truncated_xhr(self):
        d = item_dir("<html><body><p>공고보기</p><p>물건A</p></body></html>", xhr='{"inqRgstMtrsCrtiClg": "<table')
        parse.parse_item("X", d)

    def test_appr_13_xhr_wrong_types(self):
        for v in ("[1,2]", '{"inqRgstMtrsCrtiClg": 5}'):
            d = item_dir("<html><body><p>공고보기</p><p>물건A</p></body></html>", xhr=v)
            parse.parse_item("X", d)

    def test_appr_13_stmt_garbage(self):
        for res in ({"resValue": None}, {"resValue": {"viewData": "!!!notbase64"}},
                    {"resValue": {"viewData": base64.b64encode(b"not json").decode()}}):
            d = item_dir("<html><body><p>공고보기</p><p>물건A</p></body></html>", stmt="h\n=========\nx\n----\n" + json.dumps(res))
            parse.parse_item("X", d)

    def test_appr_14_note_not_cut_by_org_name(self):
        st = parse.statement(clip_raw(["▣ 기타 유의 사항", "- 자세한 사항은 한국자산관리공사에 문의 바람", "- 가등기 있음", "2026.10.15", "한국자산관리공사 서울"]))
        self.assertEqual(st["note"], ["- 자세한 사항은 한국자산관리공사에 문의 바람", "- 가등기 있음"])

    def test_appr_14_occupancy_without_lease_header(self):
        st = parse.statement(clip_raw(["▣ 공매재산 이용 및 점유현황", "구분", "비고", "홍길동", "▣ 배분요구 및 채권신고 현황", "구분", "비고", "배분요구 행"]))
        self.assertEqual(st["occupancy_rows"], ["홍길동"])


class TestBug_Report(unittest.TestCase):
    def test_appr_11_nonpositive_cap_wording(self):
        it = {"exit": analyze.exit_numbers({"appraisal": 300_000, "price": 100_000}), "round": "1"}
        text = "\n".join(report.exit_lines(it))
        self.assertIn("38만원", text)
        self.assertNotIn("35만원", text)

    def test_appr_10_price_over_budget_cap_is_warned(self):
        it = {"appraisal": 30_000_000, "price": 9_800_000, "round": "037",
              "schedule": [{"no": "037", "start": "2026-10-19 09:00", "price": 9_800_000}]}
        it["exit"] = analyze.exit_numbers(it)
        text = "\n".join(report.exit_lines(it))
        self.assertIn("예산 상한", text)
        self.assertIn("넘는다", text)

    def test_appr_10_under_budget_cap_no_warning(self):
        it = {"appraisal": 30_000_000, "price": 5_000_000, "round": "037",
              "schedule": [{"no": "037", "start": "2026-10-19 09:00", "price": 5_000_000}]}
        it["exit"] = analyze.exit_numbers(it)
        self.assertNotIn("넘는다", "\n".join(report.exit_lines(it)))


# ───────────────────────── 수정안으로도 남는 한계 ─────────────────────────

class TestOpen_Limits(unittest.TestCase):
    def test_subject_sentence_with_keyword_words_is_still_skipped(self):
        # appr-4 후반부: '접근조건/획지…' 낀 서술 문장. APPR_SKIP 키워드는 '맹지인 비교 표준지에 비해 … 가로조건' 같은 격차율 문장을
        # 막으려는 것이라 단순히 풀 수 없다(풀면 05933-001의 '획지조건 획지, 맹지, 방위…' 머리글이 오탐된다).
        self.assertIn("맹지", msgs("본건은 맹지로서 접근조건이 불량함"))

    def test_line_wrapped_sentences(self):
        self.assertNotIn("맹지", msgs("도로에 접하고 있어 맹지가\n아님"))
        self.assertIn("지목은 대지 등이나 현황은 전·답(경작 중)", msgs("지목은 임야이나\n현황은 전으로 이용 중임."))


if __name__ == "__main__":
    unittest.main()
