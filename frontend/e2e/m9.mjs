// c9 E2E — 거래대금(억) 레시피: 분봉 "intraday_value_burst"(억 단위 표시) · 틱 "tick_value_burst"(틱 탭 칸 채우기) → 실행 → 결과. 진짜 Chrome·서버(기본 8780).
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'
const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm9')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm9prof-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const shot = (n) => page.screenshot({ path: path.join(OUT, `m9_${n}.png`), fullPage: true })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, t = 60000) => page.waitForSelector(sel, { timeout: t })
const text = (sel) => page.$eval(sel, (e) => e.textContent ?? '')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const runIds = []
async function applyRecipe(id) {
  await page.click($('recipe-open')); await wait($('recipe-modal'))
  await wait($(`recipe-${id}-apply`), 15000)
  await page.evaluate((i) => document.querySelector(`[data-testid="recipe-${i}-apply"]`).click(), id)
  await sleep(900)
}
async function run(label, timeout = 420000) {
  await page.waitForFunction(() => { const b = document.querySelector('[data-testid="run-btn"]'); return b && !b.disabled }, { timeout: 60000 })
  // 실행 버튼은 고정 막대 안에 있어 좌표 클릭이 가끔 빗나간다(원인 미확정) — DOM 클릭으로 누르고 창이 안 뜨면 한 번 더
  for (let k = 0; k < 3; k++) {
    await page.evaluate(() => document.querySelector('[data-testid="run-btn"]').click())
    if (await page.waitForSelector($('run-modal'), { timeout: 8000 }).then(() => true).catch(() => false)) break
  }
  await wait($('run-modal'), 5000); log(label, '실행 중…')
  await page.waitForFunction(() => location.hash.startsWith('#/results/'), { timeout })
  runIds.push(page.url().split('#/results/')[1]); await wait($('metric-cards'), 60000)
}
try {
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  const caps = await page.evaluate(async () => (await (await fetch('/api/meta/indicators')).json()).data)
  check('서버 능력: 틱 조건 칸 목록에 value_window', caps.capabilities.tick_catalog_fields.includes('value_window'), caps.capabilities.tick_catalog_fields.join(','))
  check('지표 목록에 거래대금(억)', caps.indicators.some((i) => i.name === 'value_eok') && caps.indicators.some((i) => i.name === 'value_sum_eok'))
  // 분봉 레시피
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' }); await wait($('spec-name')); await wait($('narration'), 30000)
  await applyRecipe('intraday_value_burst')
  await wait($('panel-intraday'), 15000)
  const rowTxt = await page.$$eval('[data-testid^="row-strategy.entry.items."]', (n) => n.map((e) => e.innerText.replace(/\s+/g, ' ')).join(' | '))
  check('분봉 거래대금 레시피: 조건 행에 "억" 단위가 붙음', /억/.test(rowTxt), rowTxt.slice(0, 160))
  await shot('1_intraday_value_burst')
  await run('분봉 거래대금 급증')
  const w = await text($('warning-badges')).catch(() => '')
  check('결과 경고에 종가×거래량 근사 문구', /근사/.test(w), w.slice(0, 90))
  // 틱 레시피
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' }); await wait($('spec-name')); await wait($('narration'), 30000)
  await applyRecipe('tick_value_burst')
  await wait($('panel-tick'), 15000)
  check('틱 레시피: 틱 탭이 열리고 "최근 체결대금(억)" 조건이 켜짐(10억·1분)', await page.$eval($('tick-vwin-on'), (e) => e.getAttribute('aria-checked') === 'true') && (await page.$eval($('tick-vwin-eok'), (e) => e.value)) === '10')
  check('틱 레시피: 고점 돌파 등 다른 조건은 꺼짐', await page.$eval($('tick-breakout-on'), (e) => e.getAttribute('aria-checked') === 'false'))
  await shot('2_tick_value_burst')
  await run('틱 체결대금 급증')
  const t = await text($('tick-summary')).catch(() => '')
  check('틱 결과 표본 카드', /신호 수/.test(t), t.replace(/\s+/g, ' ').slice(0, 90))
  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) { check('E2E 진행 중 예외', false, String(e).slice(0, 500)); await shot('zz_failure').catch(() => {}) }
finally {
  for (const id of runIds) { const r = await fetch(`${BASE}/api/runs/${id}`, { method: 'DELETE', headers: { Origin: BASE } }).catch(() => null); log('삭제', id, r?.status) }
  await browser.close()
  fs.writeFileSync(path.join(OUT, 'm9_results.json'), JSON.stringify(results, null, 1))
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
