// 17:20 요청 — 실행 중 실시간 곡선(RunModal) · 결과 화면 [재생](ReplayPanel). 순수 계산은 lib/replay 로 값 검사, 화면은 EChart 대역이 내는 옵션 JSON 으로 검사.
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RunModal } from '@/components/builder/RunModal'
import { advance, BASE_DAYS_PER_SEC, dayOf, eventsBetween, focusCode, holdingSpans, liveCurveOption, replayCandleOption, replayDays, replayEquityOption, replayMinuteOption, statAt, usableLivePoints } from '@/lib/replay'
import { ResultPage } from '@/pages/ResultPage'
import type { EquityPoint, SpecJson, Trade } from '@/types/studio'
import * as sx from './fixtures/studio'
import { realDetail, realEquity, realTrades } from './fixtures/studioReal'
import { alDetail, alTrades } from './fixtures/studioReal6'
import { mockApi, renderApp } from './helpers'

beforeEach(() => localStorage.clear())
afterEach(() => vi.useRealTimers())

const eq = (day: string, equity: number, n = 0): EquityPoint => ({ ts: `${day}T00:00:00`, equity, drawdown_pct: 0, n_positions: n })
const tr = (code: string, entry: string, exit: string | null, pct = 0.05): Trade => ({ code, name: code, sector: null, entry_ts: `${entry}T00:00:00`, entry_price: 100, exit_ts: exit ? `${exit}T00:00:00` : null, exit_price: exit ? 105 : null, qty: 1, gross_pnl: 5, commission: 0, tax: 0, slippage_cost: 0, net_pnl: 5, net_pct: pct, exit_reason: 'signal', bars_held: 1 })

