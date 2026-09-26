// 시간대 배너 (§5.4 개요 1번): 지금 구간 + "대량 수집: 가능 / 확인 필요 / 20:10 예약만" + 소피증권 운영 시간(출처 표기)
import { Alert, Space, Typography } from 'antd'
import { bulkText, fmtTs, WINDOW_LABEL } from '@/lib/format'
import type { OverviewData } from '@/types/data'

const TYPE = { allow_now: 'success', needs_confirm: 'warning', schedule_only: 'warning' } as const

export function WindowBanner({ now }: { now: OverviewData['now'] }) {
  const h = now.sophie_hours
  return (
    <Alert
      data-testid="window-banner"
      type={TYPE[now.bulk.decision]}
      showIcon
      message={
        <Space split={<Typography.Text type="secondary">|</Typography.Text>} wrap>
          <strong>지금 {fmtTs(now.ts)} — {WINDOW_LABEL[now.window]}</strong>
          <span>{bulkText(now.bulk.decision, now.bulk.suggest_at, h.connect_to)}</span>
        </Space>
      }
      description={
        <Typography.Text type="secondary">
          소피증권 운영 시간: 접속 {h.connect_from} · 정규장 {h.open}~{h.close} · 접속 종료 {h.connect_to} (출처: {h.source})
        </Typography.Text>
      }
    />
  )
}
