// 검증 화면(최적화·워크포워드·홀드아웃) 순수 계산 — 조합 표 → 히트맵 자료, 구간 그림 옵션, 사전 판정 기준 방향, 설정 → 요청 변환.
// 화면 컴포넌트가 아니라 여기 둔 이유: jsdom 에서 값을 바로 검사할 수 있게(차트 캔버스 없이).
import type { EChartOption } from '@/components/charts/EChart'
import { DOWN, SERIES_COLORS, UP } from '@/lib/chartOptions'
import type { EquityPoint, FoldRow, GridRow, Objective, ParamRange, SegmentInfo, SpecJson } from '@/types/studio'

export const OBJECTIVES: { key: Objective; label: string; help: string }[] = [
  { key: 'sharpe', label: '샤프', help: '위험 한 단위당 수익 — 기본값' },
  { key: 'cagr', label: '연 환산 수익률', help: '수익만 본다(낙폭은 안 봄)' },
  { key: 'calmar', label: '칼마', help: '수익 ÷ 최대 낙폭' },
  { key: 'profit_factor', label: '손익비', help: '번 돈 ÷ 잃은 돈' },
  { key: 'expectancy', label: '거래당 기대값', help: '한 번 거래의 평균 수익률' },
]

/** 값이 작을수록 좋은 지표(서버 studio.domain.validation.LOWER_IS_BETTER 와 같은 뜻) — 사전 판정 기준의 방향을 화면에 미리 보여주는 용도 */
export const LOWER_IS_BETTER = new Set(['max_drawdown_pct', 'volatility_pct', 'mdd_duration_bars', 'max_consec_losses', 'turnover', 'commission_total', 'tax_total', 'slippage_total', 'avg_holding_bars'])
export const criteriaDirection = (metric: string): 'max' | 'min' => (LOWER_IS_BETTER.has(metric) ? 'max' : 'min')

const RESERVED = /^(status|selected|rank_is|chosen_folds|is_.*|oos_.*|full_.*)$/

/** 조합 표에서 변수 열 이름 — 성과 열(is_·oos_·full_)과 상태 열을 뺀 나머지 */
export const gridVariables = (rows: GridRow[]): string[] => (rows.length ? Object.keys(rows[0]).filter((k) => !RESERVED.test(k)) : [])

/** 실제로 값이 둘 이상 나온 변수만(고정된 변수는 축이 될 수 없다) */
export const varyingVariables = (rows: GridRow[]): string[] =>
  gridVariables(rows).filter((k) => new Set(rows.map((r) => r[k])).size > 1)

/** 훑을 수 있는 변수: min·max·step 이 다 있고 max > min (서버 grid_axes 규칙) */
export const rangeVariables = (params: Record<string, ParamRange>): string[] =>
  Object.entries(params).filter(([, r]) => r.min != null && r.max != null && r.step != null && r.step > 0 && r.max > r.min).map(([k]) => k)

export interface HeatCell { x: number; y: number; value: number; n: number; selected: boolean }
export interface HeatData { xs: number[]; ys: number[]; cells: HeatCell[]; folded: boolean }

/**
 * 조합 표 → 2변수 히트맵 자료. 변수가 셋 이상이면 나머지 변수는 "그 칸에서 가장 좋은 값"으로 접는다(folded=true 로 화면에 밝힌다).
 * 값이 없는 조합(무효·거래 부족)은 칸에서 빠진다 — 지어내지 않는다. 낮을수록 좋은 열(…_mdd_pct)은 min, 나머지는 max.
 */
export function heatmapData(rows: GridRow[], xVar: string, yVar: string, col: string): HeatData {
  const lower = /mdd|volatility/.test(col)
  const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
  const xs = [...new Set(rows.map((r) => r[xVar]).filter(num))].sort((a, b) => a - b)
  const ys = [...new Set(rows.map((r) => r[yVar]).filter(num))].sort((a, b) => a - b)
  const best = new Map<string, HeatCell>()
  for (const r of rows) {
    const x = r[xVar], y = r[yVar], v = r[col]
    if (!num(x) || !num(y) || !num(v)) continue
    const key = `${x}|${y}`
    const cur = best.get(key)
    const sel = r.selected === true
    if (!cur) best.set(key, { x: xs.indexOf(x), y: ys.indexOf(y), value: v, n: 1, selected: sel })
    else {
      cur.n += 1
      cur.selected = cur.selected || sel
      if (lower ? v < cur.value : v > cur.value) cur.value = v
    }
  }
  return { xs, ys, cells: [...best.values()], folded: rows.length > xs.length * ys.length }
}

export function heatmapOption(h: HeatData, xName: string, yName: string, valueLabel: string): EChartOption {
  const vals = h.cells.map((c) => c.value)
  const lim = Math.max(0.0001, ...vals.map((v) => Math.abs(v)))
  return {
    grid: { left: 64, right: 24, top: 16, bottom: 64 },
    tooltip: { formatter: (p: { data: { value: number[] } }) => `${xName} ${h.xs[p.data.value[0]]} · ${yName} ${h.ys[p.data.value[1]]}<br/>${valueLabel} ${p.data.value[2].toFixed(2)}${h.folded ? ` (다른 변수 ${p.data.value[3]}가지 중 최고)` : ''}` },
    xAxis: { type: 'category', name: xName, data: h.xs.map(String), splitArea: { show: true } },
    yAxis: { type: 'category', name: yName, data: h.ys.map(String), splitArea: { show: true } },
    visualMap: { min: -lim, max: lim, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: [DOWN, '#ffffff', UP] } },
    series: [{
      type: 'heatmap',
      data: h.cells.map((c) => ({ value: [c.x, c.y, +c.value.toFixed(3), c.n], ...(c.selected ? { itemStyle: { borderColor: '#000', borderWidth: 3 } } : {}) })),
      label: { show: true, formatter: (p: { data: { value: number[] } }) => p.data.value[2].toFixed(2) },
    }],
  }
}

