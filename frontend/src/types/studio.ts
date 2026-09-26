// 백테스트 스튜디오 API 타입 — 서버(studio/api/routes/*)와 같은 모양. 단일 출처: 설계서 §3.2(명세)·§4(API).
// 명세(SpecJson)는 서버 pydantic 이 최종 검증하고, 화면은 편집에 필요한 만큼만 타입을 둔다.

// ───────────── 명세 (Spec) ─────────────
export type ParamRef = { param: string }
export type Num = number | ParamRef
export const isParam = (v: unknown): v is ParamRef => typeof v === 'object' && v !== null && 'param' in v

export type FieldName = 'open' | 'high' | 'low' | 'close' | 'volume' | 'value'
// 서버가 새 연산자를 넣으면(N봉 이내 크로스·참이면 등) 목록에 그대로 나온다 — 화면 라벨이 없으면 이름 그대로 보인다
export type Op = 'gt' | 'gte' | 'lt' | 'lte' | 'cross_above' | 'cross_below' | (string & {})
export type ParamValue = ParamRef | boolean | number | string

// tf: 시간 단위(studio-conditions c1) — 없으면 실행 봉("bar"). 서버가 능력(capabilities.timeframes)을 알릴 때만 화면이 보낸다
export interface FieldOperand { kind: 'field'; name: FieldName; offset?: number; mul?: Num; tf?: string }
export interface IndOperand { kind: 'ind'; name: string; params?: Record<string, ParamValue>; offset?: number; mul?: Num; tf?: string }
export interface MarketOperand { kind: 'market'; index: 'kospi' | 'kosdaq'; name: 'close' | 'sma' | 'change_pct'; params?: Record<string, ParamValue> }
export interface ConstOperand { kind: 'const'; value: Num }
/** 포지션 값(청산 조건 전용, c2): return_pct·bars_held·minutes_held·max_return_pct·drawdown_pct·entry_price */
export interface PosOperand { kind: 'pos'; name: string }
export type Operand = FieldOperand | IndOperand | MarketOperand | ConstOperand | PosOperand

/** right 는 is_true·is_false 에선 없다. within 은 cross_*_within 의 "최근 k봉 안" (c1 확정) */
export interface Condition { left: Operand; op: Op; right?: Operand | null; hold?: number; within?: number }
/** formula: 수식으로 만든 그룹의 원문(평가엔 안 쓰임, 재현·표시용) */
export interface Group { logic: 'all' | 'any'; items: (Condition | Group)[]; negate?: boolean; formula?: string | null }
export const isGroup = (i: Condition | Group): i is Group => 'logic' in i

export type Mode = 'daily_single' | 'daily_portfolio' | 'intraday' | 'tick'
export type LegacyValue = ParamRef | boolean | number | string | null

export type StrategySpec =
  | { source: 'builder'; entry: Group; exit: Group }
  | { source: 'legacy'; name: string; params: Record<string, LegacyValue> }

export interface ParamRange { default: number; min?: number | null; max?: number | null; step?: number | null }

export interface SpecJson {
  version: 1
  name: string
  mode: Mode
  period: { start: string; end: string }
  universe: {
    type: 'all' | 'top_value' | 'codes'
    n: number
    lookback_days: number
    markets: ('거래소' | '코스닥')[]
    exclude: ('spac' | 'preferred' | 'mega_cap')[]
    codes: string[]
  }
  strategy: StrategySpec | null
  market_filter: Group | null
  exits: ExitsCfg
  portfolio: {
    initial_capital: number
    max_positions: Num
    sizing: 'equal_slot_fixed' | 'equal_slot_compound' | 'fixed_amount' | 'risk_pct'
    fixed_amount?: Num | null
    risk_pct?: Num | null
    max_weight_pct: Num
    rank_by: 'value' | 'change_pct' | 'random'
    random_seed: number
  }
  costs: {
    commission_rate: number
    tax_rate: number
    slippage_mode: 'rate' | 'ticks' | 'max_rate_tick'
    slippage_rate: number
    slippage_ticks: number
  }
  fills: { same_bar_policy: 'stop_first' | 'target_first'; volume_cap_pct: number | null }
  intraday?: IntradayCfg | null
  tick?: TickCfg | null
  compat: { legacy: boolean }
  params: Record<string, ParamRange>
  validation: { holdout_pct?: number; objective?: string; min_trades?: number; criteria?: Record<string, number> } | null
}

