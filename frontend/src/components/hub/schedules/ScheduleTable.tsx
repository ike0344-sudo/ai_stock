// 일정 표 (§5.4): 이름·주인·언제·마지막 시작/끝/결과·다음 예정·놓침 배지 · 허브 소유만 켜기/끄기·시각 변경(외부는 잠금 아이콘 + "워치독이 관리")
// · 허브 소유 일정 회차 기록(최근 14회)
import { LockOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { App, Space, Switch, Table, Tag, TimePicker, Tooltip, Typography } from 'antd'
import dayjs from 'dayjs'
import { patchSchedule } from '@/api/hub'
import { DASH, fmtNum, fmtTs } from '@/lib/format'
import type { ScheduleOwner, ScheduleRow, ScheduleRun } from '@/types/data'

export const OWNER_LABEL: Record<ScheduleOwner, string> = { hub: '허브', watchdog: '워치독', '8765': '8765', sophie: '소피증권' }
const MANAGER: Record<ScheduleOwner, string> = { hub: '', watchdog: '워치독이 관리', '8765': '8765 대시보드가 관리', sophie: '소피증권이 관리' }

export function ScheduleTable({ rows }: { rows: ScheduleRow[] }) {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const patch = async (id: string, body: { enabled?: boolean; time?: string }) => {
    try {
      await patchSchedule(id, body)
      void qc.invalidateQueries({ queryKey: ['hub'] })
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e))
    }
  }
  return (
    <Table<ScheduleRow>
      data-testid="schedule-table"
      size="small"
      rowKey="id"
      pagination={false}
      dataSource={rows}
      columns={[
        {
          title: '일정', render: (_, r) => (
            <Space direction="vertical" size={0}>
              <strong>{r.label}</strong>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>{r.does}</Typography.Text>
            </Space>
          ),
        },
        { title: '주인', dataIndex: 'owner', render: (o: ScheduleOwner) => <Tag color={o === 'hub' ? 'blue' : 'default'}>{OWNER_LABEL[o]}</Tag> },
        { title: '언제', dataIndex: 'when' },
        { title: '마지막 시작', dataIndex: 'last_started', render: (t: string | null) => fmtTs(t) },
        { title: '마지막 끝', dataIndex: 'last_finished', render: (t: string | null) => fmtTs(t) },
        {
          title: '결과', render: (_, r) => (r.last_ok === null && !r.last_result ? DASH : <Tag color={r.last_ok === false ? 'error' : 'success'}>{r.last_result ?? (r.last_ok ? '완료' : '실패')}</Tag>),
        },
        { title: '다음 예정', dataIndex: 'next_expected', render: (t: string | null) => fmtTs(t) },
        { title: '놓침', render: (_, r) => (r.missed ? <Tag color="red" data-testid={`missed-${r.id}`}>{r.missed_note ?? '놓침'}</Tag> : null) },
        {
          title: '관리', render: (_, r) =>
            r.editable ? (
              <Space>
                <Switch size="small" checked={!!r.enabled} onChange={(v) => patch(r.id, { enabled: v })} aria-label={`${r.label} 켜기/끄기`} />
                {r.time && (
                  <TimePicker size="small" format="HH:mm" allowClear={false} value={dayjs(r.time, 'HH:mm')} onChange={(v) => v && patch(r.id, { time: v.format('HH:mm') })} />
                )}
              </Space>
            ) : (
              <Tooltip title={MANAGER[r.owner]}><span data-testid={`locked-${r.id}`}><LockOutlined /> {MANAGER[r.owner]}</span></Tooltip>
            ),
        },
      ]}
      expandable={{
        rowExpandable: (r) => r.runs.length > 0,
        expandedRowRender: (r) => <RunsTable runs={r.runs} />,
      }}
    />
  )
}

function RunsTable({ runs }: { runs: ScheduleRun[] }) {
  return (
    <Table<ScheduleRun>
      size="small"
      pagination={false}
      rowKey={(r) => `${r.job_id ?? ''}${r.started}`}
      dataSource={runs.slice(0, 14)}
      columns={[
        { title: '시작', dataIndex: 'started', render: (t: string) => fmtTs(t) },
        { title: '끝', dataIndex: 'finished', render: (t: string | null) => fmtTs(t) },
        { title: '계획', dataIndex: 'planned', render: fmtNum },
        { title: '받은', dataIndex: 'received', render: fmtNum },
        { title: '남은', dataIndex: 'remaining', render: fmtNum },
        { title: '미룬', dataIndex: 'deferred', render: fmtNum },
        { title: '결과', render: (_, r) => <Tag color={r.ok === false ? 'error' : r.ok ? 'success' : 'default'}>{r.result}</Tag> },
      ]}
    />
  )
}
