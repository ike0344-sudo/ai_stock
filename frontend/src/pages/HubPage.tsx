// 데이터 허브 — 6탭. 탭은 주소(#/hub/{overview,collect,schedules,ledger,quality,sophie})로 고른다.
import { Tabs } from 'antd'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { CollectTab } from './hub/CollectTab'
import { LedgerTab } from './hub/LedgerTab'
import { OverviewTab } from './hub/OverviewTab'
import { QualityTab } from './hub/QualityTab'
import { SchedulesTab } from './hub/SchedulesTab'
import { SophieTab } from './hub/SophieTab'

export const HUB_TABS = [
  { key: 'overview', label: '개요', children: <OverviewTab /> },
  { key: 'collect', label: '수집', children: <CollectTab /> },
  { key: 'schedules', label: '일정', children: <SchedulesTab /> },
  { key: 'ledger', label: '장부', children: <LedgerTab /> },
  { key: 'quality', label: '품질', children: <QualityTab /> },
  { key: 'sophie', label: '소피증권', children: <SophieTab /> },
]

export function HubPage() {
  const { tab } = useParams()
  const navigate = useNavigate()
  if (!tab || !HUB_TABS.some((t) => t.key === tab)) return <Navigate to="/hub/overview" replace />
  // destroyOnHidden: 안 보는 탭은 그리지 않아 폴링도 멈춘다(요청 낭비 방지)
  return <Tabs activeKey={tab} onChange={(k) => navigate(`/hub/${k}`)} items={HUB_TABS} destroyOnHidden />
}
