"""영역 dev (개발 연관 매칭과 데이터) 검토용 단위 시험.

TestBehaviorOK  : 현재 코드에서 통과해야 하는 시험(정상 동작 기록).
TestKnownBugs   : 현재 코드에서 실패하는 시험(발견 사항 재현). 고치면 통과해야 한다.

실행: cd /home/user/kamang && python3 -m unittest -v /tmp/.../codereview/dev/test_dev.py
"""
import os as _os
REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
FIXTURES = _os.environ.get("ONBID_FIXTURES", "/nonexistent-onbid-fixtures")
FIXTURES_PARENT = _os.path.dirname(FIXTURES)
import copy
import datetime
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, REPO_ROOT)   # DEV_REPO=<패치본 루트>로 수정안을 검증할 수 있다

from onbid import devzone as dz  # noqa: E402
from onbid import geo, report  # noqa: E402

SCRATCH = FIXTURES
SEARCH_A = os.path.join(FIXTURES, "search_A.json")
TODAY = datetime.date(2026, 10, 18)


def E(**kw):
    """유효한 최소 항목."""
    base = dict(id="t-1", name="시험 사업", kind="산업단지", stage="계획", sido="경기도", sgg=["수원시 영통구"], emd=["매탄동"],
                summary="요약", asof="2026-09", sources=["https://example.com/a"], confidence="low")
    base.update(kw)
    return base


def D(tier=1, stage="계획", **kw):
    """match()가 만드는 dev 원소 모양."""
    d = dict(tier=tier, why="읍면동 일치", id="x", name="시험 사업", kind="산업단지", stage=stage, place="수원시 영통구 매탄동",
             investor=None, scale=None, schedule=None, land_rules=None, summary="요약", asof="2026-09",
             sources=["https://example.com/a"], confidence="low")
    d.update(kw)
    return d


def tmp_json(obj, text=None):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    f.write(text if text is not None else json.dumps(obj, ensure_ascii=False))
    f.close()
    return f.name


# ───────────────────────── 현재 통과해야 하는 시험 ─────────────────────────

