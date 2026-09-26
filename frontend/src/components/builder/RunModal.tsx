// 백테스트 실행 진행 모달 (§5.4): 제출 → 작업 진행률 폴링 → 완료면 결과 화면으로 · 취소 가능 · 실패 사유 표시
import { Alert, Button, Modal, Progress, Space, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { cancelJob } from '@/api/hub'
import { getJob, submitBacktest } from '@/api/studio'
import { usableLivePoints } from '@/lib/replay'
import { LiveCurve } from './LiveCurve'
import type { JobRow } from '@/types'
import type { SpecJson } from '@/types/studio'

const STAGE_KO: Record<string, string> = { load: '데이터 불러오는 중', signals: '조건 계산 중', engine: '체결 시뮬레이션 중', metrics: '지표 계산 중', done: '저장 중', prepare: '준비 중', grid: '조합을 하나씩 돌리는 중', select: '후보 고르는 중', final: '최종 계산 중' }
const POLL_MS = 1000
const REPLAY_MS = 2500 // 엔진이 곡선을 0.3초 만에 끝내는 빠른 실행도 "지나가는" 모습이 보이게, 끝난 뒤 받아 둔 곡선을 이 시간 동안 왼→오로 다시 그린다
const REPLAY_STEP_MS = 60
const DONE = new Set(['succeeded', 'failed', 'cancelled'])

interface Props {
  spec: SpecJson | null // null 이면 닫힘 — 값이 들어오는 순간 제출한다(새 객체가 들어올 때마다 한 번)
  onClose: () => void
  /** 백테스트가 아닌 작업(최적화·워크포워드·홀드아웃)은 제출 함수를 준다. 없으면 백테스트 제출 */
  request?: (spec: SpecJson) => Promise<{ job_id: string; run_id: string }>
  title?: string
}

export function RunModal({ spec, onClose, request, title = '백테스트 실행' }: Props) {
  const navigate = useNavigate()
  const [job, setJob] = useState<JobRow | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const alive = useRef(true)
  const [reveal, setReveal] = useState<number | null>(null) // 완료 뒤 곡선 재생 중이면 지금까지 보인 점 수
  const replayTimer = useRef<ReturnType<typeof setInterval> | undefined>(undefined)

  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  useEffect(() => {
    if (!spec) return
    setJob(null); setRunId(null); setError(null); setReveal(null)
    let stop = false
    let timer: ReturnType<typeof setTimeout> | undefined
    ;(async () => {
      try {
        const r = await (request ? request(spec) : submitBacktest(spec))
        if (stop) return
        setRunId(r.run_id)
        const tick = async () => {
          try {
            const j = await getJob(r.job_id)
            if (stop) return
            setJob(j)
            if (j.status === 'succeeded') {
              const pts = request ? [] : usableLivePoints(j.progress?.live_curve)
              const go = () => { navigate(`/results/${r.run_id}`); onClose() }
              if (pts.length < 2) { go(); return }
              const step = Math.max(1, Math.ceil(pts.length / (REPLAY_MS / REPLAY_STEP_MS)))
              let shown = 0
              replayTimer.current = setInterval(() => {
                shown = Math.min(pts.length, shown + step)
                setReveal(shown)
                if (shown >= pts.length) { clearInterval(replayTimer.current); replayTimer.current = setTimeout(go, 500) as never }
              }, REPLAY_STEP_MS)
              return
            }
            if (DONE.has(j.status)) return
          } catch (e) {
            if (!stop) setError(e instanceof Error ? e.message : String(e))
            return
          }
          timer = setTimeout(tick, POLL_MS)
        }
        void tick()
      } catch (e) {
        if (stop) return
        const fe = e instanceof ApiError ? Object.entries(e.fieldErrors).map(([k, v]) => `${k}: ${v}`).join(' / ') : ''
        setError(e instanceof ApiError ? `${e.code} — ${e.message}${fe ? ` (${fe})` : ''}` : String(e))
      }
    })()
    return () => { stop = true; if (timer) clearTimeout(timer); clearInterval(replayTimer.current); clearTimeout(replayTimer.current as never) }
    // spec 객체가 바뀔 때만(실행 버튼을 누를 때마다 새 객체) — navigate·onClose 는 안정적이지 않아도 제출을 다시 하면 안 된다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec])

  const failed = job?.status === 'failed' || job?.status === 'cancelled' || !!error
  const pct = job?.progress.pct ?? 0
  const running = !!spec && !failed && !(job && DONE.has(job.status))
  const all = usableLivePoints(job?.progress?.live_curve) // 실행 중 곡선(없으면 진행 막대만)
  const live = reveal === null ? all : all.slice(0, Math.max(1, reveal))

  return (
    <Modal open={!!spec} title={title} width={live.length ? 760 : 520} onCancel={running ? undefined : onClose} closable={!running} maskClosable={false} destroyOnHidden data-testid="run-modal"
      footer={
        <Space>
          {running && job && <Button danger onClick={() => cancelJob(job.job_id).catch((e) => setError(String(e)))} data-testid="run-cancel">취소</Button>}
          {!running && <Button onClick={onClose}>닫기</Button>}
        </Space>
      }>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Progress percent={Math.round(pct)} status={failed ? 'exception' : running ? 'active' : 'normal'} data-testid="run-progress" />
        {spec && live.length > 0 && !request && <LiveCurve points={live} spec={spec} />}
        <Typography.Text data-testid="run-stage">
          {error ? '오류' : job?.status === 'queued' || !job ? '대기 중…' : job.status === 'cancelled' ? '취소됨' : job.status === 'failed' ? '실패'
            : STAGE_KO[job.progress.stage ?? ''] ?? job.progress.stage ?? '실행 중'}
        </Typography.Text>
        {runId && <Typography.Text type="secondary" style={{ fontSize: 12 }}>결과 번호 {runId}</Typography.Text>}
        {(error || job?.error) && <Alert type="error" showIcon message="실행하지 못했습니다" description={error ?? job?.error} data-testid="run-error" />}
      </Space>
    </Modal>
  )
}
