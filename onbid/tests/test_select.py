"""영역 sel(선별·등급·정렬) 검증 시험. 합성 입력을 인라인으로 쓴다.

이름 규칙
  test_ok_*  : 현재 코드에서 통과(README와 일치하는 동작을 못 박아 둔 것)
  test_bug_* : 현재 코드에서 실패(발견 사항을 드러낸다. 고치면 통과해야 한다)

실행: python3 -B -m unittest /tmp/.../test_sel.py -v   (저장소 파일은 건드리지 않는다)
"""
import os as _os
REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
FIXTURES = _os.environ.get("ONBID_FIXTURES", "/nonexistent-onbid-fixtures")
FIXTURES_PARENT = _os.path.dirname(FIXTURES)
import datetime
import re
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, REPO_ROOT)

from onbid import analyze as A  # noqa: E402
from onbid import carfilter, geo  # noqa: E402

TODAY = datetime.date(2026, 10, 18)


# ───────────────────────── 합성 행 만들기 ─────────────────────────

def rlst(mng, name, cat, price, alc="Y", typ="압류재산", sgg="경기도 군포시 산본동", begin="2026-10-20 10:00", **kw):
    r = {"scrnIndctCltrMngNo": mng, "pbctBegnDtm": begin, "onbidCltrNm": name, "ctgrFullNm": cat, "lowstBidPrc": price,
         "alcYn": alc, "scrnPrptDvsnNm": typ, "sidoSgkEmd": sgg, "regOrgNm": "한국자산관리공사"}
    r.update(kw)
    return r


def mvast(mng, name, cat, price=500_000, appr=0, org="테스트기관", sgg="경기도 군포시 산본동", **kw):
    r = {"scrnIndctCltrMngNo": mng, "pbctBegnDtm": "2026-10-20 10:00", "onbidCltrNm": name, "ctgrFullNm": cat,
         "lowstBidPrc": price, "cltrApslEvlAvgAmt": appr, "regOrgNm": org, "sidoSgkEmd": sgg, "scrnPrptDvsnNm": "압류재산"}
    r.update(kw)
    return r


def car(mng, name, price=5_000_000, cat="자동차 / 승용차", sgg="경기도 군포시 산본동", **kw):
    r = {"scrnIndctCltrMngNo": mng, "pbctBegnDtm": "2026-10-20 10:00", "onbidCltrNm": name, "ctgrFullNm": cat,
         "lowstBidPrc": price, "sidoSgkEmd": sgg, "sidoEmd": sgg.split()[0][:2], "nrtpNm": "2015", "carFuelKindCd": "가솔린",
         "cptnMtdNm": "일반경쟁"}
    r.update(kw)
    return r


def item_A(**kw):
    it = {"land_class": "우선", "kv": {}, "notes": [],
          "reg": [["1", "위임기관", "안****", "2021-10-27", "미표시"], ["2", "압류", "국****", "2022-04-13", "미표시"]], "reg_cnt": 2,
          "statement": {"available": True, "keep": [], "surface": [], "note": [], "occupancy_rows": [], "lease_rows": []},
          "occ_cnt": 0, "lease_cnt": 0}
    it.update(kw)
    return it


def item_D(**kw):
    it = {"kv": {}, "notes": [], "reg": [], "occ": [], "lease": [],
          "statement": {"available": True, "keep": [], "surface": [], "note": [], "occupancy_rows": [], "lease_rows": []}}
    it.update(kw)
    return it


def ids(pool):
    return [v["row"]["scrnIndctCltrMngNo"] for v in pool]


# ═════════════════════════ 통과해야 하는 시험(현재 통과) ═════════════════════════

