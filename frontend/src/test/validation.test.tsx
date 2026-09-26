// module-5 화면 — 검증 계산(lib/validation) · 결과 패널(최적화·워크포워드·홀드아웃) · 최적화 설정 화면. 값은 실제 서버 응답(studioReal5).
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { OptimizePage } from '@/pages/OptimizePage'
import { ResultPage } from '@/pages/ResultPage'
import {
  criteriaDirection, defaultForm, formFromSpec, gridVariables, heatmapData, rangeVariables, segmentBands, toConfig, toWalkforward, varyingVariables, withBands, withValidation,
} from '@/lib/validation'
import { equityOption } from '@/lib/chartOptions'
import type { SpecJson } from '@/types/studio'
import { realEquity, realTrades } from './fixtures/studioReal'
import { realFolds, realGrid, realHoDetail, realHoSummary, realOptDetail, realOptSummary, realWfDetail, realWfSummary } from './fixtures/studioReal5'
import { mockApi, renderApp } from './helpers'

beforeEach(() => localStorage.clear())

const spec = realOptDetail.spec

describe('검증 계산', () => {
  it('조합 표에서 변수 열과 실제로 훑은 변수를 가른다', () => {
    expect(gridVariables(realGrid)).toEqual(['n', 'vol_mult', 'exit_n'])
    expect(varyingVariables(realGrid)).toEqual(['n', 'vol_mult']) // exit_n 은 한 값 — 축이 될 수 없다
    expect(rangeVariables(spec.params)).toEqual(['n', 'vol_mult', 'exit_n'])
    expect(rangeVariables({ a: { default: 1 }, b: { default: 1, min: 0, max: 2 }, c: { default: 1, min: 2, max: 2, step: 1 } })).toEqual([])
  })

  it('히트맵 자료: 12×5 칸, 값은 조합 표 그대로, 고른 조합만 selected', () => {
    const h = heatmapData(realGrid, 'n', 'vol_mult', 'oos_sharpe')
    expect(h.xs).toHaveLength(12)
    expect(h.ys).toEqual([1, 1.5, 2, 2.5, 3])
    expect(h.cells).toHaveLength(60)
    expect(h.folded).toBe(false)
    const row = realGrid.find((r) => r.n === 60 && r.vol_mult === 3)!
    const cell = h.cells.find((c) => c.x === h.xs.indexOf(60) && c.y === h.ys.indexOf(3))!
    expect(cell.value).toBe(row.oos_sharpe)
    expect(h.cells.filter((c) => c.selected)).toHaveLength(1)
    expect(cell.selected).toBe(true)
  })

  it('무효 조합은 칸에서 빠지고, 변수가 셋이면 나머지는 최고값으로 접는다(낮을수록 좋은 열은 최저값)', () => {
    const rows = [
      { n: 1, m: 1, k: 1, status: 'ok', oos_sharpe: 1, oos_mdd_pct: 30, selected: false },
      { n: 1, m: 1, k: 2, status: 'ok', oos_sharpe: 3, oos_mdd_pct: 10, selected: true },
      { n: 2, m: 1, k: 1, status: 'invalid: x', oos_sharpe: null, oos_mdd_pct: null, selected: false },
    ]
    const h = heatmapData(rows, 'n', 'm', 'oos_sharpe')
    expect(h.cells).toHaveLength(1)
    expect(h.cells[0]).toMatchObject({ value: 3, n: 2, selected: true })
    expect(h.folded).toBe(true)
    expect(heatmapData(rows, 'n', 'm', 'oos_mdd_pct').cells[0].value).toBe(10)
  })

  it('사전 판정 기준의 방향과 설정 → 요청 변환', () => {
    expect(criteriaDirection('sharpe')).toBe('min')
    expect(criteriaDirection('max_drawdown_pct')).toBe('max')
    const f = { ...defaultForm(), objective: 'calmar' as const, minTrades: 20, holdoutPct: 25, trainPct: 60, vary: ['n'], criteria: [{ metric: 'sharpe', value: 0.5 }, { metric: 'max_drawdown_pct', value: null }, { metric: '', value: 3 }] }
    const s = withValidation(spec, f)
    expect(s.validation).toEqual({ objective: 'calmar', min_trades: 20, holdout_pct: 25, criteria: { sharpe: 0.5 } }) // 빈 값·빈 지표 기준은 안 보낸다
    expect(toConfig(f)).toEqual({ train_pct: 60, vary: ['n'] })
    expect(toConfig({ ...f, vary: null, splitDate: '2025-06-30' })).toEqual({ train_pct: 60, split_date: '2025-06-30' })
    expect(toWalkforward({ ...f, wf: { train: 200, test: 50, step: null, mode: 'anchored' } })).toEqual({ train_days: 200, test_days: 50, mode: 'anchored' })
    expect(formFromSpec({ ...spec, validation: { objective: 'cagr', min_trades: 12, holdout_pct: 10, criteria: { sharpe: 1 } } })).toMatchObject({ objective: 'cagr', minTrades: 12, holdoutPct: 10, criteria: [{ metric: 'sharpe', value: 1 }] })
  })

  it('구간 띠는 곡선에 있는 날짜로 맞춰 얹힌다', () => {
    const bands = segmentBands(realOptSummary.segments)
    expect(bands.map((b) => b.name)).toEqual(['학습(IS)', '검증(OOS)', '홀드아웃(잠김)'])
    const o = withBands(equityOption(realEquity, { log: false }), realEquity, bands) as { series: { markArea: { data: unknown[][] } }[] }
    const first = realEquity[0].ts.slice(0, 10)
    expect(o.series[0].markArea.data.length).toBeGreaterThan(0)
    expect((o.series[0].markArea.data[0][0] as { xAxis: string }).xAxis >= first).toBe(true)
  })
})

