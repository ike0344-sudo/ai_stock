import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { getBasket } from '@/lib/compareBasket'
import { ComparePage } from '@/pages/ComparePage'
import { ResultPage } from '@/pages/ResultPage'
import { RunsPage } from '@/pages/RunsPage'
import type { RunDetail } from '@/types/studio'
import * as sx from './fixtures/studio'
import { realDetail, realEquity, realTrades } from './fixtures/studioReal'
import { mockApi, renderApp } from './helpers'

const ID = sx.RUN_A
const resultRoutes = (detail: RunDetail = realDetail, over: Record<string, Parameters<typeof mockApi>[0][string]> = {}) => ({
  [`GET /api/runs/${ID}`]: { data: detail },
  [`GET /api/runs/${ID}/equity`]: { data: realEquity },
  [`GET /api/runs/${ID}/trades`]: { data: realTrades },
  [`GET /api/stocks/${realTrades[0].code}/bars`]: { data: sx.bars },
  ...over,
})
const result = () => renderApp(<Routes><Route path="/results/:runId" element={<ResultPage />} /><Route path="/backtest" element={<div data-testid="bt-route" />} /></Routes>, `/results/${ID}`)

beforeEach(() => localStorage.clear())

describe('결과 화면 (실제 응답 값으로)', () => {
  it('헤더: 이름·모드·기간·데이터 기준(허브 기준일)·엔진·git·소요·버튼 4개', async () => {
    mockApi(resultRoutes())
    result()
    const h = await screen.findByTestId('result-header')
    expect(within(h).getByTestId('run-name')).toHaveValue(realDetail.spec.name)
    expect(h).toHaveTextContent('일봉 · 포트폴리오')
    expect(h).toHaveTextContent('2025-01-02 ~ 2025-08-29')
    expect(within(h).getByTestId('data-basis')).toHaveTextContent('일봉 2026-09-23(허브 기준일)')
    expect(h).toHaveTextContent('엔진 0.1.0')
    expect(h).toHaveTextContent(`소요 ${realDetail.meta.elapsed_sec}초`)
    for (const id of ['rerun-btn', 'clone-btn', 'basket-btn', 'csv-btn']) expect(within(h).getByTestId(id)).toBeInTheDocument()
    expect(within(h).getByTestId('csv-btn')).toHaveAttribute('href', `/api/runs/${ID}/export/trades.csv`)
  })

  it('지표 카드는 접지 않고 전부(24개) 보이며 §5.5 판정 색이 붙는다', async () => {
    mockApi(resultRoutes())
    result()
    const cards = await screen.findByTestId('metric-cards')
    expect(within(cards).getAllByTestId(/^metric-[a-z_]+$/)).toHaveLength(24)
    // 실제 값: 샤프 0.57 → 보통, MDD 29.31% → 보통, 초과수익 -23.11 → 나쁨, 거래 157 → 좋음, PF 1.08 → 보통
    const v = (k: string) => screen.getByTestId(`metric-${k}`).getAttribute('data-verdict')
    expect([v('sharpe'), v('max_drawdown_pct'), v('excess_return_pct'), v('num_trades'), v('profit_factor'), v('sortino'), v('calmar')]).toEqual(['mid', 'mid', 'bad', 'good', 'mid', 'mid', 'mid'])
    expect(v('total_return_pct')).toBe('none') // 기준이 없는 지표는 판정 없음
    expect(screen.getByTestId('metric-total_return_pct-value')).toHaveTextContent('+9.70%')
    expect(screen.getByTestId('metric-max_drawdown_pct-value')).toHaveTextContent('29.31%')
    expect(within(screen.getByTestId('metric-excess_return_pct')).getByText('나쁨')).toBeInTheDocument()
    expect(screen.queryByTestId('legacy-line')).not.toBeInTheDocument() // 호환 모드가 아니면 CLI 줄 없음
  })

  it('호환 모드 결과는 "기존 CLI 기준" 줄을 함께 보여준다', async () => {
    const compat = { ...realDetail, summary: { ...realDetail.summary, legacy_metrics: { total_return_pct: 5.5, cagr_pct: 8, win_rate_pct: 40, max_drawdown_pct: 12, sharpe_ratio: 0.9, num_trades: 30 } } }
    mockApi(resultRoutes(compat))
    result()
    expect(await screen.findByTestId('legacy-line')).toHaveTextContent('총수익률 +5.50% · CAGR +8.00% · 승률 40.0% · MDD 12.00% · 샤프(거래 기준) 0.90 · 거래 수 30')
  })

  it('경고는 전부 그대로 배지로(요약·접기 없음)', async () => {
    mockApi(resultRoutes())
    result()
    const w = await screen.findByTestId('warning-badges')
    for (const text of realDetail.warnings) expect(w).toHaveTextContent(text.slice(0, 20))
    expect(within(w).getAllByRole('alert').length).toBe(new Set([...realDetail.warnings, ...realDetail.summary.warnings]).size)
    expect(w).toHaveTextContent('생존 편향')
  })

  it('차트 패널이 전부 있다: 수익곡선·낙폭·월별·연도·분포·MFE/MAE·보유기간·업종·테마·청산 사유·비용 민감도·몬테카를로·집중도', async () => {
    mockApi(resultRoutes())
    result()
    await screen.findByTestId('panel-equity')
    for (const id of ['panel-drawdown', 'panel-monthly', 'panel-yearly', 'panel-hist', 'panel-mfemae', 'panel-holding', 'panel-sector', 'panel-theme', 'panel-exit-reasons', 'panel-cost', 'panel-montecarlo', 'panel-concentration']) {
      expect(await screen.findByTestId(id)).toBeInTheDocument()
    }
    // 수익곡선은 코스피·코스닥을 겹쳐 그린다
    const opt = JSON.parse(within(screen.getByTestId('panel-equity')).getByTestId('echart').textContent!)
    expect(opt.series.map((s: { name: string }) => s.name)).toEqual(['내 전략', '코스피(같은 돈으로 지수)', '코스닥'])
    expect(opt.yAxis.type).toBe('value')
    await userEvent.click(screen.getByTestId('log-switch'))
    await waitFor(() => expect(JSON.parse(within(screen.getByTestId('panel-equity')).getByTestId('echart').textContent!).yAxis.type).toBe('log'))
  })

  it('견고성: 손익분기 배수 판정·집중도(뒤집힘)·몬테카를로 수치', async () => {
    mockApi(resultRoutes())
    result()
    expect(await screen.findByTestId('breakeven')).toHaveTextContent('×1.60')
    expect(screen.getByTestId('panel-cost')).toHaveTextContent('보통') // 1.0 ≤ 1.60 < 2.0
    expect(screen.getByTestId('panel-concentration')).toHaveTextContent('뒤집힘')
    expect(screen.getByTestId('panel-concentration')).toHaveTextContent('034020')
    expect(screen.getByTestId('panel-montecarlo')).toHaveTextContent('-32.6%')
    expect(screen.getByTestId('panel-montecarlo')).toHaveTextContent('낙폭이 30%를 넘을 확률 29%')
  })

  it('값이 없으면 "없음"이라고 말한다(지어내지 않음): 견고성 없음 · 테마 매핑 없음', async () => {
    const bare = { ...realDetail, summary: { ...realDetail.summary, robustness: null }, analysis: { ...realDetail.analysis, by_theme_group: null } }
    mockApi(resultRoutes(bare))
    result()
    expect(await screen.findByTestId('panel-robustness-none')).toHaveTextContent('견고성 점검 없음')
    expect(await screen.findByTestId('panel-theme')).toHaveTextContent('테마 그룹 매핑이 없어 계산하지 못했습니다')
    expect(screen.queryByTestId('criteria-table')).not.toBeInTheDocument()
  })

  it('사전 판정 기준 표(있을 때만)', async () => {
    const withCrit = { ...realDetail, summary: { ...realDetail.summary, criteria: [{ metric: 'sharpe', threshold: 1, value: 0.57, passed: false }, { metric: 'num_trades', threshold: 100, value: 157, passed: true }] } }
    mockApi(resultRoutes(withCrit))
    result()
    const t = await screen.findByTestId('criteria-table')
    expect(t).toHaveTextContent('샤프')
    expect(within(t).getByText('미달')).toBeInTheDocument()
    expect(within(t).getByText('통과')).toBeInTheDocument()
  })

  it('없는 결과는 안내 문구, 분해 계산이 실패해도 나머지 화면은 산다', async () => {
    mockApi(resultRoutes(realDetail, { [`GET /api/runs/${ID}`]: { status: 404, error: { code: 'NOT_FOUND', message: '찾을 수 없음' } } }))
    const { unmount } = result()
    expect(await screen.findByTestId('result-error')).toHaveTextContent('이 실행 결과를 찾을 수 없습니다')
    unmount()
    mockApi(resultRoutes({ ...realDetail, analysis: { ...realDetail.analysis, error: 'ValueError: 깨짐' } as never }))
    result()
    expect(await screen.findByTestId('analysis-error')).toHaveTextContent('깨짐')
    expect(screen.getByTestId('metric-cards')).toBeInTheDocument()
  })
})

