import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { gapOption } from '@/components/hub/quality/GapBars'
import { StatusBar } from '@/components/layout/StatusBar'
import { HubPage } from '@/pages/HubPage'
import { LedgerTab } from '@/pages/hub/LedgerTab'
import { QualityTab } from '@/pages/hub/QualityTab'
import { SchedulesTab } from '@/pages/hub/SchedulesTab'
import { SophieTab } from '@/pages/hub/SophieTab'
import { Route, Routes } from 'react-router-dom'
import * as fx from './fixtures/hub'
import { mockApi, renderApp } from './helpers'

const META = { 'GET /api/meta/status': { data: { engine_version: '0.1.0', server_time: '2026-09-25T10:00:00', jobs: { scheduled: 1, queued: 2, running: 3 } } } }

describe('일정 탭', () => {
  it('외부 소유는 잠금 표시(스위치 없음), 허브 소유만 켜기/끄기, 놓침 배지', async () => {
    mockApi({ 'GET /api/data/schedules': { data: fx.schedules }, 'GET /api/data/alerts': { data: fx.alerts } })
    renderApp(<SchedulesTab />)
    const t = await screen.findByTestId('schedule-table')
    expect(within(t).getByTestId('locked-daily_report')).toHaveTextContent('워치독이 관리')
    expect(within(t).getByTestId('locked-sophie_restart')).toHaveTextContent('소피증권이 관리')
    expect(within(t).getAllByRole('switch')).toHaveLength(1) // tick_nightly 만
    expect(within(t).getByTestId('missed-sophie_restart')).toHaveTextContent('18일째 기록 없음')
    expect(within(t).queryByTestId('missed-tick_nightly')).not.toBeInTheDocument()
  })

  it('허브 일정 끄기 → PATCH {enabled:false}', async () => {
    const { calls } = mockApi({
      'GET /api/data/schedules': { data: fx.schedules }, 'GET /api/data/alerts': { data: fx.alerts },
      'PATCH /api/data/schedules/tick_nightly': { data: { ...fx.schedules[2], enabled: false } },
    })
    renderApp(<SchedulesTab />)
    await userEvent.click(await screen.findByRole('switch', { name: '체결 야간 수집 켜기/끄기' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ enabled: false }))
    expect(calls.find((c) => c.method === 'PATCH')?.path).toBe('/api/data/schedules/tick_nightly')
  })

  it('알림 규칙 표: 켜기/끄기·마지막 발송, 기본값과 다르면 표시', async () => {
    const { calls } = mockApi({
      'GET /api/data/schedules': { data: fx.schedules }, 'GET /api/data/alerts': { data: fx.alerts },
      'PATCH /api/data/alerts/unledgered_write': { data: { ...fx.alerts.rules[1], enabled: true } },
    })
    renderApp(<SchedulesTab />)
    const t = await screen.findByTestId('alert-rules')
    expect(t).toHaveTextContent('보관 누락')
    expect(t).toHaveTextContent('09-25 09:10')
    await userEvent.click(within(t).getByRole('switch', { name: '장부 없는 쓰기 켜기/끄기' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ enabled: true }))
  })

  it('허브 소유 회차 기록(runs)이 있는 행만 펼쳐진다', async () => {
    mockApi({ 'GET /api/data/schedules': { data: fx.schedules }, 'GET /api/data/alerts': { data: fx.alerts } })
    renderApp(<SchedulesTab />)
    const t = await screen.findByTestId('schedule-table')
    expect(t.querySelectorAll('.ant-table-row-expand-icon:not(.ant-table-row-expand-icon-spaced)')).toHaveLength(1)
  })
})

