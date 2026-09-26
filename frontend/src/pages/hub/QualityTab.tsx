import { Card, Col, Row, Space } from 'antd'
import { useHub } from '@/api/hub'
import { HubGate } from '@/components/hub/HubGate'
import { ArchiveCoverage } from '@/components/hub/quality/ArchiveCoverage'
import { GapBars } from '@/components/hub/quality/GapBars'
import { QualityTable } from '@/components/hub/quality/QualityTable'
import { StaleTable } from '@/components/hub/quality/StaleTable'
import type { ArchiveData, GapsData, QualityData, StaleData } from '@/types/data'

export function QualityTab() {
  const stale = useHub<StaleData>('/api/data/stale?dataset=daily', { refetchMs: 60_000 })
  const quality = useHub<QualityData>('/api/data/quality?dataset=daily')
  const gaps = useHub<GapsData>('/api/data/gaps?dataset=daily&days=120')
  const archive = useHub<ArchiveData>('/api/data/archive', { refetchMs: 60_000 })
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}><Card size="small" title="밀린 종목 (일봉)"><HubGate query={stale} path="/api/data/stale">{(d) => <StaleTable data={d} />}</HubGate></Card></Col>
        <Col xs={24} xl={12}><Card size="small" title="품질 문제 (일봉)"><HubGate query={quality} path="/api/data/quality">{(d) => <QualityTable data={d} />}</HubGate></Card></Col>
      </Row>
      <Card size="small" title="결측 거래일 (최근 120거래일)"><HubGate query={gaps} path="/api/data/gaps">{(d) => <GapBars data={d} />}</HubGate></Card>
      <Card size="small" title="통합 분봉 보관소 커버리지"><HubGate query={archive} path="/api/data/archive">{(d) => <ArchiveCoverage data={d} />}</HubGate></Card>
    </Space>
  )
}