// ───────────── 카탈로그 ─────────────
export interface CatalogParam { name: string; kind: 'int' | 'float' | 'bool' | 'enum'; default: unknown; lo: number | null; hi: number | null; choices: string[] | null; label: string }
/** category(키)·category_ko·definition·example·live·volume_based 는 서버 카탈로그(c1 확정 칸)가 줄 때만 있다 — 없으면 화면이 자체 분류·"알려 주지 않음"으로 메운다 */
export interface IndicatorDef { name: string; label: string; desc: string; params: CatalogParam[]; modes: Mode[]; timing: string; compute: boolean; category?: string; category_ko?: string; definition?: string; example?: string; live?: boolean; live_reason?: string; volume_based?: boolean }
/** 서버가 지금 이해하는 것 — 모델을 들여다본 결과(studio/application/capabilities.py). 화면은 여기 있는 칸만 보낸다 */
export interface Capabilities { timeframes: string[] | null; condition_fields: string[]; group_fields: string[]; operand_kinds: string[]; pos_names: string[]; exit_fields: string[]; tick_fields?: string[]; tick_catalog_fields?: string[]; formulas: boolean }
export interface IndicatorCatalog {
  indicators: IndicatorDef[]
  fields: FieldName[]
  modes: Mode[]
  ops: Op[]
  market: { indexes: ('kospi' | 'kosdaq')[]; names: ('close' | 'sma' | 'change_pct')[] }
  tick_catalog: Record<string, string>
  n_range: [number, number]
  capabilities?: Capabilities
  categories?: { key: string; label: string }[]
}
export interface LegacyParamDef { name: string; kind: 'int' | 'float' | 'enum'; default: unknown; lo: number | null; hi: number | null; choices: string[] | null; label: string; optional: boolean }
export interface LegacyStrategyDef { name: string; label: string; deprecated: boolean; note: string; params: LegacyParamDef[] }
export type DataRanges = Record<string, [string, string]>

export interface StockHit { code: string; name: string | null; sector: string | null; market: string | null }
export interface Bar { t: string; o: number; h: number; l: number; c: number; v: number }
export interface BarsData { code: string; name: string | null; interval: string; bars: Bar[] }

// ───────────── 검증·미리보기·프리셋 ─────────────
export interface ValidationIssue { path: string; loc: (string | number)[]; message: string; dataset?: string }
export interface ValidateResult { ok: boolean; errors: ValidationIssue[]; warnings: ValidationIssue[]; narration: string | null }
export interface PreviewOperand { text: string; left: number | null; right: number | null }
export interface PreviewRow { code: string; name: string | null; close: number; change_pct: number | null; value: number; value_rank: number | null; operands?: PreviewOperand[] }
export interface PreviewResult { date: string; universe_size: number; matched: number; rows: PreviewRow[]; truncated: boolean }
export interface PresetRow { name: string; title: string | null; mode: Mode | null; period: { start: string; end: string } | null; n_params: number }

