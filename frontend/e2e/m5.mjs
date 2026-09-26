// module-5 E2E — 진짜 Chrome 으로 진짜 서버(기본 8780): 최적화 → 결과 → 홀드아웃 열기 → 워크포워드.
// 사용: node e2e/m5.mjs [baseUrl] [출력폴더] [저장소 루트]      (Chrome 경로는 CHROME_PATH)
// 끝에 이 시험이 만든 실행 결과를 API 로 지우고, 홀드아웃 장부에 남은 이 시험의 열람 기록도 지운다(사용자의 열람 횟수를 오염시키지 않게).
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm5')
const ROOT = process.argv[4] ?? path.resolve('..')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })

const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }

const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm5prof-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const shot = (name) => page.screenshot({ path: path.join(OUT, `m5_${name}.png`), fullPage: true })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, timeout = 60000) => page.waitForSelector(sel, { timeout })
const text = (sel) => page.$eval(sel, (e) => e.textContent ?? '')
const runIds = []
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** 변수 체크박스(라벨에 이름이 든 것)를 켜거나 끈다 */
async function setVary(name, on) {
  const changed = await page.evaluate((n, want) => {
    const w = [...document.querySelectorAll('[data-testid="vary-group"] .ant-checkbox-wrapper')].find((x) => x.textContent.trim().startsWith(n))
    const input = w?.querySelector('input')
    if (!input) return null
    if (input.checked !== want) { input.click(); return true }
    return false
  }, name, on)
  if (changed === null) throw new Error(`변수 체크박스 없음: ${name}`)
  await sleep(700)
}

async function untilResult(label, timeout = 480000) {
  await page.waitForFunction(() => location.hash.startsWith('#/results/'), { timeout })
  const id = page.url().split('#/results/')[1]
  runIds.push(id)
  log(label, '결과', id)
  return id
}

