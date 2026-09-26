// 지표 카드 정의 — 이름은 쉬운 말, 설명은 한 줄, 판정은 verdicts.ts. 서버 summary.metrics 키와 같다(studio/domain/metrics.py).
import { DASH } from './format'

export type MetricGroup = '수익' | '위험' | '거래' | '비용'

export interface MetricDef {
  key: string
  label: string
  group: MetricGroup
  fmt: (v: number) => string
  help: string
}

const pct = (d = 2) => (v: number) => `${v.toFixed(d)}%`
const signedPct = (d = 2) => (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(d)}%`
const num = (d = 2) => (v: number) => v.toFixed(d)
const int = (v: number) => Math.round(v).toLocaleString('ko-KR')
const won = (v: number) => `${Math.round(v).toLocaleString('ko-KR')}원`

export const METRIC_DEFS: MetricDef[] = [
  { key: 'total_return_pct', label: '총수익률', group: '수익', fmt: signedPct(), help: '기간 동안 자산이 처음 대비 얼마나 늘었나(비용 뺀 뒤)' },
  { key: 'cagr_pct', label: '연 환산 수익률(CAGR)', group: '수익', fmt: signedPct(), help: '같은 속도로 1년 굴렸다면 연 몇 %인가' },
  { key: 'benchmark_return_pct', label: '코스피 수익률', group: '수익', fmt: signedPct(), help: '같은 기간 코스피 지수를 들고만 있었다면' },
  { key: 'excess_return_pct', label: '초과수익', group: '수익', fmt: signedPct(), help: '내 전략 수익 − 코스피 수익. 0 보다 커야 지수보다 나은 것' },
  { key: 'beta', label: '베타', group: '수익', fmt: num(), help: '코스피가 1% 움직일 때 내 자산이 평균 몇 % 움직이나' },
  { key: 'max_drawdown_pct', label: '최대 낙폭(MDD)', group: '위험', fmt: pct(), help: '고점에서 가장 크게 떨어진 폭 — 견딜 수 있는 수준인지 보세요' },
  { key: 'mdd_duration_bars', label: '가장 긴 물속 기간', group: '위험', fmt: (v) => `${int(v)}봉`, help: '전고점을 못 넘고 버틴 가장 긴 기간(봉 수)' },
  { key: 'volatility_pct', label: '변동성(연)', group: '위험', fmt: pct(), help: '수익이 얼마나 출렁이나(연 환산)' },
  { key: 'sharpe', label: '샤프', group: '위험', fmt: num(), help: '위험 한 단위당 수익. 클수록 좋다' },
  { key: 'sortino', label: '소르티노', group: '위험', fmt: num(), help: '샤프와 비슷하지만 떨어지는 쪽 위험만 본다' },
  { key: 'calmar', label: '칼마', group: '위험', fmt: num(), help: '연 수익률 ÷ 최대 낙폭' },
  { key: 'num_trades', label: '거래 수', group: '거래', fmt: int, help: '많을수록 결과를 믿을 만하다(30건 미만은 우연일 수 있음)' },
  { key: 'win_rate_pct', label: '승률', group: '거래', fmt: pct(1), help: '이익으로 끝난 거래 비율' },
  { key: 'profit_factor', label: '손익비(PF)', group: '거래', fmt: num(), help: '번 돈 합 ÷ 잃은 돈 합. 1 보다 커야 이득' },
  { key: 'avg_win_pct', label: '평균 이익', group: '거래', fmt: signedPct(), help: '이긴 거래의 평균 수익률' },
  { key: 'avg_loss_pct', label: '평균 손실', group: '거래', fmt: signedPct(), help: '진 거래의 평균 손실률' },
  { key: 'expectancy_pct', label: '거래당 기대값', group: '거래', fmt: signedPct(), help: '한 번 거래할 때 평균으로 남기는 수익률(비용 뺀 뒤)' },
  { key: 'max_consec_losses', label: '최대 연속 손실', group: '거래', fmt: (v) => `${int(v)}회`, help: '연달아 진 최다 횟수 — 멘탈 테스트' },
  { key: 'avg_holding_bars', label: '평균 보유 기간', group: '거래', fmt: (v) => `${v.toFixed(1)}봉`, help: '한 종목을 평균 몇 봉 들고 있었나' },
  { key: 'exposure_pct', label: '투자 비중(시간)', group: '거래', fmt: pct(1), help: '기간 중 주식을 들고 있던 날의 비율' },
  { key: 'turnover', label: '회전율', group: '거래', fmt: num(1), help: '평균 자산 대비 얼마나 사고팔았나(높을수록 비용이 커진다)' },
  { key: 'commission_total', label: '수수료 합계', group: '비용', fmt: won, help: '증권사 수수료로 나간 돈' },
  { key: 'tax_total', label: '세금 합계', group: '비용', fmt: won, help: '매도 세금으로 나간 돈' },
  { key: 'slippage_total', label: '슬리피지 합계', group: '비용', fmt: won, help: '체결가가 불리하게 밀린 만큼(가정값)' },
]

export const GROUPS: MetricGroup[] = ['수익', '위험', '거래', '비용']

export function fmtMetric(def: MetricDef, v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(v) ? DASH : def.fmt(v)
}

/** 기존 CLI(`backtesting.metrics.compute`) 기준 한 줄 — 호환 모드에서만 서버가 준다 */
export const LEGACY_LABELS: [string, string, (v: number) => string][] = [
  ['total_return_pct', '총수익률', signedPct()],
  ['cagr_pct', 'CAGR', signedPct()],
  ['win_rate_pct', '승률', pct(1)],
  ['max_drawdown_pct', 'MDD', pct()],
  ['sharpe_ratio', '샤프(거래 기준)', num()],
  ['num_trades', '거래 수', int],
]

export const fmtWon = won
export const fmtInt = int

/** 비교 화면에서 "최고" 강조 방향 — 높을수록/낮을수록 좋은 지표만. 거래 수·베타·회전율처럼 좋고 나쁨이 없는 건 강조하지 않는다. */
export const BEST_DIR: Record<string, 'high' | 'low'> = {
  total_return_pct: 'high', cagr_pct: 'high', excess_return_pct: 'high', sharpe: 'high', sortino: 'high', calmar: 'high',
  win_rate_pct: 'high', profit_factor: 'high', avg_win_pct: 'high', avg_loss_pct: 'high', expectancy_pct: 'high',
  max_drawdown_pct: 'low', volatility_pct: 'low', mdd_duration_bars: 'low', max_consec_losses: 'low',
  commission_total: 'low', tax_total: 'low', slippage_total: 'low',
}

/** 지표 하나에서 가장 좋은 값을 가진 칸의 인덱스들(동률이면 모두). 값이 null 인 칸은 빼고 본다. */
export function bestIndexes(key: string, values: (number | null | undefined)[]): number[] {
  const dir = BEST_DIR[key]
  const ok = values.map((v, i) => [v, i] as const).filter(([v]) => v !== null && v !== undefined && Number.isFinite(v))
  if (!dir || ok.length < 2) return []
  const best = dir === 'high' ? Math.max(...ok.map(([v]) => v as number)) : Math.min(...ok.map(([v]) => v as number))
  return ok.filter(([v]) => v === best).map(([, i]) => i)
}
