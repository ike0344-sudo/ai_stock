// L3 E2E (설계서 §8.5 #3·#4) — 진짜 Chrome 으로 진짜 서버(기본 http://127.0.0.1:8780)를 조작한다.
//   #3 첫 백테스트: 프리셋 → 실행 → 결과 → 거래 행 클릭(캔들 서랍)
//   #4 반복: 결과에서 조건 복제 → 손절 변경 → 실행 → 실행 기록에서 두 개 골라 비교
// 사용: node e2e/l3.mjs [baseUrl] [출력폴더]      (Chrome 경로는 CHROME_PATH, 기본 Windows 설치 위치)
// 만든 실행 결과는 끝에 API 로 지운다(사용자의 실행 기록을 어지럽히지 않게) — 삭제 자체도 이 화면의 기능이다.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'l3')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })

const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }

const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'l3prof-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const shot = (name) => page.screenshot({ path: path.join(OUT, `l3_${name}.png`), fullPage: true })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, timeout = 60000) => page.waitForSelector(sel, { timeout })
const text = (sel) => page.$eval(sel, (e) => e.textContent ?? '')
const runIds = []

async function runFromBuilder(label) {
  await page.waitForFunction(() => { const b = document.querySelector('[data-testid="run-btn"]'); return b && !b.disabled }, { timeout: 60000 })
  await page.click($('run-btn'))
  await wait($('run-modal'))
  log(label, '실행 중…')
  await page.waitForFunction(() => location.hash.startsWith('#/results/'), { timeout: 240000 })
  const id = page.url().split('#/results/')[1]
  runIds.push(id)
  await wait($('metric-cards'), 60000)
  return id
}

