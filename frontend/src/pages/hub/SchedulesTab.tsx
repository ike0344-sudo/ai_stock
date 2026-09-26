import { Card, Space } from 'antd'
import { useHub } from '@/api/hub'
import { HubGate } from '@/components/hub/HubGate'
import { AlertRulesTable } from '@/components/hub/schedules/AlertRulesTable'
import { ScheduleTable } from '@/components/hub/schedules/ScheduleTable'
import type { AlertsData, SchedulesData } from '@/types/data'

export function SchedulesTab() {
  const s = useHub<SchedulesData>('/api/data/schedules', { refetchMs: 30_000 })
  const a = useHub<AlertsData>('/api/data/alerts', { refetchMs: 30_000 })
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card size="small" title="일정">
        <HubGate query={s} path="/api/data/schedules">{(rows) => <ScheduleTable rows={rows} />}</HubGate>
      </Card>
      <Card size="small" title="알림 규칙">
        <HubGate query={a} path="/api/data/alerts">{(d) => <AlertRulesTable rules={d.rules} />}</HubGate>
      </Card>
    </Space>
  )
}
