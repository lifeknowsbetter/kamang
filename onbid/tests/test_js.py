"""영역 js — Node 수집기(search/details/results) · media.py 다운로드 · run.py(run_details, verify_link) 시험.

네트워크를 쓰지 않는다. Node 스크립트는 lib.js 를 가짜로 바꿔 복사해서 제어 흐름만 돌린다.
저장소 파일을 수정하지 않는다. 실행: python3 -m unittest -v test_js   (이 디렉터리에서)

통과(현재 코드가 기대대로 동작): P 접두어. 버그를 드러내는 시험(현재 코드에서 실패): BUG 접두어.
"""
import os as _os
REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
FIXTURES = _os.environ.get("ONBID_FIXTURES", "/nonexistent-onbid-fixtures")
FIXTURES_PARENT = _os.path.dirname(FIXTURES)
import http.server
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, REPO_ROOT)

from onbid import analyze, media, parse, report, track  # noqa: E402
from onbid import run as R  # noqa: E402

REPO_JS = os.path.join(REPO_ROOT, "onbid", "js")
HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, "live")           # 실측 검색 결과(있을 때만 쓰는 시험)

# ───────────────────────── Node 시험용 가짜 lib.js ─────────────────────────
STUB_LIB = r"""
const SC = process.env.SCENARIO || 'normal';
const TOTAL = Number(process.env.TOTAL || 1128);
const mk = (n, base) => Array.from({ length: n }, (_, i) => ({ scrnIndctCltrMngNo: 'X-' + (base + i), lowstBidPrc: 1000 }));
let respHandler = null;
const page = {
  _h: null,
  waitForLoadState: async () => {}, waitForFunction: async () => {},
  goto: async function () { if (this._h) this._h({ url: () => 'x/cltrBidRsltClg.do', postData: () => 'srchCltrType=0001&pageIndex=1' }); },
  on(ev, h) { this._h = h; }, off() {},
  content: async () => '<html>detail</html>',
  evaluate: async (fn, arg) => {
    const s = fn.toString();
    if (s.includes('$(\'#orderForm\').serialize()')) return 'srchBidPerdBgngDt=2026-10-18&srchBidPerdEndDt=2026-11-18&srchCltrType=0001';
    if (Array.isArray(arg)) {                       // details.js fetchFragments
      return Object.fromEntries(arg.map(ep => [ep, SC === 'fragerr' ? 'ERR Failed to fetch' : '<p>총 <b>0</b>건</p><table><tbody></tbody></table>']));
    }
    if (s.includes('inqCltrMapImg')) return SC === 'imgerr' ? 'ERR Failed to fetch' : '<img src="x">';
    if (s.includes('fn_pbctPrptDstmtReport') && s.includes('querySelectorAll')) return ["fn_pbctPrptDstmtReport('2026','037');"];
    return undefined;
  },
};
const popup = { waitForLoadState: async () => {}, waitForTimeout: async () => {}, evaluate: async () => {}, close: async () => {} };
const ctx = {
  on(ev, h) { respHandler = h; },
  waitForEvent: async () => {
    if (SC !== 'stmtempty' && respHandler) {        // 정상: 리포트 서버 응답이 도착한다
      await respHandler({ url: () => 'http://x/report_server.jsp', request: () => ({ postData: () => 'ClipType=pageCheck' }),
                          text: async () => '{"resValue":{"viewData":"e30="}} DocumentPageView' });
    }
    return popup;
  },
};
async function post(_page, url, body) {
  const p = new URLSearchParams(body);
  const pg = Number(p.get('pageIndex') || 1), unit = Number(p.get('pageUnit') || 100);
  if (url.includes('srchCltrCdtn')) {
    const page_ = (eff, total) => { const left = Math.max(0, total - (pg - 1) * eff); return JSON.stringify({ totalCount: total, cltrInfVOList: mk(Math.min(eff, left), (pg - 1) * eff) }); };
    if (SC === 'normal') return page_(unit, TOTAL);
    if (SC === 'cap50') return page_(50, TOTAL);
    if (SC === 'errpage3') return pg === 3 ? JSON.stringify({ result: 'fail', msg: 'session' }) : page_(unit, TOTAL);
    if (SC === 'zero') return JSON.stringify({ totalCount: 0, cltrInfVOList: [] });
  }
  if (url.includes('cltrBidRsltClg')) {
    if (SC === 'res100') return JSON.stringify({ totalCount: 250, cltrBidRsltClgInfVOList: mk(100, 0).map(r => ({ ...r, pbctStatNm: '낙찰', onbidBidAmt: '1,000', pbctExctDt: '2026-10-01 10:00:00' })) });
    if (SC === 'reserr') return JSON.stringify({ result: 'error', message: 'session expired' });
    return JSON.stringify({ cltrBidRsltClgInfVOList: [] });
  }
  return '{}';
}
module.exports = {
  launch: async () => ({ browser: { close: async () => {} }, ctx, page }),
  openSearch: async () => true, gotoDetail: async () => true, post, sleep: ms => new Promise(r => setTimeout(r, 1)),
  detailLink: () => '', ORIGIN: 'https://www.onbid.co.kr', SEARCH_URL: '',
};
"""


