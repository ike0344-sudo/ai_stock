// 17:20 요청 E2E — ① 실행 창 실시간 곡선(실행 중 곡선이 늘어남) ② 결과 화면 [재생]: 포트폴리오·단일 종목·분봉. 프레임을 찍어 GIF 재료로 남긴다.
// 사용: node e2e/m11.mjs [baseUrl] [출력폴더]   끝에 만든 실행 결과를 API 로 지운다.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm11')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm11prof-')) })
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text().slice(0, 300)) })
page.on('response', (r) => { if (r.status() >= 400) pageErrors.push(`HTTP ${r.status()} ${r.url()}`) })
const $ = (id) => `[data-testid="${id}"]`
const wait = (sel, t = 60000) => page.waitForSelector(sel, { timeout: t })
const text = (sel) => page.$eval(sel, (e) => e.textContent ?? '')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const runIds = []

async function api(method, p, body) {
  const r = await fetch(`${BASE}${p}`, { method, headers: { 'Content-Type': 'application/json', Origin: BASE }, body: body ? JSON.stringify(body) : undefined })
  return r.json()
}
async function runViaApi(spec) {
  const r = await api('POST', '/api/jobs/backtest', spec)
  const jid = r.data.job_id
  for (;;) {
    const j = (await api('GET', `/api/jobs/${jid}`)).data
    if (['succeeded', 'failed', 'cancelled'].includes(j.status)) { if (j.status !== 'succeeded') throw new Error(`작업 ${j.status}: ${j.error}`); break }
    await sleep(1500)
  }
  runIds.push(r.data.run_id)
  return r.data.run_id
}
/** 재생 패널 프레임을 찍는다(GIF 재료) */
async function frames(prefix, sel, n, gap) {
  for (let i = 0; i < n; i++) {
    const el = await page.$(sel)
    await el.screenshot({ path: path.join(OUT, `${prefix}_${String(i).padStart(2, '0')}.png`) })
    await sleep(gap)
  }
}

