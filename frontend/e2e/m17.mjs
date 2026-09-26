// 21:25 요청 E2E — 엔벨로프 사용자 경로: [조건 추가] → 엔벨로프 검색 → 카드 → 숫자 입력 → 검증 통과 + 분류별 개수·일목·CCI 검색.
// 사용: node e2e/m17.mjs [baseUrl] [출력폴더]
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm17')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm17-chrome-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, t = 60000) => page.waitForSelector(sel, { timeout: t })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const entry = $('group-strategy.entry')
const shot = async (n) => (await page.$(entry)).screenshot({ path: path.join(OUT, `m17_${n}.png`) })
const box = (id) => `[data-testid="${id}"]`
const clear = async () => { await page.click(`${box('tpl-search')} input`); await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control'); await page.keyboard.press('Backspace') }
const rowsN = async () => (await page.$$('[data-testid^="tpl-"][role="button"]')).length
try {
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait(box('spec-name')); await wait(box('narration'), 30000)
  await page.evaluate(() => [...document.querySelectorAll('.ant-tabs-tab')].find((t) => t.textContent.trim() === '분봉 단타').click())
  await wait(box('panel-intraday'), 15000); await wait(box('cards-strategy.entry'), 20000)
  await page.click(box('cards-strategy.entry-add')); await wait(box('tpl-picker'), 8000); await sleep(600)

  // 분류별 개수(접힌 머리글의 "(N)")
  const cats = await page.$$eval('[data-testid^="tpl-cat-"]', (els) => els.map((e) => e.innerText.replace(/\s+/g, ' ')))
  const sum = cats.reduce((n, c) => n + Number((c.match(/\((\d+)\)/) ?? [0, 0])[1]), 0)
  log('분류별', cats.join(' | '), '합', sum)
  check('분류별 목록이 뜬다(분류 7개, 진입 자리 합계 121장)', cats.length === 7 && sum === 121, `${cats.length}개 분류 합 ${sum}`)
  await page.screenshot({ path: path.join(OUT, 'm17_1_categories.png'), clip: { x: 300, y: 60, width: 900, height: 700 } })

  for (const q of ['CCI', '일목']) {
    await clear(); await page.keyboard.type(q); await sleep(700)
    const n = await rowsN(); const txt = await page.$eval(box('tpl-list'), (e) => e.innerText.replace(/\s+/g, ' '))
    check(`검색 "${q}" → 문장`, n > 0 && new RegExp(q, 'i').test(txt), `${n}개 · ${txt.slice(0, 70)}`)
  }
  await clear(); await page.keyboard.type('엔벨로프'); await sleep(800)
  const en = await rowsN()
  check('검색 "엔벨로프" → 3개(위쪽 뚫음·아래쪽 뚫음·저가 닿음)', en === 3, String(en))
  await page.screenshot({ path: path.join(OUT, 'm17_2_search_envelope.png'), clip: { x: 300, y: 60, width: 900, height: 620 } })
  // 위쪽 선 뚫음 카드 고르기
  const ids = await page.$$eval('[data-testid^="tpl-"][role="button"]', (els) => els.map((e) => [e.getAttribute('data-testid'), e.innerText.replace(/\s+/g, ' ').slice(0, 60)]))
  log('엔벨로프 문장', JSON.stringify(ids))
  await page.click(`[data-testid="${ids.find((x) => /위쪽/.test(x[1]))[0]}"]`); await sleep(2500)
  const card = await page.evaluateHandle(() => [...document.querySelectorAll('[data-testid="cards-strategy.entry"] [data-testid^="card-"]')].find((e) => /엔벨로프/.test(e.innerText) && e.getAttribute('data-testid').startsWith('card-') && !/-plain$/.test(e.getAttribute('data-testid'))))
  const cid = await card.evaluate((e) => e?.getAttribute('data-testid'))
  check('카드가 붙음(엔벨로프 문장, 빈칸이 입력칸)', !!cid, String(cid))
  // 숫자 입력: 카드 안 첫 숫자칸(평균 봉 수)을 20 → 30
  const slot = `[data-testid="${cid}"] [data-testid^="card-slot-"] `
  const nums = await page.$$eval(`[data-testid="${cid}"] input[data-testid^="card-slot-"]`, (els) => els.map((e) => [e.getAttribute('data-testid'), e.value]))
  log('숫자칸', JSON.stringify(nums))
  const [sid, before] = nums[0]
  await page.focus(`[data-testid="${cid}"] [data-testid="${sid}"]`); await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control'); await page.keyboard.type('30'); await page.keyboard.press('Tab'); await sleep(1800)
  const after = await page.$eval(`[data-testid="${cid}"] [data-testid="${sid}"]`, (e) => e.value)
  check('숫자 입력(평균 봉 수 → 30)', after === '30', `${before} → ${after}`)
  const nar = await page.waitForFunction(() => /엔벨로프|봉 이동평균/.test(document.querySelector('[data-testid="narration"]')?.textContent ?? ''), { timeout: 30000 }).then(() => page.$eval(box('narration'), (e) => e.textContent.replace(/\s+/g, ' '))).catch(() => '')
  log('풀이', nar.slice(0, 160))
  const ok = await page.waitForSelector(box('validation-ok'), { timeout: 30000 }).then(() => true).catch(() => false)
  check('검증 통과 — 실행할 수 있습니다', ok, ok ? '' : await page.$eval(box('validation-panel'), (e) => e.innerText.slice(0, 200)).catch(() => 'no panel'))
  const top = await (await page.$(box('cards-strategy.entry'))).boundingBox()
  await page.screenshot({ path: path.join(OUT, 'm17_3_card_valid.png'), clip: { x: 0, y: Math.max(0, top.y - 20), width: 1500, height: 420 }, captureBeyondViewport: true })
  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
  await page.screenshot({ path: path.join(OUT, 'm17_zz_failure.png'), fullPage: true }).catch(() => {})
} finally {
  await browser.close()
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
