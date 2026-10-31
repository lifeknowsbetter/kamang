"""sel 영역 검증용 단위시험. ONBID_ROOT 로 시험할 트리를 고른다(기본 /home/user/kamang, 패치본은 .../sel_verify/pkg).
test_ok_* 는 현재 코드에서 통과해야 하고, test_bug_* 는 현재 코드에서 실패(버그 재현), 패치본에서는 통과해야 한다."""
import os as _os
REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
FIXTURES = _os.environ.get("ONBID_FIXTURES", "/nonexistent-onbid-fixtures")
FIXTURES_PARENT = _os.path.dirname(FIXTURES)
import datetime, os, re, sys, unittest
ROOT = os.environ.get('ONBID_ROOT', '/home/user/kamang')
sys.path.insert(0, ROOT)
from onbid import analyze as A, carfilter, config as C, geo

TODAY = datetime.date(2026, 10, 18)


def brow(i, nm, cat='시계/귀금속 / 귀금속', price=567000, org='a', sgg='대전광역시 대덕구', appr=0):
    return {'scrnIndctCltrMngNo': i, 'pbctBegnDtm': 'x', 'onbidCltrNm': nm, 'ctgrFullNm': cat, 'lowstBidPrc': price,
            'cltrApslEvlAvgAmt': appr, 'regOrgNm': org, 'sidoSgkEmd': sgg}


def crow(i='c', nm='현대 쏘나타 1998cc', cat='자동차 / 승용차', price=5500000, **kw):
    r = {'scrnIndctCltrMngNo': i, 'pbctBegnDtm': '2026-10-20 10:00', 'onbidCltrNm': nm, 'ctgrFullNm': cat, 'lowstBidPrc': price,
         'sidoSgkEmd': '경기도 군포시 산본동', 'sidoEmd': '경기', 'nrtpNm': '2015', 'carFuelKindCd': '가솔린'}
    r.update(kw)
    return r


def drow(i, nm, cat, price=3000000):
    return {'scrnIndctCltrMngNo': i, 'pbctBegnDtm': '2026-10-20 10:00', 'lowstBidPrc': price, 'alcYn': 'N', 'scrnPrptDvsnNm': '압류재산',
            'sidoSgkEmd': '경기도 화성시 만세구 장안면', 'onbidCltrNm': nm, 'ctgrFullNm': cat}


BASE_D = {'kv': {}, 'notes': [], 'occ': [], 'lease': [], 'reg': [], 'statement': {'available': True}}


class Ok(unittest.TestCase):
    def test_ok_car_cap_boundaries(self):
        self.assertEqual(carfilter.assess('쏘나타 1998cc', '자동차 / 승용차', 2999999, '경기', 10)['verdict'], '제외')
        self.assertEqual(carfilter.assess('쏘나타 1998cc', '자동차 / 승용차', 3000000, '경기', 10)['verdict'], '확인')
        self.assertEqual(carfilter.assess('쏘나타 1998cc', '자동차 / 승용차', 4999999, '경기', 200)['verdict'], '제외')
        self.assertEqual(carfilter.assess('쏘나타 1998cc', '자동차 / 승용차', 5000000, '경기', 400)['verdict'], '확인')

    def test_ok_breakeven_example(self):
        a = carfilter.assess('쏘나타 1998cc', '자동차 / 승용차', 3000000, '경기', 30)
        self.assertEqual(round(a['extra']), 958100)
        self.assertEqual(round(a['need_pct'], 1), 24.4)

    def test_ok_real_grave_still_real(self):
        for t in ['분묘 1기가 소재함', '지상에 "분묘"가 소재하므로 분묘기지권 성립여부 등에 관하여 사전조사 후 입찰바람',
                  '소유자미상의 분묘 소재하오니 분묘기지권 성립여부 등', '필지 전체에 80여기가 넘는 분묘가 전체에 산재됨', '자연림 및 분묘가 소재함']:
            self.assertTrue(re.search(A.GRAVE_REAL, t), t)

    def test_ok_grade_A_plain_cases(self):
        reg = [['1', '위임기관', '구', '2021-06-10', '미표시'], ['2', '공유자', '임**', '2015-05-12', '0']]
        it = {'land_class': '우선', 'kv': {}, 'notes': [], 'reg': reg, 'reg_cnt': 2, 'occ_cnt': 0, 'lease_cnt': 0,
              'statement': {'available': True, 'keep': [], 'surface': [], 'note': [], 'occupancy_rows': [], 'lease_rows': []}}
        self.assertEqual(A.grade_A(it, TODAY)[0], '낮음')                      # 공유자 전원 10년 경과
        it2 = {**it, 'reg': [['1', '근저당권', '시', '2012-03-08', '1'], ['2', '공유자', '임**', '2024-05-12', '0']], 'reg_cnt': 2}
        self.assertEqual(A.grade_A(it2, TODAY)[0], '중간')                     # 근저당은 소멸 — 등급에 안 씀

    def test_ok_dist_band(self):
        self.assertEqual(geo.band_idx(None), 5)
        self.assertEqual(A._dist({'sidoSgkEmd': '경기도 군포시 산본동'}), 0)

    def test_ok_select_B_keeps_gold_ring(self):
        d, st, hits = A.select_B({'rows': [brow('g', '순금반지 3돈', price=900000)]})
        self.assertEqual(len(hits), 1)


