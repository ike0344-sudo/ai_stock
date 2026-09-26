// 품질 문제 표 (§5.4): 종류 5가지·종목·날짜·값 + 종류별 건수
import { Space, Table, Tag } from 'antd'
import { DASH, fmtNum } from '@/lib/format'
import type { QualityData, QualityIssue, QualityKind } from '@/types/data'

export const QUALITY_LABEL: Record<QualityKind, string> = {
  ohlc: 'OHLC 불일치',
  nonpositive: '0 이하 가격',
  duplicate_date: '날짜 중복',
  jump: '±30.5% 초과 변동',
  zero_volume_run: '거래량 0 연속',
}
const KINDS = Object.keys(QUALITY_LABEL) as QualityKind[]

export function QualityTable({ data }: { data: QualityData }) {
  return (
    <Space direction="vertical" size="small" style={{ width: '100%' }}>
      <Space wrap data-testid="quality-counts">
        {KINDS.map((k) => (
          <Tag key={k} color={data.counts[k] > 0 ? 'orange' : 'default'} data-testid={`qcount-${k}`}>{QUALITY_LABEL[k]} {fmtNum(data.counts[k])}건</Tag>
        ))}
        <span>검사 행 {fmtNum(data.rows_checked)}</span>
      </Space>
      <Table<QualityIssue>
        data-testid="quality-table"
        size="small"
        rowKey={(r) => `${r.code}|${r.date}|${r.kind}`}
        dataSource={data.issues}
        pagination={{ pageSize: 15, hideOnSinglePage: true }}
        locale={{ emptyText: '품질 문제가 없습니다' }}
        columns={[
          { title: '종류', dataIndex: 'kind', render: (k: QualityKind) => QUALITY_LABEL[k] },
          { title: '종목', render: (_, r) => `${r.code} ${r.name ?? DASH}` },
          { title: '날짜', dataIndex: 'date' },
          { title: '값', dataIndex: 'detail' },
        ]}
      />
    </Space>
  )
}
