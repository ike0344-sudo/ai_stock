// 서버 응답 타입 (설계서 §4, §6). 서버 쪽이 늘어나면 여기에 더한다.

export interface ErrorEnvelope {
  error: { code: string; message: string; details?: Record<string, unknown> }
}

export interface MetaStatus {
  engine_version: string
  server_time: string
  jobs: { scheduled: number; queued: number; running: number }
}

export type JobStatus = 'scheduled' | 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface JobProgress {
  pct: number | null
  stage: string | null
  message: string | null
  eta_sec: number | null
  paused: boolean
  waiting_lock: { resource: string; owner?: unknown } | null
}

/** GET /api/jobs 의 행 (studio/api/routes/jobs.py) */
export interface JobRow {
  job_id: string
  kind: string
  group: 'collect' | 'local' | 'compute'
  status: JobStatus
  scheduled_at: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  run_id: string | null
  lock: string | null
  trigger: string | null
  error: string | null
  progress: JobProgress
  cancel_requested: boolean
}

export interface JobLog {
  text: string
  next_offset: number
  eof: boolean
}