def run_js(script, args, scenario="normal", cwd=None):
    """저장소의 JS 파일을 가짜 lib.js 와 함께 임시 폴더에 복사해 실행한다."""
    d = tempfile.mkdtemp(prefix="jsmock_")
    shutil.copy(os.path.join(REPO_JS, script), os.path.join(d, script))
    with open(os.path.join(d, "lib.js"), "w") as f:
        f.write(STUB_LIB)
    env = dict(os.environ, SCENARIO=scenario)
    p = subprocess.run(["node", os.path.join(d, script), *map(str, args)], capture_output=True, text=True, env=env, timeout=60,
                       cwd=cwd or d)
    return p, d


# ───────────────────────── search.js ─────────────────────────
class SearchJs(unittest.TestCase):
    def search(self, scenario):
        out = tempfile.mkdtemp(prefix="srch_out_")
        p, _ = run_js("search.js", [out, 10_000_000, 10_000_000, 10_000_000], scenario)
        rows = {}
        for k in "ABC":
            fp = os.path.join(out, f"search_{k}.json")
            if os.path.exists(fp):
                rows[k] = json.load(open(fp))
        return p, rows

    def test_P_paginates_all_pages(self):
        p, rows = self.search("normal")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(rows["A"]["rows"]), 1128)
        self.assertEqual(rows["A"]["totalCount"], 1128)

    def test_server_page_cap_still_collects_everything(self):
        """서버가 한 번에 50건만 줘도 totalCount 까지 쪽을 넘겨 모두 받는다(받은 행 수가 totalCount 와 다르면 실패)."""
        p, rows = self.search("cap50")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(rows["A"]["rows"]), 1128)
        self.assertEqual(rows["A"]["totalCount"], 1128)

    def test_json_error_body_on_later_page_fails_run(self):
        """3쪽에서 세션 오류 JSON({result:'fail'})이 오면 재시도 뒤 실패(종료코드≠0)로 알리고 일부만 저장하지 않는다."""
        p, rows = self.search("errpage3")
        self.assertNotEqual(p.returncode, 0, "중간 쪽 오류 응답을 마지막 쪽으로 오인해 성공 처리")
        self.assertEqual(rows, {}, "일부만 받은 검색 결과를 저장하면 다음 단계가 완전한 목록으로 읽는다")

    def test_zero_rows_is_failure(self):
        """세 트랙 모두 0건이면 수집 실패로 처리한다(종료코드≠0) — run.py 가 '0건' 초안 대신 실패 리포트를 쓴다."""
        p, rows = self.search("zero")
        self.assertNotEqual(p.returncode, 0, "0건(빈 데이터)인데 종료코드 0")
        self.assertEqual(rows, {})