class Bug(unittest.TestCase):
    def test_bug_sel1_precious_metal(self):
        d, st, hits = A.select_B({'rows': [brow('b1', '귀금속 7개', price=5406000, org='청주상당경찰서', appr=5406000, sgg='충청북도 청주시 상당구')]})
        self.assertEqual(len(hits), 1)

    def test_bug_sel2_generic_grave(self):
        generic = ['- 본건 분묘 소재 여부 등 관련사항 사전조사 후 입찰바람', 'ㅇ 현황 자연림으로 미확인 분묘가 소재할 수 있사오니 사전조사 후 입찰바람.',
                   '- 본 건 정확한 지적관련 사항, 분묘소재여부, 경계 등의 확인이 필요한 경우', '분묘가 소재할 수도 있어 확인이 필요',
                   '- 본건 현황 자연림이며 우거진 입목 등으로 인해 분묘확인이 용이하지 않은 바 분묘소재여부(분묘기지권 성립여부)',
                   '지상에 "분묘"가 소재할 가능성이 있으므로 분묘기지권 성립여부 등에 관하여 사전조사']
        for t in generic:
            self.assertFalse(re.search(A.GRAVE_REAL, t), t)
            it = {'grade': '중간', 'notes': [t], 'media': None}
            A.apply_appraisal(it, 'A')
            self.assertFalse(it['bad_exit'], t)
            self.assertFalse(any(m == '분묘' for s, m in A.flags_D({**BASE_D, 'notes': [t]})), t)

    def test_bug_sel3_surviving_easement(self):
        reg = [['1', '위임기관', '경', '2025-04-14', '미표시'], ['2', '지상권', '한', '2009-05-27', '0'], ['5', '공유자', '한**', '-', '미표시']]
        it = {'land_class': '우선', 'kv': {}, 'notes': ['- 공매로 말소되지 않는 지상권이 존재하오니 사전조사 후 입찰바람'], 'reg': reg, 'reg_cnt': 3, 'occ_cnt': 0, 'lease_cnt': 0,
              'statement': {'available': True, 'keep': [], 'surface': [], 'note': [], 'occupancy_rows': [], 'lease_rows': []}}
        self.assertEqual(A.grade_A(it, TODAY)[0], '높음')

    def test_bug_sel4_jeonip_in_lease_only(self):
        it = {**BASE_D, 'statement': {'available': False}, 'occ_cnt': 1, 'lease_cnt': 1,
              'lease': [['전입세대주', '이**', '-', '-', '-', '-', '2020-10-12']], 'occ': [['-', '이**', '미상', '2020-10-12', '미상', '0', '0', '미상']]}
        self.assertIn('R', [s for s, m in A.flags_D(it)])

    def test_ok_sel4_no_double_count(self):
        it = {**BASE_D, 'occ': [['전입세대주', '황**', '미상', '2022-06-07', '미상', '0', '0', '미상']],
              'lease': [['전입세대주', '황**', '-', '-', '-', '-', '2022-06-07']]}
        self.assertIn(('R', '전입세대 1명(명도·인수 확인)'), A.flags_D(it))

    def test_bug_sel5_registry_labels(self):
        for lab in ('가등기(순위보전)', '임차권'):
            fl = A.flags_D({**BASE_D, 'reg': [['1', lab, '홍**', '2020-01-01', '미표시']]})
            self.assertIn('R', [s for s, m in fl], lab)

    def test_bug_sel6_zero_price_car(self):
        for p in (0, None):
            A.select_C({'rows': [crow(price=p)]})

    def test_bug_sel7_ev_fields(self):
        ev = crow('x', '[공매]쉐보레 스파크EV(41무7932) 춘천', carFuelKindCd='전기', drvDstcNm='230,000km', fuelContDsvlmNm='-')
        hy = crow('y', '기아 니로 1580cc', carFuelKindCd=None, fuelContDsvlmNm='휘발유+전기 1,580cc', drvDstcNm='250,000km')
        d, st, c = A.select_C({'rows': [ev, hy]})
        self.assertEqual([v['row']['scrnIndctCltrMngNo'] for v in d], [])
        self.assertEqual(carfilter.assess('한국전기안전공사 업무용 쏘나타 1999cc', '자동차 / 승용차', 5000000, '경기', 30)['tax'] > 0, True)

    def test_bug_sel8_hybrid_fuel(self):
        self.assertEqual(A.car_fuel({'fuelContDsvlmNm': '휘발유+전기 1,580cc'}), '하이브리드')
        self.assertEqual(A.car_fuel({'fuelContDsvlmNm': '경유+전기'}), '하이브리드')
        self.assertEqual(A.car_fuel({'carFuelKindCd': '디젤'}), '경유')

    def test_bug_sel9_cargo_kind(self):
        a = carfilter.assess('쌍용 코란도스포츠 2157cc', '자동차 / 화물차', 4400000, '경기', 20)
        self.assertAlmostEqual(a['tax'], a['clear'] * 0.05, places=3)

    def test_bug_sel10_year_from_displacement(self):
        self.assertIsNone(A.car_year({'nrtpNm': None, 'onbidCltrNm': '쌍용 코란도 디젤 1998cc'}))
        self.assertEqual(A.car_year({'nrtpNm': None, 'onbidCltrNm': '불용 2018년 쏘나타'}), 2018)

    def test_bug_sel11_select_D(self):
        farm = drow('D-farm', '경기도 화성시 만세구 장안면 사곡리 375-16', '토지 / 전')
        wood = drow('D-wood', '경기도 화성시 만세구 장안면 사곡리 375-17', '토지 / 임야')
        for rows in ([farm, wood], [wood, farm]):
            d, st = A.select_D({'rows': rows})
            self.assertEqual([v['row']['scrnIndctCltrMngNo'] for v in d], ['D-wood'])
        p1 = drow('P1', '경기도 화성시 만세구 장안면 사곡리 375-16', '토지 / 임야'); p2 = drow('P2', '경기도 화성시 만세구 장안면 사곡리 379-1', '토지 / 임야')
        d, st = A.select_D({'rows': [p1, p2]})
        self.assertEqual(sorted(v['row']['scrnIndctCltrMngNo'] for v in d), ['P1', 'P2'])

    def test_ok_sel11_same_building_still_merged(self):
        r1 = drow('H1', '서울특별시 구로구 구로동 97 로제리움2차 제12층 제1203호', '용도복합용건물 / 오피스텔', 8820000)
        r2 = drow('H2', '서울특별시 구로구 구로동 97 로제리움2차 제13층 제1301호', '용도복합용건물 / 오피스텔', 8820000)
        d, st = A.select_D({'rows': [r1, r2]})
        self.assertEqual([(v['row']['scrnIndctCltrMngNo'], v['dup']) for v in d], [('H1', 1)])

    def test_bug_sel12_dedupe_tie(self):
        rows = [{'scrnIndctCltrMngNo': 'P', 'pbctBegnDtm': '2026-10-07 12:00', 'pbctNsq': str(i), 'lowstBidPrc': p} for i, p in ((1, 5000000), (2, 3000000), (3, 1000000))]
        self.assertEqual(A.dedupe(rows)['P']['row']['lowstBidPrc'], A.dedupe(rows[::-1])['P']['row']['lowstBidPrc'])

    def test_bug_sel13_dash_sgg(self):
        self.assertEqual(A._dist({'sidoSgkEmd': '-', 'onbidCltrNm': '경기도 군포시 산본동 1-1'}), 0)

    def test_bug_sel14_deposits(self):
        self.assertEqual(A._deposits({'lease': [['임차권', '한**', '130,000,000', '-', '-', '2023-12-13', '2024-01-29']]}), [130000000])
        self.assertEqual(A._deposits({'lease': [['임차인', '김**', '-', '500,000', '-', '2020-01-01', '2020-01-02']]}), [])
        self.assertEqual(A._deposits({'lease': [['임차인', '김**', ',,,,', '-']]}), [])
        self.assertEqual(A._deposits({'lease': [['임차권', '장**', '200,000,000', '-', '-', 'a', 'b'], ['임차인', '장**', '200,000,000', '-', '-', 'a', 'b']]}), [200000000])

    def test_bug_sel15_keywords(self):
        rows = [brow('kw', '삼성전자 냉난방기 AP-SG803H 냉방29/난방33kW', cat='사무/가구/가전 / 가전제품및디지털제품', price=3450000, sgg='경기도 군포시'),
                brow('lens', '(주)미스터리프렌즈 사무용 책상', cat='사무/가구/가전 / 사무용가구', price=300000, sgg='경기도 군포시')]
        self.assertEqual([v['row']['scrnIndctCltrMngNo'] for v in A.select_B({'rows': rows})[2]], [])

    def test_ok_sel15_real_keywords_kept(self):
        for nm in ('반지(18K)', '오토 18K골드', '14K골드 시계케이스', '삼성 노트북 NT500', '전산장비 및 사무용기기(PC, 노트북)', '캐논 렌즈 EF'):
            self.assertTrue(re.search(C.MVAST_KEYWORDS, nm, re.I), nm)

    def test_bug_sel16_null_fields(self):
        base = brow('n', '삼성 노트북', cat='컴퓨터/전기/통신기계 / 컴퓨터및주변기기', price=500000, sgg='경기도 군포시')
        for kw in ({'ctgrFullNm': None}, {'regOrgNm': None}):
            A.select_B({'rows': [{**base, **kw}]})

    def test_bug_sel17_custody_prefix(self):
        pre = '대전광역시 대덕구 법동 282-1 대전지방국세청 보관 '
        rows = [brow('g1', pre + '순금팔찌 1점'), brow('g2', pre + '금반지 2점')]
        self.assertEqual(sorted(v['row']['scrnIndctCltrMngNo'] for v in A.select_B({'rows': rows})[2]), ['g1', 'g2'])

    def test_bug_sel19_km_case_and_special(self):
        self.assertEqual(carfilter.assess('불용 쏘나타 하이브리드 250,000Km', '자동차 / 승용차', 6000000, '경기', 10)['verdict'], '제외')
        self.assertEqual(carfilter.assess('앰블런스 쏘렌토', '자동차 / 승합차', 5000000, '경기', 30)['verdict'], '제외')

    def test_bug_sel20_yuchigwon_boilerplate(self):
        t = '내부 상태, 유치권 기타 소유권 제한 권리 존부 등을 확인 후 입찰바람'
        self.assertNotIn('유치권 신고', [m for s, m in A.flags_D({**BASE_D, 'notes': [t]})])

    def test_ok_sel20_real_claim_kept(self):
        for t in ('유치권 신고가 있음', '유치권자가 점유 중', '유치권을 주장하는 자가 있음'):
            self.assertIn('유치권 신고', [m for s, m in A.flags_D({**BASE_D, 'notes': [t]})])

    def test_sel18_price_cap_enforced_by_select(self):   # 서버 필터에만 맡기지 않고 선별에서도 1,000만원 상한을 건다
        big = {'scrnIndctCltrMngNo': 'A9', 'pbctBegnDtm': 'x', 'onbidCltrNm': '경기도 군포시 산본동 1-1', 'ctgrFullNm': '토지 / 임야', 'lowstBidPrc': 50000000,
               'alcYn': 'Y', 'scrnPrptDvsnNm': '압류재산', 'sidoSgkEmd': '경기도 군포시 산본동'}
        self.assertEqual(len(A.select_A({'rows': [big]})[0]), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