const routesFor = (d: typeof realOptDetail, extra: Record<string, Parameters<typeof mockApi>[0][string]> = {}) => ({
  [`GET /api/runs/${d.run_id}`]: { data: d },
  [`GET /api/runs/${d.run_id}/equity`]: { data: realEquity },
  [`GET /api/runs/${d.run_id}/trades`]: { data: [] },
  [`GET /api/runs/${d.run_id}/grid`]: { data: realGrid },
  [`GET /api/runs/${d.run_id}/folds`]: { data: realFolds },
  ...extra,
})
const result = (id: string) => renderApp(<Routes><Route path="/results/:runId" element={<ResultPage />} /><Route path="/backtest" element={<div />} /></Routes>, `/results/${id}`)

describe('최적화 결과', () => {
  it('고른 조합·학습 vs 검증 표·이웃 안정성·판정 기준·조합 표가 전부 펼쳐진다', async () => {
    mockApi(routesFor(realOptDetail))
    result(realOptDetail.run_id)
    const sec = await screen.findByTestId('optimize-section')
    expect(within(sec).getByTestId('selected-params')).toHaveTextContent('n=60, vol_mult=3, exit_n=7')
    expect(sec).toHaveTextContent('학습이 섞여 있다'.replace('학습이', '학습 구간이')) // 카드가 학습 구간을 포함한다는 경고
    const t = within(sec).getByTestId('is-oos-table')
    // 실제 값: 학습 샤프 -0.03(나쁨), 검증 샤프 2.46(좋음)
    expect(within(t).getByText('-0.03').closest('[data-verdict]')).toHaveAttribute('data-verdict', 'bad')
    expect(within(t).getByText('2.46').closest('[data-verdict]')).toHaveAttribute('data-verdict', 'good')
    expect(within(sec).getByTestId('stability-value')).toHaveTextContent('—') // 최고 목표값이 0 이하라 비율이 없다 — 지어내지 않음
    expect(sec).toHaveTextContent('최고 목표값이 0 이하라 비율이 뜻이 없다')
    const c = within(sec).getByTestId('criteria-oos')
    expect(within(c).getAllByText('통과')).toHaveLength(2)
    await waitFor(() => expect(within(sec).getByTestId('grid-table')).toBeInTheDocument())
    expect(within(sec).getByText('조합 60개')).toBeInTheDocument() // 쪽 표시: 60조합 전부(무효·거래 부족 포함)
    expect(within(sec).getByTestId('segments')).toHaveTextContent('2025-07-02 ~ 2026-02-20 · 156거래일')
    expect(screen.queryByTestId('criteria-table')).not.toBeInTheDocument() // 학습이 섞인 전체 구간 판정은 안 보여준다
    expect(screen.queryByTestId('overfit-warn')).not.toBeInTheDocument() // 검증이 학습보다 좋으므로 과최적화 경고 아님
    expect(screen.getByTestId('kind-tag')).toHaveTextContent('최적화')
    expect(screen.queryByTestId('rerun-btn')).not.toBeInTheDocument() // 최적화 결과는 일반 재실행 대상이 아님
  })

  it('검증이 학습의 절반에도 못 미치면 과최적화 경고', async () => {
    const bad = { ...realOptDetail, summary: { ...realOptDetail.summary, optimize: { ...realOptSummary, selected: { ...realOptSummary.selected, is_objective: 2, oos_objective: 0.5 } } } }
    mockApi(routesFor(bad))
    result(bad.run_id)
    expect(await screen.findByTestId('overfit-warn')).toBeInTheDocument()
  })

  it('홀드아웃 열기: 처음이면 안내만, 이미 열었으면 강한 경고 + 이해 체크 전엔 못 연다, 열면 조합·출처를 보낸다', async () => {
    const opens = [{ opened_at: '2026-09-25T10:00:00', family_hash: 'x', params: { n: 40 }, open_id: 'a' }, { opened_at: '2026-09-25T11:00:00', family_hash: 'x', params: { n: 50 }, open_id: 'b' }]
    const { calls } = mockApi(routesFor(realOptDetail, {
      'POST /api/validation/holdout-history': { data: { family_hash: 'x', opens, count: 2, ledger_connected: true } },
      'POST /api/jobs/holdout-check': { status: 202, data: { job_id: '20260926-010000-aaaaaa', run_id: '20260926-010000-bbbbbb' } },
    }))
    result(realOptDetail.run_id)
    await userEvent.click(await screen.findByTestId('holdout-open-btn'))
    const warn = await screen.findByTestId('holdout-warn')
    expect(warn).toHaveTextContent('이미 2번 열었다 — 이번이 3번째')
    expect(warn).toHaveTextContent('n=40')
    const ok = screen.getByTestId('holdout-confirm-ok')
    expect(ok).toBeDisabled()
    await userEvent.click(screen.getByTestId('holdout-understood'))
    await waitFor(() => expect(ok).toBeEnabled())
    await userEvent.click(ok)
    await waitFor(() => expect(calls.some((c) => c.path === '/api/jobs/holdout-check')).toBe(true))
    const sent = calls.find((c) => c.path === '/api/jobs/holdout-check')!.body as { spec: SpecJson; overrides: Record<string, number>; source_run_id: string }
    expect(sent.overrides).toEqual({ n: 60, vol_mult: 3, exit_n: 7 })
    expect(sent.source_run_id).toBe(realOptDetail.run_id)
    expect(sent.spec.validation?.holdout_pct).toBe(20)
  })

  it('처음 여는 것이면 체크 없이 바로 열 수 있다', async () => {
    mockApi(routesFor(realOptDetail, { 'POST /api/validation/holdout-history': { data: { family_hash: 'x', opens: [], count: 0, ledger_connected: true } } }))
    result(realOptDetail.run_id)
    await userEvent.click(await screen.findByTestId('holdout-open-btn'))
    expect(await screen.findByTestId('holdout-first')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('holdout-confirm-ok')).toBeEnabled())
    expect(screen.queryByTestId('holdout-understood')).not.toBeInTheDocument()
  })

  it('이력을 못 읽으면 열 수 없다(모르는 채로 열지 않는다)', async () => {
    mockApi(routesFor(realOptDetail, { 'POST /api/validation/holdout-history': { status: 500, error: { code: 'INTERNAL', message: '서버 내부 오류' } } }))
    result(realOptDetail.run_id)
    await userEvent.click(await screen.findByTestId('holdout-open-btn'))
    expect(await screen.findByText(/열람 이력을 확인하지 못해 열 수 없습니다/)).toBeInTheDocument()
    expect(screen.getByTestId('holdout-confirm-ok')).toBeDisabled()
  })
})

