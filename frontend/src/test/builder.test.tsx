import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { BacktestPage } from '@/pages/BacktestPage'
import type { SpecJson } from '@/types/studio'
import * as sx from './fixtures/studio'
import { mockApi, renderApp } from './helpers'

const presetSpec = () => sx.presetSpec
const routes = (over: Record<string, Parameters<typeof mockApi>[0][string]> = {}) => ({
  'GET /api/meta/indicators': { data: sx.catalog },
  'GET /api/meta/strategies': { data: sx.legacyDefs },
  'GET /api/meta/data-ranges': { data: sx.dataRanges },
  'GET /api/presets': { data: sx.presetRows },
  'GET /api/presets/new_high_20': { data: { name: 'new_high_20', spec: sx.presetSpec } },
  'POST /api/conditions/validate': { data: sx.validOk },
  ...over,
})

const page = () => renderApp(
  <Routes>
    <Route path="/backtest" element={<BacktestPage />} />
    <Route path="/results/:runId" element={<div data-testid="result-route">결과 화면</div>} />
  </Routes>, '/backtest')

const specOf = (calls: { path: string; body: unknown }[], last = true): SpecJson => {
  const v = calls.filter((c) => c.path.startsWith('/api/conditions/validate'))
  return (v[last ? v.length - 1 : 0].body as { spec: SpecJson }).spec
}

describe('백테스트 화면 — 뼈대', () => {
  it('렌더가 끝난다(무한 갱신 없음): 검증은 조용해진 뒤 한두 번만 묻는다', async () => {
    const { calls } = mockApi(routes())
    page()
    expect(await screen.findByTestId('backtest-page')).toBeInTheDocument()
    expect(await screen.findByTestId('narration', {}, { timeout: 9000 })).toHaveTextContent('다음 날 시가에 산다')
    await new Promise((r) => setTimeout(r, 1500))
    expect(calls.filter((c) => c.path === '/api/conditions/validate').length).toBeLessThanOrEqual(3)
    expect(calls.length).toBeLessThan(15)
  })

  it('모드 탭 4개 — 분봉·틱 탭도 켜져 있다', async () => {
    mockApi(routes())
    page()
    const tabs = await screen.findAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual(['일봉 · 단일 종목', '일봉 · 포트폴리오', '분봉 단타', '체결(틱)'])
    for (const t of tabs) expect(t).not.toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('tab', { name: '일봉 · 포트폴리오', selected: true })).toBeInTheDocument()
  })

  it('데이터 기준일이 기본 종료일이고, 기간 칸에 허브 데이터 범위가 보인다', async () => {
    const { calls } = mockApi(routes())
    page()
    expect(await screen.findByTestId('panel-period')).toHaveTextContent('일봉 데이터 2019-04-23 ~ 2026-09-23')
    await screen.findByTestId('narration', {}, { timeout: 9000 })
    await waitFor(() => expect(specOf(calls).period.end).toBe('2026-09-23'))
  })

  it('조립기 재료를 못 받으면 오류를 보여준다', async () => {
    mockApi(routes({ 'GET /api/meta/indicators': { status: 500, error: { code: 'INTERNAL', message: '서버 오류' } } }))
    page()
    expect(await screen.findByTestId('builder-error', {}, { timeout: 5000 })).toHaveTextContent('조립기 재료를 못 불러옴')
  })
})

describe('프리셋 → 조건 행 + 풀이 문장 (§8.4 #6)', () => {
  it('프리셋 불러오기: 진입 2행·청산 1행이 채워지고 변수 표와 풀이 문장이 나온다', async () => {
    mockApi(routes())
    page()
    await userEvent.click(await screen.findByTestId('preset-select'))
    await userEvent.click(await screen.findByText(/20일 신고가 돌파/, { selector: '.ant-select-item-option-content' }))
    await userEvent.click(screen.getByTestId('preset-load'))
    const entry = await screen.findByTestId('group-strategy.entry')
    await waitFor(() => expect(within(entry).getAllByTestId(/^row-strategy\.entry\.items\.\d+$/)).toHaveLength(2))
    expect(within(screen.getByTestId('group-strategy.exit')).getAllByTestId(/^row-strategy\.exit\.items\.\d+$/)).toHaveLength(1)
    expect(await screen.findByTestId('panel-params')).toHaveTextContent('vol_mult')
    expect(screen.getByTestId('narration')).toHaveTextContent('[n]일 최고가')
    expect(screen.getByTestId('load-note')).toHaveTextContent('프리셋 "new_high_20"')
  })

  it('주소의 ?preset= 으로도 바로 불러온다', async () => {
    mockApi(routes())
    renderApp(<Routes><Route path="/backtest" element={<BacktestPage />} /></Routes>, '/backtest?preset=new_high_20')
    expect(await screen.findByTestId('load-note')).toHaveTextContent('new_high_20')
    expect(await screen.findByTestId('spec-name')).toHaveValue(sx.presetSpec.name)
  })
})