describe('거래 표 → 캔들 서랍 (§8.4 #9)', () => {
  it('정렬·검색·행 클릭 → 앞뒤 30봉 + 진입·청산·손절선', async () => {
    const t0 = realTrades[0]
    const bars = { ...sx.bars, bars: sx.bars.bars.map((b, i) => ({ ...b, t: new Date(Date.UTC(2025, 0, 1 - 150 + i)).toISOString().slice(0, 10) })) }
    const { calls } = mockApi(resultRoutes(realDetail, { [`GET /api/stocks/${t0.code}/bars`]: { data: bars } }))
    result()
    const table = await screen.findByTestId('trades-table')
    await waitFor(() => expect(within(table).getAllByRole('row').length).toBeGreaterThan(5))
    // 검색
    await userEvent.type(within(screen.getByTestId('trade-search')).getByRole('searchbox'), t0.code)
    await waitFor(() => expect(within(table).getAllByRole('row').length).toBeLessThan(realTrades.length + 1))
    // 행 클릭 → 서랍
    await userEvent.click(within(table).getAllByText(t0.code)[0])
    const drawer = await screen.findByTestId('candle-drawer')
    expect(drawer).toHaveTextContent(`${t0.code}`)
    expect(drawer).toHaveTextContent(t0.entry_ts.slice(0, 10))
    const chart = await within(drawer).findByTestId('candle-chart')
    const opt = JSON.parse(within(chart).getByTestId('echart').textContent!)
    const lines = opt.series[0].markLine.data.map((l: { name: string }) => l.name)
    expect(lines).toEqual(['진입가', '손절선']) // 이 실행은 손절 7% 만 있고 익절은 없다
    const stop = opt.series[0].markLine.data[1].yAxis
    expect(stop).toBeCloseTo(t0.entry_price * 0.93, 3) // 변수가 아닌 리터럴 7% — 진입가 × (1 − 7%)
    expect(opt.series[0].markPoint.data.map((p: { name: string }) => p.name)).toEqual(['진입', '청산'])
    expect(calls.some((c) => c.path.startsWith(`/api/stocks/${t0.code}/bars?interval=1d`))).toBe(true)
  })

  it('봉을 못 받으면 서랍에 오류를 보여준다', async () => {
    const t0 = realTrades[0]
    mockApi(resultRoutes(realDetail, { [`GET /api/stocks/${t0.code}/bars`]: { status: 404, error: { code: 'NOT_FOUND', message: '일봉 데이터가 없는 종목' } } }))
    result()
    const table = await screen.findByTestId('trades-table')
    await userEvent.click((await within(table).findAllByText(t0.code))[0])
    expect(await screen.findByTestId('candle-error')).toHaveTextContent('차트 봉을 못 불러왔습니다')
  })
})

