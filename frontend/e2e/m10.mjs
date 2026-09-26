// 17:15 요청 E2E — 거래대금(억)을 찾기 쉽게: 가격·거래량 목록의 "거래대금(억)"·찾아서 고르기 검색("거래대금")·자주 쓰는 조건 버튼 → 5분 → 20 → 실행 → 결과.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm10')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm10prof-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const shot = (n) => page.screenshot({ path: path.join(OUT, `m10_${n}.png`), fullPage: true })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, t = 60000) => page.waitForSelector(sel, { timeout: t })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const dropdown = () => page.evaluate(() => [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')].pop()?.innerText ?? '')
const clickOption = (label, exact = false) => page.evaluate((l, ex) => [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')].find((o) => (ex ? o.textContent.trim() === l : o.textContent.trim().startsWith(l)))?.click(), label, exact)
const runIds = []
const entry = $('group-strategy.entry')

try {
  await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle2' })
  await wait($('spec-name')); await wait($('narration'), 30000)
  await page.evaluate(() => [...document.querySelectorAll('.ant-tabs-tab')].find((t) => t.textContent.trim() === '분봉 단타').click())
  await wait($('panel-intraday'), 15000)
  await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="panel-period"] input')].some((i) => i.value === '2026-09-23'), { timeout: 30000 }).catch(() => {})

  // 실행 봉 1분으로 — 시간 단위 "5분봉" 은 실행 봉보다 긴 것만 고를 수 있다(실행 봉이 5분이면 "이 봉" 이 곧 5분봉)
  await page.evaluate(() => [...document.querySelectorAll('[data-testid="bar-minutes"] label')].find((l) => l.textContent.trim() === '1분').click())
  await sleep(800)
  // ① 자주 쓰는 조건 버튼
  check('자주 쓰는 조건 넣기 버튼들이 보임', !!(await page.$($('quick-value_eok'))) && !!(await page.$($('quick-new_high'))) && !!(await page.$($('quick-above_vwap'))))
  await shot('1_quick_buttons')

  // ② 가격·거래량 목록에 거래대금(억)
  await page.click(`${entry} ${$('operand-left-field')}`); await sleep(500)
  const dd = await dropdown()
  check('"가격·거래량" 목록에 "거래대금" 하나만(원 단위는 숨김)', /거래대금/.test(dd) && !/거래대금\(원\)/.test(dd) && (dd.match(/거래대금/g) || []).length === 1, dd.replace(/\s+/g, ' ').slice(0, 80))
  await shot('2_field_list')
  await page.keyboard.press('Escape'); await sleep(300)

  // ③ 찾아서 고르기: "거래대금"
  await page.click(`${entry} ${$('operand-left-find')}`); await sleep(400)
  await page.keyboard.type('거래대금'); await sleep(700)
  const dd2 = await dropdown()
  check('검색 "거래대금": 거래대금·합·배수가 종류 상관없이 함께(원 항목 없음)', !/거래대금\(원\)/.test(dd2) && /합\(억\)/.test(dd2) && /평균 대비/.test(dd2) && !/종가/.test(dd2), dd2.replace(/\s+/g, ' ').slice(0, 130))
  await shot('3_find_search')
  await clickOption('거래대금', true); await sleep(900)
  const kindTxt = await page.$eval(`${entry} ${$('operand-left')}`, (e) => e.innerText.replace(/\s+/g, ' '))
  check('고르면 왼쪽이 거래대금 으로 바뀜(가격·거래량 쪽에 표시)', /가격·거래량/.test(kindTxt) && /거래대금/.test(kindTxt), kindTxt.slice(0, 100))

  // ④ 5분 → 20
  const tf = `${entry} ${$('operand-left-tf')}`
  await page.click(tf); await sleep(400)
  await clickOption('5분봉', true); await sleep(500)
  check('시간 단위 5분봉 선택', /5분봉/.test(await page.$eval(tf, (e) => e.innerText)))
  // 17:50 — 오른쪽을 손대지 않아도 "[20] 억" 입력칸이 이미 떠 있어야 한다(자동 전환 + 포커스)
  const c = `${entry} ${$('operand-right-const')}`
  await wait(c, 8000)
  const auto = await page.$eval(c, (e) => ({ v: e.value, focus: document.activeElement === e }))
  check('오른쪽이 자동으로 숫자 입력칸(기본 20)으로 바뀜', auto.v === '20', JSON.stringify(auto))
  await shot('4a_auto_input')
  await page.focus(c); await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control'); await page.keyboard.type('20'); await page.keyboard.press('Tab'); await sleep(600)
  const rightTxt = await page.$eval(`${entry} ${$('operand-right')}`, (e) => e.innerText.replace(/\s+/g, ' '))
  check('숫자 칸에 "억" 표시 + 20', /억/.test(rightTxt) && (await page.$eval(c, (e) => e.value)) === '20', rightTxt.slice(0, 60))
  await page.waitForFunction(() => /5분봉/.test(document.querySelector('[data-testid="narration"]')?.textContent ?? '') && /20억/.test(document.querySelector('[data-testid="narration"]')?.textContent ?? ''), { timeout: 30000 }).catch(() => {})
  const nar = await page.$eval($('narration'), (e) => e.textContent).catch(() => '')
  check('풀이 문장에 5분봉·20억', /5분봉/.test(nar) && /20억/.test(nar), nar.replace(/\s+/g, ' ').slice(0, 120))
  await shot('4_condition_ready')

  // ⑤ 실행
  await page.waitForFunction(() => { const b = document.querySelector('[data-testid="run-btn"]'); return b && !b.disabled }, { timeout: 60000 })
  for (let k = 0; k < 3; k++) {
    await page.evaluate(() => document.querySelector('[data-testid="run-btn"]').click())
    if (await page.waitForSelector($('run-modal'), { timeout: 8000 }).then(() => true).catch(() => false)) break
  }
  log('실행 중…')
  await page.waitForFunction(() => location.hash.startsWith('#/results/'), { timeout: 300000 })
  runIds.push(page.url().split('#/results/')[1]); await wait($('metric-cards'), 60000)
  check('결과 화면으로 이동', true, runIds[0])
  await shot('5_result')
  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
  await shot('zz_failure').catch(() => {})
} finally {
  for (const id of runIds) {
    const r = await fetch(`${BASE}/api/runs/${id}`, { method: 'DELETE', headers: { Origin: BASE } }).catch(() => null)
    log('삭제', id, r?.status)
  }
  await browser.close()
  fs.writeFileSync(path.join(OUT, 'm10_results.json'), JSON.stringify(results, null, 1))
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