class TestBehaviorOK(unittest.TestCase):
    def test_split_loc_variants(self):
        self.assertEqual(dz._split_loc("경기도 수원시 장안구 영화동"), ("경기도", "수원시", "장안구", "영화동"))
        self.assertEqual(dz._split_loc("서울특별시 중구 을지로4가"), ("서울특별시", "중구", None, "을지로4가"))
        self.assertEqual(dz._split_loc("제주특별자치도 제주시 구좌읍"), ("제주특별자치도", "제주시", None, "구좌읍"))
        self.assertEqual(dz._split_loc("경기도 화성시 만세구 장안면"), ("경기도", "화성시", "만세구", "장안면"))
        self.assertEqual(dz._split_loc("인천광역시 서해구 가좌동"), ("인천광역시", "서해구", None, "가좌동"))
        self.assertEqual(dz._split_loc("전남광주통합특별시 광산구 송정동"), ("전남광주통합특별시", "광산구", None, "송정동"))
        self.assertEqual(dz._split_loc(None), ("", "", None, ""))
        self.assertEqual(dz._split_loc("경기도"), ("경기도", "", None, ""))

    def test_norm_emd(self):
        self.assertEqual(dz._norm_emd("노원동3가"), "노원동")
        self.assertEqual(dz._norm_emd("을지로4가"), "을지로")
        self.assertEqual(dz._norm_emd("양서면(도곡리)"), "양서면")
        self.assertEqual(dz._norm_emd(" 구정면 "), "구정면")
        self.assertEqual(dz._norm_emd(None), "")

    def test_emds_split_separators(self):
        self.assertEqual(dz._emds({"emd": ["양서면·강상면", "a,b", "c/d"]}), {"양서면", "강상면", "a", "b", "c", "d"})

    def test_entry_places_strips_sido_prefix(self):
        e = {"sgg": ["서울특별시 중구", "경기도 수원시 장안구", "용인시 처인구", "평택시", "강남구"]}
        self.assertEqual(dz._entry_places(e), [("중구", None), ("수원시", "장안구"), ("용인시", "처인구"), ("평택시", None), ("강남구", None)])

    def test_tier1_gu_city(self):
        m = dz.match_entry(E(), "경기도 수원시 영통구 매탄동")
        self.assertEqual(m[0], 1)

    def test_same_city_other_gu_is_tier3(self):
        m = dz.match_entry(E(), "경기도 수원시 팔달구 매탄동")
        self.assertEqual(m, (3, "같은 시 다른 구"))

    def test_metro_same_gu_name_other_sido_not_matched(self):
        e = E(sido="부산광역시", sgg=["중구"], emd=["대청동"])
        self.assertIsNone(dz.match_entry(e, "서울특별시 중구 을지로4가"))
        self.assertIsNone(dz.match_entry(e, "울산광역시 중구 성안동"))
        self.assertEqual(dz.match_entry(e, "부산광역시 중구 대청동4가")[0], 1)   # 'N가' 정규화

    def test_gwangju_jeonnam_alias(self):
        e = E(sido="전라남도", sgg=["신안군"], emd=["흑산면"])
        self.assertEqual(dz.match_entry(e, "전남광주통합특별시 신안군 흑산면")[0], 1)
        e2 = E(sido="광주광역시", sgg=["광산구"], emd=["신촌동"])
        self.assertEqual(dz.match_entry(e2, "전남광주통합특별시 광산구 신촌동")[0], 1)
        e3 = E(sido="전남광주통합특별시", sgg=["나주시"], emd=["빛가람동"])
        self.assertEqual(dz.match_entry(e3, "전라남도 나주시 빛가람동")[0], 1)       # 옛 이름으로 적힌 물건

    def test_tier2_when_entry_has_no_emd(self):
        e = E(sgg=["평택시"], emd=None)
        self.assertEqual(dz.match_entry(e, "경기도 평택시 청북읍")[0], 2)

    def test_tier3_other_emd_and_broad(self):
        self.assertEqual(dz.match_entry(E(sgg=["평택시"], emd=["고덕면"]), "경기도 평택시 청북읍"), (3, "같은 시·구 안 다른 읍면동"))
        broad = E(kind="교통", sgg=["양평군", "이천시"], emd=None)
        self.assertEqual(dz.match_entry(broad, "경기도 양평군 지평면")[0], 3)

    def test_neighbor_city_tier3(self):
        e = E(sgg=["평택시"], emd=["고덕면"], neighbors_sgg=["안성시"])
        self.assertEqual(dz.match_entry(e, "경기도 안성시 공도읍"), (3, "인접 시군구"))

    def test_latlng_radius_within_same_sido(self):
        e = E(sgg=["평택시"], emd=["고덕면"], lat=37.08, lng=127.09)   # 오산시 중심에서 약 8km
        m = dz.match_entry(e, "경기도 오산시 오산동")
        self.assertEqual(m[0], 3)
        self.assertIn("km", m[1])
        self.assertIsNone(dz.match_entry(e, "경기도 가평군 상면"))

    def test_hwaseong_new_gu(self):
        e = E(sgg=["화성시"], emd=["봉담읍"])
        self.assertEqual(dz.match_entry(e, "경기도 화성시 만세구 봉담읍")[0], 1)
        e2 = E(sgg=["화성시 병점구"], emd=["진안동"])
        self.assertEqual(dz.match_entry(e2, "경기도 화성시 병점구 진안동")[0], 1)
        self.assertEqual(dz.match_entry(e2, "경기도 화성시 동탄구 청계동"), (3, "같은 시 다른 구"))

    def test_jeju(self):
        e = E(sido="제주특별자치도", sgg=["서귀포시"], emd=["성산읍"])
        self.assertEqual(dz.match_entry(e, "제주특별자치도 서귀포시 성산읍")[0], 1)
        self.assertIsNone(dz.match_entry(e, "제주특별자치도 제주시 애월읍"))

    def test_incheon_new_gu_when_entry_uses_new_name(self):
        e = E(sido="인천광역시", sgg=["서해구"], emd=["가좌동"])
        self.assertEqual(dz.match_entry(e, "인천광역시 서해구 가좌동")[0], 1)

    def test_empty_or_odd_loc(self):
        for loc in (None, "", "-", "경기도"):
            self.assertIsNone(dz.match_entry(E(), loc))

    def test_best_tier(self):
        self.assertEqual(dz.best_tier(None), 2)
        self.assertEqual(dz.best_tier([]), 2)
        self.assertEqual(dz.best_tier([D(1)]), 0)
        self.assertEqual(dz.best_tier([D(2)]), 0)
        self.assertEqual(dz.best_tier([D(3)]), 1)
        self.assertEqual(dz.best_tier([D(1, stage="보류·취소")]), 2)
        self.assertEqual(dz.best_tier([D(1, stage="보류·취소"), D(3)]), 1)

    # report.dev_lines
    def test_dev_lines_empty_or_missing(self):
        self.assertEqual(report.dev_lines({}), [])
        self.assertEqual(report.dev_lines({"dev": None}), [])
        self.assertEqual(report.dev_lines({"dev": []}), [])

    def test_dev_lines_tier3_only_single_line_no_warning(self):
        L = report.dev_lines({"dev": [D(3, why="인접 시군구"), D(3, why="인접 시군구", name="다른 사업")]})
        self.assertEqual(len(L), 1)
        self.assertNotIn("⚠", "\n".join(L))
        self.assertNotIn("None", "\n".join(L))

    def test_dev_lines_cancelled_only(self):
        L = report.dev_lines({"dev": [D(1, stage="보류·취소")]})
        txt = "\n".join(L)
        self.assertIn("보류·취소", txt)
        self.assertNotIn("⚠", txt)          # 취소 항목에는 수익 주의 문구를 붙이지 않는다

    def test_dev_lines_strong_has_warning_and_limits_two(self):
        L = report.dev_lines({"dev": [D(1, name="A"), D(2, name="B"), D(2, name="C")]})
        heads = [x for x in L if x.startswith("- 🏗")]
        self.assertEqual(len(heads), 2)
        self.assertIn("⚠", "\n".join(L))

    def test_dev_lines_optional_fields_absent(self):
        d = D(1)
        for k in ("sources", "summary", "schedule", "land_rules", "place"):
            d.pop(k)
        L = report.dev_lines({"dev": [d]})
        self.assertTrue(L and L[0].startswith("- 🏗"))

    def test_devscan_section_missing_data_message(self):
        L = report.devscan_section({"entries": 0, "total": 5, "counts": {"1": 0, "2": 0, "3": 0}, "shown": [], "hits": 0})
        self.assertIn("읽지 못해", "\n".join(L))
        self.assertEqual(report.devscan_section(None), [])

    # load / 파일 문제
    def test_load_missing_truncated_empty(self):
        self.assertEqual(dz.load("/nonexistent/devzones.json"), {"entries": []})
        self.assertEqual(dz.load(tmp_json(None, text="")), {"entries": []})
        self.assertEqual(dz.load(tmp_json(None, text='{"entries": [{"id": "a"')), {"entries": []})

    def test_scan_and_match_with_empty_data(self):
        rows = [{"scrnIndctCltrMngNo": "1", "scrnPrptDvsnNm": "압류재산", "sidoSgkEmd": "경기도 수원시 영통구 매탄동", "lowstBidPrc": 1}]
        r = dz.scan(rows, {"entries": []})
        self.assertEqual((r["total"], r["hits"]), (1, 0))
        self.assertEqual(dz.match("경기도 수원시 영통구 매탄동", {"entries": []}), [])

    # validate가 잡는 것
    def _validate(self, entries):
        p = tmp_json({"entries": entries})
        return dz.validate(p, today=TODAY)

    def test_validate_catches_basic_errors(self):
        errs, _ = self._validate([E(), E()])
        self.assertTrue(any("id 중복" in x for x in errs))
        errs, _ = self._validate([E(kind="없는 종류")])
        self.assertTrue(any("kind" in x for x in errs))
        errs, _ = self._validate([E(stage="착공")])
        self.assertTrue(any("stage" in x for x in errs))
        errs, _ = self._validate([E(confidence="very")])
        self.assertTrue(any("confidence" in x for x in errs))
        errs, _ = self._validate([E(sources=["ftp://x"])])
        self.assertTrue(any("출처" in x for x in errs))
        errs, _ = self._validate([E(asof="2026-13")])
        self.assertTrue(errs)
        errs, _ = self._validate([E(asof="2026-11")])
        self.assertTrue(any("미래" in x for x in errs))
        errs, _ = self._validate([E(lat=37.5)])
        self.assertTrue(any("lat/lng" in x for x in errs))
        errs, _ = self._validate([E(lat=50.0, lng=127.0)])
        self.assertTrue(any("한국 범위" in x for x in errs))
        errs, _ = self._validate([E(sido="전라북도", sgg=["전주시 완산구"])])
        self.assertTrue(any("sido" in x for x in errs))
        errs, _ = self._validate([E(sido="전남광주통합특별시(구 광주광역시)", sgg=["북구"])])      # 괄호 속 옛 이름은 허용한다
        self.assertFalse(any("sido" in x for x in errs))

    def test_validate_warns_stale_and_unknown_city(self):
        _, warns = self._validate([E(asof="2020-01")])
        self.assertTrue(any("오래됨" in x for x in warns))
        _, warns = self._validate([E(sgg=["존재안함시"])])
        self.assertTrue(any("geo" in x for x in warns))

    # 실제 데이터 / 실제 검색 결과
    def test_real_data_validates_with_no_errors(self):
        errs, _ = dz.validate()
        self.assertEqual(errs, [])

    def test_real_data_ids_unique_and_no_cancelled(self):
        ids = [e["id"] for e in dz.load()["entries"]]
        self.assertEqual(len(ids), len(set(ids)))

    @unittest.skipUnless(os.path.exists(SEARCH_A), "test5/search_A.json 없음")
    def test_real_scan_tier1_all_consistent(self):
        rows = json.load(open(SEARCH_A, encoding="utf-8"))["rows"]
        r = dz.scan(rows)
        self.assertGreaterEqual(r["counts"][1], 18)          # 데이터가 늘면 같거나 많아진다
        entries = {e["id"]: e for e in dz.load()["entries"]}
        n = 0
        seen = set()
        for row in rows:
            k = row["scrnIndctCltrMngNo"]
            if k in seen or row.get("scrnPrptDvsnNm") != "압류재산":
                continue
            seen.add(k)
            ms = [m for m in dz.match(row["sidoSgkEmd"]) if m["stage"] != "보류·취소"]
            if ms and ms[0]["tier"] == 1:
                n += 1
                _, city, gu, emd = dz._split_loc(row["sidoSgkEmd"])
                e = entries[ms[0]["id"]]
                self.assertIn(dz._norm_emd(emd), dz._emds(e))
                self.assertIn(city, [c for c, _ in dz._entry_places(e)])
        self.assertGreaterEqual(n, 18)


