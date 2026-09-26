// 19:12 요청 E2E — 분봉 새 백테스트: 진입·청산 기본 조건이 둘 다 문장 카드로 보이는지(문장에 안 맞는 행 없음).
// 사용: node e2e/m14.mjs [baseUrl] [출력폴더]
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm14')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm14-chrome-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, t = 60000) => page.waitForSelector(sel, { timeout: t })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const entry = $('group-strategy.entry')
const shot = async (n) => (await page.$(entry)).screenshot({ path: path.join(OUT, `m14_${n}.png`) })
const box = (id) => `[data-testid="${id}"]`
try {
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait(box('spec-name')); await wait(box('narration'), 30000)
  await page.evaluate(() => [...document.querySelectorAll('.ant-tabs-tab')].find((t) => t.textContent.trim() === '분봉 단타').click())
  await wait(box('panel-intraday'), 15000)
  await wait(box('cards-strategy.exit'), 20000)
  // match 가 돌아올 때까지(골격 스켈레톤이 사라질 때까지)
  await page.waitForFunction(() => document.querySelectorAll('.ant-skeleton').length === 0 && document.querySelector('[data-testid="cards-strategy.exit"] [data-testid^="card-"]'), { timeout: 30000 }).catch(() => {})
  await sleep(800)
  const info = await page.evaluate(() => ['entry', 'exit'].map((r) => {
    const g = document.querySelector(`[data-testid="cards-strategy.${r}"]`)
    return { r, cards: [...g.querySelectorAll('[data-testid^="card-"]')].map((e) => e.getAttribute('data-testid')).filter((t) => !/-plain$|^card-slot|^card-strategy|^card-sentence|^card-hint|^card-warn|^card-error|^card-built/.test(t)), plain: g.querySelectorAll('[data-testid$="-plain"]').length, text: g.innerText.replace(/\s+/g, ' ').slice(0, 200) }
  }))
  log(JSON.stringify(info))
  check('진입 조건이 문장 카드', info[0].cards.length >= 1 && info[0].plain === 0, info[0].cards.join(','))
  check('청산 조건이 문장 카드(low_break_bars)', info[1].cards.includes('card-low_break_bars') && info[1].plain === 0, info[1].cards.join(',') + ' ' + info[1].text)
  const top = await (await page.$(box('cards-strategy.entry'))).boundingBox()
  const bot = await (await page.$(box('cards-strategy.exit'))).boundingBox()
  await page.screenshot({ path: path.join(OUT, 'm14_cards_intraday.png'), clip: { x: Math.max(0, top.x - 20), y: top.y - 60, width: Math.min(1100, 1480 - top.x), height: bot.y + bot.height - top.y + 80 }, captureBeyondViewport: true })
  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
  await page.screenshot({ path: path.join(OUT, 'm14_zz_failure.png'), fullPage: true }).catch(() => {})
} finally {
  await browser.close()
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
