// 보관소 패널 (§5.4): [보관 병합 지금 실행](로컬 — API 호출 없음), 마지막 병합 시각, 누락 종목 수
import { Card, Descriptions, Space, Tag } from 'antd'
import { archiveMinuteAl, useHub } from '@/api/hub'
import { DASH, fmtNum, fmtTs, VERDICT_COLOR, VERDICT_LABEL } from '@/lib/format'
import type { ArchiveData } from '@/types/data'
import { HubGate } from '../HubGate'
import { PolicyButton } from './PolicyButton'

export function ArchivePanel() {
  const q = useHub<ArchiveData>('/api/data/archive', { refetchMs: 30_000 })
  return (
    <Card size="small" title="통합 분봉 보관소" data-testid="archive-panel">
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <HubGate query={q} path="/api/data/archive">
          {(a) => (
            <Descriptions size="small" column={1} items={[
              { label: '판정', children: <Tag color={VERDICT_COLOR[a.verdict]}>{VERDICT_LABEL[a.verdict]}</Tag> },
              { label: '마지막 병합', children: fmtTs(a.last_merge_at) },
              { label: '누락(캐시 대비)', children: `${fmtNum(a.missing_vs_cache)}종목` },
              { label: '이유', children: a.reason ?? DASH },
            ]} />
          )}
        </HubGate>
        <PolicyButton kind="archive_minute_al" labelNow="보관 병합 지금 실행" submit={(w) => { void w; return archiveMinuteAl() }} />
      </Space>
    </Card>
  )
}