describe('손으로 쓴 부분 프리셋(실측 사고: costs·fills·compat 없음)', () => {
  it('서버가 기본값을 못 채워 준 부분 명세를 받아도 화면이 죽지 않는다', async () => {
    const partial = { version: 1, name: '부분 프리셋', mode: 'daily_portfolio', period: { start: '2025-01-02', end: '2025-08-29' }, strategy: presetSpec().strategy, exits: {}, portfolio: { max_positions: 3 } }
    mockApi(routes({ 'GET /api/presets/new_high_20': { data: { name: 'new_high_20', spec: partial } } }))
    renderApp(<Routes><Route path="/backtest" element={<BacktestPage />} /></Routes>, '/backtest?preset=new_high_20')
    expect(await screen.findByTestId('spec-name')).toHaveValue('부분 프리셋')
    expect(await screen.findByTestId('panel-costs')).toHaveTextContent('수수료율')
    expect(screen.getByTestId('max-positions')).toHaveValue('3')
    expect(screen.queryByTestId('screen-crash')).not.toBeInTheDocument()
  })
})

describe('호환 모드 (§8.4 #7)', () => {
  it('단일 종목에서만 보이고, 켜면 손절·익절·비중·거래량 한도가 잠긴다', async () => {
    mockApi(routes())
    page()
    await screen.findByTestId('backtest-page')
    expect(screen.queryByTestId('panel-compat')).not.toBeInTheDocument() // 포트폴리오에는 없다
    await userEvent.click(screen.getByRole('tab', { name: '일봉 · 단일 종목' }))
    const sw = await screen.findByTestId('compat-switch')
    // 손절을 하나 켜 둔 뒤 호환 모드를 켜면 꺼지고 잠긴다
    await userEvent.click(screen.getByTestId('exit-stop_loss_pct-on'))
    expect(await screen.findByTestId('exit-stop_loss_pct')).toBeInTheDocument()
    await userEvent.click(sw)
    await waitFor(() => expect(screen.queryByTestId('exit-stop_loss_pct')).not.toBeInTheDocument())
    expect(screen.getByTestId('exit-stop_loss_pct-on')).toBeDisabled()
    expect(screen.getByTestId('exit-take_profit_pct-on')).toBeDisabled()
    expect(screen.getByTestId('max-positions')).toBeDisabled()
    expect(screen.getByTestId('compat-note')).toHaveTextContent('잠깁니다')
    expect(screen.getByTestId('panel-exits')).toHaveTextContent('호환 모드에서는')
  })

  it('단일 종목 기본값은 최대 보유 1 · 비중 100%', async () => {
    mockApi(routes())
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '일봉 · 단일 종목' }))
    expect(await screen.findByTestId('max-positions')).toHaveValue('1')
    expect(screen.getByTestId('max-weight')).toHaveValue('100')
    expect(screen.getByTestId('panel-portfolio')).toHaveTextContent('자본 전부를 씁니다')
  })
})

describe('검증 오류 → 행 강조 (§8.4 #8)', () => {
  it('서버가 가리킨 조건 행이 빨갛게 되고 오류 목록이 뜨며 실행은 막힌다', async () => {
    mockApi(routes({ 'POST /api/conditions/validate': { data: sx.validBad } }))
    page()
    const err = await screen.findByTestId('validation-errors', {}, { timeout: 9000 })
    expect(err).toHaveTextContent("없는 지표 'nope'")
    expect(err).toHaveTextContent('strategy.entry.items.0.right')
    expect(screen.getByTestId('row-strategy.entry.items.0')).toHaveAttribute('data-error', 'true')
    expect(within(screen.getByTestId('row-strategy.entry.items.0')).getByText(/없는 지표/)).toBeInTheDocument()
    expect(screen.getByTestId('row-strategy.exit.items.0')).toHaveAttribute('data-error', 'false')
    expect(screen.getByTestId('run-btn')).toBeDisabled()
    expect(screen.getByTestId('preview-btn')).toBeDisabled()
    expect(screen.getByTestId('validation-warnings')).toHaveTextContent('2019-04-23')
    expect(screen.getByTestId('narration-panel')).toHaveTextContent('오류를 고치면 풀이가 나옵니다')
  })

  it('진입 조건을 모두 지우면 "최소 1개가 필요"를 화면이 먼저 알려 준다', async () => {
    mockApi(routes())
    page()
    await screen.findByTestId('group-strategy.entry')
    await userEvent.click(within(screen.getByTestId('row-strategy.entry.items.0')).getByRole('button', { name: '조건 삭제' }))
    expect(await screen.findByTestId('group-strategy.entry-empty')).toHaveTextContent('최소 1개가 필요')
  })
})

