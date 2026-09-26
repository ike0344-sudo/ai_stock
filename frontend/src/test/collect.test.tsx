import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { CodesSelect } from '@/components/hub/collect/CodesSelect'
import { displayStatus, JobTable } from '@/components/hub/collect/JobTable'
import { PolicyButton } from '@/components/hub/collect/PolicyButton'
import { isImminent, TickWindowCalendar, TICK_COLOR } from '@/components/hub/collect/TickWindowCalendar'
import { CollectTab } from '@/pages/hub/CollectTab'
import type { JobRow } from '@/types'
import * as fx from './fixtures/hub'
import { mockApi, renderApp } from './helpers'
import { collectDaily } from '@/api/hub'

const job = (o: Partial<JobRow>): JobRow => ({
  job_id: '20260925-201502-a1b2c3', kind: 'collect_ticks', group: 'collect', status: 'running', scheduled_at: null,
  created_at: '2026-09-25T20:15:00', started_at: '2026-09-25T20:15:02', finished_at: null, run_id: null, lock: 'tick_al', trigger: 'user',
  error: null, cancel_requested: false,
  progress: { pct: 42, stage: '수집', message: '[63/150]', eta_sec: 3600, paused: false, waiting_lock: null }, ...o,
})

const policyRoute = (p: unknown) => ({ 'GET /api/data/policy': { data: p } })

describe('PolicyButton — 정책 판정이 버튼을 바꾼다', () => {
  const submit = () => Promise.resolve({ job_id: 'x', status: 'queued', scheduled_at: null })

  it('schedule_only(정규장 대량): "지금" 버튼이 없고 20:10 예약만', async () => {
    mockApi(policyRoute(fx.policy.scheduleOnly))
    renderApp(<PolicyButton kind="collect_minute_al" mode="sophie_baseline" submit={submit} />)
    const box = await screen.findByTestId('policy-button')
    expect(box).toHaveAttribute('data-decision', 'schedule_only')
    expect(within(box).getByRole('button', { name: /20:10 예약/ })).toBeEnabled()
    expect(within(box).queryByRole('button', { name: '지금 실행' })).not.toBeInTheDocument()
    expect(box).toHaveTextContent('대상 288개 · 예상 1시간 26분(추정: 09-19 실측 86분)') // 추정임을 밝힌다
    expect(box).toHaveTextContent('NXT 마감(20:00) 전이면 잘립니다')
  })

  it('needs_confirm: [확인 후 실행] + [예약]', async () => {
    mockApi(policyRoute(fx.policy.needsConfirm))
    renderApp(<PolicyButton kind="collect_minute_al" mode="sophie_baseline" submit={submit} />)
    const box = await screen.findByTestId('policy-button')
    expect(box).toHaveAttribute('data-decision', 'needs_confirm')
    expect(within(box).getByRole('button', { name: '확인 후 실행' })).toBeInTheDocument()
    expect(within(box).getByRole('button', { name: /예약/ })).toBeInTheDocument()
  })

  it('allow_now: [지금 실행] → when=now 로 제출하고, 없는 confirm 은 보내지 않는다', async () => {
    mockApi(policyRoute(fx.policy.allowNow))
    let sent: unknown
    renderApp(<PolicyButton kind="collect_minute_al" mode="sophie_baseline" submit={(w) => { sent = w; return submit() }} />)
    await userEvent.click(await screen.findByRole('button', { name: '지금 실행' }))
    await waitFor(() => expect(sent).toEqual({ when: 'now' }))
  })

  it('schedule_only 예약 제출: when=scheduled + 제안 시각(20:10)', async () => {
    mockApi(policyRoute(fx.policy.scheduleOnly))
    let sent: { when: string; scheduled_at?: string | null } | undefined
    renderApp(<PolicyButton kind="collect_minute_al" mode="sophie_baseline" submit={(w) => { sent = w; return submit() }} />)
    await userEvent.click(await screen.findByRole('button', { name: /20:10 예약/ }))
    await waitFor(() => expect(sent).toBeDefined())
    expect(sent!.when).toBe('scheduled')
    expect(sent!.scheduled_at).toBe('2026-09-25T20:10:00')
  })

  it('blocked(기준선 갱신 실행 중): 버튼 비활성 + 사유', async () => {
    mockApi(policyRoute(fx.policy.blockedRefresh))
    renderApp(<PolicyButton kind="collect_minute_al" mode="sophie_baseline" submit={submit} />)
    const btn = await screen.findByRole('button', { name: '지금 실행' })
    expect(btn).toBeDisabled()
    expect(screen.getByTestId('policy-button')).toHaveTextContent('소피증권 분봉 기준선 갱신이 실행 중입니다')
  })

  it('정책 API 가 없으면 버튼은 비활성 "허브 API 준비 중" — 실행 경로가 없다', async () => {
    const { calls } = mockApi({})
    renderApp(<PolicyButton kind="collect_daily" mode="stale" submit={submit} />)
    const box = await screen.findByTestId('policy-unavailable')
    expect(within(box).getByRole('button', { name: '허브 API 준비 중' })).toBeDisabled()
    expect(calls.every((c) => c.method === 'GET')).toBe(true)
  })

  it('로컬 작업(보관 병합): 정규장이어도 바로 실행', async () => {
    mockApi(policyRoute(fx.policy.local))
    renderApp(<PolicyButton kind="archive_minute_al" labelNow="보관 병합 지금 실행" submit={submit} />)
    expect(await screen.findByRole('button', { name: '보관 병합 지금 실행' })).toBeEnabled()
  })

  it('서버가 거절하면(422) 코드·메시지·제안 시각을 보여준다', async () => {
    mockApi({
      ...policyRoute(fx.policy.allowNow),
      'POST /api/data/jobs/collect-daily': { status: 422, error: { code: 'SOPHIE_MARKET_HOURS', message: '정규장 대량 수집은 예약만', details: { suggest_at: '2026-09-25T20:10:00' } } },
    })
    renderApp(<PolicyButton kind="collect_daily" mode="stale" submit={() => collectDaily({ mode: 'stale', when: 'now' })} />)
    await userEvent.click(await screen.findByRole('button', { name: '지금 실행' }))
    expect(await screen.findByText(/SOPHIE_MARKET_HOURS.*제안 20:10/)).toBeInTheDocument()
  })
})

