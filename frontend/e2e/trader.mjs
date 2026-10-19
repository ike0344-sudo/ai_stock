// 매매 데스크 확인 (10-19) — 사용: node frontend/e2e/trader.mjs [baseUrl] [출력폴더]
// 사용자 경로대로: 종목 칸에 코드 입력 → Enter → 목록·차트 칸·주문 칸에 그 종목이 뜨고, 호가 칸·잔고 탭이 그려지고,
// '매수·청산 규칙'을 누르면 규칙 화면(조건·분할 매수·시간 구간·분할 익절·안전장치)이 나온다. 콘솔 오류 0, 가로 넘침 없음.
// 주문 버튼은 누르지 않는다(앱키가 있으면 실제 주문이 나간다).
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8790'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'trader')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const errors = []
const fail = (m) => { console.log('실패:', m); process.exitCode = 1 }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'td-chrome-')) })

for (const [name, vp] of [['pc', { width: 1600, height: 1000 }], ['phone', { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }]]) {
  const page = await browser.newPage()
  page.on('pageerror', (e) => errors.push(`${name} ${e}`))
  page.on('console', (m) => { if (m.type() === 'error' && !/favicon|503|Service Unavailable/.test(m.text() + (m.location()?.url ?? ''))) errors.push(`${name} ${m.text()}`) })
  await page.setViewport(vp)
  await page.goto(BASE, { waitUntil: 'networkidle0', timeout: 60000 })
  await page.type('#add', '005930')
  await page.keyboard.press('Enter')
  await page.waitForFunction(() => document.querySelector('#wlist [data-pick="005930"]'), { timeout: 15000 })
  await sleep(2500)
  const c = await page.evaluate(() => ({
    watch: document.querySelectorAll('#wlist .w').length, charts: document.querySelectorAll('#charts .ch').length,
    order: document.getElementById('oName').textContent, book: document.getElementById('book').textContent.trim().length > 0,
    tabs: document.querySelectorAll('#tabs [data-t]').length, ladder: document.querySelectorAll('#ladRows .lad').length,
  }))
  if (!c.watch || !c.charts || !c.order.includes('삼성') || !c.book || c.tabs !== 4 || !c.ladder) fail(`${name} 매매 화면 ${JSON.stringify(c)}`)
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true })
  await page.click('#toRules')
  await page.waitForSelector('#rulesView .cond, #rulesView #cAdd', { timeout: 10000 })
  const r = await page.evaluate(() => ({
    rules: document.querySelectorAll('#rulesView .rl').length, times: document.querySelectorAll('#rulesView input[type=time]').length,
    takes: document.querySelectorAll('#rulesView [data-tkp]').length, safety: document.querySelectorAll('#rulesView [data-sf]').length,
  }))
  if (r.rules < 2 || r.times < 4 || r.takes < 2 || r.safety !== 4) fail(`${name} 규칙 화면 ${JSON.stringify(r)}`)
  await page.screenshot({ path: path.join(OUT, `${name}_rules.png`), fullPage: true })
  const w = await page.evaluate(() => document.documentElement.scrollWidth)
  if (w > vp.width) fail(`${name} 가로 넘침 ${w}`)
  await page.click('#toRules')
  await page.evaluate(() => fetch('/api/watch/005930', { method: 'DELETE' }))
  console.log(name, JSON.stringify(c), JSON.stringify(r))
}
if (errors.length) fail(errors.join('\n'))
await browser.close()
console.log(process.exitCode ? '끝(실패 있음)' : '끝 — 실패 0', OUT)
