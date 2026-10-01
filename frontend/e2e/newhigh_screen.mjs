// 52주 신고가 · 신고가 후보 화면 확인 — 임시 로컬 서버(8765 안 건드림) 대상 (lead 09-28 22:35 편지)
// 사용: node frontend/e2e/newhigh_screen.mjs [baseUrl] [출력폴더]
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8899'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'newhigh_screen')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const errors = []
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1650, height: 1200 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'nh-chrome-')) })
const page = await browser.newPage()
page.on('pageerror', (e) => errors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400 && !r.url().includes('favicon')) errors.push(`HTTP ${r.status()} ${r.url()}`) })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
try {
  await page.goto(`${BASE}/index.html`, { waitUntil: 'networkidle2', timeout: 30000 }).catch(() => {})
  // 사용자 경로: 메인 대시보드(대신 rs.html 을 경유) → "신고가 →" 링크가 index.html 에 있지만 임시서버엔 백엔드 API 가 없어 index.html 이 못 뜬다 —
  // rs.html 의 상단 탭에서 "52주 신고가" 를 눌러 들어가는 경로로 확인한다.
  await page.goto(`${BASE}/rs.html`, { waitUntil: 'networkidle2', timeout: 30000 })
  await page.waitForSelector('.page-tabs a', { timeout: 15000 })
  await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2' }), page.click('#tab-link-new, .page-tabs a[href="/newhigh.html"]').catch(() => page.click('.page-tabs a:nth-child(2)'))])
  await page.waitForSelector('#stat-cards', { timeout: 15000 })
  await sleep(600)
  await page.screenshot({ path: path.join(OUT, 'nh_01_candidates.png'), fullPage: true })
  log('후보 탭 스크린샷 저장')
  const rowCount1 = await page.$eval('#c-row-count', (e) => e.textContent)
  log('후보 탭 종목 수(기본 필터)', rowCount1)

  // 필터 하나 적용: RS 전체로 풀어서 더 보이게
  await page.select('#c-rs-select', '0')
  await sleep(400)
  await page.screenshot({ path: path.join(OUT, 'nh_02_candidates_filtered.png'), fullPage: true })
  const rowCount2 = await page.$eval('#c-row-count', (e) => e.textContent)
  log('후보 탭 종목 수(RS 전체)', rowCount2)

  // 주요종목 탭
  await page.click('#page-seg button[data-tab="new"]')
  await sleep(600)
  await page.screenshot({ path: path.join(OUT, 'nh_03_new_highs.png'), fullPage: true })
  log('주요종목 탭 스크린샷 저장')
  const rowCount3 = await page.$eval('#n-row-count', (e) => e.textContent)
  log('주요종목 탭 종목 수(기본 필터)', rowCount3)
} catch (e) {
  errors.push(String(e))
  await page.screenshot({ path: path.join(OUT, 'nh_zz_failure.png'), fullPage: true }).catch(() => {})
} finally {
  await browser.close()
  log('콘솔/페이지/네트워크 오류', errors.length, errors.slice(0, 8).join(' | '))
  process.exit(0)
}