describe('결과 헤더 동작', () => {
  it('이름 고치기 → PATCH name, 별표 → PATCH starred, 메모 → PATCH memo (명세는 안 보낸다)', async () => {
    const { calls } = mockApi(resultRoutes(realDetail, { [`PATCH /api/runs/${ID}`]: { data: sx.runRows[1] } }))
    result()
    const name = await screen.findByTestId('run-name')
    await userEvent.clear(name)
    await userEvent.type(name, '내 이름{Enter}')
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ name: '내 이름' }))
    await userEvent.click(screen.getByTestId('star-btn'))
    await waitFor(() => expect(calls.filter((c) => c.method === 'PATCH').at(-1)?.body).toEqual({ starred: true }))
    await userEvent.type(screen.getByTestId('run-memo'), '메모 1')
    await userEvent.tab()
    await waitFor(() => expect(calls.filter((c) => c.method === 'PATCH').at(-1)?.body).toEqual({ memo: '메모 1' }))
    expect(calls.filter((c) => c.method === 'PATCH').every((c) => !('spec' in (c.body as object)))).toBe(true)
  })

  it('[비교에 추가] → 바구니, [조건 복제해서 수정] → 백테스트 화면으로', async () => {
    mockApi(resultRoutes())
    result()
    await userEvent.click(await screen.findByTestId('basket-btn'))
    expect(getBasket()).toEqual([ID])
    await userEvent.click(screen.getByTestId('clone-btn'))
    expect(await screen.findByTestId('bt-route')).toBeInTheDocument()
  })

  it('[재실행] → 같은 명세를 다시 제출한다', async () => {
    const { calls } = mockApi(resultRoutes(realDetail, {
      'POST /api/jobs/backtest': { status: 202, data: { job_id: '20260925-231117-aaaaaa', run_id: sx.RUN_B } },
      'GET /api/jobs/20260925-231117-aaaaaa': { data: sx.job({ status: 'running' }) },
    }))
    result()
    await userEvent.click(await screen.findByTestId('rerun-btn'))
    await waitFor(() => expect(calls.find((c) => c.method === 'POST' && c.path === '/api/jobs/backtest')?.body).toEqual(realDetail.spec))
  })
})

