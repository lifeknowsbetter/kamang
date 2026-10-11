// 조건검색 3종(지분 부동산 / 동산 / 자동차)을 한 브라우저 세션에서 돌려 원자료 JSON으로 저장한다.
//   node onbid/js/search.js <outDir> <부동산상한> <동산상한> <자동차상한>
// 입찰기간은 사이트 기본값(오늘~1개월)을 그대로 쓴다.
// 주의: 서버가 지분여부(srchAlcYnType) 조건을 무시하므로 지분 판정은 응답의 alcYn=='Y'로 따로 한다.
const fs = require('fs');
const path = require('path');
const { launch, openSearch, post } = require('./lib');

const [, , outDir, rlstMax = '3000000', mvastMax = '1000000', carMax = '5000000'] = process.argv;
const ENDPOINT = '/op/cltrpbancinf/cltr/cltrcdtnsrch/CltrCdtnSrchController/srchCltrCdtn.do';
const PAGE = 100;

const TRACKS = [
  { key: 'A', label: '부동산', params: { srchCltrType: '0001', srchAlcYnType: 'Y' }, max: rlstMax },
  { key: 'B', label: '동산', params: { srchCltrType: '0003' }, max: mvastMax },
  { key: 'C', label: '자동차', params: { srchCltrType: '0002' }, max: carMax },
];

async function searchTrack(page, base, t) {
  const p = new URLSearchParams(base);
  const set = (k, v) => p.set(k, v);
  set('srchDspsMthod', '0001');            // 매각
  set('srchLowstBidBgng', '001');          // 최저입찰가 직접입력
  set('srchLowstBidBgngPrc', '0');
  set('srchLowstBidEndPrc', String(t.max));
  for (const [k, v] of Object.entries(t.params)) set(k, v);
  set('pageUnit', String(PAGE)); set('recordCountPerPage', String(PAGE)); set('pageSize', '10');
  const rows = [];
  let total = null;
  for (let pg = 1; pg <= 50; pg++) {
    set('pageIndex', String(pg)); set('firstIndex', String((pg - 1) * PAGE)); set('lastIndex', String(pg * PAGE));
    let j = null;
    for (let tryNo = 0; tryNo < 4 && !j; tryNo++) {
      try { j = JSON.parse(await post(page, ENDPOINT, p.toString())); }
      catch (e) { console.error(`${t.label} p${pg} 재시도`, e.message.slice(0, 100)); await openSearch(page); }
    }
    if (!j) throw new Error(`${t.label} 검색 실패 (page ${pg})`);
    total = j.totalCount;
    const list = j.cltrInfVOList || [];
    rows.push(...list);
    if (list.length < PAGE) break;
  }
  return { track: t.key, label: t.label, max: Number(t.max), totalCount: total, rows };
}

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const { browser, page } = await launch();
  if (!(await openSearch(page))) throw new Error('온비드 조건검색 화면 접속 실패');
  // orderForm은 화면의 첫 자동검색이 끝나야 채워진다. 비어 있는 채로 보내면 서버가 "현재 입찰중" 물건만
  // 돌려줘서 다음 주 입찰 예정(입찰준비중) 물건이 통째로 빠진다.
  await page.waitForLoadState('networkidle', { timeout: 60000 }).catch(() => {});
  await page.waitForFunction(() => !!new URLSearchParams($('#orderForm').serialize()).get('srchBidPerdBgngDt'),
    null, { timeout: 60000 }).catch(() => console.error('경고: orderForm 기본값이 비어 있어 직접 채움'));
  const p0 = new URLSearchParams(await page.evaluate(() => $('#orderForm').serialize()));
  if (!p0.get('srchBidPerdBgngDt')) {
    const fmt = d => d.toISOString().slice(0, 10);
    const now = new Date(Date.now() + 9 * 3600 * 1000);       // KST
    const end = new Date(now); end.setMonth(end.getMonth() + 1);
    const defaults = {
      crpsNo: '1', updrNo: '1', srchBidPerdType: '0002', srchBidPerdBgngDt: fmt(now), srchBidPerdEndDt: fmt(end),
      srchpbancPbctCltrStatCd: '0002', srchPrptType: ',0007,0010,0005,0003,0013,0002,0011,0006,0008,0004,0012,0001',
      srchLdarType: 'ALL', srchBldSqmsType: 'ALL', srchBidMthod: 'ALL', srchUsbdNftType: 'ALL', srchApslEvlAmtType: '001',
      usrNo: '0', srchWordType: '0001', srchSortType: 'ASC', searchCltrMnmtNoYn: 'N',
      srchFuelType: ',0001,0002,0003,0004,0005,0006,0007,0008,0099',
    };
    for (const [k, v] of Object.entries(defaults)) p0.set(k, v);
  }
  const base = p0.toString();
  const window_ = [p0.get('srchBidPerdBgngDt'), p0.get('srchBidPerdEndDt')];
  for (const t of TRACKS) {
    const r = await searchTrack(page, base, t);
    r.bidWindow = window_;
    fs.writeFileSync(path.join(outDir, `search_${t.key}.json`), JSON.stringify(r));
    console.error(`${t.label}: ${r.rows.length}행 (서버 totalCount ${r.totalCount})`);
    if (!r.rows.length) console.error(`경고: ${t.label} 검색 결과 0건`);
  }
  await browser.close();
})().catch(e => { console.error('검색 실패:', e.message); process.exit(1); });
