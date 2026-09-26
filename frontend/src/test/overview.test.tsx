import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { datasetRows } from '@/components/hub/overview/DatasetCards'
import { OverviewTab } from '@/pages/hub/OverviewTab'
import * as fx from './fixtures/hub'
import { mockApi, renderApp } from './helpers'

describe('개요 탭', () => {
  it('허브 API 가 없으면 값 없이 "허브 API 준비 중"만 보인다(가짜 값 없음)', async () => {
    mockApi({}) // 모든 경로 404 NOT_FOUND
    renderApp(<OverviewTab />)
    expect(await screen.findByTestId('hub-unavailable')).toHaveTextContent('허브 API 준비 중')
    expect(screen.queryByTestId('dataset-cards')).not.toBeInTheDocument()
    expect(screen.queryByText(/2577/)).not.toBeInTheDocument()
  })

  it('서버 오류(500)는 준비 중이 아니라 오류로 보인다', async () => {
    mockApi({ 'GET /api/data/overview': { status: 500, error: { code: 'INTERNAL', message: '서버 내부 오류' } } })
    renderApp(<OverviewTab />)
    expect(await screen.findByTestId('hub-error', {}, { timeout: 5000 })).toHaveTextContent('INTERNAL') // 훅이 오류를 1회 재시도한다
    expect(screen.queryByTestId('hub-unavailable')).not.toBeInTheDocument()
  })

  it('시간대 배너: 정규장 + 대량 수집 20:10 예약만 + 소피증권 운영 시간(출처)', async () => {
    mockApi({ 'GET /api/data/overview': { data: fx.overview } })
    renderApp(<OverviewTab />)
    const b = await screen.findByTestId('window-banner')
    expect(b).toHaveTextContent('정규장')
    expect(b).toHaveTextContent('대량 수집: 20:10 예약만')
    expect(b).toHaveTextContent('접속 08:20')
    expect(b).toHaveTextContent('출처: kospi-theme-engine/config.yaml')
  })

  it('야간이면 "지금 가능"', async () => {
    mockApi({ 'GET /api/data/overview': { data: fx.overviewNight } })
    renderApp(<OverviewTab />)
    expect(await screen.findByTestId('window-banner')).toHaveTextContent('대량 수집: 지금 가능')
    expect(screen.getByTestId('activity-empty')).toBeInTheDocument()
    expect(screen.getByTestId('alerts-empty')).toBeInTheDocument()
  })

  it('데이터셋 카드 11개, 판정 색(data-verdict), 소피증권 유니버스 밀림 표시', async () => {
    mockApi({ 'GET /api/data/overview': { data: fx.overview } })
    renderApp(<OverviewTab />)
    const cards = await screen.findByTestId('dataset-cards')
    expect(within(cards).getAllByTestId(/^card-/)).toHaveLength(11)
    const daily = screen.getByTestId('card-daily')
    expect(daily).toHaveAttribute('data-verdict', 'bad')
    expect(daily).toHaveTextContent('소피증권 유니버스 밀림')
    expect(daily).toHaveTextContent('2026-09-24 / 2026-09-24') // 기준일 / 기대일
    expect(daily).toHaveTextContent('야간 갱신 · backfill_universe')
    expect(daily).toHaveTextContent('daily_minute — 비어 있음')
    expect(screen.getByTestId('card-index')).toHaveAttribute('data-verdict', 'good')
  })

  it('통합 분봉 캐시 카드: "갱신 때 덮어씀" 문구 + 보관소 카드 링크, 보관 규칙 배지', async () => {
    mockApi({ 'GET /api/data/overview': { data: fx.overview } })
    renderApp(<OverviewTab />)
    const c = await screen.findByTestId('card-minute_al')
    expect(c).toHaveTextContent('갱신 때 덮어씀')
    expect(within(c).getByRole('link', { name: '통합 1분봉 보관소' })).toHaveAttribute('href', '#ds-minute_al_archive')
    expect(screen.getByTestId('card-minute_al_archive')).toHaveTextContent('영구 보관')
  })

  it('일봉 카드: 아침 따라잡기 결과(받은·못 받은) / 안 돈 날은 "돌지 않음"', async () => {
    mockApi({ 'GET /api/data/overview': { data: fx.overview } })
    const { unmount } = renderApp(<OverviewTab />)
    expect(await screen.findByTestId('catchup-extra')).toHaveTextContent('받은 40 · 못 받은 2')
    unmount()
    mockApi({ 'GET /api/data/overview': { data: fx.overviewNight } })
    renderApp(<OverviewTab />)
    expect(await screen.findByTestId('catchup-extra')).toHaveTextContent('오늘은 돌지 않음')
  })

  it('통합 체결 카드: 체결 API 가 있으면 가장 먼저 사라질 날짜·자동 수집, 없으면 그 줄만 "준비 중"', async () => {
    mockApi({ 'GET /api/data/overview': { data: fx.overview }, 'GET /api/data/tick-window': { data: fx.tickWindow } })
    const { unmount } = renderApp(<OverviewTab />)
    const extra = await screen.findByTestId('tick-extra')
    expect(extra).toHaveTextContent('2026-09-21 (1거래일 남음)')
    expect(extra).toHaveTextContent('켜짐')
    unmount()
    mockApi({ 'GET /api/data/overview': { data: fx.overview } }) // tick-window 404
    renderApp(<OverviewTab />)
    expect(await screen.findByTestId('tick-extra-unavailable')).toHaveTextContent('허브 API 준비 중')
    expect(screen.getByTestId('card-tick_al')).toHaveTextContent('조회창 빠진 쌍') // 개요의 값은 그대로
  })

  it('지금 쓰는 작업(출처·진행률·잠금 대기)과 활성 알림(처음 감지 시각)', async () => {
    mockApi({ 'GET /api/data/overview': { data: fx.overview } })
    renderApp(<OverviewTab />)
    const act = await screen.findByTestId('activity-list')
    expect(act).toHaveTextContent('야간 갱신')
    expect(act).toHaveTextContent('820/2016')
    expect(act).toHaveTextContent('잠금 대기')
    const al = screen.getByTestId('alert-list')
    expect(al).toHaveTextContent('보관 누락')
    expect(al).toHaveTextContent('처음 감지 09-25 09:10')
  })

  it('폴링이 데이터를 다시 받아도 화면이 유지된다(로딩 깜빡임 없음)', async () => {
    mockApi({ 'GET /api/data/overview': { data: fx.overview } })
    renderApp(<OverviewTab />)
    await waitFor(() => expect(screen.getByTestId('dataset-cards')).toBeInTheDocument())
  })
})

describe('datasetRows — 값이 null 이면 "—", 없는 키는 칸 자체를 만들지 않는다', () => {
  it('키가 없는 칸은 안 만들고, null 은 대시', () => {
    const rows = Object.fromEntries(datasetRows({ ...fx.overview.datasets[0], reference_date: null, expected_date: null }).map(([k, v]) => [k, v]))
    expect(rows['최신일(기준 / 기대)']).toBe('— / —')
    expect(rows['최빈 최신일']).toBeUndefined() // minute_al 전용 칸
    expect(datasetRows(fx.overview.datasets.find((d) => d.id === 'reference_static')!)).toEqual([])
  })
})
