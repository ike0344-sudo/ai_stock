// 장부 탭 (§5.4): 장부 표(시각·잠금 자원·쓴 주체·출처·대상 수·결과·소요) + 필터(자원·출처·기간) + 장부 없는 쓰기 목록
import { Card, DatePicker, Select, Space, Table, Tag, Typography } from 'antd'
import type { Dayjs } from 'dayjs'
import { useState } from 'react'
import { qs, useHub } from '@/api/hub'
import { HubGate } from '@/components/hub/HubGate'
import { DASH, fmtDuration, fmtTs } from '@/lib/format'
import type { LedgerRun, LockResource, RunState, Source, UnledgeredWrite } from '@/types/data'

const STATE_COLOR: Record<RunState, string> = { '실행 중': 'processing', 완료: 'success', 실패: 'error', 중단됨: 'warning' }
const LOCKS: LockResource[] = ['daily_minute', 'minute_al', 'tick_al']
const SOURCES: Source[] = ['허브', '야간 갱신', '8765', '소피증권', '수동']

export function LedgerTab() {
  const [lock, setLock] = useState<LockResource | undefined>()
  const [source, setSource] = useState<Source | undefined>()
  const [since, setSince] = useState<Dayjs | null>(null)
  const path = `/api/data/ledger${qs({ lock, source, since: since?.format('YYYY-MM-DD'), limit: 100 })}`
  const q = useHub<LedgerRun[]>(path, { refetchMs: 10_000 })
  const un = useHub<UnledgeredWrite[]>('/api/data/ledger/unledgered?hours=24', { refetchMs: 60_000 })

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card size="small" title="쓰기 장부">
        <Space wrap style={{ marginBottom: 12 }}>
          <Select<LockResource> allowClear placeholder="잠금 자원" style={{ width: 160 }} value={lock} onChange={setLock} options={LOCKS.map((v) => ({ value: v, label: v }))} />
          <Select<Source> allowClear placeholder="출처" style={{ width: 140 }} value={source} onChange={setSource} options={SOURCES.map((v) => ({ value: v, label: v }))} />
          <DatePicker placeholder="이 날짜부터" value={since} onChange={setSince} />
        </Space>
        <HubGate query={q} path="/api/data/ledger">
          {(rows) => (
            <Table<LedgerRun>
              data-testid="ledger-table"
              size="small"
              rowKey="run"
              dataSource={rows}
              pagination={{ pageSize: 20, hideOnSinglePage: true }}
              locale={{ emptyText: '조건에 맞는 장부 기록이 없습니다' }}
              columns={[
                { title: '시각', dataIndex: 'ts', render: (t: string) => fmtTs(t, true) },
                { title: '잠금 자원', dataIndex: 'lock', render: (l: string | null) => l ?? DASH },
                { title: '쓴 주체', dataIndex: 'writer', render: (w: string | null) => w ?? DASH },
                { title: '출처', dataIndex: 'source', render: (s: string) => <Tag color={s === '허브' ? 'blue' : 'default'}>{s}</Tag> },
                { title: '대상 수', render: (_, r) => (r.total === null ? DASH : `${r.done ?? 0}/${r.total}`) },
                { title: '결과', dataIndex: 'state', render: (s: RunState, r) => <Tag color={STATE_COLOR[s]} title={r.error ?? undefined}>{s}</Tag> },
                { title: '소요', dataIndex: 'duration_sec', render: (d: number | null) => fmtDuration(d) },
              ]}
              expandable={{
                rowExpandable: (r) => !!r.error || !!r.detail,
                expandedRowRender: (r) => (
                  <Typography.Text type={r.error ? 'danger' : 'secondary'}>{r.error ?? JSON.stringify(r.detail)}</Typography.Text>
                ),
              }}
            />
          )}
        </HubGate>
      </Card>
      <Card size="small" title="장부 없는 쓰기 (최근 24시간)">
        <HubGate query={un} path="/api/data/ledger/unledgered">
          {(rows) => (
            <Table<UnledgeredWrite>
              data-testid="unledgered-table"
              size="small"
              rowKey={(r) => r.file}
              dataSource={rows}
              pagination={{ pageSize: 10, hideOnSinglePage: true }}
              locale={{ emptyText: '관문을 안 거친 쓰기가 감지되지 않았습니다' }}
              columns={[
                { title: '파일', dataIndex: 'file' },
                { title: '수정 시각', dataIndex: 'mtime', render: (t: string) => fmtTs(t, true) },
                { title: '데이터셋', dataIndex: 'dataset' },
              ]}
            />
          )}
        </HubGate>
      </Card>
    </Space>
  )
}
