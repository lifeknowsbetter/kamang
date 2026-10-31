"""dev 영역 검증용 단위 시험(독립 재작성). 시험 대상 코드는 DEV_REPO(기본 /home/user/kamang)의 onbid 패키지.

  cd /home/user/kamang && python3 -W ignore <이 파일>                       # 현재 코드: TestCurrentOK 통과, TestBugs 실패(버그 재현)
  DEV_REPO=<scratch>/codereview/dev2/p python3 -W ignore <이 파일>           # 수정안 적용본: 전부 통과해야 함
"""
import os as _os
REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
FIXTURES = _os.environ.get("ONBID_FIXTURES", "/nonexistent-onbid-fixtures")
FIXTURES_PARENT = _os.path.dirname(FIXTURES)
import datetime
import json
import os
import sys
import tempfile
import unittest

REPO = REPO_ROOT
sys.path.insert(0, REPO)
from onbid import devzone as dz, geo, report  # noqa: E402

SP = FIXTURES_PARENT
TMP = tempfile.mkdtemp(prefix="devverify_")
TODAY = datetime.date(2026, 10, 18)


def E(**kw):
    e = dict(id="t-1", name="t", kind="산업단지", stage="계획", sido="인천광역시", sgg=["남동구"], summary="s", asof="2026-09",
             sources=["https://a.com/x"], confidence="low", emd=["논현동"])
    e.update(kw)
    return e


_n = [0]


