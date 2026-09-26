// module-6 화면 — 분봉·틱 명세 도우미(lib/spec) · 입력 탭 · 결과 패널(출처 배너·커버리지·틱 정밀화·거래 표·캔들 서랍). 값은 실제 서버 응답(studioReal6).
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { clampPeriodToRange, defaultTick, newSpec, normalizeSpec, setTickEntrySource, switchMode } from '@/lib/spec'
import { BacktestPage } from '@/pages/BacktestPage'
import { ResultPage } from '@/pages/ResultPage'
import type { IntradaySources, SpecJson } from '@/types/studio'
import * as sx from './fixtures/studio'
import { realEquity } from './fixtures/studioReal'
import { alDetail, alTrades, krxDetail, refineDetail, refineRefine, refineTrades, tickDetail, tickTrades } from './fixtures/studioReal6'
import { mockApi, renderApp } from './helpers'

beforeEach(() => localStorage.clear())

const RANGES = { ...sx.dataRanges, minute_al: ['2025-08-01', '2026-09-23'], minute_krx: ['2025-07-01', '2026-09-23'], tick_al: ['2026-08-04', '2026-09-23'] } as Record<string, [string, string]>
const SOURCES: IntradaySources = {
  minute: { al: { total: 135, full: 40, partial: 95, range: ['2025-08-01', '2026-09-23'] }, krx: { total: 1055, full: 1044, partial: 11, range: ['2025-07-01', '2026-09-23'] } },
  tick: { codes: 173, days: 17, first: '2026-08-04', last: '2026-09-23', days_in_range: 17 },
}

