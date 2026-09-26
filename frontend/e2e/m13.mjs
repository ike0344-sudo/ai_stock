// 18:30 요청 E2E — 문장 카드: 빈 상태 → [조건 추가] → "1분봉이 직전 봉보다 1% 이상" → 1 입력 → 실행 → 결과.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm13')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm13prof-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const shot = (n) => page.screenshot({ path: path.join(OUT, `m13_${n}.png`), fullPage: true })
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
  await page.evaluate(() => [...document.querySelectorAll('[data-testid="bar-minutes"] label')].find((l) => l.textContent.trim() === '1분').click())
  await sleep(1500)
  await wait($('cards-strategy.entry'), 20000)
  check('서버가 문장 카드를 지원 — 카드 화면이 기본', !!(await page.$($('cards-strategy.entry-add'))))

  // 빈 상태: 기본으로 들어 있는 진입 조건을 지운다
  for (let k = 0; k < 5; k++) {
    const del = await page.$(`${entry.replace('group-strategy.entry', 'cards-strategy.entry')} [aria-label="조건 삭제"]`)
    if (!del) break
    await del.click(); await sleep(300)
  }
  const emptyTxt = await page.$eval($('cards-strategy.entry-empty'), (e) => e.innerText).catch(() => '')
  check('빈 상태 안내 문구', /조건 추가/.test(emptyTxt), emptyTxt)
  await shot('1_empty')

  // 조건 추가 → 목록
  await page.click($('cards-strategy.entry-add')); await wait($('tpl-picker'), 8000); await sleep(500)
  await shot('2_picker')
  await page.type($('tpl-search') + ' input', '직전 봉').catch(async () => { await page.keyboard.type('직전 봉') }); await sleep(600)
  const list = await page.$eval($('tpl-list'), (e) => e.innerText.replace(/\s+/g, ' '))
  check('검색 "직전 봉" → "1분봉 … 직전 봉보다 N% 이상 올랐다" 문장이 보임', /직전 봉보다 \d+% 이상 올랐다/.test(list), list.slice(0, 120))
  await shot('3_picker_search')
  await page.click($('tpl-change_up')); await wait($('card-change_up'), 15000); await sleep(800)
  const card = await page.$eval($('card-change_up'), (e) => e.innerText.replace(/\s+/g, ' '))
  check('카드가 붙음(문장 + 쉬운 설명)', /가격이 직전 봉보다/.test(card) && /올랐/.test(card), card.slice(0, 160))
  // 1 입력
  const x = `${$('card-change_up')} ${$('card-slot-x')}`
  await page.focus(x); await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control'); await page.keyboard.type('1'); await page.keyboard.press('Tab'); await sleep(1500)
  const xv = await page.$eval(x, (e) => e.value)
  check('빈칸에 1 입력', xv === '1', xv)
  const nar = await page.waitForFunction(() => /등락률.%.가 1 이상/.test(document.querySelector('[data-testid="narration"]')?.textContent ?? ''), { timeout: 30000 }).then(() => page.$eval($('narration'), (e) => e.textContent)).catch(() => '')
  check('아래 풀이 문장에도 "등락률(%)가 1 이상" 이 반영됨', /등락률.%.가 1 이상/.test(nar), nar.replace(/\s+/g, ' ').slice(0, 140))
  await shot('4_card_ready')

  // 실행
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
  fs.writeFileSync(path.join(OUT, 'm13_results.json'), JSON.stringify(results, null, 1))
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