class OkSelection(unittest.TestCase):
    def test_ok_land_class(self):
        lc = lambda cat: A.land_class({"ctgrFullNm": cat})[0]
        for sub in ("전", "답", "과수원"):
            self.assertEqual(lc(f"토지 / {sub}"), "농지")
        for sub in ("임야", "대지", "대", "도로", "구거"):
            self.assertEqual(lc(f"토지 / {sub}"), "우선")
        self.assertEqual(lc("토지 / 잡종지"), "기타토지")
        self.assertEqual(lc("주거용건물 / 아파트"), "건물")
        self.assertEqual(A.land_class({})[0], "건물")          # 분류가 없어도 예외가 나지 않는다

    def test_ok_dedupe_earliest_begin(self):
        rows = [rlst("X", "a", "토지 / 임야", 3_000_000, begin="2026-10-27 10:00"),
                rlst("X", "a", "토지 / 임야", 5_000_000, begin="2026-10-20 10:00")]
        self.assertEqual(A.dedupe(rows)["X"]["row"]["lowstBidPrc"], 5_000_000)

    def test_ok_select_A_scope(self):
        rows = [rlst("A-ok", "경기도 안양시 만안구 안양동 1", "토지 / 임야", 3_000_000),
                rlst("A-farm", "경기도 안양시 만안구 안양동 2", "토지 / 전", 2_000_000),          # 농지 제외
                rlst("A-solo", "경기도 안양시 만안구 안양동 3", "토지 / 임야", 2_000_000, alc="N"),   # 비지분은 D
                rlst("A-bank", "경기도 안양시 만안구 안양동 4", "토지 / 임야", 2_000_000, typ="파산자산"),  # 압류재산만
                rlst("A-none", "경기도 안양시 만안구 안양동 5", "토지 / 임야", 2_000_000, alc=None, typ="국유재산")]
        pool, st = A.select_A({"rows": rows})
        self.assertEqual(ids(pool), ["A-ok"])
        self.assertEqual(st["지분물건"], 3)

    def test_ok_select_D_scope_and_building_group(self):
        rows = [rlst("D-ok", "경기도 안양시 만안구 안양동 1", "토지 / 임야", 3_000_000, alc="N"),
                rlst("D-farm", "경기도 안양시 만안구 안양동 2", "토지 / 답", 2_000_000, alc="N"),
                rlst("D-share", "경기도 안양시 만안구 안양동 3", "토지 / 임야", 2_000_000, alc="Y"),
                rlst("D-pub", "경기도 안양시 만안구 안양동 4", "토지 / 임야", 2_000_000, alc="N", typ="공유재산"),
                rlst("D-b1", "경기도 수원시 장안구 영화동 308-1 동성영화타운 제2층 제185호", "상가용및업무용건물 / 상업용빌딩", 3_775_000, alc="N", sgg="경기도 수원시 장안구 영화동"),
                rlst("D-b2", "경기도 수원시 장안구 영화동 308-1 동성영화타운 제2층 제240호", "상가용및업무용건물 / 상업용빌딩", 3_775_000, alc="N", sgg="경기도 수원시 장안구 영화동")]
        pool, st = A.select_D({"rows": rows})
        got = set(ids(pool))
        self.assertEqual(got, {"D-ok", "D-b1"})
        self.assertEqual(next(v for v in pool if v["row"]["scrnIndctCltrMngNo"] == "D-b1")["dup"], 1)

    def test_ok_select_B_rights_excluded(self):
        rows = [mvast("B-ok", "롤렉스 시계", "시계/귀금속 / 시계"),
                mvast("B-stock", "(주)에스바디워크컴퍼니 발행주식 보통주식", "유가증권 / 유가증권(주식, 채권 등)"),
                mvast("B-coop", "기계설비건설공제조합 출자증권 8좌", "시계/귀금속 / 귀금속"),         # 분류가 달라도 이름으로 제외
                mvast("B-patent", "특허권 및 상표권", "무형자산 / 특허권")]
        pool, st, hits = A.select_B({"rows": rows})
        self.assertEqual(ids(pool), ["B-ok"])

    def test_ok_select_C_drops_structurally_useless(self):
        rows = [car("C-ok", "현대 쏘나타 1998cc", 5_000_000),
                car("C-cheap", "현대 쏘나타 1998cc", 2_900_000),
                car("C-far", "현대 쏘나타 1998cc", 4_000_000, sgg="경상남도 창원시 마산합포구"),
                car("C-bus", "현대 에어로타운 5899cc", 8_000_000, cat="자동차 / 버스"),
                car("C-ev200k", "쏘울EV 75cc 224,290km", 6_000_000)]
        pool, st, cars = A.select_C({"rows": rows})
        self.assertEqual(ids(pool), ["C-ok"])