describe('워크포워드 결과', () => {
  it('WFE 판정 색·수익 난 폴드·폴드 표·변수 변화', async () => {
    mockApi(routesFor(realWfDetail))
    result(realWfDetail.run_id)
    const sec = await screen.findByTestId('walkforward-section')
    expect(within(sec).getByTestId('wfe-value')).toHaveTextContent('1.00') // 실제 0.995
    expect(within(sec).getByTestId('wfe-card')).toHaveAttribute('data-verdict', 'good')
    expect(within(sec).getByTestId('positive-folds-card')).toHaveTextContent('2 / 4')
    await waitFor(() => expect(within(sec).getByTestId('folds-table')).toBeInTheDocument())
    expect(within(within(sec).getByTestId('folds-table')).getAllByRole('row')).toHaveLength(1 + realWfSummary.n_folds)
    expect(within(sec).getByTestId('params-drift')).toHaveTextContent('60 → 120 → 50 → 50')
    expect(within(sec).getByTestId('folds-table')).toHaveTextContent('2025-01-10 ~ 2025-04-10')
  })

  it('워크포워드 거래에는 MFE/MAE 열이 없다(실제 응답) — 거래 표·차트가 죽지 않고 "—" 로 보인다', async () => {
    const trades = realTrades.slice(0, 5).map((t) => { const { mfe_pct: _a, mae_pct: _b, ...rest } = t; return { ...rest, fold: 0 } })
    mockApi(routesFor(realWfDetail, { [`GET /api/runs/${realWfDetail.run_id}/trades`]: { data: trades } }))
    result(realWfDetail.run_id)
    const table = await screen.findByTestId('trades-table')
    await waitFor(() => expect(within(table).getAllByRole('row').length).toBeGreaterThan(1))
    expect(screen.queryByText(/이 화면을 그리다 오류가 났습니다/)).not.toBeInTheDocument()
    expect(screen.getByTestId('walkforward-section')).toBeInTheDocument()
  })

  it('WFE 가 없으면(null) 지어내지 않고 이유를 말한다', async () => {
    const d = { ...realWfDetail, summary: { ...realWfDetail.summary, walkforward: { ...realWfSummary, wfe: null } } }
    mockApi(routesFor(d))
    result(d.run_id)
    const card = await screen.findByTestId('wfe-card')
    expect(card).toHaveTextContent('없음')
    expect(card).toHaveTextContent('비율이 뜻이 없다')
    expect(card).toHaveAttribute('data-verdict', 'none')
  })
})