try {
  // ───────── #3 첫 백테스트 ─────────
  await page.goto(`${BASE}/#/backtest?preset=new_high_20`, { waitUntil: 'networkidle2' })
  await wait($('spec-name'))
  await page.waitForFunction(() => document.querySelector('[data-testid="load-note"]')?.textContent?.includes('new_high_20'), { timeout: 30000 })
  await wait($('narration'), 30000)
  check('#3 프리셋 불러오기 → 풀이 문장', (await text($('narration'))).includes('다음 날 시가에 산다'), (await text($('narration'))).slice(0, 60))
  const entryRows = await page.$$eval('[data-testid^="row-strategy.entry.items."]', (n) => n.length)
  check('#3 진입 조건 행 2개', entryRows === 2, `rows=${entryRows}`)
  await shot('1_builder')

  const id1 = await runFromBuilder('#3')
  check('#3 결과 화면으로 이동', /^\d{8}-\d{6}-[0-9a-f]{6}$/.test(id1), id1)
  const cardCount = await page.$$eval('[data-testid^="metric-"][data-verdict]', (n) => n.length)
  check('#3 지표 카드 24개(전부 값)', cardCount === 24, `cards=${cardCount}`)
  const sharpe = await text($('metric-sharpe-value'))
  check('#3 샤프 값이 숫자', /^-?\d+\.\d+$/.test(sharpe.trim()), sharpe)
  const verdict = await page.$eval($('metric-sharpe'), (e) => e.getAttribute('data-verdict'))
  check('#3 샤프에 판정 색(좋음/보통/나쁨)', ['good', 'mid', 'bad'].includes(verdict), verdict)
  for (const id of ['panel-equity', 'panel-drawdown', 'panel-monthly', 'panel-hist', 'panel-sector', 'panel-cost', 'trades-table']) await wait($(id), 30000)
  const canvases = await page.$$eval('[data-testid="panel-equity"] canvas', (n) => n.length)
  check('#3 수익곡선 차트가 실제로 그려짐(canvas)', canvases > 0, `canvas=${canvases}`)
  await shot('2_result')

  await page.waitForSelector('[data-testid="trades-table"] tbody tr.ant-table-row', { timeout: 30000 })
  const firstRowText = await page.$eval('[data-testid="trades-table"] tbody tr.ant-table-row', (e) => e.textContent)
  await page.click('[data-testid="trades-table"] tbody tr.ant-table-row td')
  await wait($('candle-drawer'), 30000)
  await wait($('candle-chart'), 60000)
  const drawerCanvas = await page.$$eval('[data-testid="candle-chart"] canvas', (n) => n.length)
  check('#3 거래 클릭 → 캔들 서랍 + 차트', drawerCanvas > 0, firstRowText.slice(0, 40))
  await new Promise((r) => setTimeout(r, 800))
  await shot('3_candle')
  await page.keyboard.press('Escape')
  await page.waitForSelector($('candle-drawer'), { hidden: true, timeout: 10000 }).catch(() => {})
  await new Promise((r) => setTimeout(r, 600)) // 서랍이 닫히는 애니메이션이 클릭을 가리지 않게

  // ───────── #4 반복: 복제 → 손절 변경 → 실행 → 비교 ─────────
  await page.click($('clone-btn'))
  await page.waitForFunction(() => location.hash.startsWith('#/backtest?from='), { timeout: 15000 })
  await page.waitForFunction(() => document.querySelector('[data-testid="load-note"]')?.textContent?.includes('복제'), { timeout: 30000 })
  const name2 = await page.$eval($('spec-name'), (e) => e.value)
  check('#4 복제: 이름에 (복사)', name2.endsWith('(복사)'), name2)
  const stopBefore = await page.$eval($('exit-stop_loss_pct'), (e) => e.value)
  await page.$eval($('exit-stop_loss_pct'), (e) => { e.focus(); e.select() }) // 칸 전체를 선택한 뒤 덮어쓴다
  await page.keyboard.type('5')
  await page.keyboard.press('Tab')
  const stopAfter = await page.$eval($('exit-stop_loss_pct'), (e) => e.value)
  check('#4 손절 변경', stopBefore.startsWith('7') && stopAfter.startsWith('5'), `${stopBefore} → ${stopAfter}`)
  await page.$eval($('spec-name'), (e) => { e.focus() })
  await page.$eval($('spec-name'), (e) => { e.focus(); e.select() })
  await page.keyboard.type('L3 손절 5%')
  await page.waitForFunction(() => document.querySelector('[data-testid="validation-ok"]'), { timeout: 30000 })
  await shot('4_builder_clone')
  const id2 = await runFromBuilder('#4')
  check('#4 두 번째 결과', id2 !== id1, id2)

  await page.goto(`${BASE}/#/runs`, { waitUntil: 'networkidle2' })
  await wait($('runs-table'))
  await page.waitForFunction((a, b) => document.body.textContent.includes(a) && document.body.textContent.includes(b), { timeout: 30000 }, id1, id2)
  const rowSel = async (id) => page.evaluateHandle((rid) => [...document.querySelectorAll('[data-testid="runs-table"] tbody tr.ant-table-row')].find((r) => r.textContent.includes(rid)).querySelector('input[type=checkbox]'), id)
  await (await rowSel(id1)).click()
  await (await rowSel(id2)).click()
  await page.waitForFunction(() => { const b = document.querySelector('[data-testid="compare-btn"]'); return b && !b.disabled }, { timeout: 10000 })
  await shot('5_runs')
  await page.click($('compare-btn'))
  await wait($('compare-page'), 60000)
  await wait('[data-testid="compare-chart"] canvas', 30000)
  const diffs = await page.$$eval($('diff-item'), (n) => n.map((e) => e.textContent))
  check('#4 비교: 곡선 겹치기 차트', true)
  check('#4 비교: 조건 차이 문장에 손절 7 → 5', diffs.some((d) => d.includes('손절') && d.includes('7') && d.includes('5')), diffs.join(' | '))
  const best = await page.$$eval('[data-testid^="cmp-"][data-best="true"]', (n) => n.length)
  check('#4 비교: 좋은 쪽 강조가 있다', best > 0, `best cells=${best}`)
  await shot('6_compare')

  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 400))
  await shot('zz_failure').catch(() => {})
} finally {
  // 뒤처리: 이 시험이 만든 실행 결과만 지운다
  for (const id of runIds) {
    const r = await fetch(`${BASE}/api/runs/${id}`, { method: 'DELETE' }).catch(() => null)
    log('삭제', id, r?.status)
  }
  await browser.close()
  fs.writeFileSync(path.join(OUT, 'l3_results.json'), JSON.stringify(results, null, 1))
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