// ───────────── 실행 기록·결과 ─────────────
export type MetricMap = Record<string, number | null>
/** summary.metrics — 숫자 지표 + skipped(체결 건너뜀 사유별 건수) 같은 묶음 하나가 섞여 있다 */
export type FullMetrics = Record<string, number | null | Record<string, number>>
/** 숫자 지표 하나를 꺼낸다(숫자가 아니면 null) */
export const mv = (m: FullMetrics | undefined, key: string): number | null => { const v = m?.[key]; return typeof v === 'number' ? v : null }
export interface RunRow {
  run_id: string
  name: string | null
  kind: string
  mode: Mode | null
  period: { start: string; end: string } | null
  compat: boolean
  created_at: string | null
  engine_version: string | null
  starred: boolean
  memo: string | null
  metrics: MetricMap
  n_trades: number | null
  elapsed_sec: number | null
}
export interface PeriodReturn { period: string; return_pct: number }
export interface GroupPerf { key: string; n: number; win_rate_pct: number; net_pnl: number; avg_net_pct: number }
export interface Analysis {
  monthly: PeriodReturn[]
  yearly: PeriodReturn[]
  exit_reasons: { reason: string; n: number; share_pct: number; avg_net_pct: number }[]
  by_sector: GroupPerf[]
  by_theme_group: GroupPerf[] | null
  histogram: { edges: number[]; counts: number[] }
  error?: string
}
export interface CostRow { mult: number; net_pnl: number; net_return_pct: number }
export interface ConcentrationRow { k: number; removed: string[]; removed_pnl?: number; net_pnl_excluding: number; sign_flipped: boolean }
export interface Robustness {
  n_trades?: number
  cost_sensitivity: CostRow[] | null
  breakeven_cost_mult: number | null
  cost_sensitivity_meta?: { gross_before_costs: number; total_costs: number; approximation: string }
  monte_carlo: null | {
    n_sims: number; seed: number; n_trades: number; weight: number; approximation?: string
    final_return_pct: { p5: number; p50: number; p95: number }
    max_drawdown_pct: { p5: number; p50: number; p95: number }
    prob_mdd_gt_30?: number
  }
  concentration: null | { total_net_pnl?: number; by_code: ConcentrationRow[]; by_date: ConcentrationRow[] }
}
export interface CriteriaRow { metric: string; threshold: number; direction?: string; value: number | null; passed: boolean; note?: string | null }
export interface RunSummary {
  metrics: FullMetrics
  legacy_metrics: Record<string, number | null> | null
  skipped: Record<string, number>
  n_trades: number
  n_closed: number
  n_codes: number
  n_bars: number
  universe_excluded?: Record<string, number>
  warnings: string[]
  robustness: Robustness | null
  criteria: CriteriaRow[]
  [k: string]: unknown
}
export interface RunMeta {
  run_id: string
  name?: string
  memo?: string | null
  starred?: boolean
  mode: Mode
  compat: boolean
  spec_hash: string
  structure_hash?: string
  warmup_bars?: number
  engine_version: string
  git?: { commit?: string; dirty?: boolean } | null
  created_at: string
  elapsed_sec: number
  period_used: [string, string]
  data: Record<string, [string, string]>
  params: Record<string, number>
  warnings: string[]
  kind?: string
  minute_source?: MinuteSource
  bar_minutes?: number
  entry_source?: string
}
export interface RunDetail {
  run_id: string
  meta: RunMeta
  spec: SpecJson
  summary: RunSummary
  warnings: string[]
  analysis: Analysis
  narration: string | null
  /** 결과 화면에 나오는 모든 종목코드 → 종목명(서버 종목 마스터). 이름을 모르는 코드는 빠진다 */
  names?: Record<string, string>
  has_grid: boolean
  has_folds: boolean
}
export interface Trade {
  code: string
  name: string | null
  sector: string | null
  entry_ts: string
  entry_price: number
  exit_ts: string | null
  exit_price: number | null
  qty: number
  gross_pnl: number | null
  commission: number
  tax: number
  slippage_cost: number
  net_pnl: number | null
  net_pct: number | null
  exit_reason: string | null
  bars_held: number
  mfe_pct?: number | null
  mae_pct?: number | null
  // 틱 정밀화(모드 A) 실행에만 있는 열 — 봉 기준가 대 틱 기준가(SC-7 "매매별 체결가 차이")
  entry_ref_bar?: number | null
  entry_ref_tick?: number | null
  entry_diff_pct?: number | null
  exit_ref_bar?: number | null
  exit_ref_tick?: number | null
  exit_diff_pct?: number | null
  net_pnl_tick?: number | null
  net_pct_tick?: number | null
  tick_refined?: boolean | null
  // 분할 익절(c2)이면 진입 한 건이 조각 행 여럿 — 같은 entry_id 가 진입 한 건, slice 는 1부터
  entry_id?: number | null
  slice?: number | null
}
export interface EquityPoint {
  ts: string
  equity: number
  drawdown_pct: number
  cash?: number | null
  positions_value?: number | null
  n_positions?: number | null
  benchmark_kospi?: number | null
  benchmark_kosdaq?: number | null
  rel?: number
}
export interface SpecDiffItem { path: string; label: string; a: string; b: string; text: string }
export interface CompareRun extends RunRow { metrics_all: FullMetrics; equity: EquityPoint[]; initial_capital: number }
export interface CompareData { runs: CompareRun[]; diffs: { run_id: string; vs: string; items: SpecDiffItem[] }[] }


