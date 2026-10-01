// RS 화면 재구성 확인 — 사용자 경로(메인 → RS 링크 → 필터) 스크린샷 (lead 09-28 22:00 편지)
// 사용: node frontend/e2e/rs_screen.mjs [baseUrl] [출력폴더]
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8765'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'rs_screen')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const errors = []
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1600, height: 1100 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'rs-chrome-')) })
const page = await browser.newPage()
page.on('pageerror', (e) => errors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) errors.push(`HTTP ${r.status()} ${r.url()}`) })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
try {
  // 사용자 경로: 메인 대시보드 → "RS 상위 2% →" 링크
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle2', timeout: 30000 })
  await page.waitForSelector('a[href="/rs.html"]', { timeout: 15000 })
  await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2' }), page.click('a[href="/rs.html"]')])
  await page.waitForSelector('#table-body tr', { timeout: 15000 })
  await sleep(500)
  await page.screenshot({ path: path.join(OUT, 'rs_01_initial.png'), fullPage: true })
  log('초기 화면 스크린샷 저장')

  // 필터: 100억+(당일 거래대금), 코스닥, 섹터 칩 하나
  await page.select('#value-select', '10000000000')
  await page.select('#market-select', '코스닥')
  await sleep(300)
  const chip = await page.evaluateHandle(() => [...document.querySelectorAll('#sector-chips .chip')].find((c) => !c.textContent.includes('전체')))
  if (chip && chip.asElement()) { await chip.asElement().click(); log('섹터 칩 클릭') } else { log('섹터 칩 없음(빈 데이터일 수 있음)') }
  await sleep(500)
  await page.screenshot({ path: path.join(OUT, 'rs_02_filtered.png'), fullPage: true })
  log('필터 적용 화면 스크린샷 저장')

  const rowCount = await page.$eval('#row-count', (e) => e.textContent)
  log('필터 후 종목 수', rowCount)
  const firstRowText = await page.$eval('#table-body tr:first-child', (e) => e.innerText.replace(/\s+/g, ' ')).catch(() => '(없음)')
  log('첫 행', firstRowText)
} catch (e) {
  errors.push(String(e))
  await page.screenshot({ path: path.join(OUT, 'rs_zz_failure.png'), fullPage: true }).catch(() => {})
} finally {
  await browser.close()
  log('콘솔/페이지 오류', errors.length, errors.slice(0, 5).join(' | '))
  process.exit(0)
}