describe('홀드아웃 결과', () => {
  it('첫 열람이면 안내, 학습·검증·홀드아웃을 나란히 보여준다', async () => {
    mockApi(routesFor(realHoDetail, { [`GET /api/runs/${realHoSummary.source_run_id}`]: { data: realOptDetail } }))
    result(realHoDetail.run_id)
    const sec = await screen.findByTestId('holdout-section')
    expect(within(sec).getByTestId('holdout-nth')).toHaveTextContent('홀드아웃 첫 열람')
    const t = await within(sec).findByTestId('three-way-table')
    expect(t).toHaveTextContent('학습(IS)')
    expect(t).toHaveTextContent('홀드아웃')
    expect(t).toHaveTextContent('-0.82') // 홀드아웃 샤프(실제) — 검증 2.46 과 대조
    expect(t).toHaveTextContent('2.46')
  })

  it('두 번째 이상 열람이면 오류색으로 횟수와 이전 열람을 보여준다', async () => {
    const d = { ...realHoDetail, summary: { ...realHoDetail.summary, holdout: { ...realHoSummary, nth_open: 3, previous_opens: [{ opened_at: '2026-09-26T00:19:01', family_hash: 'x', params: { n: 60 }, open_id: 'o1' }] } } }
    mockApi(routesFor(d))
    result(d.run_id)
    const nth = await screen.findByTestId('holdout-nth')
    expect(nth).toHaveTextContent('3번째 홀드아웃 열람 — 신뢰가 깎였다')
    expect(nth).toHaveTextContent('2026-09-26 00:19:01 에 연 적 있음')
  })
})

