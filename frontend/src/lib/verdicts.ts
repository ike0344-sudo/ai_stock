// 지표 판정 기준 (설계서 §5.5) — 숫자에는 좋다/보통/나쁘다를 붙인다(사용자 원칙: 쉬운 말 + 판정).
// 색은 데이터 신선도 판정과 같은 3색이다. 기준이 없는 지표는 판정 없음(null) — 지어내지 않는다.

export type Verdict3 = 'good' | 'mid' | 'bad'

export const VERDICT3_COLOR: Record<Verdict3, string> = { good: '#52c41a', mid: '#fa8c16', bad: '#f5222d' }
export const VERDICT3_LABEL: Record<Verdict3, string> = { good: '좋음', mid: '보통', bad: '나쁨' }

type Rule = (v: number) => Verdict3

const atLeast = (good: number, mid: number): Rule => (v) => (v >= good ? 'good' : v >= mid ? 'mid' : 'bad')

/** 지표 키(서버 metrics 키) → 판정 규칙. §5.5 표 그대로. */
const RULES: Record<string, Rule> = {
  sharpe: atLeast(1.0, 0.5),
  sortino: atLeast(1.5, 0.75),
  max_drawdown_pct: (v) => (v <= 15 ? 'good' : v <= 30 ? 'mid' : 'bad'),
  calmar: atLeast(1.0, 0.3),
  profit_factor: atLeast(1.5, 1.0),
  expectancy_pct: (v) => (v > 0.3 ? 'good' : v > 0 ? 'mid' : 'bad'),
  excess_return_pct: (v) => (v > 0 ? 'good' : 'bad'), // 보통 구간 없음
  num_trades: atLeast(100, 30),
  wfe: atLeast(0.5, 0.3),
  neighbor_stability: atLeast(0.7, 0.5),
  breakeven_cost_mult: atLeast(2.0, 1.0),
}

export function verdictOf(key: string, value: number | null | undefined): Verdict3 | null {
  const rule = RULES[key]
  if (!rule || value === null || value === undefined || !Number.isFinite(value)) return null
  return rule(value)
}

/** 판정 기준을 사람 말로 (툴팁·범례용) */
export const RULE_TEXT: Record<string, string> = {
  sharpe: '좋음 ≥ 1.0 · 보통 0.5~1.0 · 나쁨 < 0.5',
  sortino: '좋음 ≥ 1.5 · 보통 0.75~1.5 · 나쁨 < 0.75',
  max_drawdown_pct: '좋음 ≤ 15% · 보통 15~30% · 나쁨 > 30%',
  calmar: '좋음 ≥ 1.0 · 보통 0.3~1.0 · 나쁨 < 0.3',
  profit_factor: '좋음 ≥ 1.5 · 보통 1.0~1.5 · 나쁨 < 1.0',
  expectancy_pct: '좋음 > 0.3% · 보통 0~0.3% · 나쁨 ≤ 0',
  excess_return_pct: '좋음 > 0 · 나쁨 ≤ 0',
  num_trades: '좋음 ≥ 100 · 보통 30~99 · 나쁨 < 30',
  wfe: '좋음 ≥ 0.5 · 보통 0.3~0.5 · 나쁨 < 0.3',
  neighbor_stability: '좋음 ≥ 0.7 · 보통 0.5~0.7 · 나쁨 < 0.5',
  breakeven_cost_mult: '좋음 ≥ 2.0 · 보통 1.0~2.0 · 나쁨 < 1.0',
}