describe('재생 계산', () => {
  it('날짜는 곡선에서 중복 없이 오름차순', () => {
    expect(replayDays([eq('2025-01-02', 1), { ...eq('2025-01-02', 1), ts: '2025-01-02T15:30:00' }, eq('2025-01-03', 2)])).toEqual(['2025-01-02', '2025-01-03'])
  })

  it('전진: 1배속 = 초당 8거래일, 배속에 비례하고 끝에서 멈춘다', () => {
    expect(advance(0, 1, 1000, 500)).toBe(BASE_DAYS_PER_SEC)
    expect(advance(0, 4, 1000, 500)).toBe(32)
    expect(advance(0, 16, 50, 500)).toBeCloseTo(6.4, 5) // 프레임(50ms) 하나에 16배속이면 6.4거래일 — 여러 봉을 묶어 그린다
    expect(advance(490, 16, 1000, 500)).toBe(500)
    expect(advance(0, 1, 1000, 500, 1)).toBe(1) // 분봉·틱 재생은 1배속 = 초당 1거래일
  })

  it('이벤트: (from, to] 구간에 산·판 거래를 모두 센다(배속이 빨라 며칠 건너뛰어도 안 빠짐)', () => {
    const t = [tr('A', '2025-01-03', '2025-01-08'), tr('B', '2025-01-06', null), tr('C', '2025-01-02', '2025-01-03')]
    const one = eventsBetween(t, '2025-01-02', '2025-01-03')
    expect(one.bought.map((x) => x.code)).toEqual(['A'])
    expect(one.sold.map((x) => x.code)).toEqual(['C'])
    const jump = eventsBetween(t, '2025-01-02', '2025-01-08')
    expect(jump.bought.map((x) => x.code)).toEqual(['A', 'B'])
    expect(jump.sold.map((x) => x.code)).toEqual(['A', 'C'])
    expect(eventsBetween(t, null, '2025-01-02').bought.map((x) => x.code)).toEqual(['C']) // 처음(from 없음)은 그 날 포함
  })

  it('보유 구간과 분봉 재생 종목 고르기(진입 종목 우선)', () => {
    const t = [tr('A', '2025-01-03', '2025-01-08'), tr('B', '2025-01-06', null)]
    expect(holdingSpans(t, 'A', '2025-02-01')).toEqual([['2025-01-03', '2025-01-08']])
    expect(holdingSpans(t, 'B', '2025-02-01')).toEqual([['2025-01-06', '2025-02-01']]) // 안 팔렸으면 끝날까지
    expect(focusCode([tr('X', '2025-01-05', '2025-01-06'), tr('Y', '2025-01-01', '2025-01-06')], '2025-01-06')?.code).toBe('X') // 같은 점수면 코드 순
    expect(focusCode([tr('Y', '2025-01-06', '2025-01-07'), tr('X', '2025-01-01', '2025-01-06')], '2025-01-06')?.code).toBe('Y') // 그날 진입한 종목이 청산만 한 종목보다 우선
    expect(focusCode(t, '2025-01-04')).toBeNull()
  })

  it('그 날 값: 그 날(또는 그 전) 마지막 평가금과 수익률', () => {
    const e = [eq('2025-01-02', 10_000_000, 0), eq('2025-01-03', 10_500_000, 2), eq('2025-01-06', 9_900_000, 3)]
    const days = replayDays(e)
    expect(statAt(e, days, 1, 10_000_000)).toMatchObject({ day: '2025-01-03', equity: 10_500_000, positions: 2 })
    expect(statAt(e, days, 1, 10_000_000).returnPct).toBeCloseTo(5, 6)
    expect(statAt(e, days, 2, 10_000_000).returnPct).toBeCloseTo(-1, 6)
  })

  it('수익곡선 옵션: x 축은 전체 날짜로 고정, 곡선은 cursor 까지만', () => {
    const e = [eq('2025-01-02', 1), eq('2025-01-03', 2), eq('2025-01-06', 3), eq('2025-01-07', 4)]
    const days = replayDays(e)
    const o = replayEquityOption(e, days, 1) as { xAxis: { data: string[] }; series: { data: number[] }[]; animation: boolean }
    expect(o.xAxis.data).toEqual(days)
    expect(o.series[0].data).toEqual([1, 2])
    expect(o.animation).toBe(false) // 프레임은 우리가 몰고 간다
    expect((replayEquityOption(e, days, 3) as { series: { data: number[] }[] }).series[0].data).toEqual([1, 2, 3, 4])
  })

  it('캔들 옵션: 최근 60봉 창이 옆으로 흐르고, 창 안의 매수·매도만 찍히며 보유 구간이 음영', () => {
    const bars = Array.from({ length: 200 }, (_, i) => ({ t: dayOf(new Date(Date.UTC(2025, 0, 1 + i)).toISOString()), o: 100, h: 110, l: 90, c: 105, v: 1 }))
    const trades = [tr('A', bars[10].t, bars[20].t), tr('A', bars[150].t, bars[160].t)]
    const o1 = replayCandleOption(bars, trades, 30) as { xAxis: { data: string[] }; series: { markPoint: { data: { name: string }[] }; markArea: { data: unknown[][] } }[] }
    expect(o1.xAxis.data).toHaveLength(31) // 아직 60봉이 안 찼다
    expect(o1.series[0].markPoint.data.map((p) => p.name)).toEqual(['매수', '매도']) // 첫 거래만(둘째는 아직 안 왔다)
    expect(o1.series[0].markArea.data).toHaveLength(1)
    const o2 = replayCandleOption(bars, trades, 170) as typeof o1
    expect(o2.xAxis.data).toHaveLength(60)
    expect(o2.xAxis.data[59]).toBe(bars[170].t)
    expect(o2.series[0].markPoint.data.map((p) => p.name)).toEqual(['매수', '매도']) // 창 밖(옛 거래)은 빠지고 둘째만
  })

  it('분봉 옵션: 그날 봉만, 매수·매도 표시는 그 시각 다음에 끝나는 봉에', () => {
    const bars = ['09:05', '09:10', '09:15', '09:20'].map((h, i) => ({ t: `2025-01-06 ${h}`, o: 100 + i, h: 101 + i, l: 99, c: 100 + i, v: 1 }))
    const t = { ...tr('A', '2025-01-06', '2025-01-06'), entry_ts: '2025-01-06T09:06:00', exit_ts: '2025-01-06T09:15:00' }
    const o = replayMinuteOption(bars, [t], '2025-01-06') as { xAxis: { data: string[] }; series: { markPoint: { data: { coord: [string, number]; value: string }[] } }[] }
    expect(o.xAxis.data).toEqual(['09:05', '09:10', '09:15', '09:20'])
    const pts = o.series[0].markPoint.data
    expect(pts.find((p) => p.value === '매수')!.coord[0]).toBe('09:10') // 09:06 체결 → 09:10 에 끝나는 봉
    expect(pts.find((p) => p.value === '매도')!.coord[0]).toBe('09:15')
  })
})