class OkCarfilter(unittest.TestCase):
    def v(self, name, price, dist=10, cat="자동차 / 승용차", sido="경기"):
        return carfilter.assess(name, cat, price, sido, dist)["verdict"]

    def test_ok_price_and_distance_boundaries(self):
        self.assertEqual(self.v("현대 쏘나타 1998cc", 2_999_999), "제외")
        self.assertEqual(self.v("현대 쏘나타 1998cc", 3_000_000), "확인")
        self.assertEqual(self.v("현대 쏘나타 1998cc", 4_999_999, dist=199), "확인")
        self.assertEqual(self.v("현대 쏘나타 1998cc", 4_999_999, dist=200), "제외")
        self.assertEqual(self.v("현대 쏘나타 1998cc", 5_000_000, dist=400), "확인")      # 500만 이상은 거리로 빼지 않는다
        self.assertEqual(self.v("현대 쏘나타 1998cc", 3_000_000, dist=None), "확인")      # 위치 불명은 빼지 않는다

    def test_ok_ev_battery_km(self):
        self.assertEqual(self.v("쏘울EV 75cc 199,999km", 6_000_000), "확인")
        self.assertEqual(self.v("쏘울EV 75cc 224,290km", 6_000_000), "제외")
        self.assertEqual(self.v("쏘나타 하이브리드 250,000km", 6_000_000), "제외")

    def test_ok_no_false_special_for_common_models(self):
        for nm, cat in (("현대 소형 화물 포터Ⅱ 2497cc", "자동차 / 화물차"), ("기아 소형 화물 봉고3 2497cc", "자동차 / 화물차"),
                        ("현대 그랜드스타렉스 12인승", "자동차 / 승합차"), ("기아 모하비 3.0 디젤 2959cc", "자동차 / SUV"),
                        ("기아 카니발 9인승", "자동차 / 승합차")):
            a = carfilter.assess(nm, cat, 5_000_000, "경기", 30)
            self.assertEqual(a["verdict"], "확인", nm)

    def test_ok_special_names_are_dropped(self):
        for nm in ("현대 에이엠5톤압축식진개차 6299cc", "엠블런스[구급차]", "이엔쓰리펌프소방차", "자일대우버스 BH090", "불용차량(진개덤프 8058) 폐차 조건부 매각"):
            self.assertEqual(self.v(nm, 8_000_000, cat="자동차 / 화물차"), "제외", nm)

    def test_ok_breakeven_formula(self):
        a = carfilter.assess("현대 쏘나타 1998cc", "자동차 / 승용차", 3_000_000, "경기", 30)
        clear = 3_000_000 * 1.31
        extra = clear * 0.07 + (60_000 + 30_000) + 150_000 + 50_000 + 0.10 * clear
        self.assertAlmostEqual(a["clear"], clear)
        self.assertAlmostEqual(a["extra"], extra)
        self.assertAlmostEqual(a["breakeven"], clear + extra)
        self.assertAlmostEqual(a["need_pct"], extra / clear * 100)
        self.assertEqual(carfilter.assess("x", "자동차", 5_000_000, "제주", 431)["tow"], 60_000 + 431_000 + 600_000)

    def test_ok_rate_bands(self):
        got = [carfilter.rate(p) for p in (0, 999_999, 1_000_000, 1_999_999, 2_000_000, 2_999_999, 3_000_000, 4_999_999, 5_000_000, 10_000_000)]
        self.assertEqual(got, [2.09, 2.09, 1.70, 1.70, 1.61, 1.61, 1.31, 1.31, 1.09, 1.09])

    def test_ok_light_car_no_tax_and_ev_relief(self):
        self.assertEqual(carfilter.assess("기아 모닝 998cc", "자동차 / 승용차", 5_000_000, "경기", 10)["tax"], 0)
        self.assertEqual(carfilter.assess("쏘울EV 75cc", "자동차 / SUV", 5_000_000, "경기", 10)["tax"], 0)   # 7%×5.45M=381,500 < 140만 감면


class OkGeo(unittest.TestCase):
    def test_ok_variants(self):
        d = lambda s: geo.dist_from_sanbon(s)
        self.assertEqual(d("경기도 군포시 산본동"), (0, "sgg"))
        self.assertEqual(d("경기도 고양시 덕양구 관산동")[1], "sgg")                 # 구가 있는 시
        self.assertEqual(d("경기도 화성시 만세구 장안면")[1], "sgg")
        self.assertEqual(d("세종특별자치시 한솔동")[1], "sido")                      # 세종은 시도 중심으로
        self.assertEqual(d("세종특별자치시 조치원읍")[1], "sgg")
        self.assertGreater(d("제주특별자치도 제주시 애월읍")[0], 400)
        self.assertEqual(d("전남광주통합특별시 북구 오룡동")[1], "sgg")             # 통합특별시
        self.assertEqual(d("강원특별자치도 춘천시 동면")[1], "sgg")
        self.assertEqual(d("경기도  군포시   산본동")[0], 0)                          # 공백 중복
        self.assertEqual(d(None), (None, None))
        self.assertEqual(d(""), (None, None))

    def test_ok_band_edges(self):
        self.assertEqual([geo.band_idx(x) for x in (0, 20, 21, 50, 51, 100, 101, 200, 201, None)], [0, 0, 1, 1, 2, 2, 3, 3, 4, 5])


