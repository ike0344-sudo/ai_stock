// studio-conditions c6 E2E — 진짜 Chrome 으로 진짜 서버(기본 8780):
//   ① 지표 선택창(분류·검색·비활성 이유) ② 레시피 "이평 골든크로스" → 실행 → 결과 ③ 레시피 "분봉 N일 신고가 돌파"(시간 단위) → 실행 → 결과
//   ④ 수식 → 검사(오류 위치) → 저장 → 조건에 넣기 → 실행 → 결과 ⑤ 새 연산자·포지션 피연산자
// 사용: node e2e/m7.mjs [baseUrl] [출력폴더]      끝에 만든 실행 결과·수식을 API 로 지운다.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm7')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })

const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }

const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm7prof-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
// 문법 오류를 일부러 낸 검사(422 FORMULA_INVALID)의 브라우저 콘솔 문구는 정상이라 거른다
page.on('console', (m) => { if (m.type() === 'error' && !/status of 422/.test(m.text())) pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400 && !r.url().includes('/api/formulas/check')) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const shot = (name) => page.screenshot({ path: path.join(OUT, `m7_${name}.png`), fullPage: true })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, timeout = 60000) => page.waitForSelector(sel, { timeout })
const text = (sel) => page.$eval(sel, (e) => e.textContent ?? '')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const runIds = []
const formulaNames = []

