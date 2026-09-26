// 18:20 요청 E2E — 가격이 아닌 단위 지표(N봉 등락률(%)·몸통(%)·RSI·정배열 1/0)를 "직접 고르는 경로"(종류=지표 → 지표 고르기)로 골랐을 때 오른쪽이 바로 숫자칸(단위 표시)이 되는지.
// 사용: node e2e/m12.mjs [baseUrl] [출력폴더]  — 실행은 하지 않는다(화면만).
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm12')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm12-chrome-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, t = 60000) => page.waitForSelector(sel, { timeout: t })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const entry = $('group-strategy.entry')
const shot = async (n) => (await page.$(entry)).screenshot({ path: path.join(OUT, `m12_${n}.png`) })
const clickOption = (label, exact = false) => page.evaluate((l, ex) => [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')].find((o) => (ex ? o.textContent.trim() === l : o.textContent.trim().startsWith(l)))?.click(), label, exact)
const opText = () => page.$eval(`${entry} ${$('op-select')}`, (e) => e.innerText.replace(/\s+/g, ' '))
const rowText = () => page.$eval(entry, (e) => e.innerText.replace(/\s+/g, ' '))

// 사용자 경로: 종류 = 지표 → 지표 목록에서 고르기 (왼쪽)
async function pickIndicator(label) {
  await page.click(`${entry} ${$('operand-left-kind')}`); await sleep(400)
  await clickOption('지표', true); await sleep(500)
  await page.click(`${entry} ${$('operand-left-ind')}`); await sleep(500)
  await page.keyboard.type(label.replace(/\(.*/, '')); await sleep(600)
  await clickOption(label, true); await sleep(900)
}
const rightConst = () => page.$eval(`${entry} ${$('operand-right-const')}`, (e) => ({ v: e.value, box: e.closest('[data-testid="operand-right"]')?.innerText.replace(/\s+/g, ' ') })).catch(() => null)

try {
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait($('spec-name')); await wait($('narration'), 30000)
  await page.evaluate(() => [...document.querySelectorAll('.ant-tabs-tab')].find((t) => t.textContent.trim() === '분봉 단타').click())
  await wait($('panel-intraday'), 15000)
  await page.evaluate(() => [...document.querySelectorAll('[data-testid="bar-minutes"] label')].find((l) => l.textContent.trim() === '1분').click())
  await sleep(800)

  // ① N봉 등락률(%) → 기간 1 → 이상
  await pickIndicator('N봉 등락률(%)')
  const p1 = await rightConst()
  check('N봉 등락률(%) 고르면 오른쪽에 "[1] %" 숫자칸이 바로 보임', !!p1 && p1.v === '1' && /%/.test(p1.box), JSON.stringify(p1))
  const n = `${entry} ${$('operand-left-param-n')}`
  if (await page.$(n)) { await page.focus(n); await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control'); await page.keyboard.type('1'); await page.keyboard.press('Tab'); await sleep(400) }
  await page.click(`${entry} ${$('op-select')}`); await sleep(400)
  await clickOption('이상', false); await sleep(700)
  const t1 = await rowText()
  check('연산자 "이상" 까지 골라도 "[1] %" 칸이 그대로', /이상/.test(t1) && /%/.test((await rightConst())?.box ?? ''), t1.slice(0, 160))
  await shot('1_change_pct')

  // ② 몸통(%)
  await pickIndicator('몸통(%)')
  const p2 = await rightConst()
  check('몸통(%) → "[3] %" 숫자칸', !!p2 && p2.v === '3' && /%/.test(p2.box), JSON.stringify(p2))
  await shot('2_body_pct')

  // ③ RSI
  await pickIndicator('RSI')
  const p3 = await rightConst()
  check('RSI → "[30]" 숫자칸', !!p3 && p3.v === '30', JSON.stringify(p3))
  await shot('3_rsi')

  // ④ 정배열(1/0) → 참이면
  await pickIndicator('정배열(1/0)')
  const t4 = await rowText()
  check('정배열(1/0) → 연산자 "참이면", 오른쪽 칸 없음', /^참이면/.test(await opText()) && !(await page.$(`${entry} ${$('operand-right-const')}`)), t4.slice(0, 160))
  await shot('4_ma_aligned')

  // ⑤ 종가(가격)로 되돌리면 원래대로(N봉 최고값 비교, 연산자 초과)
  await page.click(`${entry} ${$('operand-left-kind')}`); await sleep(400)
  await clickOption('가격·거래량', true); await sleep(900)
  const t5 = await rowText()
  check('가격(종가)으로 되돌리면 "N봉 최고값" 비교로 복귀', /최고값/.test(t5) && /^초과/.test(await opText()), t5.slice(0, 160))
  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
  await page.screenshot({ path: path.join(OUT, 'm12_zz_failure.png'), fullPage: true }).catch(() => {})
} finally {
  await browser.close()
  fs.writeFileSync(path.join(OUT, 'm12_results.json'), JSON.stringify(results, null, 1))
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
