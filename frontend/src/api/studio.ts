// 스튜디오 API 호출 — 조회는 react-query 훅, 변경은 함수(호출하는 쪽이 성공 후 무효화). 서버: studio/api/routes/*
import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import type { JobRow } from '@/types'
import type {
  BarsData, CompareData, IntradaySources, DataRanges, EquityPoint, FoldsFile, GridInfo, GridRow, HoldoutHistory, IndicatorCatalog, LegacyStrategyDef, PresetRow, PreviewResult, Recipe,
  RunDetail, RunRow, SpecJson, StockHit, Trade, ValidateResult, ValidationConfig, WalkforwardConfig,
} from '@/types/studio'
import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut } from './client'

type Q<T> = UseQueryResult<T, ApiError>
const FOREVER = { staleTime: Infinity, retry: false } as const

// ── 카탈로그 (앱이 켜져 있는 동안 안 바뀐다)
export const useIndicators = (): Q<IndicatorCatalog> => useQuery({ queryKey: ['meta', 'indicators'], queryFn: () => apiGet<IndicatorCatalog>('/api/meta/indicators'), ...FOREVER })
export const useLegacyStrategies = (): Q<LegacyStrategyDef[]> => useQuery({ queryKey: ['meta', 'strategies'], queryFn: () => apiGet<LegacyStrategyDef[]>('/api/meta/strategies'), ...FOREVER })
export const useDataRanges = (): Q<DataRanges> => useQuery({ queryKey: ['meta', 'data-ranges'], queryFn: () => apiGet<DataRanges>('/api/meta/data-ranges'), staleTime: 5 * 60_000, retry: false })

export const useRecipes = (): Q<Recipe[]> => useQuery({ queryKey: ['meta', 'recipes'], queryFn: () => apiGet<Recipe[]>('/api/meta/recipes'), staleTime: 5 * 60_000, retry: false })

// ── 종목
export const useStockSearch = (q: string): Q<StockHit[]> =>
  useQuery({ queryKey: ['stocks', q], queryFn: () => apiGet<StockHit[]>(`/api/stocks?q=${encodeURIComponent(q)}`), enabled: q.trim().length > 0, staleTime: 60_000 })
/** interval: 1d 또는 분봉(5m 등, 출처 al|krx). 분봉의 t 는 봉 끝 시각 */
export const useBars = (code: string | null, start?: string, end?: string, interval = '1d', source = 'al'): Q<BarsData> =>
  useQuery({
    queryKey: ['bars', code, start, end, interval, source],
    queryFn: () => apiGet<BarsData>(`/api/stocks/${code}/bars?interval=${interval}${interval !== '1d' ? `&source=${source}` : ''}${start ? `&start=${start}` : ''}${end ? `&end=${end}` : ''}`),
    enabled: !!code, staleTime: 5 * 60_000,
  })

export const useIntradaySources = (start: string, end: string, enabled = true): Q<IntradaySources> =>
  useQuery({ queryKey: ['meta', 'intraday-sources', start, end], queryFn: () => apiGet<IntradaySources>(`/api/meta/intraday-sources?start=${start}&end=${end}`), enabled, staleTime: 5 * 60_000, retry: false })

// ── 프리셋
export const usePresets = (): Q<PresetRow[]> => useQuery({ queryKey: ['presets'], queryFn: () => apiGet<PresetRow[]>('/api/presets') })
export const getPreset = (name: string) => apiGet<{ name: string; spec: SpecJson }>(`/api/presets/${encodeURIComponent(name)}`)
export const putPreset = (name: string, spec: SpecJson) => apiPut<{ name: string }>(`/api/presets/${encodeURIComponent(name)}`, spec)
export const deletePreset = (name: string) => apiDelete<{ deleted: boolean }>(`/api/presets/${encodeURIComponent(name)}`)

// ── 조건
export const validateSpec = (spec: SpecJson) => apiPost<ValidateResult>('/api/conditions/validate', { spec })
export const previewSpec = (spec: SpecJson, limit = 50) => apiPost<PreviewResult>('/api/conditions/preview', { spec, limit })