// ───────────── 구간(학습 · 검증 · 홀드아웃)을 얹은 수익곡선 ─────────────
export interface Band { name: string; from: string; to: string; color: string }

export const segmentBands = (seg: { is: SegmentInfo; oos: SegmentInfo; holdout: SegmentInfo | null }): Band[] => [
  { name: '학습(IS)', from: seg.is[0], to: seg.is[1], color: '#8c8c8c22' },
  { name: '검증(OOS)', from: seg.oos[0], to: seg.oos[1], color: '#1677ff22' },
  ...(seg.holdout ? [{ name: '홀드아웃(잠김)', from: seg.holdout[0], to: seg.holdout[1], color: '#fa8c1622' }] : []),
]

/** 곡선의 날짜(카테고리) 중 [from, to] 안의 첫·끝 날짜 — 구간 경계가 거래일이 아니어도 그림이 깨지지 않게 */
function clampToAxis(days: string[], from: string, to: string): [string, string] | null {
  const a = days.find((d) => d >= from)
  const b = [...days].reverse().find((d) => d <= to)
  return a && b && a <= b ? [a, b] : null
}

export function withBands(option: EChartOption, eq: EquityPoint[], bands: Band[]): EChartOption {
  const days = eq.map((p) => p.ts.slice(0, 10))
  const areas = bands.flatMap((b) => {
    const r = clampToAxis(days, b.from, b.to)
    return r ? [[{ name: b.name, xAxis: r[0], itemStyle: { color: b.color }, label: { position: 'insideTop' } }, { xAxis: r[1] }]] : []
  })
  const o = option as { series: { markArea?: unknown }[] }
  const first = o.series[0]
  return { ...(option as object), series: [{ ...first, markArea: { silent: true, data: areas } }, ...o.series.slice(1)] } as EChartOption
}

// ───────────── 워크포워드 폴드 ─────────────
export function foldsOption(folds: FoldRow[], objective: string): EChartOption {
  const ok = folds.filter((f) => !f.skipped)
  return {
    grid: { left: 56, right: 16, top: 36, bottom: 32 },
    legend: { top: 4 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: ok.map((f) => `폴드 ${f.fold + 1}`) },
    yAxis: { type: 'value', name: objective },
    series: [
      { name: '학습 구간(IS)', type: 'bar', data: ok.map((f) => f.is_objective ?? null), color: '#8c8c8c' },
      { name: '검증 구간(OOS)', type: 'bar', data: ok.map((f) => f.oos_objective ?? null), color: SERIES_COLORS[0] },
    ],
  }
}

// ───────────── 화면 설정 → 요청 ─────────────
export interface ValidationForm {
  objective: Objective
  minTrades: number
  holdoutPct: number
  trainPct: number
  splitDate: string | null
  vary: string[] | null // null = 범위가 다 있는 변수 전부
  criteria: { metric: string; value: number | null }[]
  wf: { train: number; test: number; step: number | null; mode: 'rolling' | 'anchored' }
}

export const defaultForm = (): ValidationForm => ({
  objective: 'sharpe', minTrades: 30, holdoutPct: 20, trainPct: 70, splitDate: null, vary: null, criteria: [],
  wf: { train: 250, test: 60, step: null, mode: 'rolling' },
})

/** 명세에 검증 설정을 얹는다 — 목표·최소 거래·홀드아웃·사전 판정 기준은 spec.validation 에(실행 뒤 spec.json 으로 잠긴다) */
export function withValidation(spec: SpecJson, f: ValidationForm): SpecJson {
  const criteria: Record<string, number> = {}
  for (const c of f.criteria) if (c.metric && c.value !== null && Number.isFinite(c.value)) criteria[c.metric] = c.value
  return { ...spec, validation: { objective: f.objective, min_trades: f.minTrades, holdout_pct: f.holdoutPct, criteria } }
}

export function toConfig(f: ValidationForm) {
  return {
    train_pct: f.trainPct,
    ...(f.splitDate ? { split_date: f.splitDate } : {}),
    ...(f.vary ? { vary: f.vary } : {}),
  }
}

export const toWalkforward = (f: ValidationForm) => ({
  train_days: f.wf.train, test_days: f.wf.test, ...(f.wf.step ? { step_days: f.wf.step } : {}), mode: f.wf.mode,
})

/** 저장된 명세(spec.validation) → 폼 초기값 */
export function formFromSpec(spec: SpecJson): ValidationForm {
  const v = spec.validation
  const base = defaultForm()
  if (!v) return base
  return {
    ...base,
    objective: (v.objective as Objective | undefined) ?? base.objective,
    minTrades: v.min_trades ?? base.minTrades,
    holdoutPct: v.holdout_pct ?? base.holdoutPct,
    criteria: Object.entries(v.criteria ?? {}).map(([metric, value]) => ({ metric, value })),
  }
}