async function openBacktest() {
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait($('spec-name'))
  await wait($('narration'), 30000)
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
async function applyRecipe(id) {
  await page.click($('recipe-open'))
  await wait($('recipe-modal'))
  await wait($(`recipe-${id}-apply`), 15000)
  await page.evaluate((i) => document.querySelector(`[data-testid="recipe-${i}-apply"]`).click(), id)
  await page.waitForFunction(() => !document.querySelector('[data-testid="recipe-modal"]') || getComputedStyle(document.querySelector('.ant-modal-wrap')).display === 'none', { timeout: 10000 }).catch(() => {})
  await sleep(600)
}

try {
  // ───────── ① 지표 선택창 ─────────
  await openBacktest()
  const caps = await page.evaluate(async () => (await (await fetch('/api/meta/indicators')).json()).data.capabilities)
  check('서버 능력: 시간 단위·hold·negate·pos·수식이 켜져 있다', !!caps.timeframes && caps.condition_fields.includes('hold') && caps.group_fields.includes('negate') && caps.operand_kinds.includes('pos') && caps.formulas === true, JSON.stringify(caps).slice(0, 120))
  const entry = `${$('group-strategy.entry')}`
  await page.click(`${entry} ${$('operand-right-ind')}`)
  await sleep(500)
  await page.keyboard.type('vwap')
  await sleep(700)
  const dd = await page.evaluate(() => [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')].map((d) => d.innerText).join('\n'))
  check('지표 검색("vwap"): 비활성이어도 찾아지고 이유가 보이며 다른 지표는 걸러진다', /VWAP/.test(dd) && /분봉 조건에서만 쓸 수 있다/.test(dd) && !/이동평균/.test(dd), dd.replace(/\s+/g, ' ').slice(0, 100))
  await shot('1_indicator_search')
  await page.keyboard.press('Escape')
  await sleep(300)
  await page.click(`${entry} ${$('operand-right-ind')}`)
  await sleep(500)
  const dd2 = await page.evaluate(() => [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')].map((d) => d.innerText).join('\n'))
  check('지표 목록에 분류 이름이 보인다', /가격·이평·신고가/.test(dd2), dd2.replace(/\s+/g, ' ').slice(0, 80))
  await page.keyboard.press('Escape')

  // ───────── ② 레시피(일봉) ─────────
  await openBacktest()
  await applyRecipe('golden_cross')
  const note = await text($('load-note'))
  check('레시피 불러오기 안내', note.includes('이평 골든크로스'), note.slice(0, 60))
  await page.waitForFunction(() => /5일 이동평균/.test(document.querySelector('[data-testid="narration"]')?.textContent ?? ''), { timeout: 30000 }).catch(() => {})
  const nar = await text($('narration')).catch(() => '')
  check('풀이 문장이 레시피 조건으로 바뀜(5일선·20일선)', /5일 이동평균/.test(nar) && /20일 이동평균/.test(nar), nar.replace(/\s+/g, ' ').slice(0, 90))
  await shot('2_recipe_daily')
  await runAndWait('레시피(골든크로스)')
  check('레시피 결과: 지표 카드', true)

  // ───────── ③ 분봉 N일 신고가(시간 단위) ─────────
  await openBacktest()
  await applyRecipe('intraday_daily_high_break')
  await wait($('panel-intraday'), 15000)
  const tfText = await page.$$eval('[data-testid="operand-right-tf"]', (n) => n.map((e) => e.textContent))
  check('분봉 레시피: 오른쪽 피연산자의 시간 단위가 "일봉(전일 확정)"', tfText.some((t) => t.includes('일봉(전일 확정)')), tfText.join('|'))
  await page.waitForFunction(() => /전일/.test(document.querySelector('[data-testid="narration"]')?.textContent ?? ''), { timeout: 30000 }).catch(() => {})
  const nar2 = await text($('narration'))
  check('풀이 문장에 시간 단위가 보인다(전일)', /전일/.test(nar2), nar2.replace(/\s+/g, ' ').slice(0, 120))
  await shot('3_recipe_intraday_tf')
  await runAndWait('분봉 N일 신고가', 300000)
  const warn = await text($('result-page')).catch(() => '')
  check('분봉 결과 화면(커버리지 카드)', !!(await page.$($('intraday-coverage'))))
  await shot('4_recipe_intraday_result')

  // ───────── ④ 수식 ─────────
  await openBacktest()
  await wait($('formula-panel'), 15000)
  check('수식 편집기가 열려 있다(준비 중 문구 아님)', !(await page.$($('formula-pending'))))
  await page.type($('formula-text'), 'C > ')
  await page.click($('formula-check'))
  await wait($('formula-error'), 15000)
  const caret = await text($('formula-caret'))
  check('문법 오류: 줄·칸과 ^ 표시', /1줄 \d+칸/.test(caret) && caret.includes('^'), caret.replace(/\n/g, ' / ').slice(0, 90))
  await shot('5_formula_error')
  await page.focus($('formula-text'))
  await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control')
  await page.keyboard.press('Backspace')
  await page.type($('formula-text'), 'C > HIGHEST(H,20) AND V > 2 * V(1)')
  await page.click($('formula-check'))
  await wait($('formula-ok'), 15000)
  check('수식 검사 통과 + 풀이 문장', (await text($('formula-ok'))).length > 8, (await text($('formula-ok'))).slice(0, 80))
  await page.type($('formula-name'), 'E2E수식')
  formulaNames.push('E2E수식')
  await page.click($('formula-save'))
  await wait($('formula-load-E2E수식'), 15000)
  check('저장 → 내 수식 목록에 나타남', true)
  const before = await page.$$eval('[data-testid^="row-strategy.entry.items."]', (n) => n.length)
  await page.click($('formula-insert-entry'))
  await sleep(1200)
  const after = await page.$$eval('[data-testid^="row-strategy.entry.items."]', (n) => n.length)
  check('[진입 조건에 넣기] → 조건 행이 늘어남', after > before, `${before} → ${after}`)
  await wait($('validation-ok'), 30000)
  await shot('6_formula_inserted')
  await runAndWait('수식 조건 실행')
  check('수식 조건 결과', true)

  // ───────── ⑤ 새 연산자·포지션 ─────────
  await openBacktest()
  await page.click(`${$('group-strategy.entry')} ${$('op-select')}`)
  await sleep(400)
  await page.evaluate(() => [...document.querySelectorAll('.ant-select-item-option')].find((o) => o.textContent.includes('최근 N봉 안에 위로 돌파'))?.click())
  await wait(`${$('group-strategy.entry')} ${$('within-input')}`, 8000)
  check('N봉 이내 크로스: N 칸이 생김', true)
  await page.click(`${$('group-strategy.exit')} ${$('operand-left-kind')}`)
  await sleep(400)
  await page.evaluate(() => [...document.querySelectorAll('.ant-select-item-option')].find((o) => o.textContent.trim() === '포지션')?.click())
  await wait(`${$('group-strategy.exit')} ${$('operand-left-pos')}`, 8000)
  check('청산 조건에서 포지션 피연산자를 고를 수 있다', true)
  const pend = await text($('exits-advanced-pending')).catch(() => '')
  log('청산 고급 칸 상태:', pend ? '서버 준비 중 안내' : '서버가 알림(칸 표시)')
  await shot('7_ops_pos')

  // ───────── ⑥ 청산 고급 칸(c2): 분할 익절 + 본전 손절 → 실행 → 조각 행 ─────────
  await openBacktest()
  const panelSel = $('panel-exits')
  await page.waitForSelector(`${panelSel} ${$('exit-levels-on')}`, { timeout: 10000 })
  check('청산 고급 칸이 나타남(서버 준비 중 문구 아님)', !(await page.$($('exits-advanced-pending'))))
  await page.click(`${panelSel} ${$('exit-levels-on')}`)
  await page.click(`${panelSel} ${$('exit-breakeven_after_pct-on')}`)
  await sleep(800)
  check('분할 익절 켜면 단일 익절이 꺼짐', await page.$eval(`${panelSel} ${$('exit-take_profit_pct-on')}`, (e) => e.getAttribute('aria-checked') === 'false'))
  await shot('8_exits_levels')
  await runAndWait('분할 익절 실행')
  await page.waitForSelector($('slice-tag'), { timeout: 30000 })
  const tags = await page.$$eval($('slice-tag'), (n) => n.slice(0, 4).map((e) => e.textContent))
  check('결과: 거래 표에 조각 표시(1/2 …)', tags.some((t) => /\d\/[2-9]/.test(t)), tags.join(' '))
  const warnTxt = await text($('warning-badges'))
  check('결과: "진입 기준(조각 합산)" 경고', /진입 기준\(조각 합산\)/.test(warnTxt))
  await shot('9_exits_levels_result')

  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
  await shot('zz_failure').catch(() => {})
} finally {
  for (const id of runIds) {
    const r = await fetch(`${BASE}/api/runs/${id}`, { method: 'DELETE', headers: { Origin: BASE } }).catch(() => null)
    log('삭제 실행', id, r?.status)
  }
  for (const n of formulaNames) {
    const r = await fetch(`${BASE}/api/formulas/${encodeURIComponent(n)}`, { method: 'DELETE', headers: { Origin: BASE } }).catch(() => null)
    log('삭제 수식', n, r?.status)
  }
  await browser.close()
  fs.writeFileSync(path.join(OUT, 'm7_results.json'), JSON.stringify(results, null, 1))
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