describe('실시간 곡선 계산', () => {
  it('쓸 수 없는 점(값 없음·NaN)은 건너뛰고 날짜 순, 점 배열이 {points} 로 감싸져 와도 받는다', () => {
    const raw = [{ date: '2025-01-03', equity: 2 }, { date: '2025-01-02', equity: 1 }, { date: '2025-01-04', equity: null }, { date: '2025-01-05', equity: Number.NaN }, { equity: 5 }]
    expect(usableLivePoints(raw).map((p) => p.date)).toEqual(['2025-01-02', '2025-01-03'])
    expect(usableLivePoints({ points: raw })).toHaveLength(2)
    expect(usableLivePoints(undefined)).toEqual([])
    expect(usableLivePoints('x')).toEqual([])
  })

  it('옵션: 기간 전체 x 축 + 시작 자본선 + 이기고 있으면 빨강(한국 관례)·지면 파랑', () => {
    const period = { start: '2025-01-02', end: '2025-08-29' }
    const up = liveCurveOption([{ date: '2025-01-02', equity: 10_000_000 }, { date: '2025-02-03', equity: 10_500_000 }], period, 10_000_000) as { xAxis: { min: string; max: string }; series: { data: unknown[][]; lineStyle: { color: string }; markLine: { data: { yAxis: number }[] } }[]; animationDurationUpdate: number }
    expect(up.xAxis).toMatchObject({ min: '2025-01-02', max: '2025-08-29' })
    expect(up.series[0].data).toEqual([['2025-01-02', 10_000_000], ['2025-02-03', 10_500_000]])
    expect(up.series[0].markLine.data[0].yAxis).toBe(10_000_000)
    expect(up.series[0].lineStyle.color).toBe('#f5222d')
    const down = liveCurveOption([{ date: '2025-01-02', equity: 9_000_000 }], period, 10_000_000) as typeof up
    expect(down.series[0].lineStyle.color).toBe('#1677ff')
    expect(up.animationDurationUpdate).toBeGreaterThan(0) // 자라는 모습의 부드러운 이어짐
  })
})

const spec = (sx.presetSpec as SpecJson)
const job = (pts: unknown[] | undefined, status = 'running', pct = 40) => ({
  job_id: '20260926-100000-aaaaaa', kind: 'backtest', group: 'compute', status, scheduled_at: null, created_at: '2026-09-26T10:00:00', started_at: '2026-09-26T10:00:01', finished_at: null, run_id: '20260926-100000-bbbbbb', lock: null, trigger: null, error: null,
  cancel_requested: false, progress: { pct, stage: 'engine', message: null, eta_sec: null, paused: false, waiting_lock: null, ...(pts ? { live_curve: pts } : {}) },
})