describe('분봉·틱 명세 도우미', () => {
  it('새 분봉 명세: 30일 창·통합 출처·전일 상위 30·15:20 청산, 새 틱 명세는 전략 없이 틱 조건', () => {
    const i = newSpec('intraday', { end: '2026-09-23' })
    expect(i.period).toEqual({ start: '2026-08-24', end: '2026-09-23' })
    expect(i.intraday).toEqual({ bar_minutes: 5, source: 'al', prefilter: null, prefilter_top_value: 30, eod_time: '15:20' })
    expect(i.tick).toBeNull()
    expect(i.strategy?.source).toBe('builder')
    const t = newSpec('tick', { end: '2026-09-23' })
    expect(t.strategy).toBeNull() // 틱 조건 진입엔 전략 조건식이 없다
    expect(t.tick).toEqual(defaultTick())
    expect(newSpec('daily_portfolio').intraday).toBeNull()
  })

  it('모드 바꾸기: 분봉·틱은 그 데이터의 끝에서 30일, 일봉으로 돌아오면 3년·전략 복원·분봉/틱 설정 제거', () => {
    const d = newSpec('daily_portfolio', { end: '2026-09-23' })
    const legacy: SpecJson = { ...d, strategy: { source: 'legacy', name: 'ma_crossover', params: {} } }
    const i = switchMode(legacy, 'intraday', ['2025-08-01', '2026-09-10'])
    expect(i.period).toEqual({ start: '2026-08-11', end: '2026-09-10' })
    expect(i.strategy?.source).toBe('builder') // 기존 전략은 일봉 전용이라 조립기로 바뀐다
    expect(i.intraday?.source).toBe('al')
    const t = switchMode(i, 'tick', ['2026-08-04', '2026-09-23'])
    expect(t.strategy).toBeNull()
    expect(t.tick?.entry_source).toBe('catalog')
    expect(t.period.end).toBe('2026-09-23')
    const back = switchMode(t, 'daily_portfolio', ['2019-04-23', '2026-09-23'])
    expect(back.strategy?.source).toBe('builder')
    expect(back.tick).toBeNull()
    expect(back.intraday).toBeNull()
    expect(back.period).toEqual({ start: '2023-09-23', end: '2026-09-23' })
  })

  it('틱 진입 방식: 분봉+틱 정밀화는 전략과 분봉 설정이 필요하고, 틱 조건으로 돌아오면 전략이 사라진다', () => {
    const t = newSpec('tick', { end: '2026-09-23' })
    const r = setTickEntrySource(t, 'minute_refine')
    expect(r.tick?.entry_source).toBe('minute_refine')
    expect(r.strategy?.source).toBe('builder')
    expect(r.intraday).not.toBeNull()
    const c = setTickEntrySource(r, 'catalog')
    expect(c.strategy).toBeNull()
    expect(c.tick?.catalog).toEqual(t.tick?.catalog) // 틱 조건 값은 그대로
  })

  it('기간 끝이 데이터 끝을 넘으면 끝에서 30일로 당기고, 이미 안이면 그대로 둔다', () => {
    const p = { start: '2026-08-26', end: '2026-09-25' }
    expect(clampPeriodToRange(p, ['2025-08-01', '2026-09-23'])).toEqual({ start: '2026-08-24', end: '2026-09-23' })
    expect(clampPeriodToRange({ start: '2026-08-26', end: '2026-09-20' }, ['2025-08-01', '2026-09-23'])).toEqual({ start: '2026-08-26', end: '2026-09-20' })
    expect(clampPeriodToRange(p, ['2026-09-10', '2026-09-23'])).toEqual({ start: '2026-09-10', end: '2026-09-23' }) // 데이터가 30일보다 짧으면 처음부터
    const inside = { start: '2026-08-26', end: '2026-09-20' }
    expect(clampPeriodToRange(inside, ['2025-08-01', '2026-09-23'])).toBe(inside)
  })

  it('normalizeSpec: 손으로 쓴 틱 프리셋(전략 null)은 전략 없이, 칸이 빠진 분봉 명세는 기본값으로 채운다', () => {
    const tickPreset = normalizeSpec({ mode: 'tick', period: { start: '2026-09-01', end: '2026-09-23' }, strategy: null, tick: { entry_source: 'catalog', catalog: { breakout_min: 3 } } } as unknown as Partial<SpecJson>)
    expect(tickPreset.strategy).toBeNull()
    expect(tickPreset.tick?.catalog).toMatchObject({ breakout_min: 3, time_from: '09:05', time_to: '15:00', value_speed: null })
    expect(tickPreset.tick?.cooldown_sec).toBe(300)
    const i = normalizeSpec({ mode: 'intraday', period: { start: '2026-09-01', end: '2026-09-23' }, intraday: { bar_minutes: 15 } } as unknown as Partial<SpecJson>)
    expect(i.intraday).toMatchObject({ bar_minutes: 15, source: 'al', prefilter_top_value: 30, eod_time: '15:20' })
    expect(normalizeSpec({ mode: 'daily_portfolio', strategy: null } as unknown as Partial<SpecJson>).strategy?.source).toBe('builder') // 일봉엔 전략이 꼭 있어야 한다
  })
})

const routes = (over: Record<string, Parameters<typeof mockApi>[0][string]> = {}) => ({
  'GET /api/meta/indicators': { data: sx.catalog },
  'GET /api/meta/strategies': { data: sx.legacyDefs },
  'GET /api/meta/data-ranges': { data: RANGES },
  'GET /api/meta/intraday-sources': { data: SOURCES },
  'GET /api/presets': { data: sx.presetRows },
  'POST /api/conditions/validate': { data: sx.validOk },
  'POST /api/jobs/backtest': { status: 202, data: { job_id: '20260926-030000-aaaaaa', run_id: '20260926-030000-bbbbbb' } },
  ...over,
})
const page = () => renderApp(<Routes><Route path="/backtest" element={<BacktestPage />} /><Route path="/results/:runId" element={<div />} /></Routes>, '/backtest')
const lastSpec = (calls: { path: string; body: unknown }[]): SpecJson => {
  const v = calls.filter((c) => c.path.startsWith('/api/conditions/validate'))
  return (v[v.length - 1].body as { spec: SpecJson }).spec
}

