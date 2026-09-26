// 21:46 요청 E2E — 문장 카드 목록 126장: 분류 접기·검색(엔벨로프·CCI·일목)·기본 문장 표시.
// 사용: node e2e/m16.mjs [baseUrl] [출력폴더]
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm16')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm16-chrome-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, t = 60000) => page.waitForSelector(sel, { timeout: t })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const entry = $('group-strategy.entry')
const shot = async (n) => (await page.$(entry)).screenshot({ path: path.join(OUT, `m16_${n}.png`) })
const box = (id) => `[data-testid="${id}"]`
const shotPicker = (n) => page.screenshot({ path: path.join(OUT, `m16_${n}.png`), clip: { x: 300, y: 60, width: 900, height: 780 } })
try {
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait(box('spec-name')); await wait(box('narration'), 30000)
  await page.evaluate(() => [...document.querySelectorAll('.ant-tabs-tab')].find((t) => t.textContent.trim() === '분봉 단타').click())
  await wait(box('panel-intraday'), 15000); await wait(box('cards-strategy.entry'), 20000)
  await page.click(box('cards-strategy.entry-add')); await wait(box('tpl-picker'), 8000); await sleep(600)
  const c0 = await page.$eval(box('tpl-count'), (e) => e.innerText)
  const rows0 = (await page.$$('[data-testid^="tpl-"][role="button"]')).length
  check('처음엔 분류만 보이고 문장 카드는 접혀 있다', rows0 === 0 && /분류를 눌러/.test(c0), `${c0} / 펼친 문장 ${rows0}`)
  check('전체 문장 수 표시(126 전후)', /문장 1\d\d개/.test(c0), c0)
  await shotPicker('1_collapsed')
  for (const [q, want] of [['엔벨로프', /엔벨로프/], ['CCI', /CCI/i], ['일목', /일목/]]) {
    await page.click(`${box('tpl-search')} input`); await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control'); await page.keyboard.press('Backspace'); await page.keyboard.type(q); await sleep(700)
    const txt = await page.$eval(box('tpl-list'), (e) => e.innerText.replace(/\s+/g, ' '))
    const n = (await page.$$('[data-testid^="tpl-"][role="button"]')).length
    check(`검색 "${q}" → 문장이 나온다`, n > 0 && want.test(txt), `${n}개 · ${txt.slice(0, 90)}`)
    if (q === '엔벨로프') await shotPicker('2_search_envelope')
    if (q === '일목') { check('자동 문장에 "기본 문장" 표시', /기본 문장/.test(txt), ''); await shotPicker('2b_search_ichimoku') }
  }
  // 엔벨로프 문장 하나를 고른다
  await page.click(`${box('tpl-search')} input`); await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control'); await page.keyboard.press('Backspace'); await page.keyboard.type('일목 선행스팬1'); await sleep(700)
  const first = await page.$('[data-testid^="tpl-"][role="button"]:not([aria-disabled="true"])')
  await first.click(); await sleep(2500)
  const cards = await page.$$eval(box('cards-strategy.entry') + ' [data-testid^="card-"]', (els) => els.map((e) => e.getAttribute('data-testid')).filter((t) => /^card-[a-z_0-9]+$/.test(t) && !/^card-(slot|sentence|hint|warn|error|built|auto)/.test(t)))
  const autoTag = await page.$(box('cards-strategy.entry') + ' ' + box('card-auto'))
  check('고른 자동 문장(일목 선행스팬1)이 카드로 붙고 "기본 문장" 표시', cards.length >= 1 && !!autoTag, cards.join(','))
  const top = await (await page.$(box('cards-strategy.entry'))).boundingBox()
  await page.screenshot({ path: path.join(OUT, 'm16_3_card.png'), clip: { x: Math.max(0, top.x - 20), y: top.y - 10, width: 1000, height: Math.min(400, top.height + 20) }, captureBeyondViewport: true })
  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
  await page.screenshot({ path: path.join(OUT, 'm16_zz_failure.png'), fullPage: true }).catch(() => {})
} finally {
  await browser.close()
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
