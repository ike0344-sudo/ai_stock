// 스튜디오 화면 테스트 고정 값 — 카탈로그·프리셋·검증·미리보기·비교. 실제 결과(거래·곡선·지표)는 studioReal.ts(실제 응답 발췌).
import type { JobRow } from '@/types'
import type { BarsData, CompareData, IndicatorCatalog, LegacyStrategyDef, PresetRow, PreviewResult, RunRow, SpecJson, ValidateResult } from '@/types/studio'
import { realDetail } from './studioReal'

const p = (name: string, kind: 'int' | 'float' | 'bool' | 'enum', def: unknown, o: { lo?: number; hi?: number; choices?: string[]; label?: string } = {}) =>
  ({ name, kind, default: def, lo: o.lo ?? null, hi: o.hi ?? null, choices: o.choices ?? null, label: o.label ?? name })
const FIELDS = ['open', 'high', 'low', 'close', 'volume', 'value']
const DAILY = ['daily_single', 'daily_portfolio'] as const

export const catalog: IndicatorCatalog = {
  indicators: [
    { name: 'sma', label: '이동평균', desc: '단순 이동평균', params: [p('src', 'enum', 'close', { choices: FIELDS, label: '대상 값' }), p('n', 'int', 20, { lo: 1, hi: 500, label: '기간(봉)' })], modes: [...DAILY, 'intraday', 'tick'], timing: 't 포함', compute: true },
    { name: 'highest', label: 'N봉 최고값', desc: '직전 N봉 최고값', params: [p('src', 'enum', 'high', { choices: FIELDS, label: '대상 값' }), p('n', 'int', 20, { lo: 1, hi: 500, label: '기간(봉)' }), p('include_current', 'bool', false, { label: '오늘 포함' })], modes: [...DAILY, 'intraday', 'tick'], timing: '기본 t 제외', compute: true },
    { name: 'lowest', label: 'N봉 최저값', desc: '직전 N봉 최저값', params: [p('src', 'enum', 'low', { choices: FIELDS }), p('n', 'int', 10, { lo: 1, hi: 500, label: '기간(봉)' }), p('include_current', 'bool', false, { label: '오늘 포함' })], modes: [...DAILY, 'intraday', 'tick'], timing: '기본 t 제외', compute: true },
    { name: 'rsi', label: 'RSI', desc: 'RSI', params: [p('n', 'int', 14, { lo: 1, hi: 500, label: '기간(봉)' })], modes: [...DAILY, 'intraday', 'tick'], timing: 't 포함', compute: true },
    { name: 'value_rank', label: '거래대금 순위', desc: '순위', params: [p('lookback', 'int', 1, { lo: 1, hi: 60, label: '평균 일수' })], modes: [...DAILY], timing: 't 종가', compute: true },
    { name: 'vwap', label: 'VWAP', desc: '분봉 전용', params: [], modes: ['intraday'], timing: 't 까지', compute: true },
  ],
  fields: ['open', 'high', 'low', 'close', 'volume', 'value'],
  modes: ['daily_single', 'daily_portfolio', 'intraday', 'tick'],
  ops: ['gt', 'gte', 'lt', 'lte', 'cross_above', 'cross_below'],
  market: { indexes: ['kospi', 'kosdaq'], names: ['close', 'sma', 'change_pct'] },
  tick_catalog: { breakout_min: 'N분 고점 돌파' },
  n_range: [1, 500],
}

export const legacyDefs: LegacyStrategyDef[] = [
  { name: 'ma_crossover', label: '이동평균 크로스', deprecated: false, note: '', params: [
    { name: 'short_window', kind: 'int', default: 5, lo: 1, hi: 499, choices: null, label: '단기 이평(일)', optional: false },
    { name: 'long_window', kind: 'int', default: 20, lo: 2, hi: 500, choices: null, label: '장기 이평(일)', optional: false }] },
  { name: 'pullback_reentry', label: '눌림목 재돌파', deprecated: true, note: '가설 기각으로 폐기', params: [] },
]

export const presetRows: PresetRow[] = [
  { name: 'new_high_20', title: '20일 신고가 돌파 (시연용·미검증)', mode: 'daily_portfolio', period: { start: '2021-01-04', end: '2026-08-31' }, n_params: 3 },
  { name: 'golden_cross_5_20', title: '골든크로스', mode: 'daily_single', period: { start: '2021-01-04', end: '2026-08-31' }, n_params: 0 },
]

export const presetSpec: SpecJson = realDetail.spec // 실제 프리셋으로 돌린 결과의 명세(변수 3개 포함)

export const dataRanges = { daily: ['2019-04-23', '2026-09-23'], kospi: ['2021-07-26', '2026-09-23'], kosdaq: ['2021-07-26', '2026-09-23'] } as Record<string, [string, string]>