describe('분봉 탭', () => {
  it('탭을 켜면 분봉 설정이 나오고 기간은 분봉 데이터 끝에서 30일, 출처별 사용 가능 기간이 보인다', async () => {
    const { calls } = mockApi(routes())
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '분봉 단타' }))
    const panel = await screen.findByTestId('panel-intraday')
    expect(within(panel).getByTestId('bar-minutes')).toBeInTheDocument()
    expect(await screen.findByTestId('panel-period')).toHaveTextContent('통합 분봉 데이터 2025-08-01 ~ 2026-09-23')
    const av = await screen.findByTestId('source-availability')
    expect(av).toHaveTextContent('통합(AL) — NXT 체결 포함')
    expect(av).toHaveTextContent('1055')
    expect(within(av).getByText('선택됨').closest('tr')).toHaveTextContent('통합')
    await waitFor(() => expect(lastSpec(calls).mode).toBe('intraday'))
    const s = lastSpec(calls)
    expect(s.period).toEqual({ start: '2026-08-24', end: '2026-09-23' })
    expect(s.intraday).toMatchObject({ source: 'al', bar_minutes: 5, prefilter_top_value: 30 })
    expect(s.tick ?? null).toBeNull()
    expect(calls.some((c) => c.path.startsWith('/api/meta/intraday-sources?start=2026-08-24&end=2026-09-23'))).toBe(true)
  })

  it('KRX 를 고르면 큰 경고가 뜨고 명세·기간 기준이 KRX 로 바뀐다', async () => {
    const { calls } = mockApi(routes())
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '분봉 단타' }))
    await screen.findByTestId('panel-intraday')
    expect(screen.queryByTestId('krx-warning')).not.toBeInTheDocument()
    await userEvent.click(within(screen.getByTestId('minute-source')).getByText('KRX 전용'))
    expect(await screen.findByTestId('krx-warning')).toHaveTextContent('KRX 기준(NXT 제외, 거래량·거래대금이 통합보다 20~40% 작음)')
    expect(screen.getByTestId('panel-period')).toHaveTextContent('KRX 분봉 데이터 2025-07-01')
    await waitFor(() => expect(lastSpec(calls).intraday?.source).toBe('krx'))
    expect(screen.getByTestId('source-availability')).toBeInTheDocument()
    expect(within(screen.getByTestId('source-availability')).getByText('선택됨').closest('tr')).toHaveTextContent('KRX')
  })

  it('선택한 출처가 기간을 통째로 덮는 종목이 없으면 "일부만" 경고, 아예 없으면 오류(실행이 빈손)', async () => {
    const { unmount } = (mockApi(routes({ 'GET /api/meta/intraday-sources': { data: { ...SOURCES, minute: { ...SOURCES.minute, al: { ...SOURCES.minute.al, full: 0 } } } } })), page())
    await userEvent.click(await screen.findByRole('tab', { name: '분봉 단타' }))
    expect(await screen.findByTestId('source-partial')).toHaveTextContent('일부만 덮는다')
    expect(screen.queryByTestId('source-none')).not.toBeInTheDocument()
    unmount()
    mockApi(routes({ 'GET /api/meta/intraday-sources': { data: { ...SOURCES, minute: { ...SOURCES.minute, al: { ...SOURCES.minute.al, full: 0, partial: 0 } } } } }))
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '분봉 단타' }))
    expect(await screen.findByTestId('source-none')).toHaveTextContent('분봉이 하나도 없다')
  })

  it('분봉에선 기존 전략을 쓸 수 없고, 유니버스 N 은 무시된다고 알리며, 오늘 종목 미리보기는 꺼진다', async () => {
    mockApi(routes())
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '분봉 단타' }))
    await screen.findByTestId('panel-intraday')
    expect(within(screen.getByTestId('strategy-source')).getByText('기존 전략').closest('label')?.querySelector('input')).toBeDisabled()
    expect(screen.getByTestId('universe-n')).toBeDisabled()
    expect(screen.getByTestId('panel-universe')).toHaveTextContent('분봉 모드에서는 무시된다')
    expect(screen.getByTestId('preview-btn')).toBeDisabled()
  })

  it('일봉 사전 필터를 켜면 전일 일봉 조건 편집기가 나온다', async () => {
    const { calls } = mockApi(routes())
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '분봉 단타' }))
    await userEvent.click(await screen.findByTestId('prefilter-switch'))
    expect(await screen.findByTestId('row-intraday.prefilter.items.0')).toBeInTheDocument()
    await waitFor(() => expect(lastSpec(calls).intraday?.prefilter?.items).toHaveLength(1))
    fireEvent.change(screen.getByTestId('prefilter-top'), { target: { value: '50' } })
    await waitFor(() => expect(lastSpec(calls).intraday?.prefilter_top_value).toBe(50))
  })

  it('실행하면 분봉 명세 그대로 제출한다', async () => {
    const { calls } = mockApi(routes())
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '분봉 단타' }))
    await waitFor(() => expect(screen.getByTestId('run-btn')).toBeEnabled(), { timeout: 9000 })
    await userEvent.click(screen.getByTestId('run-btn'))
    await waitFor(() => expect(calls.some((c) => c.path === '/api/jobs/backtest')).toBe(true))
    const body = calls.find((c) => c.path === '/api/jobs/backtest')!.body as SpecJson
    expect(body.mode).toBe('intraday')
    expect(body.intraday?.source).toBe('al')
  })
})