describe('TickWindowCalendar', () => {
  it('상태별 색과 소실 임박(빠진 게 있고 남은 거래일 ≤3) 표시', () => {
    renderApp(<TickWindowCalendar dates={fx.tickWindow.dates} />)
    const cell = (d: string) => screen.getByTestId(`tick-${d}`)
    expect(cell('2026-09-18')).toHaveStyle({ background: TICK_COLOR.collected })
    expect(cell('2026-09-21')).toHaveStyle({ background: TICK_COLOR.partial })
    expect(cell('2026-09-22')).toHaveStyle({ background: TICK_COLOR.missing })
    expect(cell('2026-09-24')).toHaveStyle({ background: TICK_COLOR.pending })
    expect(cell('2026-09-21')).toHaveAttribute('data-imminent', 'true') // 빠짐 + 남은 1거래일
    expect(cell('2026-09-22')).toHaveAttribute('data-imminent', 'true')
    expect(cell('2026-09-18')).toHaveAttribute('data-imminent', 'false') // 다 받았으면 임박 아님
    expect(cell('2026-09-24')).toHaveAttribute('data-imminent', 'false') // 오늘은 못 받는 게 정상
  })

  it('경계: 남은 거래일 3 은 임박, 4 는 아님', () => {
    const base = { date: '2026-09-01', status: 'partial' as const, collected_codes: 1, expected_codes: 2, missing_count: 1, missing_sample: ['1'] }
    expect(isImminent({ ...base, days_left: 3 })).toBe(true)
    expect(isImminent({ ...base, days_left: 4 })).toBe(false)
  })
})

