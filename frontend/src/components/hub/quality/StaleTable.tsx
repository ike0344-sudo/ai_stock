// 밀린 종목 표 (§5.4 품질): 코드·이름·마지막 날짜·며칠 밀림·소피증권 유니버스 배지·체크 → [선택 종목 받기]
import { Space, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { collectDaily } from '@/api/hub'
import { PolicyButton } from '@/components/hub/collect/PolicyButton'
import { DASH } from '@/lib/format'
import type { StaleData, StaleRow } from '@/types/data'

export function StaleTable({ data }: { data: StaleData }) {
  const [sel, setSel] = useState<string[]>([])
  return (
    <Space direction="vertical" size="small" style={{ width: '100%' }}>
      <Typography.Text type="secondary">기준일 {data.reference_date ?? DASH} · 밀린 종목 {data.rows.length}개</Typography.Text>
      <Table<StaleRow>
        data-testid="stale-table"
        size="small"
        rowKey="code"
        dataSource={data.rows}
        pagination={{ pageSize: 15, hideOnSinglePage: true }}
        rowSelection={{ selectedRowKeys: sel, onChange: (k) => setSel(k as string[]) }}
        locale={{ emptyText: '밀린 종목이 없습니다' }}
        columns={[
          { title: '코드', dataIndex: 'code' },
          { title: '이름', dataIndex: 'name', render: (n: string | null) => n ?? DASH },
          { title: '마지막 날짜', dataIndex: 'last' },
          { title: '며칠 밀림', dataIndex: 'days_behind', sorter: (a, b) => a.days_behind - b.days_behind, render: (d: number) => `${d}일` },
          {
            title: '구분',
            render: (_, r) => (
              <Space>
                {r.sophie && <Tag color="red">소피증권 유니버스</Tag>}
                {r.inactive && <Tag>{r.inactive}</Tag>}
              </Space>
            ),
          },
        ]}
      />
      <PolicyButton
        kind="collect_daily"
        mode="codes"
        codes={sel}
        disabled={sel.length === 0}
        disabledReason="표에서 종목을 체크하세요"
        labelNow={`선택 종목 받기 (${sel.length})`}
        submit={(w) => collectDaily({ mode: 'codes', codes: sel, ...w })}
      />
    </Space>
  )
}