describe('틱 탭', () => {
  const openTick = async () => {
    const r = mockApi(routes())
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '체결(틱)' }))
    await screen.findByTestId('panel-tick')
    return r
  }

  it('틱 조건 진입: 전략 없음 안내 · 표본 안내(17거래일·173종목) · 틱 조건 3종 · 시간 손절', async () => {
    const { calls } = await openTick()
    expect(screen.getByTestId('tick-no-strategy')).toBeInTheDocument()
    expect(await screen.findByTestId('tick-sample')).toHaveTextContent('17거래일')
    expect(screen.getByTestId('tick-sample')).toHaveTextContent('173종목')
    for (const id of ['tick-breakout-on', 'tick-speed-on', 'tick-buy-on', 'tick-gap-on', 'tick-timestop-on']) expect(screen.getByTestId(id)).toBeInTheDocument()
    expect(screen.getByTestId('tick-breakout')).toBeInTheDocument()
    expect(screen.getByTestId('panel-exits')).toHaveTextContent('시간 손절') // 틱은 최대 보유 봉이 없다
    expect(screen.getByTestId('panel-exits')).not.toHaveTextContent('최대 보유 봉 이 봉 수를')
    expect(screen.getByTestId('panel-costs')).toHaveTextContent('틱 모드는 거래량 한도를 적용하지 않는다')
    await waitFor(() => expect(lastSpec(calls).mode).toBe('tick'))
    expect(lastSpec(calls).strategy).toBeNull()
    expect(lastSpec(calls).tick).toMatchObject({ entry_source: 'catalog', cooldown_sec: 300, exclude_gap_open_pct: 5, time_stop_sec: 600 })
  })

  it('틱 조건을 다 끄면 오류 문구, 체결대금 속도를 켜면 값 칸이 생기고 명세에 실린다', async () => {
    const { calls } = await openTick()
    await userEvent.click(screen.getByTestId('tick-breakout-on'))
    expect(await screen.findByTestId('tick-no-cond')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('tick-speed-on'))
    expect(screen.queryByTestId('tick-no-cond')).not.toBeInTheDocument()
    await waitFor(() => expect(lastSpec(calls).tick?.catalog).toMatchObject({ breakout_min: null, value_speed: { w: 1, ratio: 3 } }))
    fireEvent.change(screen.getByTestId('tick-speed-ratio'), { target: { value: '5' } })
    await waitFor(() => expect(lastSpec(calls).tick?.catalog.value_speed?.ratio).toBe(5))
  })

  it('체결 표본이 고른 기간에 하나도 없으면 알린다', async () => {
    mockApi(routes({ 'GET /api/meta/intraday-sources': { data: { ...SOURCES, tick: { ...SOURCES.tick, days_in_range: 0 } } } }))
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '체결(틱)' }))
    expect(await screen.findByTestId('tick-none')).toHaveTextContent('하나도 없다')
  })

  it('분봉+틱 정밀화로 바꾸면 분봉 설정과 전략이 생기고, 틱 조건으로 돌아오면 전략이 사라진다', async () => {
    const { calls } = await openTick()
    await userEvent.click(within(screen.getByTestId('tick-entry-source')).getByText('분봉 신호 + 틱 정밀화'))
    expect(await screen.findByTestId('panel-intraday')).toBeInTheDocument()
    expect(screen.queryByTestId('tick-catalog')).not.toBeInTheDocument()
    expect(screen.getByTestId('strategy-source')).toBeInTheDocument()
    await waitFor(() => expect(lastSpec(calls).tick?.entry_source).toBe('minute_refine'))
    expect(lastSpec(calls).strategy?.source).toBe('builder')
    expect(lastSpec(calls).intraday).not.toBeNull()
    await userEvent.click(within(screen.getByTestId('tick-entry-source')).getByText('틱 조건으로 바로 진입'))
    await waitFor(() => expect(lastSpec(calls).strategy).toBeNull())
    expect(screen.queryByTestId('panel-intraday')).not.toBeInTheDocument()
  })
})