# ───────────────────────── details.js ─────────────────────────
class DetailsJs(unittest.TestCase):
    def run_details_js(self, scenario):
        out = tempfile.mkdtemp(prefix="det_out_")
        pool = os.path.join(out, "_pool.json")
        json.dump([{"scrnIndctCltrMngNo": "T-1"}], open(pool, "w"))
        p, _ = run_js("details.js", [pool, out], scenario)
        return p, out

    def test_P_happy_path_writes_done_and_all_parts(self):
        p, out = self.run_details_js("normal")
        self.assertEqual(p.returncode, 0, p.stderr)
        for ext in ("html", "xhr", "img", "stmt", "done"):
            self.assertTrue(os.path.exists(os.path.join(out, f"T-1.{ext}")), ext)
        self.assertIn("DocumentPageView", open(os.path.join(out, "T-1.stmt")).read())

    def test_fragment_error_is_not_marked_done(self):
        """조각(권리·점유·임대차) 조회가 'ERR …'이면 .xhr 도 .done 도 쓰지 않는다 — 점유·임대차 조회 실패가 '문제 없음'이 되지 않게."""
        p, out = self.run_details_js("fragerr")
        self.assertFalse(os.path.exists(os.path.join(out, "T-1.xhr")))
        self.assertFalse(os.path.exists(os.path.join(out, "T-1.done")), ".done 이 있으면 --skip-search 재실행에서도 다시 받지 않는다")

    def test_statement_never_arrived_is_read_as_unavailable(self):
        """명세서 버튼이 있는데 리포트 서버 응답이 안 오면 빈 .stmt 가 남는다. 완료 처리는 되지만 parse 가 '공개 안 됨'으로 읽어
        flags_D 가 '명세서 미공개' 경고를 낸다(수집 실패가 '권리관계 깨끗함'이 되지 않는다)."""
        p, out = self.run_details_js("stmtempty")
        stmt = open(os.path.join(out, "T-1.stmt")).read()
        self.assertNotIn("DocumentPageView", stmt)
        self.assertFalse(parse.statement(stmt)["available"])

    def test_image_popup_error_is_not_marked_done(self):
        p, out = self.run_details_js("imgerr")
        self.assertFalse(os.path.exists(os.path.join(out, "T-1.img")))
        self.assertFalse(os.path.exists(os.path.join(out, "T-1.done")))


class StatementParse(unittest.TestCase):
    # 실제 수집본(test5/items/2025-14353-001.stmt)과 같은 모양: 버튼은 있고 리포트 서버는 pageCheck 응답만 왔다
    REAL_EMPTY = ("fn_pbctPrptDstmtReport('2026', '037');|fn_pbctPrptDstmtReport('2026', '037');\n=========\n"
                  "ClipType=pageCheck&ClipData=%7B%22cnt%22%3A1%7D\n----\n"
                  '{"id":2,"resValue":{"is_s":false,"status":true,"event":200,"count":2,"endReport":true}}')

    def test_P_no_button_is_unavailable(self):
        self.assertFalse(parse.statement("NO_BUTTON")["available"])

    def test_BUG_button_but_no_report_is_reported_as_available_and_empty(self):
        """수집 실패를 '명세서 공개됨 + 인수권리·점유 없음'으로 읽는다 → flags_D 의 '명세서 미공개' 경고가 사라지고 등급이 올라간다."""
        st = parse.statement(self.REAL_EMPTY)
        self.assertFalse(st["available"], "본문이 하나도 없는데 available=True")

    def test_BUG_flags_D_loses_unpublished_warning_for_failed_capture(self):
        it = {"statement": parse.statement(self.REAL_EMPTY), "kv": {}, "notes": []}
        msgs = [m for _, m in analyze.flags_D(it)]
        self.assertTrue(any("명세서" in m for m in msgs), f"명세서 미확인 경고 없음: {msgs}")


