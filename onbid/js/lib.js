// 온비드 브라우저 헬퍼. 온비드는 상세 페이지를 POST 폼 이동으로만 열어 주고(직접 GET은 400),
// 검색·상세 데이터 상당수가 페이지 안 XHR로 늦게 채워지므로 실제 브라우저(Playwright)로 다룬다.
const path = require('path');

function loadPlaywright() {
  const candidates = [
    'playwright',
    '/opt/node22/lib/node_modules/playwright',
    path.join(process.env.NODE_PATH || '', 'playwright'),
  ];
  for (const c of candidates) {
    try { return require(c); } catch (e) { /* 다음 후보 */ }
  }
  throw new Error('playwright 모듈을 찾지 못함 (npm i -g playwright 또는 NODE_PATH 설정)');
}

const { chromium } = loadPlaywright();

const ORIGIN = 'https://www.onbid.co.kr';
const SEARCH_URL = ORIGIN + '/op/cltrpbancinf/cltr/cltrcdtnsrch/CltrCdtnSrchController/mvmnCltrCdtnSrchClg.do';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36';

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function launch() {
  const opts = {};
  if (process.env.HTTPS_PROXY) opts.proxy = { server: process.env.HTTPS_PROXY };
  if (process.env.PW_CHROMIUM) opts.executablePath = process.env.PW_CHROMIUM;
  const browser = await chromium.launch(opts);
  const ctx = await browser.newContext({ userAgent: UA, locale: 'ko-KR' });
  const page = await ctx.newPage();
  return { browser, ctx, page };
}

// 조건검색 화면을 열고 jQuery와 사이트 함수가 준비될 때까지 기다린다. 연결이 자주 끊겨 재시도한다.
async function openSearch(page) {
  for (let i = 0; i < 6; i++) {
    try {
      await page.goto(SEARCH_URL, { waitUntil: 'domcontentloaded', timeout: 90000 });
      await page.waitForFunction(() => typeof window.$ === 'function' && typeof window.fn_goCltrDetail === 'function'
        && typeof window.fn_frmToJson === 'function', null, { timeout: 45000 });
      return true;
    } catch (e) {
      console.error('검색화면 재시도', i, e.message.slice(0, 120));
      await sleep(3000 * (i + 1));
    }
  }
  return false;
}

// 사이트 자체 함수로 상세 화면에 POST 이동한다. 성공 여부는 본문 문구로 확인한다.
async function gotoDetail(page, item) {
  const a = [item.cltrScrnGrpCd, item.cltrPrptDivCd, item.onbidCltrno, item.onbidPbancNo, item.pbctNo, item.pbctCdtnNo];
  for (let i = 0; i < 4; i++) {
    try {
      if (!(await page.evaluate(() => typeof window.fn_goCltrDetail === 'function').catch(() => false))) {
        if (!(await openSearch(page))) continue;
      }
      await Promise.all([
        page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 90000 }),
        page.evaluate(args => window.fn_goCltrDetail(...args), a),
      ]);
      await page.waitForFunction(() => {
        const t = document.body ? document.body.innerText : '';
        return t.includes('세부정보') && typeof window.fn_frmToJson === 'function';
      }, null, { timeout: 45000 });
      return true;
    } catch (e) {
      console.error('상세 재시도', item.scrnIndctCltrMngNo, i, e.message.slice(0, 120));
      await openSearch(page);
    }
  }
  return false;
}

// 페이지 컨텍스트에서 폼 POST(XHR) 호출. 세션 쿠키와 CSRF가 그대로 쓰인다.
async function post(page, url, body) {
  return page.evaluate(async ([url, body]) => {
    const r = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        Accept: 'application/json, text/javascript, */*; q=0.01',
      },
      body,
      signal: AbortSignal.timeout(60000),       // 응답이 멈춘 요청이 전체 수집을 붙잡지 않게 한다(호출부의 재시도 경로를 탄다)
    });
    return r.text();
  }, [url, body]);
}

// 물건상세 공유 링크 형식. 이 6개 파라미터만 넣어야 GET으로 열린다(다른 파라미터를 붙이면 400).
function detailLink(item) {
  const q = ['cltrScrnGrpCd', 'cltrPrptDivCd', 'onbidCltrno', 'onbidPbancNo', 'pbctNo', 'pbctCdtnNo']
    .map(k => `${k}=${encodeURIComponent(item[k])}`).join('&');
  return `${ORIGIN}/op/cltrpbancinf/cltrdtl/CltrDtlController/mvmnCltrDtl.do?${q}`;
}

module.exports = { launch, openSearch, gotoDetail, post, detailLink, sleep, ORIGIN, SEARCH_URL };
