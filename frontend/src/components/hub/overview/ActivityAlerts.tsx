// 지금 쓰는 작업 목록 + 활성 알림 목록 (§5.4 개요)
import { Empty, List, Progress, Space, Tag, Typography } from 'antd'
import { DASH, fmtTs } from '@/lib/format'
import type { ActiveAlert, ActivityRow } from '@/types/data'

export function ActivityList({ rows }: { rows: ActivityRow[] }) {
  if (!rows.length) return <Empty data-testid="activity-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description="지금 쓰고 있는 작업이 없습니다" />
  return (
    <List
      data-testid="activity-list"
      size="small"
      dataSource={rows}
      renderItem={(r) => {
        const pct = r.done !== null && r.total ? Math.round((r.done / r.total) * 100) : null
        return (
          <List.Item>
            <Space wrap style={{ width: '100%' }}>
              <Tag color={r.source === '허브' ? 'blue' : 'default'}>{r.source}</Tag>
              <strong>{r.writer ?? DASH}</strong>
              <Typography.Text type="secondary">→ {r.dataset ?? r.lock ?? DASH}</Typography.Text>
              {r.state === '잠금 대기' ? <Tag color="orange">잠금 대기</Tag> : pct !== null ? <Progress percent={pct} size="small" style={{ width: 160 }} format={() => `${r.done}/${r.total}`} /> : <Tag>진행률 없음</Tag>}
              <Typography.Text type="secondary">시작 {fmtTs(r.since)}</Typography.Text>
            </Space>
          </List.Item>
        )
      }}
    />
  )
}

export function AlertList({ alerts }: { alerts: ActiveAlert[] }) {
  if (!alerts.length) return <Empty data-testid="alerts-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description="활성 알림이 없습니다" />
  return (
    <List
      data-testid="alert-list"
      size="small"
      dataSource={alerts}
      renderItem={(a) => (
        <List.Item>
          <Space direction="vertical" size={0}>
            <Space><Tag color="red">{a.title}</Tag><Typography.Text type="secondary">처음 감지 {fmtTs(a.first_seen)}</Typography.Text></Space>
            <span>{a.message}</span>
          </Space>
        </List.Item>
      )}
    />
  )
}