describe('실행 창 실시간 곡선', () => {
  const pts = (n: number) => Array.from({ length: n }, (_, i) => ({ date: `2025-01-${String(2 + i).padStart(2, '0')}`, equity: 10_000_000 + i * 50_000, cash: 5_000_000, n_positions: i % 3, n_trades: i * 2, ...(i === n - 1 ? { last_event: { side: 'buy' as const, code: '005930', name: '삼성전자' } } : {}) }))
  it('곡선이 오면 곡선·지금 날짜·평가금(수익률)·거래 수·보유 종목이 보이고, 폴링마다 늘어난다', async () => {
    let n = 0
    mockApi({
      'POST /api/jobs/backtest': { status: 202, data: { job_id: '20260926-100000-aaaaaa', run_id: '20260926-100000-bbbbbb' } },
      'GET /api/jobs/20260926-100000-aaaaaa': () => ({ data: job(pts(++n === 1 ? 3 : 6)) }),
    })
    renderApp(<Routes><Route path="/" element={<RunModal spec={spec} onClose={() => {}} />} /></Routes>)
    const box = await screen.findByTestId('live-curve', {}, { timeout: 5000 })
    expect(within(box).getByTestId('live-date')).toHaveTextContent('2025-01-04')
    expect(within(box).getByTestId('live-equity')).toHaveTextContent('10,100,000원')
    expect(within(box).getByTestId('live-equity')).toHaveTextContent('+1.00%')
    expect(within(box).getByTestId('live-positions')).toHaveTextContent('2')
    expect(within(box).getByTestId('echart')).toHaveTextContent('"id":"live"')
    await waitFor(() => expect(screen.getByTestId('live-date')).toHaveTextContent('2025-01-07'), { timeout: 4000 }) // 다음 폴링: 6점
    expect(screen.getByTestId('live-trades')).toHaveTextContent('10')
    expect(screen.getByTestId('live-event')).toHaveTextContent('매수 삼성전자')
    expect(screen.getByTestId('run-progress')).toBeInTheDocument() // 진행 막대는 그대로 남는다(정보를 가리지 않음)
  })

  it('빠른 실행이 이미 끝나 있어도(엔진 0.3초) 받아 둔 곡선을 왼→오로 다시 그린 뒤 결과 화면으로 넘어간다', async () => {
    mockApi({
      'POST /api/jobs/backtest': { status: 202, data: { job_id: '20260926-100000-aaaaaa', run_id: '20260926-100000-bbbbbb' } },
      'GET /api/jobs/20260926-100000-aaaaaa': { data: job(pts(30), 'succeeded', 100) },
    })
    renderApp(<Routes><Route path="/" element={<RunModal spec={spec} onClose={() => {}} />} /><Route path="/results/:runId" element={<div data-testid="result-page" />} /></Routes>)
    const box = await screen.findByTestId('live-curve', {}, { timeout: 5000 })
    expect(screen.queryByTestId('result-page')).not.toBeInTheDocument() // 재생하는 동안은 아직 결과 화면이 아니다
    const first = within(box).getByTestId('live-date').textContent
    await waitFor(() => expect(screen.getByTestId('live-date').textContent).not.toBe(first), { timeout: 3000 }) // 점이 늘어난다
    expect(await screen.findByTestId('result-page', {}, { timeout: 6000 })).toBeInTheDocument()
  }, 15000)

  it('곡선이 없으면(옛 작업·그리드) 진행 막대만 보인다', async () => {
    mockApi({
      'POST /api/jobs/backtest': { status: 202, data: { job_id: '20260926-100000-aaaaaa', run_id: '20260926-100000-bbbbbb' } },
      'GET /api/jobs/20260926-100000-aaaaaa': { data: job(undefined) },
    })
    renderApp(<Routes><Route path="/" element={<RunModal spec={spec} onClose={() => {}} />} /></Routes>)
    await screen.findByTestId('run-progress')
    await waitFor(() => expect(screen.getByTestId('run-stage')).toHaveTextContent('체결 시뮬레이션 중'))
    expect(screen.queryByTestId('live-curve')).not.toBeInTheDocument()
  })
})

const ID = realDetail.run_id
const resultRoutes = (d = realDetail, trades: Trade[] = realTrades, equity: EquityPoint[] = realEquity, extra: Record<string, Parameters<typeof mockApi>[0][string]> = {}) => ({
  [`GET /api/runs/${d.run_id}`]: { data: d }, [`GET /api/runs/${d.run_id}/equity`]: { data: equity }, [`GET /api/runs/${d.run_id}/trades`]: { data: trades }, ...extra,
})
const result = (id: string) => renderApp(<Routes><Route path="/results/:runId" element={<ResultPage />} /></Routes>, `/results/${id}`)
const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

