// 거래대금 폭발 화면 확인 — 임시 로컬 서버(8765 안 건드림) 대상, 사용자 경로(RS 화면 위 탭 → 거래대금 폭발)
// 사용: node frontend/e2e/burst_screen.mjs [baseUrl] [출력폴더]
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8899'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'burst_screen')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const errors = []
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1100 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'vb-chrome-')) })
const page = await browser.newPage()
page.on('pageerror', (e) => errors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400 && !r.url().includes('favicon') && !r.url().includes('/api/')) errors.push(`HTTP ${r.status()} ${r.url()}`) })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
try {
  await page.goto(`${BASE}/rs.html`, { waitUntil: 'networkidle2', timeout: 30000 })
  await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2' }), page.click('.page-tabs a[href="/burst.html"]')])
  await page.waitForSelector('#table-body tr', { timeout: 15000 })
  await sleep(400)
  await page.screenshot({ path: path.join(OUT, 'vb_01_default.png'), fullPage: true })
  console.log('기본(1,000억+) 종목 수', await page.$eval('#row-count', (e) => e.textContent))
  // 사용자가 찾던 형태: 4년 이상 · 1,000억+ · 폭발일 +7% 이상
  await page.select('#tier-select', '1')
  await page.select('#chg-select', '7')
  await sleep(300)
  await page.screenshot({ path: path.join(OUT, 'vb_02_4y_7pct.png'), fullPage: true })
  console.log('4년+·+7% 종목 수', await page.$eval('#row-count', (e) => e.textContent))
  console.log('종목', await page.$$eval('#table-body .name-main', (els) => els.map((e) => e.textContent).join(', ')))
  // 마우스 오버 240일봉(5·10·20일선) — 두 번째 줄(심텍)
  const tr = await page.$('#table-body tr:nth-child(2)')
  const box = await tr.boundingBox()
  await page.mouse.move(box.x + 200, box.y + box.height / 2)
  await sleep(400)
  console.log('오버 차트 보임', await page.$eval('#hover-chart', (e) => !e.hidden && e.querySelectorAll('polyline').length))
  await page.screenshot({ path: path.join(OUT, 'vb_04_hover.png') })
  await page.mouse.move(5, 5)
  await page.setViewport({ width: 390, height: 900 })
  await sleep(300)
  await page.screenshot({ path: path.join(OUT, 'vb_03_mobile.png'), fullPage: false })
} finally {
  console.log('오류', errors.length ? errors : '없음')
  await browser.close()
}