describe('실행 기록 (§5.4)', () => {
  const runs = (over: Record<string, Parameters<typeof mockApi>[0][string]> = {}) =>
    mockApi({ 'GET /api/runs': { data: sx.runRows }, ...over })
  const page = (route = '/runs') => renderApp(<Routes><Route path="/runs" element={<RunsPage />} /><Route path="/compare" element={<ComparePage />} /></Routes>, route)

  it('표: 별표·이름·모드·기간·총수익·CAGR·MDD·샤프·거래·메모·생성, 지표 판정 색', async () => {
    runs()
    page()
    const t = await screen.findByTestId('runs-table')
    await waitFor(() => expect(within(t).getAllByRole('row').length).toBe(3))
    expect(t).toHaveTextContent('신고가 돌파 (손절 5%)')
    expect(t).toHaveTextContent('+25.16%'.replace('25.16', '14.20'))
    // 샤프 1.21 좋음 / 0.57 보통, MDD 12.4 좋음 / 29.3 보통
    const cells = within(t).getAllByText(/^(1\.21|0\.57)$/)
    expect(cells.map((c) => c.getAttribute('data-verdict'))).toEqual(['good', 'mid'])
    expect(t).toHaveTextContent('손절 강화')
  })

  it('별표 토글 → PATCH, 인라인 이름 편집 → PATCH', async () => {
    const { calls } = runs({ [`PATCH /api/runs/${sx.RUN_B}`]: { data: sx.runRows[0] } })
    page()
    await userEvent.click(await screen.findByTestId(`star-${sx.RUN_B}`))
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ starred: false })) // 이미 별표라 해제
    await userEvent.click(screen.getByTestId(`name-${sx.RUN_B}`))
    const input = await screen.findByTestId(`name-${sx.RUN_B}-input`)
    await userEvent.clear(input)
    await userEvent.type(input, '새 이름{Enter}')
    await waitFor(() => expect(calls.filter((c) => c.method === 'PATCH').at(-1)?.body).toEqual({ name: '새 이름' }))
  })

  it('비교는 2~5개를 골라야 켜지고, 누르면 주소에 id 가 실려 비교 화면으로', async () => {
    runs({ '/api/runs/compare': { data: sx.compareData }, 'POST /api/runs/compare': { data: sx.compareData } })
    page()
    const btn = await screen.findByTestId('compare-btn')
    expect(btn).toBeDisabled()
    await waitFor(() => expect(within(screen.getByTestId('runs-table')).getAllByRole('checkbox')).toHaveLength(3)) // 헤더 + 2행
    const boxes = within(screen.getByTestId('runs-table')).getAllByRole('checkbox')
    await userEvent.click(boxes[1])
    expect(btn).toBeDisabled() // 1개
    await userEvent.click(boxes[2])
    expect(btn).toBeEnabled()
    await userEvent.click(btn)
    expect(await screen.findByTestId('compare-page')).toBeInTheDocument()
  })

  it('삭제는 확인 뒤에만 — 실행 결과만 지운다는 문구, DELETE 호출, 바구니에서도 뺀다', async () => {
    localStorage.setItem('studio.compare', JSON.stringify([sx.RUN_A, sx.RUN_B]))
    const { calls } = runs({ [`DELETE /api/runs/${sx.RUN_A}`]: { data: { run_id: sx.RUN_A, deleted: true } } })
    page()
    const table = await screen.findByTestId('runs-table')
    await waitFor(() => expect(within(table).getAllByRole('checkbox')).toHaveLength(3))
    const boxes = within(table).getAllByRole('checkbox')
    await userEvent.click(boxes[2]) // RUN_A (생성 최신 순 두 번째)
    await userEvent.click(screen.getByTestId('delete-btn'))
    expect(await screen.findByText(/시장 데이터는 지우지 않습니다/)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false) // 확인 전엔 안 지운다
    await userEvent.click(screen.getByRole('button', { name: '삭제' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual([`/api/runs/${sx.RUN_A}`]))
    expect(getBasket()).toEqual([sx.RUN_B])
  })

  it('검색·필터는 서버 질의로', async () => {
    const { calls } = runs()
    page()
    await screen.findByTestId('runs-table')
    await userEvent.type(within(screen.getByTestId('runs-search')).getByRole('searchbox'), '손절{Enter}')
    await waitFor(() => expect(calls.some((c) => c.path.includes('q=%EC%86%90%EC%A0%88'))).toBe(true))
    await userEvent.click(screen.getByTestId('runs-starred-only'))
    await waitFor(() => expect(calls.some((c) => c.path.includes('starred=true'))).toBe(true))
  })

  it('기록이 없으면 안내 문구', async () => {
    mockApi({ 'GET /api/runs': { data: [] } })
    page()
    expect(await screen.findByText('실행 기록이 없습니다 — 백테스트를 한 번 돌려 보세요')).toBeInTheDocument()
  })
})