describe('결과 화면 [재생]', () => {
  it('처음엔 안내 카드만(다른 정보를 안 가림), 누르면 재생 패널이 열려 곡선이 그려져 나간다', async () => {
    mockApi(resultRoutes())
    result(ID)
    expect(await screen.findByTestId('replay-card')).toHaveTextContent('새로 계산하지 않습니다')
    expect(screen.queryByTestId('replay-panel')).not.toBeInTheDocument()
    vi.useFakeTimers({ shouldAdvanceTime: true })
    fireEvent.click(screen.getByTestId('replay-open'))
    const panel = await screen.findByTestId('replay-panel')
    const first = within(panel).getByTestId('replay-day').textContent
    expect(first).toBe('2025-01-02')
    await tick(1000) // 4배속(기본) 1초 = 32거래일
    expect(within(panel).getByTestId('replay-day').textContent).not.toBe(first)
    const opt = JSON.parse(within(within(panel).getByTestId('replay-equity-chart')).getByTestId('echart').textContent!)
    expect(opt.series[0].id).toBe('eq')
    expect(opt.series[0].data.filter((v: number | null) => v !== null).length).toBeGreaterThan(1) // 곡선이 자라 있다
    expect(within(panel).getByTestId('replay-bought')).toBeInTheDocument()
    expect(within(panel).getByTestId('replay-sold')).toBeInTheDocument()
  })

  it('일시정지하면 멈추고, 다시 재생하면 이어가며, 배속 16배는 더 빨리 간다', async () => {
    mockApi(resultRoutes())
    result(ID)
    await screen.findByTestId('replay-card')
    vi.useFakeTimers({ shouldAdvanceTime: true })
    fireEvent.click(screen.getByTestId('replay-open'))
    const panel = await screen.findByTestId('replay-panel')
    await tick(500)
    fireEvent.click(within(panel).getByTestId('replay-toggle')) // 일시정지
    const paused = within(panel).getByTestId('replay-day').textContent
    await tick(1500)
    expect(within(panel).getByTestId('replay-day').textContent).toBe(paused)
    expect(within(panel).getByTestId('replay-toggle')).toHaveTextContent('재생')
    fireEvent.click(within(panel).getByText('16배'))
    fireEvent.click(within(panel).getByTestId('replay-toggle'))
    await tick(400) // 16배속 0.4초 = 51거래일 → 60점 곡선의 끝 근처
    const after = within(panel).getByTestId('replay-day').textContent!
    expect(after > paused!).toBe(true)
    await tick(2000)
    expect(within(panel).getByTestId('replay-toggle')).toHaveTextContent('처음부터') // 끝에서 멈춘다
  })

  it('슬라이더로 날짜를 옮기면 그 날짜로 가고 재생은 멈춘다', async () => {
    mockApi(resultRoutes())
    result(ID)
    await screen.findByTestId('replay-card')
    fireEvent.click(screen.getByTestId('replay-open'))
    const panel = await screen.findByTestId('replay-panel')
    const handle = within(panel).getByRole('slider')
    fireEvent.keyDown(handle, { key: 'End', keyCode: 35, which: 35 })
    await waitFor(() => expect(within(panel).getByTestId('replay-toggle')).toHaveTextContent('처음부터'))
    expect(within(panel).getByTestId('replay-day').textContent).toBe(replayDays(realEquity).at(-1))
    expect(within(panel).getByTestId('replay-equity')).toHaveTextContent('평가금')
  })

  it('단일 종목: 캔들 창이 옆으로 흐르고 매수·매도가 찍힌다(결과의 봉 API 사용)', async () => {
    const one = { ...realDetail, spec: { ...realDetail.spec, mode: 'daily_single' as const, universe: { ...realDetail.spec.universe, type: 'codes' as const, codes: ['277810'] } } }
    const trades = [tr('277810', '2025-01-10', '2025-01-20')]
    const { calls } = mockApi(resultRoutes(one, trades, realEquity, { 'GET /api/stocks/277810/bars': { data: sx.bars } }))
    result(ID)
    fireEvent.click(await screen.findByTestId('replay-open'))
    const chart = await screen.findByTestId('replay-candle')
    const opt = JSON.parse(within(chart).getByTestId('echart').textContent!)
    expect(opt.series[0].type).toBe('candlestick')
    expect(opt.xAxis.data.length).toBeLessThanOrEqual(60)
    expect(calls.some((c) => c.path.includes('/api/stocks/277810/bars') && c.path.includes('interval=1d'))).toBe(true)
  })

  it('분봉: 날 단위로 넘어가며 그날 거래가 있던 종목의 분봉을 봉 길이·출처 그대로 불러온다', async () => {
    const t0 = alTrades[0]
    const day = dayOf(t0.entry_ts)
    const equity = [eq(day, 10_000_000, 1), eq('2026-08-26', 10_100_000, 0)]
    const minuteBars = { code: t0.code, name: t0.name, interval: '5m', source: 'al', bars: [{ t: `${day} 09:05`, o: 1, h: 2, l: 0.5, c: 1.5, v: 1 }, { t: `${day} 09:10`, o: 1.5, h: 2, l: 1, c: 1.8, v: 1 }] }
    const { calls } = mockApi(resultRoutes(alDetail, alTrades, equity, { [`GET /api/stocks/${t0.code}/bars`]: { data: minuteBars } }))
    result(alDetail.run_id)
    fireEvent.click(await screen.findByTestId('replay-open'))
    const box = await screen.findByTestId('replay-minute')
    await waitFor(() => expect(calls.some((c) => c.path.includes(`/api/stocks/${t0.code}/bars`) && c.path.includes('interval=5m') && c.path.includes('source=al') && c.path.includes(`start=${day}&end=${day}`))).toBe(true))
    expect(box).toHaveTextContent(`${day}`)
    expect(box).toHaveTextContent('5분봉')
  })

  it('최적화·워크포워드 결과에는 재생이 없다(곡선의 뜻이 다르다)', async () => {
    const opt = { ...realDetail, meta: { ...realDetail.meta, kind: 'walkforward' } }
    mockApi(resultRoutes(opt as typeof realDetail, [], realEquity, { [`GET /api/runs/${ID}/folds`]: { status: 404, error: { code: 'NOT_FOUND', message: 'x' } } }))
    result(ID)
    await screen.findByTestId('result-page')
    expect(screen.queryByTestId('replay-card')).not.toBeInTheDocument()
  })
})