// ───────────── 검증 (module-5): 최적화 · 워크포워드 · 홀드아웃 ─────────────
export type Objective = 'sharpe' | 'cagr' | 'calmar' | 'profit_factor' | 'expectancy'
export interface GridInfo { n: number; limit: number; warn_over: number; axes: Record<string, number>; too_large: boolean; warn: boolean }
/** 조합 표 한 행: 변수 열 + status + is_/oos_ 열 + rank_is + selected (워크포워드는 full_*·chosen_folds) */
export type GridRow = Record<string, number | string | boolean | null>
export type SegmentInfo = [string, string, number] // 시작·끝·거래일 수
export interface SegmentMetrics { params: Record<string, number>; is: FullMetrics; oos: FullMetrics; is_objective: number | null; oos_objective: number | null; selected_by: string }
export interface OptimizeSummary {
  objective: Objective
  min_trades: number
  n_combos: number
  n_valid: number
  n_invalid: number
  segments: { is: SegmentInfo; oos: SegmentInfo; holdout: SegmentInfo | null }
  selected: SegmentMetrics
  neighbor_stability: { ratio: number | null; median: number | null; best: number | null; n_neighbors: number; n_invalid: number; warn: boolean; reason?: string }
  criteria_on_oos: CriteriaRow[]
  selection_note?: string
}
export interface FoldRow {
  fold: number
  train: [string, string]
  test: [string, string]
  params?: Record<string, number>
  is?: FullMetrics
  oos?: FullMetrics
  is_objective?: number | null
  oos_objective?: number | null
  skipped?: string
}
export interface FoldsFile { config: { train_days: number; test_days: number; step_days: number; mode: 'rolling' | 'anchored' }; folds: FoldRow[] }
export interface WalkforwardSummary {
  objective: Objective
  min_trades: number
  n_folds: number
  n_validated: number
  positive_folds: number
  wfe: number | null
  oos_metrics?: FullMetrics
  params_drift: Record<string, { values: number[]; n_distinct: number; min: number; max: number }>
  n_combos: number
  holdout: [string, string] | null
  note?: string
}
export interface HoldoutOpen { opened_at: string; open_id?: string; run_id?: string | null; family_hash: string; structure_hash?: string; period?: [string, string, number?]; params?: Record<string, number>; source_run_id?: string | null }
export interface HoldoutSummary {
  period: SegmentInfo
  nth_open: number
  nth_open_structure?: number
  previous_opens: HoldoutOpen[]
  params: Record<string, number>
  source_run_id?: string | null
  structure_hash?: string
  family_hash?: string
  note?: string
}
export interface HoldoutHistory { family_hash: string; opens: HoldoutOpen[]; count: number; ledger_connected: boolean }
/** 서버로 보내는 최적화 설정 — 목표·최소 거래·홀드아웃·사전 판정 기준은 spec.validation 에, 나머지는 config 에 둔다 */
export interface ValidationConfig { train_pct?: number; split_date?: string; vary?: string[] }
export interface WalkforwardConfig { train_days: number; test_days: number; step_days?: number; mode: 'rolling' | 'anchored' }