describe('비교 화면 (§5.4)', () => {
  const cmp = (route: string) => renderApp(<Routes><Route path="/compare" element={<ComparePage />} /><Route path="/runs" element={<div data-testid="runs-route" />} /></Routes>, route)

  it('2개 미만이면 고르라는 안내', async () => {
    mockApi({})
    cmp('/compare?ids=only-one')
    expect(await screen.findByTestId('compare-need-two')).toHaveTextContent('2개 이상')
  })

  it('곡선 겹치기 · 지표 표(좋은 쪽 강조) · 조건 차이 문장', async () => {
    const { calls } = mockApi({ 'POST /api/runs/compare': { data: sx.compareData } })
    cmp(`/compare?ids=${sx.RUN_A},${sx.RUN_B}`)
    const chart = await screen.findByTestId('compare-chart')
    const opt = JSON.parse(within(chart).getByTestId('echart').textContent!)
    expect(opt.series).toHaveLength(2) // 곡선 2개
    expect(opt.series[1].data).toEqual([100, 102])
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ ids: [sx.RUN_A, sx.RUN_B] })
    // 샤프: 두 번째(1.21)가 최고, MDD: 두 번째(12.4)가 최고(낮을수록 좋음), 거래 수는 강조 없음
    expect(screen.getByTestId('cmp-sharpe-1')).toHaveAttribute('data-best', 'true')
    expect(screen.getByTestId('cmp-sharpe-0')).toHaveAttribute('data-best', 'false')
    expect(screen.getByTestId('cmp-max_drawdown_pct-1')).toHaveAttribute('data-best', 'true')
    expect(screen.getByTestId('cmp-num_trades-1')).toHaveAttribute('data-best', 'false')
    expect(screen.getByTestId('cmp-sharpe-1')).toHaveAttribute('data-verdict', 'good')
    expect(screen.getByTestId('compare-diffs')).toHaveTextContent('손절(%): 7 → 5')
  })

  it('조건이 같으면 그렇게 말하고, 서버 오류는 문구로', async () => {
    mockApi({ 'POST /api/runs/compare': { data: { ...sx.compareData, diffs: [{ run_id: sx.RUN_B, vs: sx.RUN_A, items: [] }] } } })
    const { unmount } = cmp(`/compare?ids=${sx.RUN_A},${sx.RUN_B}`)
    expect(await screen.findByText('조건이 같습니다(이름만 다름)')).toBeInTheDocument()
    unmount()
    mockApi({ 'POST /api/runs/compare': { status: 404, error: { code: 'NOT_FOUND', message: '찾을 수 없음' } } })
    cmp(`/compare?ids=${sx.RUN_A},${sx.RUN_B}`)
    expect(await screen.findByTestId('compare-error')).toHaveTextContent('비교하지 못했습니다')
  })

  it('주소에 id 가 없으면 담아 둔 바구니를 쓴다', async () => {
    localStorage.setItem('studio.compare', JSON.stringify([sx.RUN_A, sx.RUN_B]))
    const { calls } = mockApi({ 'POST /api/runs/compare': { data: sx.compareData } })
    cmp('/compare')
    await screen.findByTestId('compare-page')
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ ids: [sx.RUN_A, sx.RUN_B] })
  })
})