describe('장부 탭', () => {
  it('장부 표: 출처·결과(성공·실패·중단됨)·소요, 필터 → 쿼리 반영', async () => {
    const { calls } = mockApi({ 'GET /api/data/ledger': { data: fx.ledger }, 'GET /api/data/ledger/unledgered': { data: [] } })
    renderApp(<LedgerTab />)
    const t = await screen.findByTestId('ledger-table')
    expect(t).toHaveTextContent('야간 갱신')
    expect(t).toHaveTextContent('실행 중')
    expect(t).toHaveTextContent('중단됨')
    expect(t).toHaveTextContent('40분') // 2429초
    expect(await screen.findByText('관문을 안 거친 쓰기가 감지되지 않았습니다')).toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/data/ledger?') && c.path.includes('limit=100'))).toBe(true)
  })

  it('장부 없는 쓰기가 있으면 파일·수정 시각·데이터셋을 보여준다', async () => {
    mockApi({
      'GET /api/data/ledger': { data: [] },
      'GET /api/data/ledger/unledgered': { data: [{ dataset: 'daily', lock: 'daily_minute', file: 'data/stocks/daily/005930.csv', mtime: '2026-09-25T11:00:00' }] },
    })
    renderApp(<LedgerTab />)
    expect(await screen.findByTestId('unledgered-table')).toHaveTextContent('data/stocks/daily/005930.csv')
  })

  it('API 없음 → 두 패널 모두 준비 중', async () => {
    mockApi({})
    renderApp(<LedgerTab />)
    await waitFor(() => expect(screen.getAllByTestId('hub-unavailable')).toHaveLength(2))
  })
})

describe('품질 탭', () => {
  it('gapOption: 기준(90%) 미만 막대는 빨강, 이상은 초록', () => {
    const o = gapOption(fx.gaps) as { series: { data: { value: number; itemStyle: { color: string } }[] }[] }
    const colors = o.series[0].data.map((d) => d.itemStyle.color)
    expect(colors).toEqual(['#52c41a', '#52c41a', '#f5222d', '#52c41a', '#52c41a'])
  })

  it('품질 탭 전체: 밀린 종목(소피증권 배지)·품질 5종 건수·결측 요약·보관소', async () => {
    mockApi({
      'GET /api/data/stale': { data: fx.stale }, 'GET /api/data/quality': { data: fx.quality },
      'GET /api/data/gaps': { data: fx.gaps }, 'GET /api/data/archive': { data: fx.archive },
      'GET /api/data/policy': { data: fx.policy.allowNow },
    })
    renderApp(<QualityTab />)
    const st = await screen.findByTestId('stale-table')
    expect(st).toHaveTextContent('소피증권 유니버스')
    expect(st).toHaveTextContent('거래정지')
    expect(st).toHaveTextContent('54일')
    expect(await screen.findByRole('button', { name: /선택 종목 받기 \(0\)/ })).toBeDisabled() // 체크 전엔 못 누른다
    expect(await screen.findByTestId('qcount-jump')).toHaveTextContent('2건')
    expect(screen.getByTestId('qcount-ohlc')).toHaveTextContent('0건')
    expect(screen.getByTestId('quality-table')).toHaveTextContent('삼성전자')
    expect(await screen.findByTestId('gap-summary')).toHaveTextContent('90% 미만 1일 — 2026-09-22')
    expect(screen.getByTestId('archive-coverage')).toHaveTextContent('2,041')
  })

  it('밀린 종목 체크 → [선택 종목 받기] 가 그 코드로 collect-daily 를 보낸다', async () => {
    const { calls } = mockApi({
      'GET /api/data/stale': { data: fx.stale }, 'GET /api/data/quality': { data: fx.quality },
      'GET /api/data/gaps': { data: fx.gaps }, 'GET /api/data/archive': { data: fx.archive },
      'GET /api/data/policy': { data: fx.policy.allowNow },
      'POST /api/data/jobs/collect-daily': { status: 202, data: { job_id: '20260925-101010-aaaaaa', status: 'queued', scheduled_at: null } },
    })
    renderApp(<QualityTab />)
    const st = await screen.findByTestId('stale-table')
    await userEvent.click(within(st).getAllByRole('checkbox')[1]) // 첫 행(005930)
    await userEvent.click(await screen.findByRole('button', { name: /선택 종목 받기 \(1\)/ }))
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ mode: 'codes', codes: ['005930'], when: 'now' }))
  })
})

