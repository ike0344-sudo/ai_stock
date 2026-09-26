// 22:05 요청 E2E — [조건 추가] 목록을 접지 않고 전부 보이기: 처음 연 화면·분류 버튼 스크롤·엔벨로프 검색.
// 사용: node e2e/m18.mjs [baseUrl] [출력폴더]
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm18')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm18-chrome-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, t = 60000) => page.waitForSelector(sel, { timeout: t })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const entry = $('group-strategy.entry')
const shot = async (n) => (await page.$(entry)).screenshot({ path: path.join(OUT, `m18_${n}.png`) })
const box = (id) => `[data-testid="${id}"]`
const clear = async () => { await page.click(`${box('tpl-search')} input`); await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control'); await page.keyboard.press('Backspace') }
const shotModal = (n) => page.screenshot({ path: path.join(OUT, `m18_${n}.png`) })
try {
  await page.setViewport({ width: 1600, height: 1000 })
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait(box('spec-name')); await wait(box('narration'), 30000)
  await page.evaluate(() => [...document.querySelectorAll('.ant-tabs-tab')].find((t) => t.textContent.trim() === '분봉 단타').click())
  await wait(box('panel-intraday'), 15000); await wait(box('cards-strategy.entry'), 20000)
  await page.click(box('cards-strategy.entry-add')); await wait(box('tpl-picker'), 8000); await sleep(800)
  const n0 = (await page.$$('[data-testid^="tpl-"][role="button"]')).length
  const groupsOpen = await page.$$eval('[data-testid^="tpl-group-"]', (els) => els.map((e) => e.getAttribute('data-testid') + ':' + e.querySelectorAll('[role="button"]').length))
  const count = await page.$eval(box('tpl-count'), (e) => e.innerText)
  check('처음 열면 문장 121개가 전부 펼쳐져 있다(접힌 것 없음)', n0 === 121, `${n0}개 · ${groupsOpen.join(' ')}`)
  check('"접힘" 안내 문구가 없다', !/눌러 펼치/.test(count), count)
  // 화면에 실제로 보이는 문장 수(스크롤 안 하고)
  const vis = await page.evaluate(() => { const box = document.querySelector('[data-testid="tpl-list"]').getBoundingClientRect(); return [...document.querySelectorAll('[data-testid^="tpl-"][role="button"]')].filter((e) => { const r = e.getBoundingClientRect(); return r.top >= box.top && r.bottom <= box.bottom }).length })
  const cols = await page.evaluate(() => { const g = document.querySelector('[data-testid^="tpl-group-"] > div:nth-child(2)'); return getComputedStyle(g).gridTemplateColumns.split(' ').length })
  log('스크롤 없이 보이는 문장', vis, '열', cols)
  check('여러 열로 배치(2열 이상)', cols >= 2, `${cols}열, 스크롤 없이 ${vis}개`)
  await shotModal('1_opened_all')
  // 분류 버튼 → 스크롤(다른 분류는 그대로)
  const before = await page.$eval(box('tpl-list'), (e) => e.scrollTop)
  await page.click(box('tpl-cat-indicator')); await sleep(1200)
  const after = await page.$eval(box('tpl-list'), (e) => e.scrollTop)
  const n1 = (await page.$$('[data-testid^="tpl-"][role="button"]')).length
  check('분류 버튼을 누르면 그 분류로 스크롤(다른 분류는 안 숨김)', after > before && n1 === 121, `scrollTop ${before} → ${after}, 문장 ${n1}개`)
  await shotModal('2_category_jump')
  await clear(); await page.keyboard.type('엔벨로프'); await sleep(900)
  const en = (await page.$$('[data-testid^="tpl-"][role="button"]')).length
  check('검색 "엔벨로프" → 3개로 거름', en === 3, String(en))
  await shotModal('3_search_envelope')
  await clear(); await sleep(600)
  check('검색을 지우면 다시 121개 전부', (await page.$$('[data-testid^="tpl-"][role="button"]')).length === 121)
  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
  await page.screenshot({ path: path.join(OUT, 'm18_zz_failure.png') }).catch(() => {})
} finally {
  await browser.close()
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