try {
  // ───────── ① 실행 창 실시간 곡선 ─────────
  await page.goto(`${BASE}/#/backtest?preset=new_high_20`, { waitUntil: 'networkidle2' })
  await wait($('spec-name')); await wait($('narration'), 30000)
  await page.waitForFunction(() => { const b = document.querySelector('[data-testid="run-btn"]'); return b && !b.disabled }, { timeout: 60000 })
  for (let k = 0; k < 3; k++) {
    await page.evaluate(() => document.querySelector('[data-testid="run-btn"]').click())
    if (await page.waitForSelector($('run-modal'), { timeout: 8000 }).then(() => true).catch(() => false)) break
  }
  log('실행 중… 실행 창 관찰')
  const seen = []
  const t0 = Date.now()
  let i = 0
  while (!(await page.evaluate(() => location.hash.startsWith('#/results/'))) && Date.now() - t0 < 240000) {
    const st = await page.evaluate(() => {
      const q = (id) => document.querySelector(`[data-testid="${id}"]`)?.textContent ?? null
      return { curve: !!document.querySelector('[data-testid="live-curve"]'), date: q('live-date'), equity: q('live-equity'), trades: q('live-trades'), pos: q('live-positions'), stage: q('run-stage') }
    })
    seen.push(st)
    if (st.curve && i % 2 === 0) await page.screenshot({ path: path.join(OUT, `live_${String(i).padStart(3, '0')}.png`), clip: { x: 350, y: 100, width: 800, height: 620 } }).catch(() => {})
    i++
    await sleep(500)
  }
  runIds.push(page.url().split('#/results/')[1])
  const dates = [...new Set(seen.filter((s) => s.curve).map((s) => s.date))]
  check('실행 창에 실시간 곡선이 나타남', seen.some((s) => s.curve), `관찰 ${seen.length}회, 곡선 ${seen.filter((s) => s.curve).length}회`)
  check('곡선이 실행 중에 늘어남(지금 날짜가 여러 번 바뀜)', dates.length >= 3, `${dates.length}개 날짜: ${dates.slice(0, 3).join(', ')} … ${dates.slice(-1)}`)
  const lastLive = [...seen].reverse().find((s) => s.curve)
  check('지금 날짜·평가금·거래 수·보유 종목이 채워짐', !!(lastLive && lastLive.date && lastLive.equity && lastLive.trades !== null && lastLive.pos !== null), JSON.stringify(lastLive))
  await wait($('metric-cards'), 60000)

  // ───────── ② 포트폴리오 재생 ─────────
  await wait($('replay-open'), 30000)
  await page.evaluate(() => document.querySelector('[data-testid="replay-open"]').scrollIntoView({ block: 'center' }))
  await page.click($('replay-open'))
  await wait($('replay-panel'), 10000)
  const d1 = await text($('replay-day'))
  await sleep(2000)
  const d2 = await text($('replay-day'))
  check('재생: 날짜가 흘러감', d1 !== d2, `${d1} → ${d2}`)
  await page.click($('replay-speed') + ' label:nth-child(3)') // 16배
  await frames('replay_portfolio', $('replay-panel'), 14, 350)
  await page.evaluate(() => document.querySelector('[data-testid="replay-toggle"]').click()) // 일시정지 or 처음부터
  await sleep(300)
  const p1 = await text($('replay-day')); await sleep(1200); const p2 = await text($('replay-day'))
  check('일시정지: 멈춤(또는 끝에서 멈춤)', p1 === p2, `${p1}`)
  const n1 = await page.$$eval($('replay-bought') + ' div', (n) => n.length)
  check('그날 산·판 종목 목록이 있음', await page.$($('replay-bought')) !== null && await page.$($('replay-sold')) !== null, `bought div ${n1}`)
  // 슬라이더로 이동
  const box = await (await page.$($('replay-panel') + ' .ant-slider-rail')).boundingBox()
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height / 2); await sleep(500)
  const mid = await text($('replay-day'))
  check('슬라이더로 날짜 이동(중간)', mid > '2021-06' && mid < '2026-01', mid)
  const eqTxt = await text($('replay-equity'))
  check('재생 헤더에 평가금·수익률', /평가금.*%/.test(eqTxt), eqTxt)
  await page.screenshot({ path: path.join(OUT, 'm11_replay_portfolio.png'), fullPage: false })

  // ───────── ③ 단일 종목 재생(캔들) ─────────
  const single = { version: 1, name: 'E2E 단일', mode: 'daily_single', period: { start: '2024-01-02', end: '2026-08-31' }, universe: { type: 'codes', n: 100, lookback_days: 1, markets: ['거래소', '코스닥'], exclude: [], codes: ['005930'] },
    strategy: { source: 'builder', entry: { logic: 'all', items: [{ left: { kind: 'field', name: 'close' }, op: 'gt', right: { kind: 'ind', name: 'sma', params: { src: 'close', n: 20 } } }] }, exit: { logic: 'any', items: [{ left: { kind: 'field', name: 'close' }, op: 'lt', right: { kind: 'ind', name: 'sma', params: { src: 'close', n: 10 } } }] } },
    exits: { stop_loss_pct: 7 }, portfolio: { initial_capital: 10000000, max_positions: 1, max_weight_pct: 100 }, fills: { volume_cap_pct: null } }
  const sid = await runViaApi(single)
  await page.goto(`${BASE}/#/results/${sid}`, { waitUntil: 'networkidle2' })
  await wait($('replay-open'), 30000)
  await page.evaluate(() => document.querySelector('[data-testid="replay-open"]').scrollIntoView({ block: 'center' }))
  await page.click($('replay-open'))
  await wait($('replay-candle'), 30000)
  const s1 = await text($('replay-day')); await sleep(2500); const s2 = await text($('replay-day'))
  check('단일 종목 재생: 캔들 창이 흐르며 날짜가 바뀜', s1 !== s2, `${s1} → ${s2}`)
  await page.click($('replay-speed') + ' label:nth-child(3)')
  await frames('replay_single', $('replay-panel'), 14, 350)
  check('단일 종목 재생: 캔들 차트 그려짐', (await page.$$($('replay-candle') + ' canvas')).length > 0)

  // ───────── ④ 분봉 재생 ─────────
  const intra = { version: 1, name: 'E2E 분봉', mode: 'intraday', period: { start: '2026-08-24', end: '2026-09-23' }, universe: { type: 'top_value', n: 100, lookback_days: 1, markets: ['거래소', '코스닥'], exclude: ['spac', 'preferred', 'mega_cap'], codes: [] },
    strategy: { source: 'builder', entry: { logic: 'all', items: [{ left: { kind: 'field', name: 'close' }, op: 'gt', right: { kind: 'ind', name: 'highest', params: { src: 'high', n: 20 } } }] }, exit: { logic: 'any', items: [] } },
    exits: { stop_loss_pct: 1.5, take_profit_pct: 3 }, portfolio: { initial_capital: 10000000, max_positions: 3, max_weight_pct: 34 }, intraday: { bar_minutes: 5, source: 'al', prefilter: null, prefilter_top_value: 30, eod_time: '15:20' } }
  const iid = await runViaApi(intra)
  await page.goto(`${BASE}/#/results/${iid}`, { waitUntil: 'networkidle2' })
  await wait($('replay-open'), 30000)
  await page.evaluate(() => document.querySelector('[data-testid="replay-open"]').scrollIntoView({ block: 'center' }))
  await page.click($('replay-open'))
  await wait($('replay-minute'), 30000)
  await sleep(2500)
  const mtxt = await text($('replay-minute'))
  check('분봉 재생: 그날 거래 종목의 분봉을 보여 줌', /5분봉/.test(mtxt) || /거래가 없어/.test(mtxt), mtxt.slice(0, 60))
  await page.click($('replay-speed') + ' label:nth-child(1)') // 1배 — 날 단위로 천천히
  await frames('replay_intraday', $('replay-panel'), 14, 500)
  await page.waitForSelector($('replay-minute') + ' canvas', { timeout: 40000 }).catch(() => {})
  check('분봉 재생: 분봉 차트가 그려진 프레임이 있음', (await page.$$($('replay-minute') + ' canvas')).length > 0, (await text($('replay-minute'))).slice(0, 60))

  check('콘솔·페이지 오류 없음', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
  await page.screenshot({ path: path.join(OUT, 'zz_failure.png'), fullPage: true }).catch(() => {})
} finally {
  for (const id of runIds) { const r = await fetch(`${BASE}/api/runs/${id}`, { method: 'DELETE', headers: { Origin: BASE } }).catch(() => null); log('삭제', id, r?.status) }
  await browser.close()
  fs.writeFileSync(path.join(OUT, 'm11_results.json'), JSON.stringify(results, null, 1))
  const failed = results.filter((r) => !r.ok)
  log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL PASSED ${results.length}/${results.length}`)
  process.exit(failed.length ? 1 : 0)
}
