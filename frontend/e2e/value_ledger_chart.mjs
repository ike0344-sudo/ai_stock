// 신고대금 장부 줄 차트 확인 — 임시 로컬 서버(8765 안 건드림) 대상 (lead 10-15)
// 사용: node frontend/e2e/value_ledger_chart.mjs [baseUrl] [출력폴더]
// PC: 달을 골라 줄에 마우스를 올린다 → 차트·신고일 표시. 휴대폰: 줄 탭 → 열림, 같은 줄 탭 → 닫힘, 다른 줄 → 바뀜, 바깥 탭 → 닫힘.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8799'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'value_ledger_chart')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const errors = []
const fail = (m) => { console.log('실패:', m); process.exitCode = 1 }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'vl-chrome-')) })

async function open(viewport) {
  const page = await browser.newPage()
  page.on('pageerror', (e) => errors.push(String(e)))
  page.on('console', (m) => { if (m.type() === 'error' && !(m.location()?.url ?? '').endsWith('/favicon.ico')) errors.push(`${m.text()} ${m.location()?.url ?? ''}`) })
  await page.setViewport(viewport)
  await page.goto(`${BASE}/value_ledger.html`, { waitUntil: 'networkidle0' })
  await page.waitForSelector('#table-body tr[data-i]')
  // 사용자 경로: 2024년 3월 칸을 누른다
  await page.click('button.mcell[data-m="2024-03"]')
  await page.waitForSelector('#table-body tr[data-i]')
  return page
}
const chartState = (page) => page.evaluate(() => {
  const hc = document.getElementById('row-chart')
  return { hidden: hc.hidden || getComputedStyle(hc).display === 'none', svg: !!hc.querySelector('svg'), text: hc.innerText, band: !!hc.querySelector('rect[opacity=".12"]') }
})
const waitSvg = (page) => page.waitForFunction(() => { const h = document.getElementById('row-chart'); return !h.hidden && h.querySelector('svg') }, { timeout: 10000 })

// ---- PC
{
  const page = await open({ width: 1650, height: 1100 })
  const row = await page.$('#table-body tr[data-i="2"]')
  await row.evaluate((el) => el.scrollIntoView({ block: 'center' }))
  const box = await row.boundingBox()
  await page.mouse.move(box.x + 200, box.y + box.height / 2)
  await waitSvg(page)
  const s = await chartState(page)
  if (!s.band || !s.text.includes('신고일')) fail(`PC 차트 표식 없음 ${JSON.stringify(s)}`)
  await page.screenshot({ path: path.join(OUT, 'pc_hover.png') })
  await page.mouse.move(5, 5)
  await new Promise((r) => setTimeout(r, 200))
  if (!(await chartState(page)).hidden) fail('PC 마우스를 빼도 안 닫힘')
  console.log('PC:', s.text.split('\n')[0])
}

// ---- 휴대폰
{
  const page = await open({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })
  const tapRow = async (i) => {
    const r = await page.$(`#table-body tr[data-i="${i}"] td:nth-child(2)`)
    await r.evaluate((el) => el.scrollIntoView({ block: 'center' }))
    await new Promise((res) => setTimeout(res, 150))
    await r.tap()
  }
  await tapRow(1); await waitSvg(page)
  const s = await chartState(page)
  if (!s.svg) fail('폰 탭해도 안 열림')
  await new Promise((r) => setTimeout(r, 300))
  if ((await chartState(page)).hidden) fail('폰 열린 뒤 저절로 닫힘')
  await page.screenshot({ path: path.join(OUT, 'mobile_tap.png') })
  await tapRow(1); await new Promise((r) => setTimeout(r, 200))
  if (!(await chartState(page)).hidden) fail('폰 같은 줄 다시 탭해도 안 닫힘')
  await tapRow(1); await waitSvg(page)
  await tapRow(3); await waitSvg(page)
  const on = await page.evaluate(() => document.querySelector('#table-body tr.hc-on')?.dataset.i)
  if (on !== '3') fail(`폰 다른 줄 탭 시 안 바뀜(${on})`)
  await page.tap('#sel-title'); await new Promise((r) => setTimeout(r, 200))
  if (!(await chartState(page)).hidden) fail('폰 바깥 탭해도 안 닫힘')
  console.log('폰: 열림·같은 줄 닫힘·다른 줄 바뀜·바깥 닫힘 확인')
}
await browser.close()
if (errors.length) fail(`콘솔 오류 ${errors.join(' | ')}`)
console.log('스크린샷', OUT)