class OkGradeAndFlags(unittest.TestCase):
    def g(self, **kw):
        return A.grade_A(item_A(**kw), TODAY)[0]

    def test_ok_grade_A_rules(self):
        self.assertEqual(self.g(), "낮음")                                                        # 공유자 없음
        co = lambda d: [["1", "공유자", "김**", d, "미표시"]]
        self.assertEqual(self.g(reg=co("2005-01-01"), reg_cnt=1), "낮음")                         # 전원 10년 이상
        self.assertEqual(self.g(reg=co("2020-01-01"), reg_cnt=1), "중간")
        self.assertEqual(self.g(reg=co("-"), reg_cnt=1), "중간")
        self.assertEqual(self.g(reg=[], reg_cnt=0), "중간")                                       # 정보 부족
        self.assertEqual(self.g(land_class="농지"), "높음")
        self.assertEqual(self.g(occ_cnt=1), "높음")
        self.assertEqual(self.g(lease_cnt=1), "높음")
        self.assertEqual(self.g(statement={"available": True, "keep": ["전세권"], "surface": []}), "높음")

    def test_ok_flags_D_core(self):
        dep = A.flags_D(item_D(lease=[["임차인", "황**", "135,000,000", "-", "-", "2022-05-23", "2022-06-07"]]))
        self.assertIn("R", [s for s, _ in dep])
        self.assertTrue(any("135,000,000" in m for _, m in dep))
        mv = A.flags_D(item_D(occ=[["전입세대주", "김**", "미상", "2017-11-13", "미상", "0", "0", "미상"]]))
        self.assertIn(("R", "전입세대 1명(명도·인수 확인)"), mv)
        self.assertIn(("Y", "공매재산명세서 미공개(입찰 임박 시 재확인)"), A.flags_D(item_D(statement={"available": False})))
        self.assertIn(("R", "등기: 전세권"), A.flags_D(item_D(reg=[["1", "전세권", "홍**", "2020-01-01", "0"]])))
        y = A.flags_D(item_D(notes=["- 본건 집합건축물대장상 위반건축물로 등재"]))
        self.assertIn(("Y", "위반건축물"), y)

    def test_ok_build_D_grade_mapping(self):
        r = A.build_D([{**item_D(notes=["위반건축물"]), "row": {"sidoSgkEmd": "경기도 군포시"}, "price": 1, "appraisal": 10, "schedule": []}], TODAY)[0]
        self.assertEqual(r["grade"], "중간")
        r = A.build_D([{**item_D(occ_cnt=0, lease_cnt=0), "statement": {"available": True}, "row": {"sidoSgkEmd": "경기도 군포시"}, "price": 1, "appraisal": 10, "schedule": []}], TODAY)[0]
        self.assertEqual(r["grade"], "낮음")

    def test_ok_grave_real_phrases_flagged(self):
        for t in ("본건 분묘 1기가 소재함.", "지상에 \"분묘\"가 소재하므로 분묘기지권 성립여부 등에 관하여 사전조사 후 입찰바람",
                  "필지 전체에 80여기가 넘는 분묘가 전체에 산재됨.", "지상에 소유자미상의 분묘 소재하오니 분묘기지권 성립여부 등"):
            self.assertIn(("Y", "분묘"), A.flags_D(item_D(notes=[t])), t)

    def test_ok_proposed_grave_regex_separates_real_and_generic(self):
        """제안 정규식이 실제 문구 4건은 잡고 일반 유의 문구 6건은 안 잡는지(수정안 검증용, 코드에는 아직 없음)."""
        new = r"분묘(?!기지권)(?![^.\n]{0,14}(?:가능성|여부|수\s*(?:도\s*)?있|확인))(?![^.\n]{0,6}없)"
        generic = ["- 본건 육안으로 확인되지 않은 분묘가 소재할 수 있으므로 사전조사 후 입찰바람.", "ㅇ 현황 맹지 및 자연림으로 미확인 분묘가 소재할 수 있사오니",
                   "- 본건 분묘 소재 여부 등 관련사항 사전조사 후 입찰바람", "ㅇ현황 자연림으로 지상에 \"분묘\"가 소재할 가능성이 있으므로 분묘기지권 성립여부 등에",
                   "- 본 건 정확한 지적관련 사항, 분묘소재여부, 경계 등의 확인이 필요한 경우에는", "파묘 및 평장 등 식별하기 곤란한 분묘가 소재할 수도 있어 분묘소재여부(분묘기지권 성립여부) 확인이 필요하므로"]
        real = ["본건 분묘 1기가 소재함.", "지상에 \"분묘\"가 소재하므로 분묘기지권 성립여부 등에 관하여 사전조사 후 입찰바람",
                "필지 전체에 80여기가 넘는 분묘가 전체에 산재됨.", "지상에 소유자미상의 분묘 소재하오니 분묘기지권 성립여부 등"]
        for t in generic:
            self.assertIsNone(re.search(new, t), t)
        for t in real:
            self.assertIsNotNone(re.search(new, t), t)

    def test_ok_share_ratio(self):
        self.assertAlmostEqual(A._share_ratio("지분(총면적 117㎡ 117분의84 지분)"), 84 / 117)
        self.assertAlmostEqual(A._share_ratio("지분(총면적 1,650㎡ 1650분의988.84 지분)"), 988.84 / 1650)
        self.assertAlmostEqual(A._share_ratio("지분(총면적 15,414㎡ 15414분의330 지분)"), 330 / 15414)
        self.assertIsNone(A._share_ratio("-"))
        self.assertIsNone(A._share_ratio(None))

    def test_ok_exit_numbers_formula(self):
        it = {"appraisal": 29_820_000, "price": 8_946_000, "round": "037",
              "schedule": [{"no": "036", "price": 9_000_000}, {"no": "037", "price": 8_946_000}, {"no": "038", "price": 5_964_000}]}
        e = A.exit_numbers(it)
        self.assertEqual(e["budget_cap"], int((10_000_000 - 50_000) / 1.046))
        self.assertEqual(e["exit_cap"], int((29_820_000 * 0.7 - 50_000 - 30_000 - 300_000) / 1.046))
        self.assertEqual(e["loss"], int(8_946_000 * 1.046 + 50_000 - 29_820_000 * 0.2))
        self.assertEqual(e["first_under"]["no"], "037")
        it2 = {"appraisal": 10_000_000, "price": 9_000_000, "round": "037", "schedule": [{"no": "037", "price": 9_000_000}, {"no": "038", "price": 5_964_000}]}
        self.assertEqual(A.exit_numbers(it2)["first_under"]["no"], "038")

    def test_ok_next_round(self):
        s = [{"no": "030"}, {"no": "031/003"}, {"no": "032"}]
        self.assertEqual(A.next_round(s, "031")["no"], "032")
        self.assertIsNone(A.next_round(s, "032"))
        self.assertIsNone(A.next_round([], "031"))

    def test_ok_sort_A_order(self):
        mk = lambda n, grade, dist, nat=False, cls="우선", price=1: {"mng": n, "grade": grade, "dist": dist, "dev": None, "natural_hint": nat, "land_class": cls, "price": price}
        items = [mk("hi-near", "높음", 5), mk("mid-far", "중간", 150), mk("low-b1", "낮음", 40), mk("mid-b0", "중간", 10),
                 mk("low-b1-nat", "낮음", 40, nat=True), mk("low-b1-cheap", "낮음", 40, price=0)]
        got = [x["mng"] for x in A.sort_A(items)]
        self.assertEqual(got, ["mid-b0", "low-b1-cheap", "low-b1", "low-b1-nat", "mid-far", "hi-near"])