describe('소피증권 탭', () => {
  it('엔진·운영 시간·기준선 갱신·기준 데이터·재기동 기록·계약 표시', async () => {
    mockApi({ 'GET /api/data/sophie': { data: fx.sophie } })
    renderApp(<SophieTab />)
    const p = await screen.findByTestId('sophie-panel')
    expect(p).toHaveTextContent('가동 중 (헬스체크 401)')
    expect(p).toHaveTextContent('kospi-theme-engine/config.yaml')
    expect(p).toHaveTextContent('2026-10-03 (토) 09:00 이후')
    expect(p).toHaveTextContent('완료 · 실패 13종목 · 보유 2041종목')
    expect(p).toHaveTextContent('다음 엔진 재기동부터')
    expect(p).toHaveTextContent('(18일 전)')
    expect(within(screen.getByTestId('contract')).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.queryByTestId('stale-day')).not.toBeInTheDocument()
  })

  it('거래일에 엔진이 어제 상태면 "재기동 필요" 경고', async () => {
    mockApi({ 'GET /api/data/sophie': { data: { ...fx.sophie, engine: { ...fx.sophie.engine, stale_day: true } } } })
    renderApp(<SophieTab />)
    expect(await screen.findByTestId('stale-day')).toHaveTextContent('재기동 필요')
  })

  it('엔진이 꺼져 있으면 빨간 표시, null 값은 대시', async () => {
    mockApi({ 'GET /api/data/sophie': { data: { ...fx.sophie, engine: { up: false, healthz: null, pid: null, started_at: null, stale_day: false } } } })
    renderApp(<SophieTab />)
    expect(await screen.findByText(/꺼져 있음/)).toBeInTheDocument()
  })
})

describe('상태 바', () => {
  it('허브 API 가 있으면 시간대·대량 수집 판정·일봉 기준일+판정·알림 수', async () => {
    mockApi({ ...META, 'GET /api/data/overview': { data: fx.overview } })
    renderApp(<StatusBar />)
    const s = await screen.findByTestId('status-hub')
    expect(s).toHaveTextContent('정규장')
    expect(s).toHaveTextContent('20:10 예약만')
    expect(s).toHaveTextContent('일봉 2026-09-24 나쁨')
    expect(s).toHaveTextContent('알림 1')
    expect(await screen.findByText('실행 중 작업 3')).toBeInTheDocument()
  })

  it('허브 API 가 없으면 허브 칸만 "허브 API 준비 중", 서버·작업 수는 정상', async () => {
    mockApi(META)
    renderApp(<StatusBar />)
    expect(await screen.findByTestId('status-hub-unavailable')).toHaveTextContent('허브 API 준비 중')
    expect(await screen.findByText('서버 연결됨')).toBeInTheDocument()
    expect(screen.queryByTestId('status-hub')).not.toBeInTheDocument()
  })

  it('서버 자체가 없으면 연결 실패', async () => {
    const { fetchMock } = mockApi({})
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    renderApp(<StatusBar />)
    expect(await screen.findByText(/서버에 연결할 수 없음/)).toBeInTheDocument()
  })
})

describe('허브 페이지 — 6탭', () => {
  const page = () => (
    <Routes>
      <Route path="/hub" element={<HubPage />} />
      <Route path="/hub/:tab" element={<HubPage />} />
    </Routes>
  )

  it('탭 6개가 있고 주소로 고른다', async () => {
    mockApi({})
    renderApp(page(), '/hub/collect')
    const tabs = await screen.findAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual(['개요', '수집', '일정', '장부', '품질', '소피증권'])
    expect(screen.getByRole('tab', { name: '수집', selected: true })).toBeInTheDocument()
  })

  it('알 수 없는 탭 주소는 개요로', async () => {
    mockApi({})
    renderApp(page(), '/hub/nope')
    expect(await screen.findByRole('tab', { name: '개요', selected: true })).toBeInTheDocument()
  })

  it('API 가 하나도 없을 때 6탭 전부 가짜 값 없이 "허브 API 준비 중"으로 렌더된다', async () => {
    mockApi({ 'GET /api/jobs': { data: [] } })
    for (const tab of ['overview', 'collect', 'schedules', 'ledger', 'quality', 'sophie']) {
      const { unmount } = renderApp(page(), `/hub/${tab}`)
      await waitFor(() => expect(screen.getAllByTestId('hub-unavailable').length).toBeGreaterThan(0))
      expect(screen.queryByTestId('hub-error')).not.toBeInTheDocument()
      unmount()
    }
  })
})