const ID = (d: { run_id: string }) => d.run_id
const minuteBars = { code: '001210', name: '금호전기', interval: '5m', source: 'al', bars: Array.from({ length: 120 }, (_, i) => ({ t: `2026-08-2${i < 60 ? 3 : 4} ${String(9 + Math.floor((i % 60) / 12)).padStart(2, '0')}:${String(((i % 12) + 1) * 5 % 60).padStart(2, '0')}`, o: 1000 + i, h: 1010 + i, l: 990 + i, c: 1005 + i, v: 100 })) }
const resultRoutes = (d: typeof alDetail, trades: unknown[], over: Record<string, Parameters<typeof mockApi>[0][string]> = {}) => ({
  [`GET /api/runs/${ID(d)}`]: { data: d },
  [`GET /api/runs/${ID(d)}/equity`]: { data: realEquity },
  [`GET /api/runs/${ID(d)}/trades`]: { data: trades },
  ...over,
})
const result = (id: string) => renderApp(<Routes><Route path="/results/:runId" element={<ResultPage />} /></Routes>, `/results/${id}`)

describe('분봉·틱 결과', () => {
  it('통합 분봉 결과: 작은 출처 태그 + 커버리지(82%) · 분봉 있는 거래일 · 분봉 없는 종목', async () => {
    mockApi(resultRoutes(alDetail, alTrades))
    result(alDetail.run_id)
    expect(await screen.findByTestId('al-tag')).toHaveTextContent('통합(AL)')
    expect(screen.queryByTestId('krx-banner')).not.toBeInTheDocument()
    const cov = await screen.findByTestId('intraday-coverage')
    expect(cov).toHaveTextContent('566 / 690')
    expect(cov).toHaveTextContent('82%')
    expect(cov).toHaveTextContent('23 / 23일')
    expect(cov).toHaveTextContent('135 / 141종목')
    expect(cov).toHaveTextContent('0011A0')
    expect(within(cov).getByTestId('code-periods')).toHaveTextContent('2026-08-21')
    expect(screen.getByTestId('warning-badges')).toHaveTextContent('분봉 짧은 표본')
    expect(screen.queryByTestId('tick-refine')).not.toBeInTheDocument()
  })

  it('KRX 결과는 맨 위에 "KRX 기준" 을 크게 보인다', async () => {
    mockApi(resultRoutes(krxDetail, []))
    result(krxDetail.run_id)
    const b = await screen.findByTestId('krx-banner')
    expect(b).toHaveTextContent('KRX 기준(NXT 제외, 거래량·거래대금이 통합보다 20~40% 작음)')
    expect(b).toHaveTextContent('나란히 비교하지 마세요')
    expect(screen.getByTestId('intraday-coverage')).toHaveTextContent('690 / 690')
    expect(screen.getByTestId('warning-badges')).toHaveTextContent('KRX 전용')
  })

  it('틱 정밀화 비교: 다시 잡은 거래 수 · 체결가 차이 통계 · 봉 vs 틱 손익 차이(부호·해석)', async () => {
    mockApi(resultRoutes(refineDetail, refineTrades))
    result(refineDetail.run_id)
    const card = await screen.findByTestId('tick-refine')
    expect(within(card).getByTestId('n-refined')).toHaveTextContent('160')
    const diff = within(card).getByTestId('diff-stats')
    expect(diff).toHaveTextContent('진입가')
    expect(diff).toHaveTextContent('청산가')
    expect(diff).toHaveTextContent('-0.028%') // 청산가 차이 평균(실제 -0.0284)
    expect(diff).toHaveTextContent('-0.018%') // 중앙값
    expect(within(card).getByTestId('pnl-tick')).toHaveTextContent('-3,439,534원')
    const delta = Math.round(refineRefine.net_pnl_tick! - refineRefine.net_pnl_bar!)
    expect(within(card).getByTestId('pnl-delta')).toHaveTextContent(`${delta.toLocaleString('ko-KR')}원`)
    expect(card).toHaveTextContent('봉 기준 백테스트가 체결을 실제보다 좋게 봤다') // 틱이 더 나쁨
    expect(card).toHaveTextContent('diff = 틱 기준가 ÷ 봉 기준가 − 1') // 서버가 준 정의를 그대로
    expect(screen.getByTestId('intraday-coverage')).toBeInTheDocument() // 정밀화 실행은 분봉 표본도 함께
  })

  it('틱 정밀화 실행의 거래 표에는 체결가 차이 열이 붙고 정밀화 여부가 보인다', async () => {
    mockApi(resultRoutes(refineDetail, refineTrades))
    result(refineDetail.run_id)
    const table = await screen.findByTestId('trades-table')
    for (const h of ['진입가 차이(틱÷봉)', '청산가 차이(틱÷봉)', '틱 기준 순손익', '정밀화']) expect(within(table).getByText(h)).toBeInTheDocument()
    await waitFor(() => expect(within(table).getAllByText('틱').length).toBeGreaterThan(0))
    expect(within(table).getByText('진입 시각')).toBeInTheDocument() // 일 단위가 아니라 시각
  })

  it('틱 조건 결과: 표본 카드 · 보유는 초 단위 · 정밀화 카드 없음, 일반 거래 표엔 차이 열이 없다', async () => {
    mockApi(resultRoutes(tickDetail, tickTrades))
    result(tickDetail.run_id)
    const s = await screen.findByTestId('tick-summary')
    expect(s).toHaveTextContent('589 / 589')
    expect(s).toHaveTextContent('17거래일 · 173종목')
    expect(s).toHaveTextContent('13,788')
    expect(s).toHaveTextContent('15:19:59')
    expect(screen.queryByTestId('tick-refine')).not.toBeInTheDocument()
    const table = await screen.findByTestId('trades-table')
    await waitFor(() => expect(within(table).getAllByText(/초$/).length).toBeGreaterThan(0)) // 605초
    expect(within(table).queryByText('정밀화')).not.toBeInTheDocument()
    expect(screen.getByTestId('warning-badges')).toHaveTextContent('틱 표본')
  })

  it('분봉 거래를 누르면 그 종목의 분봉(봉 길이·출처 그대로)으로 차트를 연다', async () => {
    const { calls } = mockApi(resultRoutes(alDetail, alTrades, { [`GET /api/stocks/${alTrades[0].code}/bars`]: { data: minuteBars } }))
    result(alDetail.run_id)
    const table = await screen.findByTestId('trades-table')
    await waitFor(() => expect(within(table).getAllByRole('row').length).toBeGreaterThan(1))
    await userEvent.click(within(table).getAllByRole('row')[1])
    await screen.findByTestId('candle-drawer')
    await waitFor(() => expect(calls.some((c) => c.path.includes(`/api/stocks/${alTrades[0].code}/bars`))).toBe(true))
    const q = calls.find((c) => c.path.includes('/bars'))!.path
    expect(q).toContain('interval=5m')
    expect(q).toContain('source=al')
    expect(await screen.findByTestId('candle-chart')).toHaveTextContent('5분봉')
  })

  it('KRX 결과의 거래 차트는 KRX 분봉을 요청한다', async () => {
    const { calls } = mockApi(resultRoutes(krxDetail, [{ ...alTrades[0], code: '035420' }], { [`GET /api/stocks/035420/bars`]: { data: minuteBars } }))
    result(krxDetail.run_id)
    const table = await screen.findByTestId('trades-table')
    await waitFor(() => expect(within(table).getAllByRole('row').length).toBeGreaterThan(1))
    await userEvent.click(within(table).getAllByRole('row')[1])
    await screen.findByTestId('candle-chart')
    expect(calls.find((c) => c.path.includes('/bars'))!.path).toContain('source=krx')
  })
})