class GradeImpact(unittest.TestCase):
    EMPTY = StatementParse.REAL_EMPTY

    def _d_item(self, statement):
        return {"statement": statement, "kv": {}, "notes": [], "schedule": [], "round": "037", "row": {}, "price": 4_962_000,
                "appraisal": 49_620_000, "occ": [], "lease": [], "reg": []}

    def test_P_unavailable_statement_gives_yellow_flag_and_mid_grade(self):
        out = analyze.build_D([self._d_item({"available": False})], __import__("datetime").date(2026, 10, 19))[0]
        self.assertEqual(out["grade"], "중간")

    def test_BUG_failed_statement_capture_gives_low_grade_in_D(self):
        """실제 수집본(2025-14353-001)과 같은 빈 명세서 → 같은 물건이 명세서 미공개일 때는 중간인데 낮음으로 나온다."""
        out = analyze.build_D([self._d_item(parse.statement(self.EMPTY))], __import__("datetime").date(2026, 10, 19))[0]
        self.assertNotEqual(out["grade"], "낮음")

    def test_BUG_grade_A_treats_missing_occupancy_fragments_as_none(self):
        """details.js 가 점유·임대차 조각을 'ERR …'로 저장하면 parse 는 (None, [])로 읽고 grade_A 는 occ_cnt or 0 → 0 건으로 취급(낮음)."""
        it = {"reg": [["1", "공유자", "홍길동", "2010-01-01"]], "reg_cnt": 1, "occ_cnt": None, "lease_cnt": None, "land_class": "우선",
              "statement": {"available": True, "keep": [], "surface": [], "occupancy_rows": [], "lease_rows": []}}
        g, basis = analyze.grade_A(it, __import__("datetime").date(2026, 10, 19))
        self.assertNotEqual(g, "낮음", f"점유·임대차를 조회하지 못했는데 {g}")


# ───────────────────────── results.js ─────────────────────────
class ResultsJs(unittest.TestCase):
    def results(self, scenario):
        d = tempfile.mkdtemp(prefix="res_")
        inp, outp = os.path.join(d, "in.json"), os.path.join(d, "out.json")
        json.dump({"items": [{"mng": "M-1", "type": "0001"}],
                   "keywords": [{"key": "B:x", "kw": "x", "type": "0003", "from": "2026-07-20"}]}, open(inp, "w"))
        p, _ = run_js("results.js", [inp, outp], scenario)
        return p, json.load(open(outp)) if os.path.exists(outp) else None

    def test_P_normal_empty_results(self):
        p, out = self.results("normal")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(out["keywords"]["B:x"], [])

    def test_BUG_keyword_query_capped_at_100_without_warning(self):
        """키워드 조회는 pageIndex=1·100건만 읽고 totalCount(250)를 보지 않는다. 잘려도 경고가 없다."""
        p, out = self.results("res100")
        self.assertEqual(len(out["keywords"]["B:x"]), 100)
        self.assertRegex(p.stderr, r"100|잘|상한|totalCount|truncat", "100건 상한에 걸렸다는 경고가 stderr 에 없음")

    def test_BUG_error_json_looks_like_zero_hits(self):
        """오류 JSON(리스트 키 없음)을 []로 바꿔 버린다 → 쿼리 실패가 '낙찰 사례 없음'으로 보인다. 실패면 null 이어야 한다."""
        p, out = self.results("reserr")
        self.assertIsNone(out["keywords"]["B:x"])
        self.assertIsNone(out["items"]["M-1"])

    def test_BUG_failed_keyword_query_reported_as_no_comps(self):
        """results.js 가 null(조회 실패)을 주면 comps_summary(None)이 n_sold=0 dict 를 만들어 리포트가 '낙찰 사례 없음'이라 쓴다."""
        c = track.comps_summary(None, exclude="M", price=1_000_000)
        it = {"comps": c, "comp_key": "B:노트북"}
        line = report.comps_line(it)
        self.assertNotIn("낙찰 사례 없음", line or "", "조회 실패인데 '사례 없음'으로 표시")