# ═════════════════════════ 버그를 드러내는 시험(현재 실패) ═════════════════════════

class BugSelectionB(unittest.TestCase):
    def test_bug_select_B_keeps_generic_precious_metal_lot(self):
        """MVAST_EXCLUDE의 '금속'이 '귀금속 7개'(시계/귀금속 분류, 530만원)를 걸러 낸다."""
        row = mvast("2026-1000-055229", "귀금속 7개", "시계/귀금속 / 귀금속", 5_406_000, 5_406_000, org="청주상당경찰서",
                    sgg="충청북도 청주시 상당구 운동동", scrnPrptDvsnNm="기타일반재산")
        pool, st, hits = A.select_B({"rows": [row]})
        self.assertEqual(len(hits), 1)

    def test_bug_select_B_keyword_substring_false_positives(self):
        """\\d{2}K(re.I)가 33kW·100kg에, '렌즈'가 '프렌즈'에 걸린다."""
        rows = [mvast("kw", "삼성전자 냉난방기 AP-SG803H 냉방29/난방33kW", "사무/가구/가전 / 가전제품및디지털제품", 3_450_000),
                mvast("kg", "철제 선반 100kg 급", "사무/가구/가전 / 사무용가구", 300_000),
                mvast("lens", "(주)미스터리프렌즈 사무용 책상", "사무/가구/가전 / 사무용가구", 300_000)]
        pool, st, hits = A.select_B({"rows": rows})
        self.assertEqual(ids(hits), [])

    def test_bug_select_B_null_fields_no_crash(self):
        for kw in ({"ctgrFullNm": None}, {"regOrgNm": None}):
            row = mvast("n", "삼성 노트북", "컴퓨터/전기/통신기계 / 컴퓨터및주변기기", **kw)
            try:
                A.select_B({"rows": [row]})
            except Exception as e:                       # noqa: BLE001
                self.fail(f"{kw}: {type(e).__name__}: {e}")

    def test_bug_select_B_dedupe_key_too_coarse_for_custody_prefix(self):
        """KAMCO 동산은 이름 앞에 보관 주소가 붙어 name[:24]가 주소뿐이다. 같은 보관 장소·같은 가격의 서로 다른 귀금속이 하나로 묶인다."""
        pre = "대전광역시 대덕구 법동 282-1 대전지방국세청 보관 "
        rows = [mvast("g1", pre + "순금팔찌 1점", "시계/귀금속 / 귀금속", 567_000), mvast("g2", pre + "금반지 2점", "시계/귀금속 / 귀금속", 567_000)]
        pool, st, hits = A.select_B({"rows": rows})
        self.assertEqual(sorted(ids(hits)), ["g1", "g2"])


