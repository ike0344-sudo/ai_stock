// 허브 API 호출 훅. **라우트가 아직 없으면(404 NOT_FOUND) `unavailable`** — 화면은 그 패널을 "허브 API 준비 중" 으로
// 보여주고 가짜 값을 채우지 않는다(datahub/api.py 가 붙으면 코드 변경 없이 채워진다).
import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import type { JobLog, JobRow } from '@/types'
import type {
  AlertPatch,
  AlertRule,
  CollectDailyRequest,
  CollectMinuteAlRequest,
  CollectResponse,
  CollectTicksRequest,
  JobAccepted,
  SchedulePatch,
  ScheduleRow,
  TickRetryRequest,
  TickRetryResponse,
} from '@/types/data'
import { ApiError, apiGet, apiPatch, apiPost } from './client'

export const isUnavailable = (e: unknown): boolean => e instanceof ApiError && e.status === 404 && e.code === 'NOT_FOUND'

interface HubOpts {
  refetchMs?: number | false
  enabled?: boolean
}

/** GET 한 번 + (선택) 폴링. 404 는 재시도하지 않는다. */
export function useHub<T>(path: string, { refetchMs = false, enabled = true }: HubOpts = {}): UseQueryResult<T, ApiError> {
  return useQuery<T, ApiError>({
    queryKey: ['hub', path],
    queryFn: () => apiGet<T>(path),
    refetchInterval: refetchMs,
    enabled,
    retry: (n, err) => !isUnavailable(err) && err.code !== 'NETWORK' && n < 1,
  })
}

export const qs = (params: Record<string, string | number | boolean | null | undefined>): string => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== '') p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

/** 허브 수집 작업 표 — studio 의 /api/jobs (허브 API 와 무관하게 동작) */
export const useCollectJobs = (): UseQueryResult<JobRow[], ApiError> =>
  useQuery<JobRow[], ApiError>({
    queryKey: ['jobs', 'collect'],
    queryFn: () => apiGet<JobRow[]>('/api/jobs?group=collect&limit=50'),
    refetchInterval: 3000,
  })

export const fetchJobLog = (jobId: string, offset: number) => apiGet<JobLog>(`/api/jobs/${jobId}/log?offset=${offset}`)

// ── 제출 (POST·PATCH) — 본문 모양은 types/data.ts 가 고정한다
export const collectDaily = (b: CollectDailyRequest) => apiPost<CollectResponse>('/api/data/jobs/collect-daily', b)
export const collectTicks = (b: CollectTicksRequest) => apiPost<CollectResponse>('/api/data/jobs/collect-ticks', b)
export const collectMinuteAl = (b: CollectMinuteAlRequest) => apiPost<CollectResponse>('/api/data/jobs/collect-minute-al', b)
export const archiveMinuteAl = () => apiPost<JobAccepted>('/api/data/jobs/archive-minute-al', {})
export const retryTicks = (b: TickRetryRequest) => apiPost<TickRetryResponse>('/api/data/tick-window/retry', b)
export const patchSchedule = (id: string, b: SchedulePatch) => apiPatch<ScheduleRow>(`/api/data/schedules/${id}`, b)
export const patchAlert = (id: string, b: AlertPatch) => apiPatch<AlertRule>(`/api/data/alerts/${id}`, b)
export const cancelJob = (jobId: string) => apiPost<{ job_id: string; status: string }>(`/api/jobs/${jobId}/cancel`)
