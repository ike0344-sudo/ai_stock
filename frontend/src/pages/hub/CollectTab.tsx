import { Card, Col, Row, Space } from 'antd'
import { ArchivePanel } from '@/components/hub/collect/ArchivePanel'
import { CollectDailyPanel } from '@/components/hub/collect/CollectDailyPanel'
import { CollectMinuteAlPanel } from '@/components/hub/collect/CollectMinuteAlPanel'
import { CollectTicksPanel } from '@/components/hub/collect/CollectTicksPanel'
import { JobTable } from '@/components/hub/collect/JobTable'

export function CollectTab() {
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <CollectDailyPanel />
            <CollectMinuteAlPanel />
            <ArchivePanel />
          </Space>
        </Col>
        <Col xs={24} xl={12}><CollectTicksPanel /></Col>
      </Row>
      <Card size="small" title="작업 표 (허브 수집 작업)"><JobTable /></Card>
    </Space>
  )
}