describe('재생: 봉을 늦게 불러오는 단일 종목', () => {
  it('봉이 오기 전엔 멈추지 않고 기다렸다가, 오면 날짜가 흘러간다(로딩 중 재생이 꺼져 버리던 결함)', async () => {
    const one = { ...realDetail, spec: { ...realDetail.spec, mode: 'daily_single' as const, universe: { ...realDetail.spec.universe, type: 'codes' as const, codes: ['277810'] } } }
    let release: () => void = () => {}
    const gate = new Promise<void>((r) => { release = r })
    const routes = resultRoutes(one, [tr('277810', '2025-01-10', '2025-01-20')], realEquity, { 'GET /api/stocks/277810/bars': { data: sx.bars } })
    const base = mockApi(routes)
    const original = globalThis.fetch
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/api/stocks/277810/bars')) await gate // 봉 응답을 붙잡아 둔다
      return original(input, init)
    })
    void base
    result(ID)
    await screen.findByTestId('replay-open')
    vi.useFakeTimers({ shouldAdvanceTime: true })
    fireEvent.click(screen.getByTestId('replay-open'))
    const panel = await screen.findByTestId('replay-panel')
    expect(within(panel).getByTestId('replay-toggle')).toHaveTextContent('일시정지') // 로딩 중에도 재생 상태 유지
    await tick(600) // 봉이 안 온 채로 시간이 흘러도
    expect(within(panel).getByTestId('replay-toggle')).toHaveTextContent('일시정지') // 재생이 꺼지지 않는다(전엔 last=0 이라 곧바로 꺼졌다)
    release()
    await screen.findByTestId('replay-candle')
    const first = within(panel).getByTestId('replay-day').textContent
    await tick(1500)
    expect(within(panel).getByTestId('replay-day').textContent).not.toBe(first)
  })
})