export const validOk: ValidateResult = { ok: true, errors: [], warnings: [], narration: '종가가 [n]일 최고가를 넘고 거래량이 거래량 20일 이동평균의 [vol_mult]배 이상이면 다음 날 시가에 산다.\n종가가 [exit_n]일 최저가 미만이면 다음 날 시가에 판다.' }
export const validBad: ValidateResult = {
  ok: false, narration: null, warnings: [{ path: 'period', loc: ['period'], dataset: 'daily', message: '일봉 데이터가 2019-04-23 부터라 그 이전 구간은 신호가 0건' }],
  errors: [{ path: 'strategy.entry.items.0.right', loc: ['strategy', 'entry', 'items', 0, 'right'], message: "없는 지표 'nope' (가능: ['rsi', 'sma'])" }],
}

export const previewOk: PreviewResult = {
  date: '2026-09-23', universe_size: 100, matched: 2, truncated: false,
  rows: [
    { code: '005930', name: '삼성전자', close: 71000, change_pct: 2.5, value: 9.5e11, value_rank: 1, operands: [{ text: '종가 > 20일 최고가', left: 71000, right: 70500 }] },
    { code: '000660', name: 'SK하이닉스', close: 180000, change_pct: -0.5, value: 4.1e11, value_rank: 3, operands: [{ text: '종가 > 20일 최고가', left: 180000, right: 179000 }] },
  ],
}

export const bars: BarsData = {
  code: '277810', name: '레인보우로보틱스', interval: '1d',
  bars: Array.from({ length: 240 }, (_, i) => {
    const d = new Date(Date.UTC(2024, 10, 1 + i)).toISOString().slice(0, 10)
    return { t: d, o: 100000 + i * 100, h: 102000 + i * 100, l: 98000 + i * 100, c: 101000 + i * 100, v: 100000 }
  }),
}

const row = (id: string, name: string, o: Partial<RunRow> = {}): RunRow => ({
  run_id: id, name, kind: 'backtest', mode: 'daily_portfolio', period: { start: '2025-01-02', end: '2025-08-29' }, compat: false, created_at: '2026-09-25T22:58:26',
  engine_version: '0.1.0', starred: false, memo: null, n_trades: 157, elapsed_sec: 5.6,
  metrics: { total_return_pct: 9.7, cagr_pct: 15.6, max_drawdown_pct: 29.3, sharpe: 0.57, num_trades: 157, win_rate_pct: 29.9, profit_factor: 1.08, expectancy_pct: 0.85 }, ...o,
})
export const RUN_A = '20260925-225818-9b9af3'
export const RUN_B = '20260925-231117-07cf4a'
export const runRows: RunRow[] = [
  row(RUN_B, '신고가 돌파 (손절 5%)', { created_at: '2026-09-25T23:11:17', starred: true, memo: '손절 강화', metrics: { total_return_pct: 14.2, cagr_pct: 23.5, max_drawdown_pct: 12.4, sharpe: 1.21, num_trades: 210, win_rate_pct: 30, profit_factor: 1.4, expectancy_pct: 0.5 } }),
  row(RUN_A, '20일 신고가 돌파 (시연용·미검증)'),
]

export const compareData: CompareData = {
  runs: [
    { ...runRows[1], metrics_all: { total_return_pct: 9.7, sharpe: 0.57, max_drawdown_pct: 29.3, num_trades: 157, profit_factor: 1.08 }, initial_capital: 1e7,
      equity: [{ ts: '2025-01-02T00:00:00', equity: 1e7, drawdown_pct: 0, rel: 100 }, { ts: '2025-01-03T00:00:00', equity: 1.01e7, drawdown_pct: 0, rel: 101 }] },
    { ...runRows[0], metrics_all: { total_return_pct: 14.2, sharpe: 1.21, max_drawdown_pct: 12.4, num_trades: 210, profit_factor: 1.4 }, initial_capital: 1e7,
      equity: [{ ts: '2025-01-02T00:00:00', equity: 1e7, drawdown_pct: 0, rel: 100 }, { ts: '2025-01-03T00:00:00', equity: 1.02e7, drawdown_pct: 0, rel: 102 }] },
  ],
  diffs: [{ run_id: RUN_B, vs: RUN_A, items: [{ path: 'exits.stop_loss_pct', label: '손절(%)', a: '7', b: '5', text: '손절(%): 7 → 5' }] }],
}

export const job = (o: Partial<JobRow> = {}): JobRow => ({
  job_id: '20260925-231117-aaaaaa', kind: 'backtest', group: 'compute', status: 'queued', scheduled_at: null, created_at: '2026-09-25T23:11:17', started_at: null,
  finished_at: null, run_id: RUN_B, lock: null, trigger: 'user', error: null, cancel_requested: false,
  progress: { pct: null, stage: null, message: null, eta_sec: null, paused: false, waiting_lock: null }, ...o,
})