class BugSelectionCar(unittest.TestCase):
    def test_bug_select_C_zero_price_no_crash(self):
        """최저가 0(결측)이면 assess의 need_pct 계산이 0으로 나눠 루틴 전체가 죽는다."""
        for p in (0, None):
            try:
                A.select_C({"rows": [car("z", "현대 쏘나타 1998cc", p)]})
            except ZeroDivisionError as e:
                self.fail(f"price={p!r}: ZeroDivisionError: {e}")

    def test_bug_assess_ev_names_not_recognised(self):
        """스파크EV·니로EV·아이오닉5·EV6는 EV로 안 읽혀 20만km 배터리 제외가 새고 취득세 감면도 못 받는다."""
        for nm in ("쉐보레 스파크EV", "기아 니로EV", "현대 아이오닉5", "기아 EV6"):
            a = carfilter.assess(nm + " 224,290km", "자동차 / SUV", 6_000_000, "경기", 10)
            self.assertEqual(a["verdict"], "제외", nm)

    def test_bug_select_C_uses_row_fuel_and_km_fields(self):
        """README 4번(20만km 넘는 EV·하이브리드 제외)이 물건명에 km가 있을 때만 작동한다. 행의 drvDstcNm·연료 필드를 안 쓴다."""
        ev = car("ev", "[공매]쉐보레 스파크EV(41무7932) 춘천", 5_500_000, carFuelKindCd="전기", drvDstcNm="230,000km", fuelContDsvlmNm="-")
        hy = car("hy", "기아 니로 1580cc", 5_500_000, carFuelKindCd=None, fuelContDsvlmNm="휘발유+전기 1,580cc", drvDstcNm="250,000km")
        pool, st, cars = A.select_C({"rows": [ev, hy]})
        self.assertEqual(ids(pool), [])

    def test_bug_car_fuel_gasoline_electric_is_hybrid(self):
        """온비드 표기 '휘발유+전기'가 FUELS의 '휘발유'에 먼저 걸려 하이브리드가 휘발유로 나온다(실제 2건)."""
        self.assertEqual(A.car_fuel({"fuelContDsvlmNm": "휘발유+전기 1,580cc"}), "하이브리드")

    def test_bug_car_year_must_not_come_from_displacement(self):
        """연식 필드가 없으면 물건명에서 4자리 수를 찾는데 '1998cc'가 1998년으로 읽혀 경유 조기폐차 가점(+6)이 붙는다."""
        self.assertIsNone(A.car_year({"nrtpNm": None, "onbidCltrNm": "쌍용 코란도 디젤 1998cc"}))
        v = {"row": {"nrtpNm": None, "carFuelKindCd": "디젤", "onbidCltrNm": "쌍용 코란도 디젤 1998cc", "lowstBidPrc": 5_000_000, "ctgrFullNm": "자동차 / SUV"}}
        self.assertEqual(A._car_prescore(v), 0)

    def test_bug_assess_cargo_category_beats_model_name(self):
        """화물차 분류의 코란도스포츠가 PASSENGER 정규식 때문에 승용(취득세 7%)으로 계산된다. 화물은 5%."""
        a = carfilter.assess("쌍용 코란도스포츠 2157cc", "자동차 / 화물차", 4_400_000, "경기", 20)
        self.assertEqual(a["kind"], "기타")
        self.assertAlmostEqual(a["tax"], a["clear"] * 0.05)

    def test_bug_assess_km_unit_case_insensitive(self):
        """실제 물건명에 '139,534Km'(대문자 K) 표기가 있다. _km 정규식은 소문자 k만 받는다."""
        a = carfilter.assess("불용 쏘나타 하이브리드 250,000Km", "자동차 / 승용차", 6_000_000, "경기", 10)
        self.assertEqual(a["verdict"], "제외")


