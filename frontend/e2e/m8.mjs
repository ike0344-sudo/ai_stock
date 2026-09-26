// c8 E2E — 틱 탭의 분봉·일봉 조건 묶음: 필터 켜기 → 실행 → 결과 카드(분봉이 없어 빠진 쌍). 진짜 Chrome·진짜 서버(기본 8780).
// 사용: node e2e/m8.mjs [baseUrl] [출력폴더]   끝에 만든 실행 결과를 API 로 지운다.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm8')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm8prof-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const shot = (n) => page.screenshot({ path: path.join(OUT, `m8_${n}.png`), fullPage: true })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, t = 60000) => page.waitForSelector(sel, { timeout: t })
const text = (sel) => page.$eval(sel, (e) => e.textContent ?? '')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const runIds = []
try {
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait($('spec-name'))
  await page.evaluate(() => [...document.querySelectorAll('.ant-tabs-tab')].find((t) => t.textContent.trim() === '체결(틱)').click())
  await wait($('panel-tick'), 30000)
  await wait($('tick-filter-card'), 15000)
  check('서버가 알리면 분봉·일봉 조건 카드가 나타남', true)
  check('표본 감소 경고(약 31%)', (await text($('tick-filter-sample-warning'))).includes('31%'))
  await page.click($('tick-filter-switch'))
  await wait($('row-tick.filter.items.0'), 10000)
  check('필터를 켜면 조건 행(종가 > VWAP)이 생김', true)
  // 시간 단위 선택기(1분봉 기준): m1 비활성
  const tfSel = `${$('row-tick.filter.items.0')} ${$('operand-left-tf')}`
  const hasTf = !!(await page.$(tfSel))
  check('필터 조건에 시간 단위 선택기가 있음', hasTf)
  if (hasTf) {
    await page.click(tfSel); await sleep(500)
    const opts = await page.evaluate(() => [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')].map((o) => o.textContent + '|' + o.getAttribute('aria-disabled')))
    check('1분봉은 비활성(3~60분·일봉만)', opts.some((o) => o.startsWith('1분봉') && o.endsWith('true')) && opts.some((o) => o.startsWith('3분봉') && o.endsWith('false')), opts.slice(0, 4).join(' / '))
    await page.keyboard.press('Escape')
  }
  await page.click($('tick-prefilter-switch'))
  await wait($('row-tick.prefilter.items.0'), 10000)
  await shot('1_tick_filter_setup')
  await page.waitForFunction(() => { const b = document.querySelector('[data-testid="run-btn"]'); return b && !b.disabled }, { timeout: 60000 })
  await page.click($('run-btn'))
  await wait($('run-modal'))
  log('틱 + 필터 실행 중…')
  await page.waitForFunction(() => location.hash.startsWith('#/results/'), { timeout: 420000 })
  runIds.push(page.url().split('#/results/')[1])
  await wait($('tick-summary'), 60000)
  const sum = await text($('tick-summary'))
  check('결과: 분봉이 없어 진입 못 한 쌍 카드', /분봉이 없어 진입 못 한/.test(sum), sum.replace(/\s+/g, ' ').slice(0, 140))
  check('결과: 사전 필터로 제외한 쌍 카드', /사전 필터로 제외한/.test(sum))
  const warn = await text($('warning-badges')).catch(() => '')
  check('서버 경고 문구가 그대로 보임(분봉 없음)', /분봉/.test(warn), warn.slice(0, 80))
  await shot('2_tick_filter_result')
  // ───────── 틱 + 5분봉 + 일봉 조합(수식으로) ─────────
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait($('spec-name'))
  await page.evaluate(() => [...document.querySelectorAll('.ant-tabs-tab')].find((t) => t.textContent.trim() === '체결(틱)').click())
  await wait($('formula-text'), 30000)
  await page.type($('formula-text'), 'M5.C > M5.MA(C,20) AND DL.C > DL.MA(C,20)')
  await page.click($('formula-check'))
  await wait($('formula-ok'), 15000)
  await page.click($('formula-insert-filter'))
  await sleep(1200)
  const nar = await page.waitForFunction(() => /5분봉/.test(document.querySelector('[data-testid="narration"]')?.textContent ?? '') && /체결 시각까지 마감된 마지막 1분봉/.test(document.querySelector('[data-testid="narration"]')?.textContent ?? ''), { timeout: 30000 }).then(() => true).catch(() => false)
  const narText = await text($('narration')).catch(() => '')
  check('풀이 문장: 5분봉·일봉(장중) 조건 + "체결 시각까지 마감된 마지막 1분봉 기준"', nar, narText.replace(/\s+/g, ' ').slice(0, 200))
  await shot('3_tick_5min_daily_setup')
  await page.waitForFunction(() => { const b = document.querySelector('[data-testid="run-btn"]'); return b && !b.disabled }, { timeout: 60000 })
  await page.click($('run-btn'))
  await wait($('run-modal'))
  log('틱 + 5분봉 + 일봉 실행 중…')
  await page.waitForFunction((prev) => location.hash.startsWith('#/results/') && !location.hash.endsWith(prev), { timeout: 420000 }, runIds[0])
  runIds.push(page.url().split('#/results/')[1])
  await wait($('tick-summary'), 60000)
  const sum2 = await text($('tick-summary'))
  check('조합 결과: 표본 카드에 분봉 없어 빠진 쌍', /분봉이 없어 진입 못 한/.test(sum2), sum2.replace(/\s+/g, ' ').slice(0, 120))
  await shot('4_tick_5min_daily_result')
  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
  await shot('zz_failure').catch(() => {})
} finally {
  for (const id of runIds) { const r = await fetch(`${BASE}/api/runs/${id}`, { method: 'DELETE', headers: { Origin: BASE } }).catch(() => null); log('삭제', id, r?.status) }
  await browser.close()
  fs.writeFileSync(path.join(OUT, 'm8_results.json'), JSON.stringify(results, null, 1))
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
