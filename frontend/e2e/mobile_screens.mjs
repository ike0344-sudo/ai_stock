// 시장 화면 5개(RS 상위·52주 신고가·신고가 후보·신고가 장부·거래대금 폭발) 휴대폰 너비 스크린샷 — 위쪽 탭을 눌러 이동(사용자 경로)
// 사용: node frontend/e2e/mobile_screens.mjs [baseUrl] [출력폴더] [폭]
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8765'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'mobile_screens')
const W = Number(process.argv[4] ?? 390)
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: W, height: 860, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'mob-chrome-')) })
const page = await browser.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(String(e)))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
try {
  await page.goto(`${BASE}/rs.html`, { waitUntil: 'networkidle2', timeout: 30000 })
  const tabs = ['RS 상위', '52주 신고가', '신고가 후보', '신고가 장부', '거래대금 폭발']
  for (const [k, label] of tabs.entries()) {
    const links = await page.$$('.page-tabs a')
    for (const a of links) {
      if ((await a.evaluate((e) => e.textContent.trim())) === label) {
        await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 15000 }).catch(() => {}), a.click()])
        break
      }
    }
    await sleep(900)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    console.log(label, '가로 넘침(px)', overflow)
    await page.screenshot({ path: path.join(OUT, `m${k + 1}.png`) })
  }
} finally {
  console.log('오류', errors.length ? errors : '없음')
  await browser.close()
}