describe('최적화 설정 화면', () => {
  const info = (n: number, extra = {}) => ({ data: { n, limit: 5000, warn_over: 500, axes: { n: 12, vol_mult: 5, exit_n: 38 }, too_large: n > 5000, warn: n > 500, ...extra } })
  const routes = (gi: ReturnType<typeof info>) => ({
    'GET /api/presets': { data: [{ name: 'new_high_20', title: null, mode: 'daily_portfolio', period: null, n_params: 3 }] },
    'GET /api/runs': { data: [] },
    'GET /api/presets/new_high_20': { data: { name: 'new_high_20', spec } },
    'POST /api/validation/grid-info': gi,
    'POST /api/conditions/validate': { data: { ok: true, errors: [], warnings: [], narration: '' } },
    'POST /api/jobs/optimize': { status: 202, data: { job_id: '20260926-020000-aaaaaa', run_id: '20260926-020000-bbbbbb' } },
    'POST /api/jobs/walkforward': { status: 202, data: { job_id: '20260926-020001-aaaaaa', run_id: '20260926-020001-bbbbbb' } },
  })
  const page = () => renderApp(<Routes><Route path="/optimize" element={<OptimizePage />} /><Route path="/backtest" element={<div />} /></Routes>, '/optimize?preset=new_high_20')

  it('조합 수를 서버가 센 값으로 보여주고 정상이면 실행 버튼이 켜진다', async () => {
    mockApi(routes(info(60)))
    page()
    await waitFor(() => expect(screen.getByTestId('combo-count')).toHaveTextContent('60'))
    await waitFor(() => expect(screen.getByTestId('run-optimize')).toBeEnabled())
    expect(screen.getByTestId('holdout-pct')).toBeDisabled() // 홀드아웃 % 는 잠겨 있다
    expect(screen.getByTestId('holdout-lock')).toBeInTheDocument()
    expect(screen.queryByTestId('combo-warn')).not.toBeInTheDocument()
  })

  it('500 초과는 경고만(실행 가능), 5,000 초과는 사유와 함께 실행 불가', async () => {
    mockApi(routes(info(800)))
    const { unmount } = page()
    expect(await screen.findByTestId('combo-warn')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('run-optimize')).toBeEnabled())
    unmount()
    mockApi(routes(info(6000)))
    page()
    expect(await screen.findByTestId('combo-toolarge')).toBeInTheDocument()
    expect(screen.getByTestId('run-optimize')).toBeDisabled()
    expect(screen.getByTestId('run-walkforward')).toBeDisabled()
    expect(screen.getByTestId('block-reason')).toHaveTextContent('6,000개')
  })

  it('실행하면 목표·최소 거래·홀드아웃·판정 기준은 명세(validation)에, 분할·변수는 config 에 담아 보낸다', async () => {
    const { calls } = mockApi(routes(info(60)))
    page()
    await waitFor(() => expect(screen.getByTestId('run-optimize')).toBeEnabled())
    await userEvent.click(screen.getByTestId('criteria-add'))
    fireEvent.change(screen.getByTestId('min-trades'), { target: { value: '25' } })
    fireEvent.change(screen.getByTestId('train-pct'), { target: { value: '60' } })
    await waitFor(() => expect(screen.getByTestId('run-optimize')).toBeEnabled())
    await userEvent.click(screen.getByTestId('run-optimize'))
    await waitFor(() => expect(calls.some((c) => c.path === '/api/jobs/optimize')).toBe(true))
    const b = calls.find((c) => c.path === '/api/jobs/optimize')!.body as { spec: SpecJson; config: Record<string, unknown> }
    expect(b.spec.validation).toEqual({ objective: 'sharpe', min_trades: 25, holdout_pct: 20, criteria: { max_drawdown_pct: 30, sharpe: 0.5 } }) // 불러온 명세의 기존 기준 + 같은 지표 추가분은 합쳐진다
    expect(b.config).toEqual({ train_pct: 60 })
  })

  it('워크포워드 실행은 폴드 설정을 함께 보낸다', async () => {
    const { calls } = mockApi(routes(info(60)))
    page()
    await waitFor(() => expect(screen.getByTestId('run-walkforward')).toBeEnabled())
    fireEvent.change(screen.getByTestId('wf-train'), { target: { value: '200' } })
    await userEvent.click(screen.getByTestId('run-walkforward'))
    await waitFor(() => expect(calls.some((c) => c.path === '/api/jobs/walkforward')).toBe(true))
    const b = calls.find((c) => c.path === '/api/jobs/walkforward')!.body as { walkforward: Record<string, unknown> }
    expect(b.walkforward).toEqual({ train_days: 200, test_days: 60, mode: 'rolling' })
  })

  it('변수가 없는 명세는 이유와 갈 곳을 말하고 실행을 막는다', async () => {
    const noParams = { ...spec, params: {} }
    mockApi({ ...routes(info(0)), 'GET /api/presets/new_high_20': { data: { name: 'new_high_20', spec: noParams } } })
    page()
    expect(await screen.findByTestId('no-params')).toHaveTextContent('이 명세엔 변수가 없다')
    expect(screen.getByTestId('run-optimize')).toBeDisabled()
  })

  it('기준 명세를 아직 안 골랐으면 고르라고 안내한다', async () => {
    mockApi(routes(info(60)))
    renderApp(<Routes><Route path="/optimize" element={<OptimizePage />} /></Routes>, '/optimize')
    expect(await screen.findByTestId('source-picker')).toBeInTheDocument()
    expect(screen.queryByTestId('run-optimize')).not.toBeInTheDocument()
  })
})
