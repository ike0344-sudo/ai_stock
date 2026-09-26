import { Card, Col, Row, Space } from 'antd'
import { isUnavailable, useHub } from '@/api/hub'
import { HubGate } from '@/components/hub/HubGate'
import { ActivityList, AlertList } from '@/components/hub/overview/ActivityAlerts'
import { DatasetCards } from '@/components/hub/overview/DatasetCards'
import { WindowBanner } from '@/components/hub/overview/WindowBanner'
import type { OverviewData, TickWindowData } from '@/types/data'

export function OverviewTab() {
  const q = useHub<OverviewData>('/api/data/overview', { refetchMs: 10_000 })
  const tick = useHub<TickWindowData>('/api/data/tick-window', { refetchMs: 30_000 })
  return (
    <HubGate query={q} path="/api/data/overview">
      {(o) => (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <WindowBanner now={o.now} />
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={14}><Card size="small" title="지금 쓰는 작업"><ActivityList rows={o.activity} /></Card></Col>
            <Col xs={24} xl={10}><Card size="small" title={`활성 알림 (${o.alerts_active.length})`}><AlertList alerts={o.alerts_active} /></Card></Col>
          </Row>
          <DatasetCards
            datasets={o.datasets}
            catchup={o.daily_catchup}
            tick={{ loading: tick.isPending, unavailable: tick.isError && isUnavailable(tick.error), data: tick.data }}
          />
        </Space>
      )}
    </HubGate>
  )
}