try {
  // ───────── 최적화 ─────────
  await page.goto(`${BASE}/#/optimize?preset=new_high_20`, { waitUntil: 'networkidle2' })
  await wait($('combo-count'), 30000)
  await page.waitForFunction(() => /2,280/.test(document.querySelector('[data-testid="combo-count"]')?.textContent ?? ''), { timeout: 30000 })
  check('조합 수를 서버가 셈(전 변수 2,280)', true, await text($('combo-count')))
  check('500 초과 경고가 보임(실행은 가능)', !!(await page.$($('combo-warn'))))
  check('홀드아웃 % 는 잠겨 있음', await page.$eval($('holdout-pct'), (e) => e.disabled))
  await setVary('exit_n', false)
  await page.waitForFunction(() => document.querySelector('[data-testid="combo-count"]')?.textContent?.trim() === '60', { timeout: 30000 })
  check('exit_n 을 빼면 60조합', true)
  await page.waitForFunction(() => { const b = document.querySelector('[data-testid="run-optimize"]'); return b && !b.disabled }, { timeout: 30000 })
  await shot('1_setup')
  await page.click($('run-optimize'))
  await wait($('run-modal'))
  log('최적화 실행 중…')
  const optId = await untilResult('최적화')
  await wait($('optimize-section'), 60000)
  check('결과 화면이 최적화 결과 패널을 펼침', true)
  const sel = await text($('selected-params'))
  check('고른 조합 표시', /n=\d+/.test(sel), sel)
  await wait($('grid-table'), 30000)
  const rows = await page.$$eval('[data-testid="grid-table"] tbody tr.ant-table-row', (n) => n.length)
  check('조합 표에 행이 보임(쪽 15)', rows === 15, `rows=${rows}`)
  const heat = await page.$$eval('[data-testid="panel-heatmap"] canvas', (n) => n.length)
  check('2변수 히트맵이 실제로 그려짐', heat > 0, `canvas=${heat}`)
  const bands = await page.$$eval('[data-testid="panel-equity"] canvas', (n) => n.length)
  check('구간을 얹은 수익곡선이 그려짐', bands > 0)
  const oosVerdict = await page.$$eval('[data-testid="is-oos-table"] [data-verdict]', (n) => n.length)
  check('학습 vs 검증 표에 판정 색이 붙음', oosVerdict > 0, `n=${oosVerdict}`)
  check('종류 태그 "최적화"', (await text($('kind-tag'))).includes('최적화'))
  await shot('2_optimize_result')

  // ───────── 홀드아웃 열기 ─────────
  await page.click($('holdout-open-btn'))
  await wait($('holdout-confirm'))
  await page.waitForFunction(() => document.querySelector('[data-testid="holdout-first"]') || document.querySelector('[data-testid="holdout-warn"]'), { timeout: 30000 })
  const first = !!(await page.$($('holdout-first')))
  check('홀드아웃 확인창: 열람 이력을 읽어 첫 열람/경고를 말함', true, first ? '첫 열람' : await text($('holdout-warn')))
  await shot('3_holdout_confirm')
  if (!first) await page.click($('holdout-understood'))
  await page.waitForFunction(() => { const b = document.querySelector('[data-testid="holdout-confirm-ok"]'); return b && !b.disabled }, { timeout: 10000 })
  await page.click($('holdout-confirm-ok'))
  await page.waitForFunction((id) => location.hash.startsWith('#/results/') && !location.hash.endsWith(id), { timeout: 240000 }, optId)
  const hoId = page.url().split('#/results/')[1]
  runIds.push(hoId)
  await wait($('holdout-section'), 60000)
  const nth = await text($('holdout-nth'))
  check('홀드아웃 결과: 몇 번째 열람인지 표시', /열람/.test(nth), nth.slice(0, 60))
  await wait($('three-way-table'), 30000)
  check('학습·검증·홀드아웃을 나란히 보임', (await text($('three-way-table'))).includes('홀드아웃'))
  await shot('4_holdout_result')

  // ───────── 워크포워드 ─────────
  await page.goto(`${BASE}/#/optimize?from=${optId}`, { waitUntil: 'networkidle2' })
  await wait($('combo-count'), 30000)
  await page.waitForFunction(() => document.querySelector('[data-testid="combo-count"]')?.textContent?.trim() !== '…', { timeout: 30000 })
  await setVary('vol_mult', false)
  await setVary('exit_n', false)
  await page.waitForFunction(() => document.querySelector('[data-testid="combo-count"]')?.textContent?.trim() === '12', { timeout: 30000 })
  await page.waitForFunction(() => { const b = document.querySelector('[data-testid="run-walkforward"]'); return b && !b.disabled }, { timeout: 30000 })
  await page.click($('run-walkforward'))
  await wait($('run-modal'))
  log('워크포워드 실행 중…')
  await page.waitForFunction((a, b) => location.hash.startsWith('#/results/') && !location.hash.endsWith(a) && !location.hash.endsWith(b), { timeout: 480000 }, optId, hoId)
  const wfId = page.url().split('#/results/')[1]
  runIds.push(wfId)
  await wait($('walkforward-section'), 60000)
  const wfe = await text($('wfe-value'))
  check('워크포워드: WFE 값(또는 없음)이 표시됨', wfe.length > 0, wfe)
  await wait($('folds-table'), 30000)
  const foldRows = await page.$$eval('[data-testid="folds-table"] tbody tr', (n) => n.length)
  check('폴드 표에 행이 있음', foldRows >= 1, `folds=${foldRows}`)
  await wait('[data-testid="folds-chart"] canvas', 30000)
  check('폴드별 학습 vs 검증 차트가 그려짐', true)
  await shot('5_walkforward_result')

  // ───────── 실행 기록: 종류 표시 ─────────
  await page.goto(`${BASE}/#/optimize`, { waitUntil: 'networkidle2' })
  await wait($('past-runs'), 30000)
  const past = await text($('past-runs'))
  check('최적화 화면 "지금까지 돌린 검증"에 세 종류가 보임', past.includes('최적화') && past.includes('워크포워드') && past.includes('홀드아웃'))

  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
  await shot('zz_failure').catch(() => {})
} finally {
  for (const id of runIds) {
    const r = await fetch(`${BASE}/api/runs/${id}`, { method: 'DELETE', headers: { Origin: BASE } }).catch(() => null)
    log('삭제', id, r?.status)
  }
  // 홀드아웃 장부: 이 시험이 만든 실행(source_run_id 가 이 시험의 최적화 결과)에서 생긴 기록만 지운다
  try {
    const ledger = path.join(ROOT, 'results', 'studio', 'holdout_ledger.json')
    if (fs.existsSync(ledger)) {
      const d = JSON.parse(fs.readFileSync(ledger, 'utf-8'))
      let removed = 0
      for (const k of Object.keys(d)) {
        const keep = d[k].filter((e) => !runIds.includes(e.source_run_id))
        removed += d[k].length - keep.length
        if (keep.length) d[k] = keep; else delete d[k]
      }
      const tmp = `${ledger}.e2efix`
      fs.writeFileSync(tmp, JSON.stringify(d, null, 2), 'utf-8')
      fs.renameSync(tmp, ledger)
      log('장부에서 이 시험의 열람 기록 제거', removed)
    }
  } catch (e) { log('장부 정리 실패(수동 확인 필요)', String(e)) }
  await browser.close()
  fs.writeFileSync(path.join(OUT, 'm5_results.json'), JSON.stringify(results, null, 1))
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