# ───────────────────────── run.py ─────────────────────────
FAKE_NODE = r"""#!/usr/bin/env python3
import json, os, sys, time
# argv: node details.js <pool.json> <outDir>
pool, out = sys.argv[2], sys.argv[3]
cfg = json.load(open(os.environ["FAKE_NODE_CFG"]))
items = json.load(open(pool))
with open(cfg["log"], "a") as f:
    f.write(json.dumps({"pool": os.path.basename(pool), "n": len(items), "mngs": [i["scrnIndctCltrMngNo"] for i in items]}) + "\n")
if cfg.get("hang"):
    time.sleep(600)
for it in items:
    m = it["scrnIndctCltrMngNo"]
    if m in cfg.get("fail_always", []):
        continue
    if m in cfg.get("fail_once", []):
        mark = os.path.join(out, m + ".tried")
        if not os.path.exists(mark):
            open(mark, "w").close()
            continue
    open(os.path.join(out, m + ".done"), "w").close()
"""


class RunDetails(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rundet_")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        node = os.path.join(self.bin, "node")
        open(node, "w").write(FAKE_NODE)
        os.chmod(node, os.stat(node).st_mode | stat.S_IEXEC)
        self.items = os.path.join(self.tmp, "items")
        os.makedirs(self.items)
        self.cfgp = os.path.join(self.tmp, "cfg.json")
        self.log = os.path.join(self.tmp, "calls.log")
        open(self.log, "w").close()
        self.rows = [{"scrnIndctCltrMngNo": f"M-{i:02d}"} for i in range(12)]

    def go(self, cfg, workers=5, patch_time=False):
        cfg = dict(cfg, log=self.log)
        json.dump(cfg, open(self.cfgp, "w"))
        env = {"PATH": self.bin + os.pathsep + os.environ["PATH"], "FAKE_NODE_CFG": self.cfgp}
        with mock.patch.dict(os.environ, env):
            if patch_time:
                calls = {"n": 0}

                def fake_time():
                    calls["n"] += 1
                    return calls["n"] * 5000.0                      # 호출할 때마다 5000초씩 흐른다 → 마감(3600초) 즉시 초과
                with mock.patch.object(R.time, "time", fake_time):
                    R.run_details(self.rows, self.items, workers)
            else:
                R.run_details(self.rows, self.items, workers)
        return [json.loads(l) for l in open(self.log)]

    def done(self):
        return sorted(f[:-5] for f in os.listdir(self.items) if f.endswith(".done"))

    def test_P_round_robin_distribution_and_all_done(self):
        calls = self.go({})
        self.assertEqual(sorted(c["n"] for c in calls), [2, 2, 2, 3, 3])      # 12건 → 5개 브라우저 3,3,2,2,2
        self.assertEqual(len(self.done()), 12)
        self.assertEqual(len(calls), 5)                                      # 전부 끝나면 2차 시도 없음

    def test_P_second_attempt_retries_only_unfinished_with_two_workers(self):
        calls = self.go({"fail_once": ["M-00", "M-01", "M-02", "M-03", "M-04"]})
        first, second = calls[:5], calls[5:]
        self.assertEqual(len(second), 2)
        self.assertEqual(sorted(m for c in second for m in c["mngs"]), ["M-00", "M-01", "M-02", "M-03", "M-04"])
        self.assertEqual(len(self.done()), 12)

    def test_P_always_failing_item_stays_missing_without_exception(self):
        self.go({"fail_always": ["M-05"]})
        self.assertNotIn("M-05", self.done())
        self.assertEqual(len(self.done()), 11)

    def test_P_existing_done_is_skipped(self):
        for r in self.rows:
            open(os.path.join(self.items, r["scrnIndctCltrMngNo"] + ".done"), "w").close()
        self.assertEqual(self.go({}), [])

    def test_P_hung_worker_is_killed_at_deadline_and_retry_runs(self):
        t0 = __import__("time").time()
        calls = self.go({"hang": True}, workers=3, patch_time=True)
        self.assertLess(__import__("time").time() - t0, 60)                   # 마감 후 kill 되어 빠져나온다
        self.assertEqual(len(calls), 3 + 2)                                  # 1차 3개 + 2차 2개 모두 시도

    def test_P_note_done_marker_ignores_age(self):
        """설계 메모: .done 은 날짜를 보지 않고 건너뛴다. 루틴은 매번 새 컨테이너라 문제 없고(README), 같은 out 폴더를
        며칠 재사용하는 로컬 실행에서만 어제 상세가 재사용된다. 버그로 올리지 않는다."""
        m = self.rows[0]["scrnIndctCltrMngNo"]
        p = os.path.join(self.items, m + ".done")
        open(p, "w").close()
        os.utime(p, (0, 0))
        fetched = [x for c in self.go({}) for x in c["mngs"]]
        self.assertNotIn(m, fetched)


class VerifyLink(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html>2026-1000-055802 detail</html>" if "ok" in self.path else b"<html>error</html>"
                code = 200
                if "400" in self.path:
                    code = 400
                self.send_response(code)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_P_ok_when_mng_in_page(self):
        self.assertTrue(R.verify_link(f"http://127.0.0.1:{self.port}/ok", "2026-1000-055802"))

    def test_P_false_when_mng_missing_or_400(self):
        with mock.patch.object(R.time, "sleep", lambda s: None):
            self.assertFalse(R.verify_link(f"http://127.0.0.1:{self.port}/x", "2026-1000-055802"))
            self.assertFalse(R.verify_link(f"http://127.0.0.1:{self.port}/400", "2026-1000-055802"))


class RunNodeTimeout(unittest.TestCase):
    def test_BUG_search_timeout_raises_instead_of_failure_report(self):
        """node(search.js)가 1800초 제한을 넘으면 subprocess.TimeoutExpired 가 그대로 올라와 run.py 가 트레이스백으로 죽는다.
        (returncode≠0 일 때만 report.write_failure 를 쓴다.) 실패 리포트(report_draft.md)가 만들어져야 한다."""
        out = tempfile.mkdtemp(prefix="runto_")
        real_run = subprocess.run

        def fake_run(cmd, *a, **kw):
            if "search.js" in " ".join(map(str, cmd)):
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
            return real_run(cmd, *a, **kw)
        with mock.patch.object(sys, "argv", ["run", "--out", out, "--no-state"]), \
                mock.patch.object(R.subprocess, "run", fake_run):
            try:
                R.main()
            except subprocess.TimeoutExpired:
                pass
        self.assertTrue(os.path.exists(os.path.join(out, "report_draft.md")), "타임아웃 시 실패 리포트가 없음")


# ───────────────────────── media.py ─────────────────────────
def make_pdf(path, pages=1):
    from PIL import Image
    ims = [Image.new("RGB", (600, 800), (200, 200, 200)) for _ in range(pages)]
    ims[0].save(path, "PDF", save_all=True, append_images=ims[1:])


def make_jpeg_bytes():
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (640, 480), (30, 120, 30)).save(b, "JPEG")
    return b.getvalue()


class MediaDownload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jpeg = make_jpeg_bytes()
        d = tempfile.mkdtemp(prefix="mediasrv_")
        cls.pdf_path = os.path.join(d, "good.pdf")
        make_pdf(cls.pdf_path)
        cls.pdf = open(cls.pdf_path, "rb").read()
        cls.hits = []
        cls.mode = {"pdf": "html", "img1": "html"}
        outer = cls

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append(self.path)
                if "dnldImgFile" in self.path:
                    bad = "atchSn=1&" in self.path and outer.mode["img1"] == "html"
                    body = (b"<html>" + b"x" * 1500 + b"</html>") if bad else outer.jpeg
                    self.send_response(200); self.end_headers(); self.wfile.write(body)
                elif "dnldFile" in self.path:
                    body = (b"<html>" + b"e" * 2000 + b"</html>") if outer.mode["pdf"] == "html" else outer.pdf
                    self.send_response(200); self.end_headers(); self.wfile.write(body)
                elif "flaky" in self.path:
                    n = sum(1 for h in outer.hits if "flaky" in h)
                    if n < 3:
                        self.send_response(500); self.end_headers(); return
                    self.send_response(200); self.end_headers(); self.wfile.write(b"ok-data")
                else:
                    self.send_response(404); self.end_headers()

            def log_message(self, *a):
                pass
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="mediaout_")
        type(self).hits = []
        type(self).mode = {"pdf": "html", "img1": "html"}
        self.patches = [mock.patch.object(media, "ORIGIN", self.base), mock.patch.object(media.time, "sleep", lambda s: None)]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_P_get_retries_http_500_then_succeeds(self):
        p = os.path.join(self.d, "f.bin")
        self.assertTrue(media._get(self.base + "/flaky", p))
        self.assertEqual(open(p, "rb").read(), b"ok-data")

    def test_P_get_gives_up_on_404_and_returns_false(self):
        p = os.path.join(self.d, "f.bin")
        self.assertFalse(media._get(self.base + "/nothing", p, tries=2))

    def test_P_photos_download_and_sheet(self):
        type(self).mode["img1"] = "ok"
        item = {"photos": [{"atchFileLstNo": "1", "atchSn": "1"}, {"atchFileLstNo": "1", "atchSn": "2"}]}
        r = media.photos(item, self.d)
        self.assertEqual(r["downloaded"], 2)
        self.assertTrue(os.path.exists(r["sheet"]))

    def test_BUG_html_error_page_saved_as_photo_and_counted(self):
        """200 응답 본문이 HTML 오류 페이지여도 photo01.jpg 로 저장하고 downloaded 에 센다. 다음 실행에서도 size>0 이라 다시 받지 않는다."""
        item = {"photos": [{"atchFileLstNo": "1", "atchSn": "1"}, {"atchFileLstNo": "1", "atchSn": "2"}]}
        r = media.photos(item, self.d)
        self.assertEqual(r["downloaded"], 1, f"이미지가 아닌 응답을 사진으로 셈: downloaded={r['downloaded']}")

    def test_BUG_bad_photo_is_never_refetched_on_rerun(self):
        item = {"photos": [{"atchFileLstNo": "1", "atchSn": "1"}]}
        media.photos(item, self.d)
        type(self).mode["img1"] = "ok"                      # 서버가 회복
        type(self).hits = []
        r = media.photos(item, self.d)
        self.assertTrue(r["sheet"], "서버가 회복됐는데도 오류 HTML 이 남아 사진 모음이 없다(--skip-search 재실행 시나리오)")

    def _item(self):
        return {"pdf": {"name": "x.pdf", "atchFileLstNo": "9", "atchSn": "1", "hash": "h"}}

    def test_P_appraisal_ok_with_real_pdf(self):
        type(self).mode["pdf"] = "ok"
        r = media.appraisal(self._item(), self.d)
        self.assertEqual(r["status"], "ok")

    def test_P_appraisal_html_response_is_detected(self):
        r = media.appraisal(self._item(), self.d)
        self.assertEqual(r["status"], "다운로드 실패")           # HTML 오류 응답은 PDF 로 받아 두지 않는다
        self.assertFalse(os.path.exists(os.path.join(self.d, "appraisal.pdf")))

    def test_BUG_bad_pdf_is_cached_and_never_retried(self):
        """HTML 오류 응답(2000바이트)이 appraisal.pdf 로 남고, size>1000 이라 다음 실행은 다운로드를 건너뛴다 → 영구히 'PDF 아님'."""
        media.appraisal(self._item(), self.d)               # 첫 실행: 서버 오류 페이지
        type(self).mode["pdf"] = "ok"                       # 서버 회복
        r = media.appraisal(self._item(), self.d)           # 재실행(--skip-search)
        self.assertEqual(r["status"], "ok", f"재실행해도 오류 페이지를 지우지 않음: {r}")

    def test_BUG_pdftotext_timeout_crashes_whole_run(self):
        """pdftotext/pdftoppm 의 subprocess.run(timeout=180)이 TimeoutExpired 를 던지면 appraisal()·collect()·run.main() 까지 전파된다."""
        type(self).mode["pdf"] = "ok"
        real_run = subprocess.run

        def fake_run(cmd, *a, **kw):
            if cmd and cmd[0] == "pdftotext":
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
            return real_run(cmd, *a, **kw)
        with mock.patch.object(media.subprocess, "run", fake_run):
            try:
                r = media.appraisal(self._item(), self.d)
            except subprocess.TimeoutExpired:
                self.fail("TimeoutExpired 가 그대로 전파됨 — 한 물건의 PDF 때문에 전체 실행이 중단")
        self.assertIn("status", r)

    def test_P_get_has_per_socket_timeout_but_no_total_deadline_or_size_cap(self):
        """코드 확인용(설계 메모): urlopen(timeout=90)만 있고 전체 시간·용량 상한은 없다."""
        src = open("/home/user/kamang/onbid/media.py", encoding="utf-8").read()
        self.assertIn("timeout=90", src)
        self.assertNotIn("Content-Length", src)


