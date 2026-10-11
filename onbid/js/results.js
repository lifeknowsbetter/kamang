// 물건입찰결과 조회. 낙찰가(onbidBidAmt)·낙찰가율(rateRow1)·응찰자 수(totalBid)는 로그인 없이 공개된다.
//   node onbid/js/results.js <in.json> <out.json>
//   in.json = { items: [{mng, type}], keywords: [{key, kw, type, from}] }
//     items    — 물건관리번호로 회차별 결과 전체(날짜 조건 무시됨)
//     keywords — 물건명 키워드로 개찰일 from~오늘 사이 결과(동종 낙찰 사례용)
//   type: 0001 부동산 / 0002 자동차 / 0003 동산
const fs = require('fs');
const { launch, post, sleep } = require('./lib');

const PAGE_URL = 'https://www.onbid.co.kr/op/cltrpbancinf/bidrsltmng/cltrbidrslt/CltrBidRsltController/mvmnCltrBidRsltClg.do';
const EP = '/op/cltrpbancinf/bidrsltmng/cltrbidrslt/CltrBidRsltController/cltrBidRsltClg.do';
const [, , inFile, outFile] = process.argv;

async function openPage(page) {
  // 화면의 첫 자동조회 요청 본문을 기본값으로 쓴다(폼이 늦게 채워져 직접 직렬화하면 비어 있다).
  let init = null;
  const h = r => { if (!init && r.url().includes('cltrBidRsltClg.do')) init = r.postData(); };
  page.on('request', h);
  for (let i = 0; i < 5 && !init; i++) {
    try {
      await page.goto(PAGE_URL, { waitUntil: 'networkidle', timeout: 90000 });
      for (let w = 0; w < 20 && !init; w++) await sleep(500);
    } catch (e) { console.error('결과화면 재시도', i, e.message.slice(0, 100)); await sleep(3000 * (i + 1)); }
  }
  page.off('request', h);
  if (!init) throw new Error('입찰결과 화면 기본 조회값을 얻지 못함');
  return init;
}

async function query(page, init, set) {
  const p = new URLSearchParams(init);
  p.set('pageUnit', '100'); p.set('recordCountPerPage', '100'); p.set('pageIndex', '1');
  for (const [k, v] of Object.entries(set)) p.set(k, v);
  for (let i = 0; i < 3; i++) {
    try {
      const j = JSON.parse(await post(page, EP, p.toString()));
      return j.cltrBidRsltClgInfVOList || [];
    } catch (e) { console.error('결과조회 재시도', e.message.slice(0, 80)); await sleep(2000 * (i + 1)); }
  }
  return null;
}

const KEEP = ['scrnIndctCltrMngNo', 'onbidCltrNm', 'pbctNsq', 'pbctStatNm', 'exctStatNm', 'pbctExctDt', 'lowstBidPrc',
  'cltrApslEvlAvgAmt', 'onbidBidAmt', 'rateRow1', 'totalBid', 'sidoEmd', 'ctgrFullNm', 'dspsMthodCdNm', 'cltrPrptDivCdNm'];
const slim = rows => rows && rows.map(r => Object.fromEntries(KEEP.map(k => [k, r[k]])));

(async () => {
  const input = JSON.parse(fs.readFileSync(inFile, 'utf8'));
  const { browser, page } = await launch();
  const init = await openPage(page);
  const today = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
  const out = { items: {}, keywords: {} };
  for (const it of input.items || []) {
    const rows = await query(page, init, {
      srchCltrMnmtNo: it.mng, searchCltrMnmtNoYn: 'Y', srchCltrType: it.type || '0001',
    });
    out.items[it.mng] = slim(rows);
  }
  for (const k of input.keywords || []) {
    const rows = await query(page, init, {
      srchCltrNm: k.kw, srchCltrType: k.type, srchDspsMthod: '0001',
      srchOpbdBgdd: k.from, calOpbdBgdd: k.from, srchOpbdEndd: today, calOpbdEndd: today,
      srchBidPerdBgngDt: k.from, calBidPerdBgngDt: k.from,
    });
    out.keywords[k.key] = slim(rows);
  }
  fs.writeFileSync(outFile, JSON.stringify(out));
  await browser.close();
  console.error(`결과조회 완료: 물건 ${Object.keys(out.items).length}, 키워드 ${Object.keys(out.keywords).length}`);
})().catch(e => { console.error('결과조회 실패:', e.message); process.exit(1); });
