// 상단 상태 바 (설계서 §5.4 공통): 서버 연결 · 지금 시간대 · 일봉 기준일+판정 색 · 실행 중 작업 수 · 활성 알림 수 · 다크 모드.
// 시간대·일봉·알림은 허브 overview 에서 온다 — 허브 API 가 없으면 그 칸은 "허브 API 준비 중" 이고 값을 지어내지 않는다.
import { MoonOutlined, SunOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Badge, Space, Switch, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { ApiError } from '@/api/client'
import { isUnavailable, useHub } from '@/api/hub'
import { getMetaStatus } from '@/api/meta'
import { bulkText, DASH, VERDICT_COLOR, VERDICT_LABEL, WINDOW_LABEL } from '@/lib/format'
import { useDark } from '@/lib/theme'
import type { OverviewData } from '@/types/data'

export function HubSummary({ q }: { q: ReturnType<typeof useHub<OverviewData>> }) {
  if (q.isPending) return null
  if (q.isError) {
    return <Tag data-testid="status-hub-unavailable">{isUnavailable(q.error) ? '허브 API 준비 중' : `허브 오류: ${q.error.code}`}</Tag>
  }
  const o = q.data
  const daily = o.datasets.find((d) => d.id === 'daily')
  return (
    <Space size="small" wrap data-testid="status-hub">
      <Tag>{WINDOW_LABEL[o.now.window]}</Tag>
      <Typography.Text type="secondary">{bulkText(o.now.bulk.decision, o.now.bulk.suggest_at, o.now.sophie_hours.connect_to)}</Typography.Text>
      <Tag color={daily ? VERDICT_COLOR[daily.verdict] : 'default'}>
        일봉 {daily?.reference_date ?? DASH}{daily ? ` ${VERDICT_LABEL[daily.verdict]}` : ''}
      </Tag>
      <Tag color={o.alerts_active.length ? 'red' : 'default'}>알림 {o.alerts_active.length}</Tag>
    </Space>
  )
}

export function StatusBar() {
  const { dark, toggle } = useDark()
  const { data, error, dataUpdatedAt } = useQuery({
    queryKey: ['meta', 'status'],
    queryFn: getMetaStatus,
    refetchInterval: 10_000,
  })
  const hub = useHub<OverviewData>('/api/data/overview', { refetchMs: 10_000 })

  return (
    <Space size="large" style={{ width: '100%', justifyContent: 'space-between' }}>
      <Space size="middle" wrap>
        {error ? (
          <Badge status="error" text={error instanceof ApiError ? error.message : '서버 연결 실패'} />
        ) : (
          <Badge status={data ? 'success' : 'processing'} text={data ? '서버 연결됨' : '연결 중'} />
        )}
        {data && (
          <>
            <Tag color={data.jobs.running ? 'processing' : 'default'}>실행 중 작업 {data.jobs.running}</Tag>
            <Tag>대기 {data.jobs.queued}</Tag>
            <Tag>예약 {data.jobs.scheduled}</Tag>
          </>
        )}
        <HubSummary q={hub} />
        {data && (
          <Typography.Text type="secondary">
            엔진 {data.engine_version} · 갱신 {dayjs(dataUpdatedAt).format('HH:mm:ss')}
          </Typography.Text>
        )}
      </Space>
      <Switch
        checked={dark}
        onChange={toggle}
        checkedChildren={<MoonOutlined />}
        unCheckedChildren={<SunOutlined />}
        aria-label="다크 모드"
      />
    </Space>
  )
}