// ───────────── 분봉·틱 (module-6) ─────────────
export type MinuteSource = 'al' | 'krx'
export const BAR_MINUTES = [1, 3, 5, 10, 15, 30, 60] as const
export interface IntradayCfg { bar_minutes: (typeof BAR_MINUTES)[number]; source: MinuteSource; prefilter: Group | null; prefilter_top_value: number; eod_time: string }
export interface TickCatalogCfg {
  breakout_min: number | null
  value_speed: { w: number; ratio: number } | null
  buy_ratio: { w: number; min: number } | null
  // 아래 넷은 서버가 capabilities.tick_catalog_fields 로 알릴 때만 화면이 보낸다(없으면 undefined = 칸 없음)
  trade_strength?: { w: number; min: number } | null // w 초, min 체결강도(%)
  block_trades?: { w: number; min_value: number; min_count: number } | null // w 초, 1건 최소 체결대금(원)
  daily_breakout?: { n: number } | null // 전일까지 n일 최고가 돌파
  value_window?: { w: number; min_eok: number } | null // 최근 w분 체결대금 합 ≥ min_eok 억
  time_from: string
  time_to: string
}
export interface TickCfg {
  entry_source: 'catalog' | 'minute_refine'; catalog: TickCatalogCfg; cooldown_sec: number; exclude_gap_open_pct: number | null; time_stop_sec: number | null; eod_time: string
  /** c8 — 틱 조건과 AND 로 묶는 분봉(1분봉 기준)·일봉 조건, 그리고 그 날 틱을 볼지 정하는 일봉 사전 필터(D−1). catalog 진입에서만. 서버가 capabilities.tick_fields 로 알릴 때만 보낸다 */
  filter?: Group | null
  prefilter?: Group | null
}
/** GET /api/meta/intraday-sources — 기간을 출처별로 몇 종목이 덮는가 */
export interface IntradaySources {
  minute: Record<MinuteSource, { total: number; full: number; partial: number; range: [string, string] | null }>
  tick: { codes: number; days: number; first: string | null; last: string | null; days_in_range: number }
}
export interface IntradaySummary {
  expected_pairs: number; used_pairs: number; pairs_share: number | null
  days_with_bars: number; days_in_period: number
  codes_requested: number; codes_with_minutes: number; codes_without_minutes: string[]
  warmup_days: number; bar_minutes: number; minute_source: MinuteSource
  code_periods?: Record<string, [string, string]>
}
export interface TickSummary {
  expected_pairs: number; used_pairs: number; days: number; codes: number; signals: number
  gap_open_days_skipped: number; signals_without_entry_tick: number; eod_time: string
  filter_pairs_without_minutes?: number; prefilter_pairs_skipped?: number
}
export interface DiffStats { mean: number | null; median: number | null; p5: number | null; p95: number | null; n: number }
export interface TickRefineSummary {
  n_trades: number; n_refined: number; n_without_ticks: number; n_no_matching_tick: number
  entry_diff_pct: DiffStats; exit_diff_pct: DiffStats
  net_pnl_bar: number | null; net_pnl_tick: number | null; definition: string
}


// ───────────── 청산 규칙 확장 (c2) · 레시피 (c6) ─────────────
export interface TakeProfitLevel { pct: number; fraction: number }
export interface ExitsCfg {
  stop_loss_pct?: Num | null
  take_profit_pct?: Num | null
  trailing_stop_pct?: Num | null
  max_holding_bars?: Num | null
  // 아래는 서버가 능력(capabilities.exit_fields)으로 알릴 때만 화면이 보낸다
  take_profit_levels?: TakeProfitLevel[] | null
  take_profit_mode?: 'intrabar' | 'close' | null
  trail_activate_pct?: Num | null
  breakeven_after_pct?: Num | null
  max_holding_minutes?: Num | null
}
export interface Recipe {
  id: string
  category: string
  title: string
  description: string
  modes: Mode[]
  needs: string[]
  entry: Group
  exit: Group
  params?: Record<string, ParamRange>
  exits?: ExitsCfg
  /** 틱 레시피(modes 가 ["tick"])는 조건 행이 아니라 틱 탭 칸을 채운다 — 틱 설정 조각 */
  tick?: Omit<Partial<TickCfg>, 'catalog'> & { catalog?: Partial<TickCatalogCfg> }
  available: boolean
  unavailable_reason: string | null
}

// ── 조건 템플릿(문장 빈칸 채우기, 설계서 §5.5) — 서버 studio/api/routes/templates.py
export interface TplChoice { value: string; label: string; enabled: boolean; reason: string | null }
export type TplSlot =
  | { name: string; kind: 'number'; label: string; default: number; unit?: string; lo?: number; hi?: number; integer?: boolean }
  | { name: string; kind: 'tf' | 'choice'; label: string; default: string; choices: TplChoice[] }
export interface CondTemplate {
  id: string; category: string; category_label: string
  /** 빈칸 자리표시 문장 — `{x}억 {cmp}` 처럼 슬롯 이름이 중괄호 안, `{봉}` 은 일/봉으로 바꿔 보이는 자리 */
  sentence: string
  /** 기본값을 채운 완성 문장 */
  example: string
  hint: string; warn: string; tags: string[]
  role: 'entry' | 'exit' | 'both'
  available: boolean; reason: string
  /** true = 카탈로그로 자동 만든 기본 문장(손문장보다 딱딱하다) — 카드에 "기본 문장" 표시 */
  auto?: boolean
  slots: TplSlot[]
}
export interface CondTemplates { mode: Mode; bar_minutes: number; source: string; categories: { key: string; label: string }[]; templates: CondTemplate[] }
export type TplValues = Record<string, number | string>
export interface TplBuilt { condition: Condition; sentence: string; values: TplValues }
export interface TplMatch { id: string; category: string; values: TplValues; sentence: string }