describe('조건 편집기', () => {
  it('행 추가·복제·삭제와 하위 그룹(1단계까지)', async () => {
    mockApi(routes())
    page()
    const entry = await screen.findByTestId('group-strategy.entry')
    const rows = () => within(entry).getAllByTestId(/^row-strategy\.entry\.items\.\d+$/)
    expect(rows()).toHaveLength(1)
    await userEvent.click(screen.getByTestId('group-strategy.entry-add'))
    expect(rows()).toHaveLength(2)
    await userEvent.click(within(rows()[0]).getByRole('button', { name: '조건 복제' }))
    expect(rows()).toHaveLength(3)
    await userEvent.click(within(rows()[2]).getByRole('button', { name: '조건 삭제' }))
    expect(rows()).toHaveLength(2)
    await userEvent.click(screen.getByTestId('group-strategy.entry-add-group'))
    const nested = await screen.findByTestId('group-strategy.entry.items.2')
    expect(nested).toBeInTheDocument()
    expect(within(nested).queryByTestId('group-strategy.entry.items.2-add-group')).not.toBeInTheDocument() // 2단계는 없다
  })

  it('숫자 칸 "변수로" → 변수 표에 생기고 칸이 [이름] 태그가 되며, "고정값으로"로 되돌린다', async () => {
    const { calls } = mockApi(routes())
    page()
    const entry = await screen.findByTestId('group-strategy.entry')
    const nField = within(entry).getByTestId('operand-right-param-n')
    await userEvent.click(within(nField.closest('.ant-space') as HTMLElement).getByRole('button', { name: '변수로' }))
    expect(await screen.findByTestId('panel-params')).toHaveTextContent('highest_n')
    expect(within(entry).getByText('[highest_n]')).toBeInTheDocument()
    await waitFor(() => expect(specOf(calls).params.highest_n.default).toBe(20)) // 서버로 가는 명세에도 변수 정의가 실려 간다
    await userEvent.click(within(entry).getByRole('button', { name: '고정값으로' }))
    await waitFor(() => expect(within(entry).queryByText('[highest_n]')).not.toBeInTheDocument())
    await waitFor(() => expect(specOf(calls).params).toEqual({})) // 안 쓰이는 변수 정의는 실행 명세에서 빠진다
  })

  it('전략 소스를 기존 전략으로 바꾸면 파라미터 폼이 나오고 폐기된 전략은 경고한다', async () => {
    const { calls } = mockApi(routes())
    page()
    await screen.findByTestId('strategy-source')
    await userEvent.click(screen.getByText('기존 전략', { selector: 'label span, .ant-radio-button-wrapper span' }))
    const form = await screen.findByTestId('legacy-form')
    expect(within(form).getByTestId('legacy-param-short_window')).toHaveValue('5')
    expect(screen.queryByTestId('group-strategy.entry')).not.toBeInTheDocument()
    await waitFor(() => expect(specOf(calls).strategy).toEqual({ source: 'legacy', name: 'ma_crossover', params: { short_window: 5, long_window: 20 } }))
  })
})