class MediaOutage(unittest.TestCase):
    def test_P_contact_sheet_skips_corrupt_image(self):
        d = tempfile.mkdtemp()
        bad = os.path.join(d, "bad.jpg")
        open(bad, "wb").write(b"<html>not an image</html>" * 100)
        self.assertIsNone(media.contact_sheet([bad], os.path.join(d, "o.jpg")))

    def test_BUG_outage_backoff_has_no_circuit_breaker(self):
        """온비드가 계속 연결 거부일 때 파일 하나당 sleep 2+4+6+8=20초(마지막 실패 뒤에도 잔다). 후보 1건(사진 12+PDF 1)이면 260초,
        상위 35건이면 약 2.5시간. 한 번 실패한 호스트를 건너뛰는 장치가 없다."""
        slept = []
        item = {"photos": [{"atchFileLstNo": "1", "atchSn": str(i)} for i in range(1, 13)]}
        d = tempfile.mkdtemp()
        with mock.patch.object(media, "ORIGIN", "http://127.0.0.1:9"), mock.patch.object(media.time, "sleep", lambda s: slept.append(s)):
            media.photos(item, d)
        self.assertLess(sum(slept), 120, f"사진 12장 연속 실패 시 대기 합계 {sum(slept)}초")


class DedupeRounds(unittest.TestCase):
    def test_P_first_listed_row_of_same_window_is_representative(self):
        rows = [{"scrnIndctCltrMngNo": "A", "pbctBegnDtm": "2026-10-07 12:00", "lowstBidPrc": p, "pbctNsq": str(i + 1)}
                for i, p in enumerate((5_000_000, 3_000_000, 1_000_000))]
        g = analyze.dedupe(rows)
        self.assertEqual(g["A"]["row"]["lowstBidPrc"], 5_000_000)
        self.assertEqual(len(g["A"]["rounds"]), 3)

    def test_BUG_rounds_are_collected_but_never_shown(self):
        """같은 입찰기간 다회차(파산재단: 5백만/3백만/1백만 동시)는 rounds 에 모이지만 report.py 어디서도 쓰지 않아
        리포트에는 첫 행 가격(500만)만 나온다. (README/지시문에는 이 구조에 대한 설명이 없다)"""
        src = open("/home/user/kamang/onbid/report.py", encoding="utf-8").read()
        self.assertIn('"rounds"', src.replace("'", '"'), "rounds(검색 행 전체)를 리포트에 쓰지 않음")


@unittest.skipUnless(os.path.exists(os.path.join(LIVE, "search_A.json")), "실측 검색 결과 없음")
class LiveSnapshot(unittest.TestCase):
    def test_P_total_count_equals_rows_all_tracks(self):
        for k in "ABC":
            j = json.load(open(os.path.join(LIVE, f"search_{k}.json")))
            self.assertEqual(j["totalCount"], len(j["rows"]), k)
            self.assertLessEqual(max(int(r["lowstBidPrc"] or 0) for r in j["rows"]), 10_000_000)
            self.assertEqual(len({r["pbctCdtnNo"] for r in j["rows"]}), len(j["rows"]), "회차 행 중복 없음")

    def test_P_server_ignores_alcYn_filter_so_client_filter_is_needed(self):
        j = json.load(open(os.path.join(LIVE, "search_A.json")))
        self.assertGreater(sum(1 for r in j["rows"] if r.get("alcYn") != "Y"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