class BugSelectionLandD(unittest.TestCase):
    base = dict(alc="N")

    def test_bug_select_D_farmland_swallows_nonfarm_with_same_key(self):
        farm = rlst("D-farm", "경기도 화성시 만세구 장안면 사곡리 375-16", "토지 / 전", 3_000_000, sgg="경기도 화성시 만세구 장안면", **self.base)
        wood = rlst("D-wood", "경기도 화성시 만세구 장안면 사곡리 375-17", "토지 / 임야", 3_000_000, sgg="경기도 화성시 만세구 장안면", **self.base)
        pool, st = A.select_D({"rows": [farm, wood]})
        self.assertEqual(ids(pool), ["D-wood"])

    def test_bug_select_D_distinct_parcels_not_merged(self):
        """묶음 키가 이름 앞 22자라 '…사곡리 37'에서 끊겨 서로 다른 필지(375-16, 379-1)가 한 건이 된다."""
        a = rlst("P1", "경기도 화성시 만세구 장안면 사곡리 375-16", "토지 / 임야", 3_000_000, sgg="경기도 화성시 만세구 장안면", **self.base)
        b = rlst("P2", "경기도 화성시 만세구 장안면 사곡리 379-1", "토지 / 임야", 3_000_000, sgg="경기도 화성시 만세구 장안면", **self.base)
        pool, st = A.select_D({"rows": [a, b]})
        self.assertEqual(sorted(ids(pool)), ["P1", "P2"])

    def test_bug_dedupe_tie_must_not_depend_on_input_order(self):
        """같은 입찰 시작 시각의 여러 회차(파산재단)는 입력 순서로 대표가 바뀐다. 회차 번호로 정해야 한다."""
        rows = [{"scrnIndctCltrMngNo": "P", "pbctBegnDtm": "2026-10-07 12:00", "pbctNsq": str(i), "lowstBidPrc": p}
                for i, p in ((1, 5_000_000), (2, 3_000_000), (3, 1_000_000))]
        self.assertEqual(A.dedupe(rows)["P"]["row"]["lowstBidPrc"], A.dedupe(rows[::-1])["P"]["row"]["lowstBidPrc"])

    def test_bug_selectors_enforce_price_cap(self):
        """1,000만원 상한은 서버 검색 조건에만 의존한다. 선별 함수는 상한을 확인하지 않는다."""
        big = rlst("A9", "경기도 군포시 산본동 1-1", "토지 / 임야", 50_000_000)
        self.assertEqual(ids(A.select_A({"rows": [big]})[0]), [])
        self.assertEqual(ids(A.select_D({"rows": [{**big, "alcYn": "N"}]})[0]), [])
        self.assertEqual(ids(A.select_C({"rows": [car("C9", "현대 쏘나타 1998cc", 50_000_000)]})[0]), [])
        self.assertEqual(ids(A.select_B({"rows": [mvast("B9", "롤렉스 시계", "시계/귀금속 / 시계", 50_000_000, 60_000_000)]})[0]), [])

    def test_bug_dist_falls_back_to_name_when_sido_is_dash(self):
        """sidoSgkEmd가 '-'인 부동산 행은 이름에 주소가 있어도 위치 불명(구간 5)이 되어 맨 뒤로 간다."""
        row = rlst("dash", "경기도 군포시 산본동 1-1", "토지 / 임야", 1_000_000, sgg="-")
        self.assertEqual(A._dist(row), 0)


