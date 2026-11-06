"""감정평가서 토지이용계획 추출(onbid/landuse.py) 시험. 실행: python3 -m unittest onbid.tests.test_landuse"""
import os
import tempfile
import unittest

from onbid import landuse

SAMPLE = """\
  4. 이용상황                    5. 접면도로상황            6. 토지이용계획사항 등
  7. 제시목록외의 물건          8. 공부와의 차이           9. 기타

      6. 토지이용계획사항 등

         도시지역, 제1종일반주거지역(앞술막), 지구단위계획구역(앞술막), 소로2류(폭 8m~10m)(
         국지도로)(저촉), 가축사육제한구역<가축분뇨의 관리 및 이용에 관한 법률>,
         토지거래계약에관한허가구역(지정기간:25.8.26~26.8.25.)임.

      7. 제시목록외의 물건     해당사항 없음.
5. 기준시점
 본건의 기준시점은 가격조사 완료일인 2026년 7월 16일로 하였다.
"""


class T(unittest.TestCase):
    def _p(self, text):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "appraisal.txt")
        open(p, "w", encoding="utf-8").write(text)
        return p

    def test_extracts_zone_and_marks(self):
        i = landuse.parse_landuse(self._p(SAMPLE))
        self.assertEqual(i["zone"], "제1종일반주거지역")
        names = [n for _, n in i["marks"]]
        self.assertIn("지구단위계획구역", names)
        self.assertIn("도로 등 도시계획시설 저촉", names)
        self.assertTrue(any(n.startswith("토지거래허가구역") for n in names))
        self.assertNotIn("제시목록외", i["raw"])          # 목차·다음 항목은 섞이지 않는다

    def test_missing_returns_none_and_says_so(self):
        self.assertIsNone(landuse.parse_landuse(self._p("관련 없는 본문\n")))
        self.assertIsNone(landuse.parse_landuse("/nonexistent/appraisal.txt"))
        self.assertIn("찾지 못함", landuse.landuse_lines(None)[0])

    def test_lines_do_not_invent_when_no_designation(self):
        i = landuse.parse_landuse(self._p("6. 토지이용계획사항 등\n  보전관리지역, 가축사육제한구역\n7. 제시목록외의 물건\n"))
        self.assertIn("지정은 이 항목에 없음", "\n".join(landuse.landuse_lines(i)))


if __name__ == "__main__":
    unittest.main()