def vfile(entries_or_raw):
    _n[0] += 1
    p = os.path.join(TMP, f"v{_n[0]}.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write(entries_or_raw if isinstance(entries_or_raw, str) else json.dumps({"entries": entries_or_raw}, ensure_ascii=False))
    return p


def validate(entries_or_raw):
    return dz.validate(vfile(entries_or_raw), today=TODAY)


def D(tier, name, stage, why=None):
    return {"tier": tier, "why": why or ("읍면동 일치" if tier == 1 else "인접 시군구"), "name": name, "stage": stage, "place": "", "summary": "x",
            "asof": "2026-09", "sources": ["http://a"], "confidence": "low"}


class TestCurrentOK(unittest.TestCase):
    """현재 코드에서 통과하는 시험(회귀 방지)."""

    def test_split_loc(self):
        self.assertEqual(dz._split_loc("경기도 화성시 만세구 장안면"), ("경기도", "화성시", "만세구", "장안면"))
        self.assertEqual(dz._split_loc("서울특별시 중구 을지로4가"), ("서울특별시", "중구", None, "을지로4가"))
        self.assertEqual(dz._split_loc("제주특별자치도 제주시 구좌읍"), ("제주특별자치도", "제주시", None, "구좌읍"))

    def test_tiers(self):
        e = E(sido="경기도", sgg=["용인시 처인구"], emd=["원삼면"])
        self.assertEqual(dz.match_entry(e, "경기도 용인시 처인구 원삼면")[0], 1)
        self.assertEqual(dz.match_entry(e, "경기도 용인시 처인구 이동읍")[0], 3)
        self.assertEqual(dz.match_entry(e, "경기도 용인시 기흥구 신갈동"), (3, "같은 시 다른 구"))
        self.assertIsNone(dz.match_entry(e, "경기도 수원시 장안구 영화동"))
        e2 = E(sido="경기도", sgg=["화성시"], emd=[])
        self.assertEqual(dz.match_entry(e2, "경기도 화성시 만세구 장안면")[0], 2)

    def test_same_name_gu_other_sido_not_mixed(self):
        e = E(sido="서울특별시", sgg=["중구"], emd=["을지로"])
        self.assertIsNone(dz.match_entry(e, "부산광역시 중구 중앙동"))

    def test_neighbor_same_gu_matches(self):
        e = E(sido="경기도", sgg=["용인시 기흥구"], emd=["농서동"], neighbors_sgg=["수원시 영통구"])
        self.assertEqual(dz.match_entry(e, "경기도 수원시 영통구 영통동"), (3, "인접 시군구"))

    def test_gwangju_alias(self):
        e = E(sido="전라남도", sgg=["여수시"], emd=[])
        self.assertEqual(dz.match_entry(e, "전남광주통합특별시 여수시 화양면")[0], 2)

    def test_validate_current_data_no_errors(self):
        os.environ.pop("ONBID_DEVZONES", None)
        errs, _ = dz.validate(os.path.join(REPO, "onbid", "data", "devzones.json"), today=TODAY)
        self.assertEqual(errs, [])

    def test_validate_basic_errors(self):
        errs, _ = validate([E(kind="없는종류")])
        self.assertTrue(any("kind" in x for x in errs))
        errs, _ = validate([E(sources=[])])
        self.assertTrue(errs)

    def test_dev_lines_tier3_only_and_cancel_only(self):
        self.assertEqual(len(report.dev_lines({"dev": [D(3, "a", "계획")]})), 1)
        L = report.dev_lines({"dev": [D(1, "취소", "보류·취소")]})
        self.assertTrue(L and "취소" in L[0] and not any("⚠" in x for x in L))

    def test_devscan_section_empty_data(self):
        self.assertIn("읽지 못해", "\n".join(report.devscan_section({"entries": 0})))

    def test_load_missing_and_truncated(self):
        self.assertEqual(dz.load(os.path.join(TMP, "none.json")), {"entries": []})
        p = vfile('{"entries": [')
        self.assertEqual(dz.load(p), {"entries": []})


class TestBugs(unittest.TestCase):
    """버그 재현 시험: 현재 코드에서 실패해야 하고 수정안 적용본에서 통과해야 한다."""

    # dev-1
    def test_dev1_sejong_item_matches_sejong_entry(self):
        self.assertTrue(dz.match("세종특별자치시  연서면"))
        e = E(sido="세종특별자치시", sgg=["세종특별자치시"], emd=["연서면"])
        self.assertEqual(dz.match_entry(e, "세종특별자치시  연서면"), (1, "읍면동 일치"))
        self.assertEqual(dz.match_entry(e, "세종특별자치시  도담동")[0], 3)

    def test_dev1_sejong_neighbor_and_route(self):
        e = E(sido="충청북도", sgg=["청주시 흥덕구"], emd=["오송읍"], neighbors_sgg=["세종특별자치시"])
        self.assertEqual(dz.match_entry(e, "세종특별자치시  장군면"), (3, "인접 시군구"))
        r = E(sido="경기도", kind="교통", sgg=["안성시", "용인시 처인구", "구리시", "세종특별자치시"], emd=[])
        self.assertEqual(dz.match_entry(r, "세종특별자치시  조치원읍")[0], 3)

    # dev-2
    def test_dev2_cross_sido_sgg_in_summary(self):
        self.assertTrue(any(m["tier"] == 1 and "airport" in m["id"] for m in dz.match("경상북도 의성군 비안면")))

    def test_dev2_cross_sido_gtx_seoul(self):
        ids = [m["id"] for m in dz.match("서울특별시 강남구 삼성동")]
        self.assertIn("transport-gtxc", ids)

    def test_dev2_cross_sido_neighbors(self):
        e = E(sido="대구광역시", sgg=["군위군"], emd=["소보면"], neighbors_sgg=["구미시"])
        self.assertEqual(dz.match_entry(e, "경상북도 구미시 도량동"), (3, "인접 시군구"))

    def test_dev2_prefix_wins(self):
        e = E(sido="경기도", kind="교통", sgg=["서울특별시 중구", "강남구", "양주시"], emd=[])
        self.assertIsNotNone(dz.match_entry(e, "서울특별시 중구 을지로4가"))
        self.assertIsNone(dz.match_entry(e, "부산광역시 중구 중앙동"))

    def test_dev2_actual_data_places_resolvable(self):
        """실제 데이터의 sgg·neighbors_sgg 장소가 모두 어떤 물건 문자열로든 맞을 수 있어야 한다(죽은 참조 0)."""
        dead = []
        for e in dz.load()["entries"]:
            for key in ("sgg", "neighbors_sgg"):
                for s in e.get(key) or []:
                    p = s.split()
                    pref = p[0] if p and p[0].endswith(("도", "특별시", "광역시", "특별자치시", "특별자치도")) else None
                    if pref:
                        p = p[1:]
                    if not p:
                        city, sd = (pref, pref)
                    else:
                        city = p[0]
                        owners = [k for k, v in geo.C.items() if city in v]
                        sd = pref or (owners[0] if len(owners) == 1 else e["sido"])
                    loc = f"{sd} {city} 가나다동" if city != sd else f"{sd}  가나다동"
                    m = dz.match_entry(e, loc)
                    if m is None:
                        dead.append((e["id"], key, s))
        # 인천 '서구'(서해구 개편)와 경남 항목의 '강서구'·부산 '동구'는 데이터 쪽 문제라 허용(validate 경고 시험 참고)
        allowed = {("housing-incheon-gyeyang-3gi", "neighbors_sgg", "서구"), ("transport-gtx-def-5th-rail-plan", "sgg", "인천광역시 서구"),
                   ("yeongnam-jinhae-new-port", "neighbors_sgg", "강서구"), ("yeongnam-busan-north-port-redevelopment", "sgg", "동구")}
        self.assertEqual([d for d in dead if d not in allowed], [])

    # dev-3
    def test_dev3_validate_flags_unreadable_or_empty(self):
        for raw in ('{"entries": [', "", '{"entries": []}'):
            errs, _ = validate(raw)
            self.assertTrue(errs, raw)
        errs, _ = dz.validate(os.path.join(TMP, "no_such_file.json"), today=TODAY)
        self.assertTrue(errs)

    def test_dev3_cli_exit_code_on_truncated(self):
        import subprocess
        p = vfile('{"entries": [')
        r = subprocess.run([sys.executable, "-m", "onbid.devzone", "validate"], cwd=REPO, env={**os.environ, "ONBID_DEVZONES": p},
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout)

    # dev-4
    def test_dev4_neighbor_gu_respected(self):
        e = E(sido="경기도", sgg=["용인시 기흥구"], emd=["농서동"], neighbors_sgg=["수원시 영통구"])
        self.assertIsNone(dz.match_entry(e, "경기도 수원시 장안구 영화동"))

    # dev-5
    def test_dev5_validate_flags_dead_places(self):
        _, w = validate([E(neighbors_sgg=["서구"])])               # 인천 서구는 서해구로 개편
        self.assertTrue(any("서구" in x for x in w), w)
        _, w = validate([E(sido="경기도", sgg=["수원시"], neighbors_sgg=["존재안함시"])])
        self.assertTrue(any("존재안함시" in x for x in w), w)

    # dev-6
    def test_dev6_validate_hardening(self):
        _, w = validate([E(), E(id="t-2")])
        self.assertTrue(w)
        _, w = validate([E(neighbors_sgg=["연수구", "부평구", "계양구", "미추홀구", "강화군", "옹진군"])])
        self.assertTrue(w)
        errs, _ = validate([E(id="Housing X")])
        self.assertTrue(errs)
        errs, _ = validate([E(emd="논현동")])
        self.assertTrue(errs)
        errs, _ = validate([E(sources=["httpx"])])
        self.assertTrue(errs)

    def test_dev6_validate_lat_string_no_crash(self):
        errs, _ = validate([E(lat="37.5", lng="127.0")])
        self.assertTrue(errs)

    # dev-7
    def test_dev7_load_wrong_shape(self):
        for raw in ("[]", "null", '{"entries": {"a": 1}}', '{"entries": [null, "x"]}'):
            p = vfile(raw)
            d = dz.load(p)
            self.assertEqual(dz.match("경기도 용인시 처인구 원삼면", d), [])
            self.assertEqual(dz.scan([], d)["total"], 0)

    # dev-8
    def test_dev8_emd_paren_comma(self):
        self.assertIn("양서면", dz._emds({"emd": ["양서면(도곡리, 증동리)", "강상면"]}))

    def test_dev8_ga_number(self):
        e = E(sido="서울특별시", sgg=["중구"], emd=["을지로3가"])
        m = dz.match_entry(e, "서울특별시 중구 을지로6가")
        self.assertTrue(m is None or m[0] != 1, m)
        self.assertEqual(dz.match_entry(e, "서울특별시 중구 을지로3가")[0], 1)
        self.assertEqual(dz.match_entry(E(sido="서울특별시", sgg=["중구"], emd=["을지로"]), "서울특별시 중구 을지로6가")[0], 1)

    # dev-9
    def test_dev9_cancelled_kept_when_live_exists(self):
        L = "\n".join(report.dev_lines({"dev": [D(1, "취소된 사업", "보류·취소"), D(3, "살아있는 사업", "계획")]}))
        self.assertIn("취소된 사업", L)

    # dev-10
    def test_dev10_place_mentions_matched_city(self):
        m = [x for x in dz.match("경기도 군포시 금정동") if x["id"] == "transport-gtxc"][0]
        self.assertIn("군포시", m["place"])

    # dev-11
    def test_dev11_dash_location_fallback(self):
        d, b = geo.of({"sidoSgkEmd": "-", "onbidCltrNm": "전남광주통합특별시 여수시 화양면 서촌리 1431-1  "})
        self.assertIsNotNone(d)
        self.assertGreater(d, 200)

    # dev-15
    def test_dev15_devscan_no_empty_table(self):
        L = "\n".join(report.devscan_section({"total": 10, "counts": {"1": 0, "2": 0, "3": 0}, "shown": [], "hits": 0, "entries": 86, "built": "2026-10-18"}))
        self.assertNotIn("|---|", L)

    # dev-16
    def test_dev16_ulleung_far(self):
        d, b = geo.of({"sidoSgkEmd": "경상북도 울릉군 울릉읍"})
        self.assertGreater(d, 300)
        self.assertEqual(geo.of({"sidoSgkEmd": "대구광역시 수성구 범어동"})[1], "원거리(200km↑)")
        for s, c in (("부산광역시", "금정구"), ("부산광역시", "동구"), ("대구광역시", "수성구"), ("대구광역시", "중구")):
            self.assertIn(c, geo.C[s])


class TestNotBugs(unittest.TestCase):
    """not_a_bug/partially로 판정한 동작이 의도대로(문서·docstring 그대로) 동작함을 고정."""

    def test_dev12_tier2_counts_as_zero_by_design(self):
        self.assertEqual(dz.best_tier([D(2, "x", "계획")]), 0)
        self.assertEqual(dz.best_tier([D(3, "x", "계획")]), 1)
        self.assertEqual(dz.best_tier([D(1, "x", "보류·취소")]), 2)

    def test_dev12_real_counts(self):
        p = os.path.join(FIXTURES, "search_A.json")
        if not os.path.exists(p):
            self.skipTest("search_A.json 없음")
        r = dz.scan(json.load(open(p))["rows"])
        self.assertGreaterEqual((r["counts"][1], r["counts"][2]), (18, 54))          # 데이터가 늘면 같거나 많아진다


if __name__ == "__main__":
    unittest.main(verbosity=1)