# ───────────────────────── 현재 실패하는 시험(발견 사항) ─────────────────────────

class TestKnownBugs(unittest.TestCase):
    # dev-1: 세종특별자치시 항목은 어떤 물건과도 맞지 않는다
    def test_sejong_item_matches_sejong_entry(self):
        e = E(sido="세종특별자치시", sgg=["세종특별자치시"], emd=["연서면"])
        m = dz.match_entry(e, "세종특별자치시  연서면")      # 온비드 실제 표기(시군구 없이 공백 2개)
        self.assertIsNotNone(m)
        self.assertEqual(m[0], 1)

    def test_sejong_neighbor_and_route_entries(self):
        nb = E(sido="충청북도", sgg=["청주시 흥덕구"], emd=["오송읍"], neighbors_sgg=["세종특별자치시"])
        self.assertIsNotNone(dz.match_entry(nb, "세종특별자치시  조치원읍"))

    # dev-2: 항목의 sido 하나만 보므로 다른 시도에 걸친 sgg·neighbors_sgg는 죽는다
    def test_cross_sido_sgg_named_in_summary(self):
        e = [x for x in dz.load()["entries"] if x["id"] == "yeongnam-daegu-gyeongbuk-new-airport"][0]
        self.assertIn("비안면", e["emd"])
        m = dz.match_entry(e, "경상북도 의성군 비안면")      # 항목 summary가 '비안면(의성)'이라고 적은 곳
        self.assertIsNotNone(m)
        self.assertEqual(m[0], 1)

    def test_cross_sido_neighbors(self):
        e = E(sido="대구광역시", sgg=["군위군"], emd=["소보면"], neighbors_sgg=["구미시"])
        self.assertEqual(dz.match_entry(e, "경상북도 구미시 도량동"), (3, "인접 시군구"))

    def test_cross_sido_sgg_gtx_seoul(self):
        gtxc = [x for x in dz.load()["entries"] if x["id"] == "transport-gtxc"][0]
        self.assertIsNotNone(dz.match_entry(gtxc, "서울특별시 강남구 삼성동"))   # sgg에 '강남구' 있음

    # dev-3: neighbors_sgg '시 구'의 구를 버려 같은 시 모든 구가 인접으로 잡힌다
    def test_neighbor_gu_is_respected(self):
        e = E(sgg=["용인시 기흥구"], emd=["농서동"], neighbors_sgg=["수원시 영통구"])
        self.assertEqual(dz.match_entry(e, "경기도 수원시 영통구 매탄동"), (3, "인접 시군구"))
        self.assertIsNone(dz.match_entry(e, "경기도 수원시 장안구 영화동"))

    # dev-4: emd 항목 안에 괄호+쉼표가 있으면 쉼표에서 먼저 잘려 읍면동이 사라진다
    def test_emd_parenthesis_with_comma(self):
        self.assertIn("양서면", dz._emds({"emd": ["양서면(도곡리, 증동리)", "강상면"]}))

    # dev-5: 'N가' 정규화가 항목 쪽 N까지 지워 다른 가(街)가 일치로 잡힌다
    def test_ga_number_not_overmerged(self):
        e = E(sido="서울특별시", sgg=["중구"], emd=["을지로3가"])
        self.assertNotEqual((dz.match_entry(e, "서울특별시 중구 을지로6가") or (None,))[0], 1)

    # dev-6: 데이터 파일이 JSON이지만 모양이 틀리면 run 전체가 AttributeError
    def test_load_non_dict_json_does_not_crash(self):
        for text in ("[]", "null", '{"entries": {"a": 1}}', '{"entries": [null, "x"]}'):
            p = tmp_json(None, text=text)
            try:
                data = dz.load(p)
                dz.match("경기도 용인시 처인구 원삼면", data)
                dz.scan([{"scrnIndctCltrMngNo": "1", "scrnPrptDvsnNm": "압류재산", "sidoSgkEmd": "경기도 용인시 처인구 원삼면"}], data)
            except Exception as ex:  # noqa: BLE001
                self.fail(f"{text!r} -> {type(ex).__name__}: {ex}")

    # dev-7: validate가 읽지 못한 파일을 '항목 0개 / 오류 0'으로 통과시킨다
    def test_validate_flags_unreadable_or_empty_file(self):
        for text in ('{"entries": [{"id": "a"', ""):
            p = tmp_json(None, text=text)
            errs, _ = dz.validate(p, today=TODAY)
            self.assertTrue(errs, f"깨진 파일({text!r})이 오류 0으로 통과")
        errs, _ = dz.validate(tmp_json({"entries": []}), today=TODAY)
        self.assertTrue(errs)

    # dev-8: 옛 구 이름(인천 '서구' → 2026-07 이후 서해구)은 다른 시도에 같은 이름이 있어 validate를 그냥 통과한다
    def test_validate_flags_dead_places(self):
        for e in (E(sido="인천광역시", sgg=["남동구"], emd=None, neighbors_sgg=["서구"]),
                  E(sido="인천광역시", sgg=["서구"], emd=None)):
            errs, warns = dz.validate(tmp_json({"entries": [e]}), today=TODAY)
            joined = "\n".join(errs + warns)
            self.assertIn("서구", joined, f"옛 구 이름이 경고 없이 통과: {e['sgg']} {e.get('neighbors_sgg')}")

    # dev-2/dev-1의 데이터 쪽 증상: sgg·neighbors_sgg 문자열 중 어떤 물건과도 맞지 않는 것(효과 기반 검사)
    def test_actual_data_places_are_matchable(self):
        import re as _re
        dead = []
        for e in dz.load()["entries"]:
            for key in ("sgg", "neighbors_sgg"):
                for st in e.get(key) or []:
                    p = st.split()
                    pref = None
                    if p and _re.search(r"(도|특별시|광역시|특별자치시|특별자치도)$", p[0]):
                        pref, p = p[0], p[1:]
                    if not p:                                    # '세종특별자치시'
                        loc = f"{pref}  가상면"
                    else:
                        city = p[0]
                        gu = p[1] if len(p) > 1 else None
                        owners = [k for k, v in geo.C.items() if city in v]
                        sido = pref or (owners[0] if len(owners) == 1 else e["sido"])
                        loc = " ".join(x for x in (sido, city, gu, "가상동") if x)
                    if dz.match_entry(e, loc) is None:
                        dead.append((e["id"], key, st))
        self.assertEqual(dead, [], f"{len(dead)}건이 어떤 물건과도 맞지 않는 죽은 참조")

    # dev-9: 같은 사업이 id만 다르게 두 번 들어가도 validate가 통과시킨다
    def test_validate_flags_duplicate_project(self):
        a = E(id="a-1")
        b = copy.deepcopy(a)
        b["id"] = "b-2"
        errs, warns = dz.validate(tmp_json({"entries": [a, b]}), today=TODAY)
        self.assertTrue(any("중복" in x or "같은 사업" in x for x in errs + warns))

    def test_pending_duplicates_of_main_entries(self):
        main = {e["name"] for e in dz.load()["entries"]}
        pend = json.load(open("/home/user/kamang/onbid/data/devzones_pending.json", encoding="utf-8"))["entries"]
        self.assertEqual([p["id"] for p in pend if p["name"] in main], [])

    # dev-10: lat/lng가 문자열이면 validate 자체가 TypeError
    def test_validate_lat_string_not_crash(self):
        try:
            errs, _ = dz.validate(tmp_json({"entries": [E(lat="37.5", lng="127.0")]}), today=TODAY)
        except TypeError as ex:
            self.fail(f"validate 크래시: {ex}")
        self.assertTrue(errs)

    # dev-11: README는 neighbors_sgg 5개 이하라고 하지만 검사하지 않는다
    def test_validate_neighbors_over_five(self):
        e = E(neighbors_sgg=["안양시", "군포시", "의왕시", "과천시", "성남시", "용인시"])
        errs, warns = dz.validate(tmp_json({"entries": [e]}), today=TODAY)
        self.assertTrue(any("neighbors" in x or "인접" in x for x in errs + warns))

    # dev-12: 보류·취소 항목은 '표시하되 순위에서만 뺀다'고 문서화돼 있으나 살아 있는 항목이 있으면 숨긴다
    def test_dev_lines_keeps_cancelled_when_live_exists(self):
        L = report.dev_lines({"dev": [D(1, stage="보류·취소", name="취소된 사업"), D(3, why="인접 시군구", name="살아있는 사업")]})
        self.assertIn("취소된 사업", "\n".join(L))

    # dev-13: 연관 물건이 0건이면 머리글만 있는 빈 표가 나온다
    def test_devscan_section_no_empty_table(self):
        ds = {"total": 10, "counts": {"1": 0, "2": 0, "3": 0}, "shown": [], "hits": 0, "entries": 86, "built": "2026-10-18"}
        txt = "\n".join(report.devscan_section(ds))
        self.assertNotIn("|---|", txt)

    # dev-14: place 문자열이 sgg 앞 2개 + emd 앞 3개를 이어 붙여 읍면동이 엉뚱한 시에 붙어 보이고 매칭된 시가 빠질 수 있다
    def test_place_mentions_matched_city(self):
        ms = [m for m in dz.match("경기도 군포시 금정동") if m["id"] == "transport-gtxc"]
        self.assertTrue(ms)
        self.assertIn("군포", ms[0]["place"])

    # dev-15: sidoSgkEmd가 '-'인 실제 행(주소는 onbidCltrNm에 있음)을 위치 불명으로 처리한다
    def test_dash_location_falls_back_to_name(self):
        row = {"sidoSgkEmd": "-", "onbidCltrNm": "전남광주통합특별시 여수시 화양면 서촌리 1431-1  ", "scrnPrptDvsnNm": "압류재산",
               "scrnIndctCltrMngNo": "x", "lowstBidPrc": 5576000}
        self.assertIsNotNone(geo.of(row)[0])

    # dev-16: 인접 시군구 라벨이 붙은 약한 연관의 대부분이 neighbors의 구를 무시해서 생긴다(실제 검색 결과 기준)
    @unittest.skipUnless(os.path.exists(SEARCH_A), "test5/search_A.json 없음")
    def test_real_rows_no_wrong_gu_neighbor_hits(self):
        rows = json.load(open(SEARCH_A, encoding="utf-8"))["rows"]
        bad = 0
        seen = set()
        for r in rows:
            k = r["scrnIndctCltrMngNo"]
            if k in seen or r.get("scrnPrptDvsnNm") != "압류재산":
                continue
            seen.add(k)
            if "경기도 수원시 장안구" in r["sidoSgkEmd"]:
                if any(m["id"] == "semi-gyeonggi-hwaseong-samsung-campus" and m["why"] == "인접 시군구" for m in dz.match(r["sidoSgkEmd"])):
                    bad += 1
        self.assertEqual(bad, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
