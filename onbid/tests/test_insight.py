"""예상 낙찰가·판정 근거·낙찰 이유 추정(onbid/insight.py)."""
import unittest

from onbid import insight, report, track


def land_item(**kw):
    it = {"mng": "2026-00001-001", "name": "경기도 남양주시 화도읍 마석우리 산7-38", "price": 4_000_000, "appraisal": 10_000_000,
          "round": "040", "fails": "6회", "land_class": "우선", "row": {"ctgrFullNm": "토지 / 임야"},
          "basis": {"공유자수": 2, "인수권리": [], "지상권개요": [], "존속권리": [], "점유": 0, "임대차": 0},
          "schedule": [{"no": "040", "start": "2026-11-09 10:00", "price": 4_000_000},
                       {"no": "041", "start": "2026-11-16 10:00", "price": 3_000_000}]}
    it.update(kw)
    return it


def res_row(name, low, bid, status="낙찰", bidders=1, appr=None, cat="토지 / 임야", mng="X"):
    return {"onbidCltrNm": name, "lowstBidPrc": low, "onbidBidAmt": bid, "pbctStatNm": status, "totalBid": bidders,
            "cltrApslEvlAvgAmt": appr, "ctgrFullNm": cat, "scrnIndctCltrMngNo": mng, "pbctExctDt": "2026-10-29 11:00",
            "rateRow1": round(bid / low * 100, 2) if bid and low else "0"}


class RegionKey(unittest.TestCase):
    def test_two_tokens(self):
        self.assertEqual(insight.region_key({"name": "경기도 남양주시 화도읍 마석우리 산7-38"}), "경기도 남양주시")
        self.assertEqual(insight.region_key({"name": "서울특별시 성북구 종암동 3-1260"}), "서울특별시 성북구")

    def test_unknown(self):
        self.assertIsNone(insight.region_key({"name": "[불용차량 매각] 현대"}))
        self.assertIsNone(insight.region_key({}))


class LocalComps(unittest.TestCase):
    def test_filters_kind_window_and_self(self):
        it = land_item()
        rows = [res_row("a", 3_000_000, 3_100_000, appr=9_000_000), res_row("b", 5_000_000, 5_500_000, bidders=3),
                res_row("c", 4_000_000, 4_040_000), res_row("d", 4_000_000, None, status="유찰"),
                res_row("건물", 4_000_000, 9_000_000, cat="주거용건물 / 다세대주택"),       # 건물 — 토지 물건과 비교 안 함
                res_row("너무 비쌈", 90_000_000, 95_000_000),                              # 가격대 밖
                res_row("자기", 4_000_000, 4_100_000, mng=it["mng"])]                      # 자기 자신
        s = insight.rlst_comps(rows, it)
        self.assertEqual((s["n_sold"], s["n_unsold"]), (3, 1))
        self.assertEqual(s["solo"], 2)
        self.assertAlmostEqual(s["rate_q"][1], 103.33, places=1)

    def test_failed(self):
        self.assertTrue(insight.rlst_comps(None, land_item())["failed"])


class Expect(unittest.TestCase):
    def test_local_first_then_hist(self):
        it = land_item()
        loc = {"n_sold": 4, "rate_q": (100.0, 105.0, 110.0)}
        ex = insight.expect(it, loc, {"n": 9, "rate_q": (100.0, 101.0, 108.0)})
        self.assertEqual((ex["src"], ex["mid"], ex["lo"], ex["hi"]), ("local", 4_200_000, 4_000_000, 4_400_000))
        ex = insight.expect(it, {"failed": True}, {"n": 9, "rate_q": (100.0, 101.0, 108.0)})
        self.assertEqual((ex["src"], ex["mid"], ex["n"]), ("hist", 4_040_000, 9))
        self.assertIsNone(insight.expect(it, None, {"n": 1, "rate_q": None}))


class VerdictLand(unittest.TestCase):
    def test_bad_exit_stops_but_keeps_numbers(self):
        it = land_item(bad_exit=True)
        v = insight.build("A", it, None, {"n": 9, "rate_q": (100.0, 101.0, 108.0), "n_bidders": 9, "solo": 8})
        self.assertTrue(v["call"].startswith("⛔"))
        txt = " ".join(t for _, t in v["reasons"])
        self.assertIn("예상 낙찰가 4,040,000원", txt)        # 비권고여도 예상 낙찰가와 근거는 낸다
        self.assertIn("필요한 매도가", txt)
        self.assertIn("응찰 1명", txt)

    def test_expected_over_cap_stops(self):
        it = land_item(appraisal=6_000_000)                   # 출구 상한 = (420만 − 38만) ÷ 1.046 ≈ 365만
        v = insight.build("A", it, None, {"n": 9, "rate_q": (100.0, 101.0, 108.0)})
        self.assertTrue(v["call"].startswith("⛔"))
        self.assertTrue(any("출구 상한" in t for s, t in v["reasons"] if s == "⛔"))

    def test_wait_for_round(self):
        it = land_item(appraisal=5_500_000)                   # 상한 ≈ 331만 → 041회 300만부터
        v = insight.build("A", it, None, None)
        self.assertTrue(v["call"].startswith("⏳"), v["call"])
        self.assertIn("041회", v["call"])

    def test_conditional(self):
        v = insight.build("A", land_item(), None, None)
        self.assertTrue(v["call"].startswith("🔍"), v["call"])
        self.assertTrue(any("공유자" in u for u in v["unlock"]))

    def test_d_red_flag(self):
        it = land_item(risk_flags=[("R", "건물만 매각(대지는 제3자 소유)"), ("Y", "관리비 체납 확인 필요")])
        v = insight.build("D", it, None, None)
        self.assertTrue(v["call"].startswith("⛔"))
        self.assertIn("건물만 매각(대지는 제3자 소유)", v["stop"])

    def test_lines_render(self):
        it = land_item()
        it["insight"] = insight.build("A", it, {"n_sold": 3, "n_unsold": 3, "rate_q": (100.0, 102.0, 104.0), "kind": "토지", "solo": 3,
                                                "n_bidders": 3, "examples": [{"date": "2026-10-29", "name": "x", "lowest": 1, "bid": 2, "appr": 4, "bidders": 1}]}, None)
        L = insight.lines(it)
        self.assertTrue(L[0].startswith("- 🧭 판정"))
        self.assertTrue(any("같은 시·군 최근 낙찰" in x for x in L))
        self.assertTrue(any("개찰 6회 중 낙찰 3회" in x for x in L))


