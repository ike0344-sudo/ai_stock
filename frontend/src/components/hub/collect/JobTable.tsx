// 작업 표 (§5.4 수집 탭): 종류·상태(예약·대기·실행·잠금 대기·완료·실패·취소)·예약 시각·진행률·단계·시작·경과·남은 시간·[로그][취소]
// studio 의 /api/jobs?group=collect 를 3초마다 읽는다 — 허브 API 가 없어도 동작한다.
import { useQueryClient } from '@tanstack/react-query'
import { App, Button, Progress, Table, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'
import { cancelJob, useCollectJobs } from '@/api/hub'
import { DASH, fmtDuration, fmtTs, KIND_LABEL } from '@/lib/format'
import type { JobRow } from '@/types'
import { LogViewer } from './LogViewer'

/** 화면에 보이는 상태 — 실행 중인데 관문이 잠금을 기다리면 "잠금 대기" */
export function displayStatus(j: JobRow): { text: string; color: string } {
  if (j.status === 'running' && j.progress.waiting_lock) return { text: '잠금 대기', color: 'orange' }
  if (j.status === 'running' && j.cancel_requested) return { text: '취소 중', color: 'orange' }
  return (
    {
      scheduled: { text: '예약', color: 'purple' },
      queued: { text: '대기', color: 'default' },
      running: { text: '실행', color: 'processing' },
      succeeded: { text: '완료', color: 'success' },
      failed: { text: '실패', color: 'error' },
      cancelled: { text: '취소', color: 'default' },
    } as const
  )[j.status]
}

const ACTIVE = new Set(['scheduled', 'queued', 'running'])

export function JobTable() {
  const q = useCollectJobs()
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [logJob, setLogJob] = useState<JobRow | null>(null)

  const cancel = async (j: JobRow) => {
    try {
      await cancelJob(j.job_id)
      message.success('취소를 요청했습니다')
      void qc.invalidateQueries({ queryKey: ['jobs'] })
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e))
    }
  }

  if (q.isError) return <Typography.Text type="danger" data-testid="jobs-error">작업 목록을 못 불러옴 — {q.error.message}</Typography.Text>
  return (
    <>
      <Table<JobRow>
        data-testid="job-table"
        size="small"
        rowKey="job_id"
        loading={q.isPending}
        dataSource={q.data ?? []}
        pagination={{ pageSize: 10, hideOnSinglePage: true }}
        locale={{ emptyText: '허브가 띄운 수집 작업이 아직 없습니다' }}
        columns={[
          { title: '종류', dataIndex: 'kind', render: (k: string) => KIND_LABEL[k] ?? k },
          { title: '상태', render: (_, j) => { const s = displayStatus(j); return <Tag color={s.color}>{s.text}</Tag> } },
          { title: '예약 시각', dataIndex: 'scheduled_at', render: (t: string | null) => fmtTs(t) },
          {
            title: '진행률',
            render: (_, j) => (j.progress.pct === null ? DASH : <Progress percent={Math.round(j.progress.pct)} size="small" style={{ width: 120 }} status={j.status === 'failed' ? 'exception' : undefined} />),
          },
          { title: '단계', render: (_, j) => j.progress.stage ?? DASH },
          { title: '시작', dataIndex: 'started_at', render: (t: string | null) => fmtTs(t) },
          {
            title: '경과',
            render: (_, j) => (j.started_at ? fmtDuration(dayjs(j.finished_at ?? undefined).diff(dayjs(j.started_at), 'second')) : DASH),
          },
          { title: '남은 시간', render: (_, j) => (ACTIVE.has(j.status) ? fmtDuration(j.progress.eta_sec) : DASH) },
          {
            title: '',
            render: (_, j) => (
              <>
                <Button size="small" type="link" onClick={() => setLogJob(j)}>로그</Button>
                {ACTIVE.has(j.status) && <Button size="small" type="link" danger disabled={j.cancel_requested} onClick={() => cancel(j)}>취소</Button>}
              </>
            ),
          },
        ]}
        expandable={{ rowExpandable: (j) => !!j.error, expandedRowRender: (j) => <Typography.Text type="danger">{j.error}</Typography.Text> }}
      />
      <LogViewer job={logJob} onClose={() => setLogJob(null)} />
    </>
  )
}