describe('오늘 조건 맞는 종목 · 실행', () => {
  it('[오늘 조건 맞는 종목] → 표와 피연산자 값', async () => {
    mockApi(routes({ 'POST /api/conditions/preview': { data: sx.previewOk } }))
    page()
    await screen.findByTestId('narration', {}, { timeout: 9000 })
    await waitFor(() => expect(screen.getByTestId('preview-btn')).toBeEnabled())
    await userEvent.click(screen.getByTestId('preview-btn'))
    const panel = await screen.findByTestId('preview-panel')
    await waitFor(() => expect(panel).toHaveTextContent('삼성전자'))
    expect(panel).toHaveTextContent('오늘(2026-09-23) 조건에 맞는 종목 2개 / 대상 100종목')
    expect(panel).toHaveTextContent('+2.50%')
  })

  it('미리보기 실패(422)는 오류 문구로', async () => {
    mockApi(routes({ 'POST /api/conditions/preview': { status: 422, error: { code: 'SPEC_INVALID', message: "'intraday' 모드는 아직 지원하지 않는다" } } }))
    page()
    await screen.findByTestId('narration', {}, { timeout: 9000 })
    await waitFor(() => expect(screen.getByTestId('preview-btn')).toBeEnabled())
    await userEvent.click(screen.getByTestId('preview-btn'))
    expect(await screen.findByText(/SPEC_INVALID/)).toBeInTheDocument()
  })

  it('[백테스트 실행] → 제출 → 진행 모달(단계·진행률) → 완료되면 결과 화면으로 이동', async () => {
    let polls = 0
    const { calls } = mockApi(routes({
      'POST /api/jobs/backtest': { status: 202, data: { job_id: '20260925-231117-aaaaaa', run_id: sx.RUN_B } },
      'GET /api/jobs/20260925-231117-aaaaaa': () => {
        polls += 1
        return { data: polls < 2 ? sx.job({ status: 'running', progress: { pct: 25, stage: 'signals', message: null, eta_sec: null, paused: false, waiting_lock: null } }) : sx.job({ status: 'succeeded' }) }
      },
    }))
    page()
    await screen.findByTestId('narration', {}, { timeout: 9000 })
    await waitFor(() => expect(screen.getByTestId('run-btn')).toBeEnabled())
    await userEvent.click(screen.getByTestId('run-btn'))
    expect(await screen.findByTestId('run-modal')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('run-stage')).toHaveTextContent('조건 계산 중'))
    expect(await screen.findByTestId('result-route', {}, { timeout: 6000 })).toBeInTheDocument() // 결과 화면으로
    const post = calls.filter((c) => c.method === 'POST' && c.path === '/api/jobs/backtest')
    expect(post).toHaveLength(1) // 제출은 한 번만
    expect((post[0].body as SpecJson).strategy).toBeTruthy()
  })

  it('실행 실패는 사유를 보여주고 닫을 수 있다', async () => {
    const { calls } = mockApi(routes({
      'POST /api/jobs/backtest': { status: 202, data: { job_id: '20260925-231117-aaaaaa', run_id: sx.RUN_B } },
      'GET /api/jobs/20260925-231117-aaaaaa': { data: sx.job({ status: 'failed', error: 'BacktestError: 유니버스에 종목이 없다' }) },
    }))
    page()
    await screen.findByTestId('narration', {}, { timeout: 9000 })
    await waitFor(() => expect(screen.getByTestId('run-btn')).toBeEnabled())
    await userEvent.click(screen.getByTestId('run-btn'))
    expect(await screen.findByTestId('run-error', {}, { timeout: 4000 })).toHaveTextContent('유니버스에 종목이 없다')
    await userEvent.click(screen.getAllByRole('button', { name: '닫기' }).at(-1)!)
    // 닫힌 뒤 다시 실행하면 새 제출이 나간다 — 모달 상태가 초기화됐다는 뜻(antd 는 닫힘 애니메이션 동안 DOM 을 남겨서 존재 여부로는 못 본다)
    await waitFor(() => expect(screen.getByTestId('run-btn')).toBeEnabled())
    await userEvent.click(screen.getByTestId('run-btn'))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST' && c.path === '/api/jobs/backtest')).toHaveLength(2))
  })

  it('실행 중 [취소]는 작업 취소 API 를 부른다', async () => {
    const { calls } = mockApi(routes({
      'POST /api/jobs/backtest': { status: 202, data: { job_id: '20260925-231117-aaaaaa', run_id: sx.RUN_B } },
      'GET /api/jobs/20260925-231117-aaaaaa': { data: sx.job({ status: 'running' }) },
      'POST /api/jobs/20260925-231117-aaaaaa/cancel': { data: { job_id: 'x', status: 'running' } },
    }))
    page()
    await screen.findByTestId('narration', {}, { timeout: 9000 })
    await waitFor(() => expect(screen.getByTestId('run-btn')).toBeEnabled())
    await userEvent.click(screen.getByTestId('run-btn'))
    await userEvent.click(await screen.findByTestId('run-cancel'))
    await waitFor(() => expect(calls.some((c) => c.path === '/api/jobs/20260925-231117-aaaaaa/cancel' && c.method === 'POST')).toBe(true))
  })
})

describe('복제해서 수정 (?from=)', () => {
  it('실행의 조건을 불러와 이름 뒤에 (복사)를 붙인다', async () => {
    mockApi(routes({ [`GET /api/runs/${sx.RUN_A}`]: { data: { ...(await import('./fixtures/studioReal')).realDetail } } }))
    renderApp(<Routes><Route path="/backtest" element={<BacktestPage />} /></Routes>, `/backtest?from=${sx.RUN_A}`)
    expect(await screen.findByTestId('load-note')).toHaveTextContent(`실행 ${sx.RUN_A} 의 조건을 복제`)
    expect(screen.getByTestId('spec-name')).toHaveValue(`${sx.presetSpec.name} (복사)`)
  })
})