class BugFlags(unittest.TestCase):
    def test_bug_flags_D_gadeunggi_registry_label(self):
        """등기 구분이 실제로는 '가등기(순위보전)'인데 정확 일치 목록에 '가등기'만 있어 🔴이 안 붙는다."""
        fl = A.flags_D(item_D(reg=[["1", "가등기(순위보전)", "홍**", "2020-01-01", "미표시"]]))
        self.assertIn("R", [s for s, _ in fl])

    def test_bug_flags_D_imchakgwon_registry_label(self):
        """등기 구분이 실제로는 '임차권'(코드는 '임차권등기')이라 매칭되지 않는다."""
        fl = A.flags_D(item_D(reg=[["1", "임차권", "한**", "2023-12-13", "0"]]))
        self.assertIn("R", [s for s, _ in fl])

    def test_bug_flags_D_jeonip_in_lease_table_only(self):
        """2024-05180-001 실제 형태: lease 행 유형이 '전입세대주', occ 행 첫 칸이 '-'. 전입세대로 안 세어 🔴이 빠진다."""
        it = item_D(lease=[["전입세대주", "이**", "-", "-", "-", "-", "2020-10-12"]],
                    occ=[["-", "이**", "미상", "2020-10-12", "미상", "0", "0", "미상"]], occ_cnt=1, lease_cnt=1,
                    statement={"available": False})
        self.assertIn("R", [s for s, _ in A.flags_D(it)])

    def test_bug_deposits_include_imchakgwon_rows(self):
        """임차권 행(보증금 1.3억)은 _deposits에서 빠져 deposit_sum이 0, '임차인 신고(보증금 합계…)' 줄이 안 나온다."""
        lease = [["임차권", "한**", "130,000,000", "-", "-", "2023-12-13", "2024-01-29"]]
        self.assertEqual(A._deposits({"lease": lease}), [130_000_000])

    def test_bug_deposits_must_not_take_monthly_rent(self):
        """r[2:4]를 훑어 보증금이 '-'/0이면 차임(월세) 칸 숫자를 보증금으로 센다."""
        lease = [["임차인", "김**", "-", "500,000", "-", "2020-01-01", "2020-01-02"]]
        self.assertEqual(A._deposits({"lease": lease}), [])

    def test_bug_grave_generic_phrases_not_real_grave(self):
        """'분묘 소재 여부 확인', '미확인 분묘가 소재할 수 있사오니', '분묘기지권 성립여부'가 실제 분묘(Y, 입찰 비권장 ⛔)로 잡힌다."""
        generic = ["- 본건 육안으로 확인되지 않은 분묘가 소재할 수 있으므로 사전조사 후 입찰바람.", "ㅇ 현황 맹지 및 자연림으로 미확인 분묘가 소재할 수 있사오니 사전조사 후 입찰바람.",
                   "- 본건 분묘 소재 여부 등 관련사항 사전조사 후 입찰바람",
                   "ㅇ현황 자연림으로 지상에 \"분묘\"가 소재할 가능성이 있으므로 분묘기지권 성립여부 등에 관하여는 매수신청인의 책임하에 사전 현장조사 후 입찰바람",
                   "- 본 건 정확한 지적관련 사항, 분묘소재여부, 경계 등의 확인이 필요한 경우에는 측량등을 통한 재확인이 필요하므로",
                   "파묘 및 평장 등 식별하기 곤란한 분묘가 소재할 수도 있어 분묘소재여부(분묘기지권 성립여부) 확인이 필요하므로"]
        bad = []
        for t in generic:
            d_real = ("Y", "분묘") in A.flags_D(item_D(notes=[t]))
            it = {"grade": "중간", "notes": [t], "media": None}
            A.apply_appraisal(it, "A")
            if d_real or re.search(A.GRAVE_REAL, t):          # bad_exit는 같은 줄의 '맹지'로도 켜지므로 분묘 정규식만 따로 본다
                bad.append(t[:30])
        self.assertEqual(bad, [])

    def test_bug_flags_D_yuchigwon_boilerplate_is_not_a_claim(self):
        """'유치권 기타 소유권 제한 권리 존부 등을 확인 후 입찰바람'(일반 유의)이 🔴 '유치권 신고'가 된다."""
        t = "물건에 따라 벽체 구분 없이 인접호와 일체로 이용가능한 호수가 존재하므로, 내부 상태, 유치권 기타 소유권 제한 권리 존부 등을 확인 후 입찰바람"
        self.assertNotIn(("R", "유치권 신고"), A.flags_D(item_D(notes=[t])))


class BugGrade(unittest.TestCase):
    def test_bug_grade_A_surviving_jisangkwon_is_high(self):
        """등기에 지상권, 유의사항에 '공매로 말소되지 않는 지상권이 존재'인데 명세서 keep/surface가 비면 중간으로 나온다(실제 2026-07029-002, 2026-10778-001).
        같은 물건이 flags_D에서는 🔴(등기: 지상권)이다."""
        reg = [["1", "위임기관", "경******", "2025-04-14", "미표시"], ["2", "지상권", "한*****", "2009-05-27", "0"], ["5", "공유자", "한**", "-", "미표시"]]
        it = item_A(reg=reg, reg_cnt=3, notes=["- 공매로 말소되지 않는 지상권이 존재하오니 사전조사 후 입찰바람"])
        self.assertEqual(A.grade_A(it, TODAY)[0], "높음")


if __name__ == "__main__":
    unittest.main(verbosity=2)
