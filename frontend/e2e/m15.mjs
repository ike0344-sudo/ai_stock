// 21:10 요청 E2E — 결과 화면에서 종목이 종목코드(6자리 숫자)로만 보이는 곳 찾기·확인. 사용: node e2e/m15.mjs [baseUrl] [출력폴더] [태그=before|after]

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8780'
const OUT = process.argv[3] ?? path.join(os.tmpdir(), 'm15')
const CHROME = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
fs.mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); log(ok ? 'PASS' : 'FAIL', name, detail) }
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-gpu', '--no-sandbox'], defaultViewport: { width: 1500, height: 1000 }, userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'm15prof-')) })
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
const TAG = process.argv[4] ?? 'before'
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
// 화면에서 "6자리 코드만 있고 이름이 없는" 문구를 찾는다 — 코드가 보이는 조각(텍스트 노드·title 제외)과 그 조상 testid
const scan = () => page.evaluate(() => {
  const out = []
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const t = n.textContent.trim()
    if (!/(^|[^\d])\d{6}([^\d]|$)/.test(t) || /^\d{4}-\d{2}-\d{2}/.test(t) || /\d{8}-\d{6}/.test(t)) continue
    const el = n.parentElement
    if (el.closest('script,style')) continue
    const tid = el.closest('[data-testid]')?.getAttribute('data-testid') ?? '?'
    out.push(`${tid}: ${t.slice(0, 70)}`)
  }
  return out
})
const shotEl = async (sel, name) => { const h = await page.$(sel); if (h) { await h.scrollIntoView(); await h.screenshot({ path: path.join(OUT, `m15_${TAG}_${name}.png`) }) } return !!h }

async function inspect(label, runId) {
  await page.goto(`${BASE}/#/results/${runId}`, { waitUntil: 'networkidle2' })
  await wait($('metric-cards'), 60000); await wait($('trades-table'), 30000).catch(() => {}); await sleep(1500)
  const codes = await scan()
  log(label, '코드가 보이는 문구', codes.length, JSON.stringify(codes.slice(0, 8)))
  results.push({ name: `${label} 화면 코드 노출`, ok: true, detail: codes })
  await shotEl($('trades-table'), `${label}_trades`)
  await shotEl($('code-periods'), `${label}_codeperiods`)
  await shotEl($('intraday-coverage'), `${label}_coverage`)
  // 재생 패널
  if (await page.$($('replay-open'))) {
    await page.evaluate(() => document.querySelector('[data-testid="replay-open"]').scrollIntoView({ block: 'center' })); await page.click($('replay-open')); await sleep(2500)
    await page.click($('replay-speed') + ' label:nth-child(3)').catch(() => {}); await sleep(4000)
    await shotEl($('replay-panel'), `${label}_replay`)
    const rc = await scan(); log(label, '재생 후 코드 문구', rc.length, JSON.stringify(rc.slice(0, 5)))
  }
  return codes.length
}

try {
  const runs = (await api('GET', '/api/runs')).data
  const intra = runs.find((r) => r.mode === 'intraday')
  const out = {}
  if (intra) out.intraday = await inspect('intraday', intra.run_id)
  const ps = (await api('GET', '/api/presets/golden_cross_5_20')).data.spec
  ps.period = { start: '2025-09-01', end: '2026-09-18' }
  out.portfolio = await inspect('portfolio', await runViaApi(ps))
  const single = { ...JSON.parse(JSON.stringify(ps)), name: 'E2E 단일', mode: 'daily_single', universe: { type: 'codes', n: 100, lookback_days: 1, markets: ['거래소', '코스닥'], exclude: [], codes: ['005930'] }, portfolio: { initial_capital: 10000000, max_positions: 1, max_weight_pct: 100 } }
  out.single = await inspect('single', await runViaApi(single))
  fs.writeFileSync(path.join(OUT, `m15_${TAG}_summary.json`), JSON.stringify(out))
  log('요약', JSON.stringify(out))
} catch (e) {
  check('E2E 진행 중 예외', false, String(e).slice(0, 500))
} finally {
  for (const id of runIds) { const r = await fetch(`${BASE}/api/runs/${id}`, { method: 'DELETE', headers: { Origin: BASE } }).catch(() => null); log('삭제', id, r?.status) }
  fs.writeFileSync(path.join(OUT, `m15_${TAG}_results.json`), JSON.stringify(results, null, 1))
  await browser.close()
  process.exit(0)
}
