// module-6 E2E — 진짜 Chrome 으로 진짜 서버(기본 8780): 분봉(통합) → 분봉(KRX) → 틱 정밀화 → 틱 조건. 결과 화면·거래 캔들 서랍(분봉)까지.
// 사용: node e2e/m6.mjs [baseUrl] [출력폴더]      (Chrome 경로는 CHROME_PATH)
// 끝에 이 시험이 만든 실행 결과를 API 로 지운다.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm6')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })

const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }

const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm6prof-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const shot = (name) => page.screenshot({ path: path.join(OUT, `m6_${name}.png`), fullPage: true })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, timeout = 60000) => page.waitForSelector(sel, { timeout })
const text = (sel) => page.$eval(sel, (e) => e.textContent ?? '')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const runIds = []

/** 탭 이름으로 모드 탭을 켠다 */
async function openTab(name) {
  await page.evaluate((n) => [...document.querySelectorAll('.ant-tabs-tab')].find((t) => t.textContent.trim() === n).click(), name)
  await sleep(500)
}
/** 라디오 묶음 안의 라벨을 누른다 */
async function pick(groupId, label) {
  await page.evaluate((g, l) => [...document.querySelector(`[data-testid="${g}"]`).querySelectorAll('label')].find((x) => x.textContent.trim() === l).click(), groupId, label)
  await sleep(600)
}
async function runAndWait(label, timeout = 300000) {
  await page.waitForFunction(() => { const b = document.querySelector('[data-testid="run-btn"]'); return b && !b.disabled }, { timeout: 60000 })
  await page.click($('run-btn'))
  await wait($('run-modal'))
  log(label, '실행 중…')
  await page.waitForFunction(() => location.hash.startsWith('#/results/'), { timeout })
  const id = page.url().split('#/results/')[1]
  runIds.push(id)
  await wait($('metric-cards'), 60000)
  log(label, '결과', id)
  return id
}
async function candle(label) {
  await page.waitForSelector('[data-testid="trades-table"] tbody tr.ant-table-row', { timeout: 30000 })
  await page.click('[data-testid="trades-table"] tbody tr.ant-table-row td')
  await wait($('candle-drawer'), 30000)
  await wait('[data-testid="candle-chart"] canvas', 60000)
  const note = await text($('candle-chart'))
  check(`${label}: 거래 클릭 → 분봉 캔들 서랍`, /분봉/.test(note), note.slice(0, 70))
  await sleep(700)
  await shot(`candle_${label}`)
  await page.keyboard.press('Escape')
  await sleep(700)
}