describe('CodesSelect — 6자리 코드만', () => {
  it('형식이 틀린 코드는 넣지 않고 알린다, 소문자는 대문자로', async () => {
    let latest: string[] = []
    function Harness() {
      const [v, setV] = useState<string[]>([])
      return <CodesSelect value={v} onChange={(x) => { latest = x; setV(x) }} />
    }
    renderApp(<Harness />)
    await userEvent.type(screen.getByRole('combobox'), '005930,12345,00104k,')
    await waitFor(() => expect(latest).toEqual(['005930', '00104K']))
    expect(screen.getByTestId('codes-bad')).toHaveTextContent('12345')
  })
})

describe('JobTable', () => {
  it('displayStatus: 잠금 대기·취소 중·예약 등', () => {
    expect(displayStatus(job({ progress: { ...job({}).progress, waiting_lock: { resource: 'tick_al' } } })).text).toBe('잠금 대기')
    expect(displayStatus(job({ cancel_requested: true })).text).toBe('취소 중')
    expect(displayStatus(job({ status: 'scheduled' })).text).toBe('예약')
    expect(displayStatus(job({ status: 'failed' })).text).toBe('실패')
  })

  it('작업 표: 종류·진행률·단계·남은 시간, 실행 중에만 [취소]', async () => {
    mockApi({
      'GET /api/jobs': { data: [job({}), job({ job_id: '20260925-190000-bbbbbb', kind: 'collect_daily', status: 'succeeded', finished_at: '2026-09-25T19:10:00', started_at: '2026-09-25T19:00:00', progress: { ...job({}).progress, pct: 100 } })] },
    })
    renderApp(<JobTable />)
    const t = await screen.findByTestId('job-table')
    await waitFor(() => expect(t).toHaveTextContent('체결 수집'))
    expect(t).toHaveTextContent('일봉 최신화')
    expect(t).toHaveTextContent('1시간') // 남은 시간 eta 3600s
    expect(within(t).getAllByRole('button', { name: '취소' })).toHaveLength(1)
    expect(within(t).getAllByRole('button', { name: '로그' })).toHaveLength(2)
  })

  it('작업이 없으면 빈 상태 문구', async () => {
    mockApi({ 'GET /api/jobs': { data: [] } })
    renderApp(<JobTable />)
    expect(await screen.findByText('허브가 띄운 수집 작업이 아직 없습니다')).toBeInTheDocument()
  })
})

describe('수집 탭 — API 없이도 작업 표는 살아 있다', () => {
  it('허브 API 404: 패널마다 준비 중, 작업 표(studio /api/jobs)는 정상', async () => {
    mockApi({ 'GET /api/jobs': { data: [job({})] } })
    renderApp(<CollectTab />)
    await waitFor(() => expect(screen.getAllByTestId('hub-unavailable').length).toBeGreaterThan(0)) // 체결·보관소 패널
    expect((await screen.findAllByTestId('policy-unavailable')).length).toBeGreaterThan(0)
    expect(await screen.findByTestId('job-table')).toHaveTextContent('체결 수집')
  })

  it('허브 API 있음: 체결 달력·자동 수집 줄·수동 확인 목록·통합 분봉 기준선 표시', async () => {
    mockApi({
      'GET /api/jobs': { data: [] },
      'GET /api/data/tick-window': { data: fx.tickWindow },
      'GET /api/data/archive': { data: fx.archive },
      'GET /api/data/stale': { data: fx.stale },
      ...policyRoute(fx.policy.scheduleOnly),
    })
    renderApp(<CollectTab />)
    expect(await screen.findByTestId('tick-calendar')).toBeInTheDocument()
    expect(screen.getByTestId('tick-auto')).toHaveTextContent('지난밤(2026-09-24) 받은 150쌍 · 남은 12쌍 · 미룬 2쌍 · 시도 1회')
    expect(screen.getByTestId('given-up')).toHaveTextContent('386380 테스트종목')
    expect(await screen.findByTestId('baseline-effect')).toHaveTextContent('갱신됨(다음 재기동부터 적용)')
    expect(screen.getByTestId('archive-panel')).toHaveTextContent('2041종목')
    expect(screen.getByTestId('collect-daily')).toHaveTextContent('16시 전에는 어제까지가 최신')
  })
})