// ── 실행(작업)
export const submitBacktest = (spec: SpecJson) => apiPost<{ job_id: string; run_id: string }>('/api/jobs/backtest', spec)
export const getJob = (jobId: string) => apiGet<JobRow>(`/api/jobs/${jobId}`)

// ── 실행 기록
export interface RunFilters { q?: string; mode?: string; starred?: boolean; kind?: string }
export const useRuns = (f: RunFilters = {}): Q<RunRow[]> => {
  const qs = new URLSearchParams()
  if (f.q) qs.set('q', f.q)
  if (f.mode) qs.set('mode', f.mode)
  if (f.kind) qs.set('kind', f.kind)
  if (f.starred !== undefined) qs.set('starred', String(f.starred))
  const s = qs.toString()
  return useQuery({ queryKey: ['runs', s], queryFn: () => apiGet<RunRow[]>(`/api/runs${s ? `?${s}` : ''}`) })
}
export const useRunDetail = (id: string | undefined): Q<RunDetail> =>
  useQuery({ queryKey: ['run', id], queryFn: () => apiGet<RunDetail>(`/api/runs/${id}`), enabled: !!id, staleTime: 60_000 })
export const useTrades = (id: string | undefined): Q<Trade[]> =>
  useQuery({ queryKey: ['run', id, 'trades'], queryFn: () => apiGet<Trade[]>(`/api/runs/${id}/trades`), enabled: !!id, staleTime: 60_000 })
export const useEquity = (id: string | undefined): Q<EquityPoint[]> =>
  useQuery({ queryKey: ['run', id, 'equity'], queryFn: () => apiGet<EquityPoint[]>(`/api/runs/${id}/equity`), enabled: !!id, staleTime: 60_000 })
export const patchRun = (id: string, body: { name?: string; memo?: string | null; starred?: boolean }) => apiPatch<RunRow>(`/api/runs/${id}`, body)
export const deleteRun = (id: string) => apiDelete<{ deleted: boolean }>(`/api/runs/${id}`)
export const compareRuns = (ids: string[]) => apiPost<CompareData>('/api/runs/compare', { ids })
export const tradesCsvUrl = (id: string) => `/api/runs/${id}/export/trades.csv`

// ── 검증 (module-5)
type Submitted = { job_id: string; run_id: string }
export const submitOptimize = (spec: SpecJson, config: ValidationConfig) => apiPost<Submitted>('/api/jobs/optimize', { spec, config })
export const submitWalkforward = (spec: SpecJson, config: ValidationConfig, walkforward: WalkforwardConfig) => apiPost<Submitted>('/api/jobs/walkforward', { spec, config, walkforward })
export const submitHoldout = (spec: SpecJson, overrides: Record<string, number>, sourceRunId?: string) =>
  apiPost<Submitted>('/api/jobs/holdout-check', { spec, overrides, ...(sourceRunId ? { source_run_id: sourceRunId } : {}) })
export const fetchGridInfo = (spec: SpecJson, vary?: string[]) => apiPost<GridInfo>('/api/validation/grid-info', { spec, ...(vary ? { vary } : {}) })
export const fetchHoldoutHistory = (spec: SpecJson) => apiPost<HoldoutHistory>('/api/validation/holdout-history', { spec })
export const useGrid = (id: string | undefined, enabled: boolean): Q<GridRow[]> =>
  useQuery({ queryKey: ['run', id, 'grid'], queryFn: () => apiGet<GridRow[]>(`/api/runs/${id}/grid`), enabled: !!id && enabled, staleTime: 60_000 })
export const useFolds = (id: string | undefined, enabled: boolean): Q<FoldsFile> =>
  useQuery({ queryKey: ['run', id, 'folds'], queryFn: () => apiGet<FoldsFile>(`/api/runs/${id}/folds`), enabled: !!id && enabled, staleTime: 60_000 })