class VerdictCar(unittest.TestCase):
    def test_breakeven_from_comps(self):
        it = {"price": 2_000_000, "assess": {"clear": 3_220_000, "tax": 225_400, "extra": 1_000_000, "breakeven": 4_220_000},
              "comps": {"n_sold": 5, "n_rates": 5, "median_rate": 160.0,
                        "examples": [{"rate": r, "bidders": b} for r, b in ((150, 6), (155, 8), (160, 1), (170, 9), (180, 12))]},
              "flags": [], "notes": []}
        v = insight.build("C", it)
        self.assertEqual(v["exp"]["mid"], 3_200_000)
        self.assertTrue(v["call"].startswith("🔍"))
        self.assertTrue(any("경쟁" in t or "업자" in t for _, t in v["reasons"]))

    def test_not_running_stops(self):
        v = insight.build("C", {"price": 1_000_000, "assess": {}, "comps": {}, "flags": [], "notes": ["엔진 고장으로 운행 불가"]})
        self.assertTrue(v["call"].startswith("⛔"))


class Explain(unittest.TestCase):
    def test_solo_land_near_min_cheap(self):
        why = insight.explain({"track": "A", "status": "낙찰", "bid": 958_000, "lowest": 958_000, "rate": "100", "bidders": 1,
                               "appraisal": 4_788_333}, {"co": 3, "fails": 6, "exit_cap": 2_840_000, "exp": 970_000})
        txt = " / ".join(why)
        self.assertIn("단독 응찰", txt)
        self.assertIn("감정가의 20%", txt)
        self.assertIn("지분 매입업체", txt)
        self.assertIn("공유자 3명", txt)
        self.assertIn("상한 이하", txt)
        self.assertIn("예측의 99%", txt)

    def test_competitive_land(self):
        why = insight.explain({"track": "D", "status": "낙찰", "bid": 9_500_000, "lowest": 7_056_000, "rate": "134.64", "bidders": 2,
                               "appraisal": 8_820_000})
        self.assertIn("2명 경쟁", why[0])
        self.assertIn("감정가의 108%", why[1])

    def test_car_solo_high(self):
        why = insight.explain({"track": "C", "status": "낙찰", "bid": 7_100_000, "lowest": 4_400_000, "rate": "161.36", "bidders": 1})
        self.assertIn("단독 응찰인데", why[0])

    def test_unsold_and_movable_skipped(self):
        why = insight.explain({"track": "A", "status": "유찰", "bid": None, "lowest": 9_998_000, "bidders": 0, "appraisal": 19_994_310})
        self.assertIn("감정가의 50%", why[0])
        self.assertEqual(insight.explain({"track": "B", "status": "낙찰", "bid": 1, "lowest": 1}), [])


class Lessons(unittest.TestCase):
    def test_lessons_and_snapshot_roundtrip(self):
        st = {"items": {}, "history": []}
        it = land_item(dist=30)
        it["insight"] = insight.build("A", it, None, None)
        track.add_candidates(st, "2026-11-06", {"A": [it]})
        self.assertEqual(st["items"][it["mng"]]["feat"]["co"], 2)
        track.apply_results(st, {it["mng"]: [{"pbctStatNm": "낙찰", "pbctNsq": "040", "pbctExctDt": "2026-11-12 11:00",
                                               "lowstBidPrc": "4,000,000", "onbidBidAmt": "4,100,000", "rateRow1": "102.5",
                                               "totalBid": "1"}]}, "2026-11-13")
        h = st["history"][-1]
        self.assertEqual(h["feat"]["co"], 2)
        L = insight.lessons(st)
        self.assertTrue(L and L[0].startswith("지분(A) 낙찰 1건"))
        sec = report.tracking_section({"queried": True, "changed": [{"mng": it["mng"], "track": "A", "name": "x", "link": "l",
                                                                      "reported": True, "feat": h["feat"], **st["items"][it["mng"]]["result"],
                                                                      "appraisal": 10_000_000}], "lessons": L})
        self.assertTrue(any("🔎 왜 이 값에 팔렸나" in x for x in sec))
        self.assertTrue(any("누적 낙찰 기준선" in x for x in sec))

    def test_movable_not_snapshotted(self):
        st = {"items": {}, "history": []}
        track.add_candidates(st, "2026-11-06", {"B": [{"mng": "B1", "name": "금반지"}]})
        self.assertNotIn("feat", st["items"]["B1"])


if __name__ == "__main__":
    unittest.main()
