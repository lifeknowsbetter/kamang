// 물건상세 수집기. 물건마다 다음 파일을 <outDir>/<물건관리번호>.* 로 남긴다.
//   .html   상세 화면 전체
//   .xhr    등기사항증명서 주요정보·점유관계·임대차·배분요구 조각(HTML). 화면은 3~10건씩 페이지를
//           나눠 보여주므로 pageUnit=100으로 직접 다시 받아 공유자를 빠짐없이 얻는다.
//   .img    사진/위치도 팝업 조각(HTML) — 사진 URL 목록이 들어 있다.
//   .stmt   공매재산명세서(ClipReport) 원자료. 입찰 시작 7일 전부터만 버튼이 생긴다. 없으면 NO_BUTTON.
//   node onbid/js/details.js <pool.json> <outDir>
const fs = require('fs');
const path = require('path');
const { launch, openSearch, gotoDetail } = require('./lib');

const [, , poolFile, outDir] = process.argv;
const FRAGMENTS = ['inqRgstMtrsCrtiClg', 'inqOcpyRelClg', 'inqLeasInfClg', 'inqBondDclrPscdClg'];

async function fetchFragments(page) {
  return page.evaluate(async eps => {
    const out = {};
    const param = window.fn_frmToJson('srchCltrDtlFrm');
    param.pageUnit = 100; param.pageIndex = 1; param.viewMode = 'PC'; param.szrPrptRls = 'OPEN';
    const body = $.param(param, true);
    for (const ep of eps) {
      try {
        const r = await fetch(`/op/cltrpbancinf/cltrdtl/CltrDtlController/${ep}.do`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest' },
          body,
        });
        out[ep] = r.ok ? await r.text() : 'ERR HTTP ' + r.status;
      } catch (e) { out[ep] = 'ERR ' + e.message; }
    }
    return out;
  }, FRAGMENTS);
}

async function fetchImagePopup(page) {
  return page.evaluate(async () => {
    try {
      if (!$('#picCnt').val()) $('#picCnt').val('1');
      const params = window.fn_frmToJson('srchImgMapFrm');
      const r = await fetch('/op/cltrpbancinf/cltrdtl/CltrDtlController/inqCltrMapImg.do', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest' },
        body: $.param(params, true),
      });
      return r.ok ? await r.text() : 'ERR HTTP ' + r.status;
    } catch (e) { return 'ERR ' + e.message; }
  });
}

// 명세서 버튼을 눌러 리포트 뷰어 팝업을 띄우고, 리포트 서버 응답(viewData)을 그대로 저장한다.
async function fetchStatement(ctx, page, reports) {
  const btns = await page.evaluate(() => Array.from(document.querySelectorAll('button[onclick*="fn_pbctPrptDstmtReport"]'))
    .map(b => b.getAttribute('onclick')));
  if (!btns.length) return 'NO_BUTTON';
  reports.length = 0;
  const [popup] = await Promise.all([
    ctx.waitForEvent('page', { timeout: 60000 }),
    page.evaluate(code => eval(code), btns[btns.length - 1]),
  ]);
  await popup.waitForLoadState('domcontentloaded', { timeout: 90000 }).catch(() => {});
  for (let w = 0; w < 120 && !reports.some(x => x.includes('DocumentPageView')); w++) await popup.waitForTimeout(500);
  if (!reports.some(x => x.includes('DocumentPageView'))) {      // 버튼은 있었는데 본문을 못 받음 — 빈 명세서('공란')와 구별해 표시한다
    await popup.close().catch(() => {});
    return 'NO_RESPONSE';
  }
  // 2쪽 이후는 "다음" 버튼을 눌러야 서버가 내려준다(인수권리·지상권·기타 유의사항은 보통 2쪽).
  for (let k = 0; k < 3; k++) {
    try {
      await popup.evaluate(() => {
        const b = Array.from(document.querySelectorAll('button,div,span,img'))
          .find(e => /next/i.test(`${e.className} ${e.getAttribute('src') || ''} ${e.title || ''}`));
        if (b) b.click();
      });
      await popup.waitForTimeout(2000);
    } catch (e) { /* 마지막 쪽 */ }
  }
  await popup.close().catch(() => {});
  return btns.join('|') + '\n=========\n' + reports.join('\n=========\n');
}

(async () => {
  const items = JSON.parse(fs.readFileSync(poolFile, 'utf8'));
  fs.mkdirSync(outDir, { recursive: true });
  const { browser, ctx, page } = await launch();
  const reports = [];
  ctx.on('response', async r => {
    if (!r.url().includes('report_server.jsp')) return;
    try { reports.push((r.request().postData() || '').slice(0, 200) + '\n----\n' + await r.text()); } catch (e) { /* 무시 */ }
  });
  await openSearch(page);
  let ok = 0, fail = 0;
  for (const it of items) {
    const base = path.join(outDir, it.scrnIndctCltrMngNo);
    if (fs.existsSync(base + '.done')) { ok++; continue; }
    try {
      if (!(await gotoDetail(page, it))) { fail++; console.error('상세 실패', it.scrnIndctCltrMngNo); continue; }
      fs.writeFileSync(base + '.html', await page.content());
      const frags = await fetchFragments(page);
      const badFrag = Object.entries(frags).filter(([, v]) => /^ERR/.test(v) || !/총|조회된 결과가 없습니다/.test(v)).map(([k]) => k);
      if (badFrag.length) throw new Error('조각 수집 실패: ' + badFrag.join(','));
      fs.writeFileSync(base + '.xhr', JSON.stringify(frags));
      const img = await fetchImagePopup(page);
      if (/^ERR/.test(img)) throw new Error('사진 팝업 수집 실패');
      fs.writeFileSync(base + '.img', img);
      let stmt = await fetchStatement(ctx, page, reports);
      if (stmt === 'NO_RESPONSE') stmt = await fetchStatement(ctx, page, reports);      // 한 번 더 눌러 본다
      fs.writeFileSync(base + '.stmt', stmt);        // 끝내 못 받으면 'NO_RESPONSE' 그대로 저장 — parse 가 '명세서 읽지 못함'으로 처리한다
      fs.writeFileSync(base + '.done', '');
      ok++;
      console.error('OK', it.scrnIndctCltrMngNo);
    } catch (e) {
      fail++;
      console.error('ERR', it.scrnIndctCltrMngNo, e.message.slice(0, 160));
      await openSearch(page);
    }
  }
  await browser.close();
  console.error(`완료 ${ok}, 실패 ${fail}`);
})().catch(e => { console.error(e); process.exit(1); });