try {
  // ───────── 분봉 · 통합 ─────────
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait($('spec-name'))
  await openTab('분봉 단타')
  await wait($('panel-intraday'), 30000)
  await wait($('source-availability'), 60000) // 출처별 보관 기간 조회(라이브에선 수 초)
  const av = await text($('source-availability'))
  check('분봉 탭: 출처별 사용 가능 기간·종목 수', /통합/.test(av) && /KRX/.test(av) && /\d{3,}/.test(av), av.replace(/\s+/g, ' ').slice(0, 110))
  const period = await text($('panel-period'))
  check('기간 기준이 분봉 데이터로 바뀜', /통합 분봉 데이터/.test(period), period.slice(0, 60))
  await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="panel-period"] input')].some((i) => i.value === '2026-09-23'), { timeout: 15000 }).catch(() => {})
  const endVal = await page.$$eval('[data-testid="panel-period"] input', (n) => n.map((i) => i.value))
  check('기간 끝이 데이터 끝(2026-09-23)으로 맞춰짐', endVal.includes('2026-09-23'), endVal.join(' ~ '))
  check('통합이 기본 선택', await page.$eval($('minute-source'), (e) => e.querySelector('.ant-radio-button-wrapper-checked')?.textContent.trim() === '통합(AL)'))
  check('KRX 경고는 아직 없음', !(await page.$($('krx-warning'))))
  check('기존 전략 선택은 막혀 있음', await page.evaluate(() => { const l = [...document.querySelectorAll('[data-testid="strategy-source"] label')].find((x) => x.textContent.includes('기존 전략')); return l.querySelector('input').disabled }))
  await shot('1_intraday_setup')
  const alId = await runAndWait('분봉(통합)')
  await wait($('intraday-coverage'), 30000)
  check('결과: 통합 태그 + 분봉 커버리지 카드', !!(await page.$($('al-tag'))) && (await text($('intraday-coverage'))).includes('분봉이 있던'))
  check('결과: 종목별 보관 기간 표', !!(await page.$($('code-periods'))))
  await shot('2_intraday_al_result')
  await candle('분봉_통합')

  // ───────── 분봉 · KRX ─────────
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait($('spec-name'))
  await openTab('분봉 단타')
  await wait($('panel-intraday'), 30000)
  await pick('minute-source', 'KRX 전용')
  await wait($('krx-warning'), 10000)
  check('KRX 선택 시 큰 경고', (await text($('krx-warning'))).includes('KRX 기준(NXT 제외'))
  check('기간 기준이 KRX 분봉으로', (await text($('panel-period'))).includes('KRX 분봉 데이터'))
  await shot('3_intraday_krx_setup')
  await runAndWait('분봉(KRX)')
  await wait($('krx-banner'), 30000)
  const banner = await text($('krx-banner'))
  check('결과 맨 위에 "KRX 기준" 크게', banner.includes('KRX 기준(NXT 제외') && banner.includes('비교하지 마세요'))
  await shot('4_intraday_krx_result')
  await candle('분봉_KRX')

  // ───────── 틱 · 분봉 + 틱 정밀화 ─────────
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait($('spec-name'))
  await openTab('체결(틱)')
  await wait($('panel-tick'), 30000)
  await wait($('tick-sample'), 60000)
  const sample = await text($('tick-sample'))
  check('틱 탭: 체결 표본 안내(거래일·종목 수)', /\d+거래일/.test(sample) && /\d+종목/.test(sample), sample.slice(0, 80))
  check('틱 조건 진입은 전략 없음 안내', !!(await page.$($('tick-no-strategy'))))
  await shot('5_tick_setup')
  await pick('tick-entry-source', '분봉 신호 + 틱 정밀화')
  await wait($('panel-intraday'), 10000)
  check('정밀화로 바꾸면 분봉 설정·전략이 생김', !!(await page.$($('strategy-source'))) && !(await page.$($('tick-catalog'))))
  await runAndWait('틱 정밀화', 300000)
  await wait($('tick-refine'), 30000)
  const refine = await text($('tick-refine'))
  check('결과: 틱 정밀화 비교 카드(체결가 차이·손익 차이)', /체결가 차이/.test(refine) && /차이\(틱 − 봉\)/.test(refine), refine.replace(/\s+/g, ' ').slice(0, 90))
  const hdr = await page.$$eval('[data-testid="trades-table"] thead th', (n) => n.map((e) => e.textContent))
  check('거래 표에 체결가 차이 열', hdr.some((h) => h.includes('진입가 차이')) && hdr.some((h) => h.includes('정밀화')), hdr.join('|').slice(-60))
  await shot('6_tick_refine_result')
  await candle('틱정밀화')

  // ───────── 틱 · 틱 조건(모드 B) ─────────
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait($('spec-name'))
  await openTab('체결(틱)')
  await wait($('panel-tick'), 30000)
  await runAndWait('틱 조건', 420000)
  await wait($('tick-summary'), 30000)
  const ts = await text($('tick-summary'))
  check('결과: 틱 표본 카드', /신호 수/.test(ts) && /장마감 청산/.test(ts), ts.replace(/\s+/g, ' ').slice(0, 80))
  const bars = await page.$$eval('[data-testid="trades-table"] tbody tr.ant-table-row', (n) => n[0]?.textContent ?? '')
  check('틱 거래의 보유 기간은 초 단위', /초/.test(bars), bars.slice(0, 80))
  check('정밀화 카드는 없음', !(await page.$($('tick-refine'))))
  await shot('7_tick_catalog_result')
  await candle('틱조건')

  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
  await shot('zz_failure').catch(() => {})
} finally {
  for (const id of runIds) {
    const r = await fetch(`${BASE}/api/runs/${id}`, { method: 'DELETE', headers: { Origin: BASE } }).catch(() => null)
    log('삭제', id, r?.status)
  }
  await browser.close()
  fs.writeFileSync(path.join(OUT, 'm6_results.json'), JSON.stringify(results, null, 1))
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
