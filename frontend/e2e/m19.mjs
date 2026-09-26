// 22:06 편지(c12) E2E — 한글 파라미터 라벨이 카드 문장·고급 조립기에 그대로 보이는지.
// 사용: node e2e/m19.mjs [baseUrl] [출력폴더]
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm19')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm19-chrome-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, t = 60000) => page.waitForSelector(sel, { timeout: t })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const entry = $('group-strategy.entry')
const shot = async (n) => (await page.$(entry)).screenshot({ path: path.join(OUT, `m19_${n}.png`) })
const box = (id) => `[data-testid="${id}"]`
try {
  await page.setViewport({ width: 1600, height: 1000 })
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait(box('spec-name')); await wait(box('narration'), 30000)
  await page.evaluate(() => [...document.querySelectorAll('.ant-tabs-tab')].find((t) => t.textContent.trim() === '분봉 단타').click())
  await wait(box('panel-intraday'), 15000); await wait(box('cards-strategy.entry'), 20000)
  for (const q of ['일목 선행스팬1', 'MACD 히스토그램', '스토캐스틱 %D']) {
    await page.click(box('cards-strategy.entry-add')); await wait(box('tpl-picker'), 8000); await sleep(500)
    await page.keyboard.type(q); await sleep(700)
    const first = await page.$('[data-testid^="tpl-"][role="button"]:not([aria-disabled="true"])')
    if (!first) { check(`검색 "${q}"`, false, '없음'); continue }
    await first.click(); await sleep(1800)
  }
  const cards = await page.$$eval(box('cards-strategy.entry') + ' [data-testid="card-sentence"]', (els) => els.map((e) => e.innerText.replace(/\s+/g, ' ')))
  log(JSON.stringify(cards))
  const eng = cards.join(' ')
  check('카드 문장에 영문 파라미터 이름(conv_n·base_n·shift·fast·slow·sig)이 없다', !/conv_n|base_n|span_n|\bshift\b|\bfast\b|\bslow\b|\bsig\b|\bk \d|\bd \d/.test(eng), eng.slice(0, 200))
  check('한글 라벨: 전환선·기준선 기간', /전환선 기간/.test(eng) && /기준선 기간/.test(eng), '')
  const top = await (await page.$(box('cards-strategy.entry'))).boundingBox()
  await page.screenshot({ path: path.join(OUT, 'm19_1_cards.png'), clip: { x: 0, y: Math.max(0, top.y - 10), width: 1250, height: Math.min(700, top.height + 20) }, captureBeyondViewport: true })
  // 고급 조립기
  await page.evaluate(() => [...document.querySelectorAll('[data-testid="cards-strategy.entry-view"] label')].find((l) => /직접 조립/.test(l.textContent)).click()); await sleep(1200)
  const adv = await page.$eval(box('group-strategy.entry'), (e) => e.innerText.replace(/\s+/g, ' '))
  check('고급 조립기 파라미터 라벨이 한글(전환선·빠른 평균 등)', /전환선 기간|빠른 평균 기간|%D 평활 기간/.test(adv) && !/conv_n /.test(adv), adv.slice(0, 200))
  const top2 = await (await page.$(box('group-strategy.entry'))).boundingBox()
  await page.screenshot({ path: path.join(OUT, 'm19_2_advanced.png'), clip: { x: 0, y: Math.max(0, top2.y - 10), width: 1250, height: Math.min(800, top2.height + 20) }, captureBeyondViewport: true })
  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
  await page.screenshot({ path: path.join(OUT, 'm19_zz_failure.png') }).catch(() => {})
} finally {
  await browser.close()
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
