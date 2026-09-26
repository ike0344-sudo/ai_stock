// 조건 고르기 재료 — 분류 나무 · 검색 · 지원 여부(비활성+이유) · 시간 단위 선택지. 순수 함수(화면 밖에서 검사 가능).
// 지표 메타(분류·정의 식·예시·live)는 서버 카탈로그(c3)가 줄 때는 그것을, 아직 안 줄 때는 여기 자체 분류를 쓴다 — 서버가 주기 시작하면 저절로 넘어간다.
import type { Capabilities, IndicatorCatalog, IndicatorDef, Mode, MinuteSource } from '@/types/studio'

/** 설계서 studio-conditions §5.4 분류 나무 순서 */
export const CATEGORIES = ['가격·이평·신고가', '보조지표', '캔들', '거래량·거래대금·순위', '테마·업종·시장', '분봉 전용', '틱 전용', '포지션(청산만)', '내 수식'] as const
export const OTHER_CATEGORY = '기타'

/** 서버가 category 를 아직 안 줄 때 쓰는 임시 분류(현재 카탈로그 16종) */
const FALLBACK: Record<string, (typeof CATEGORIES)[number]> = {
  sma: '가격·이평·신고가', ema: '가격·이평·신고가', highest: '가격·이평·신고가', lowest: '가격·이평·신고가', change_pct: '가격·이평·신고가', gap_pct: '가격·이평·신고가',
  rsi: '보조지표', rsi_wilder: '보조지표', atr: '보조지표', bb_upper: '보조지표', bb_lower: '보조지표',
  vol_ratio: '거래량·거래대금·순위', value_rank: '거래량·거래대금·순위',
  day_change_pct: '분봉 전용', time: '분봉 전용', cum_value: '분봉 전용', vwap: '분봉 전용',
}

export const categoryOf = (d: IndicatorDef): string => d.category_ko ?? FALLBACK[d.name] ?? OTHER_CATEGORY

/** 분봉·틱은 지표를 분봉 기준으로 쓴다 — 카탈로그 modes 와 대조할 실제 모드 */
export const effectiveMode = (m: Mode): Mode => (m === 'tick' ? 'intraday' : m)

const MODE_KO: Record<string, string> = { daily_single: '일봉', daily_portfolio: '일봉', intraday: '분봉', tick: '틱' }
const modesKo = (modes: Mode[]): string => [...new Set(modes.map((m) => MODE_KO[m]))].join('·')

/** 이 모드에서 이 지표를 쓸 수 있나 — 못 쓰면 이유를 사람 말로 */
export function indicatorSupport(d: IndicatorDef, mode: Mode): { ok: boolean; reason: string | null } {
  if (!d.compute) return { ok: false, reason: '아직 계산하지 않는 지표(준비 중)' }
  if (!d.modes.includes(effectiveMode(mode))) return { ok: false, reason: `${modesKo(d.modes)} 조건에서만 쓸 수 있다` }
  return { ok: true, reason: null }
}

/** 검색: 이름·영문 이름·설명·분류·정의 식에서 찾는다(대소문자·공백 무시) */
export function matchesQuery(d: IndicatorDef, q: string): boolean {
  const n = q.trim().toLowerCase()
  if (!n) return true
  return [d.label, d.name, d.desc, categoryOf(d), d.definition ?? ''].some((s) => s.toLowerCase().includes(n))
}

export interface IndOption { value: string; label: string; def: IndicatorDef; disabled: boolean; reason: string | null }
export interface IndGroup { category: string; options: IndOption[] }

/** 분류 나무: 분류 순서대로, 안에서는 카탈로그 순서. 지원 안 되는 지표도 **숨기지 않고** 비활성+이유로 둔다. 검색어가 있으면 맞는 것만. */
export function indicatorTree(cat: IndicatorCatalog, mode: Mode, query = ''): IndGroup[] {
  const groups = new Map<string, IndOption[]>()
  for (const d of cat.indicators) {
    if (!matchesQuery(d, query)) continue
    const s = indicatorSupport(d, mode)
    const c = categoryOf(d)
    const list = groups.get(c) ?? []
    list.push({ value: d.name, label: d.label, def: d, disabled: !s.ok, reason: s.reason })
    groups.set(c, list)
  }
  const order = [...(cat.categories?.map((c) => c.label) ?? []), ...CATEGORIES, OTHER_CATEGORY] // 서버가 준 분류 순서가 먼저
  const keys = [...groups.keys()].sort((a, b) => (order.indexOf(a) === -1 ? 99 : order.indexOf(a)) - (order.indexOf(b) === -1 ? 99 : order.indexOf(b)))
  return keys.map((category) => ({ category, options: groups.get(category)! }))
}

// ───────────── 시간 단위 (c1) ─────────────
export const TF_LABEL: Record<string, string> = {
  bar: '이 봉', m1: '1분봉', m3: '3분봉', m5: '5분봉', m10: '10분봉', m15: '15분봉', m30: '30분봉', m60: '60분봉',
  daily_prev: '일봉(전일 확정)', daily_live: '일봉(장중 실시간)',
}
export const tfLabel = (tf: string | undefined): string => TF_LABEL[tf ?? 'bar'] ?? tf ?? '이 봉'

export interface TfOption { value: string; label: string; disabled: boolean; reason: string | null }

/**
 * 이 피연산자에 고를 수 있는 시간 단위. 분봉·틱 실행에서만 의미가 있다(일봉 실행은 "이 봉"뿐 — 선택기를 안 보인다).
 * - mN: 실행 봉 길이의 배수이면서 더 긴 것만(마감된 N분봉만 쓰는 규칙이 성립하는 경우)
 * - daily_live: 지표의 live 표시가 있어야 하고, 거래량 계열은 KRX 분봉에서만(통합 분봉+KRX 일봉을 섞으면 20~40% 부풀려진다)
 */
export function timeframeOptions(caps: Capabilities | undefined, def: IndicatorDef | undefined, mode: Mode, barMinutes: number, source: MinuteSource): TfOption[] {
  if (!caps?.timeframes || (mode !== 'intraday' && mode !== 'tick')) return []
  const has = (m: Mode) => !def || def.modes.includes(m)
  return caps.timeframes.map((value): TfOption => {
    const label = tfLabel(value)
    let reason: string | null = null
    if (value === 'bar') return { value, label, disabled: false, reason }
    const mN = /^m(\d+)$/.exec(value)
    if (mN) {
      const n = Number(mN[1])
      if (!has('intraday')) reason = '이 지표는 분봉에서 쓸 수 없다'
      else if (n <= barMinutes) reason = `실행 봉(${barMinutes}분)보다 긴 단위만 고를 수 있다`
      else if (n % barMinutes !== 0) reason = `실행 봉 ${barMinutes}분의 배수만 고를 수 있다`
    } else if (value === 'daily_prev') {
      if (!has('daily_portfolio')) reason = '이 지표는 일봉에서 쓸 수 없다'
    } else if (value === 'daily_live') {
      if (!has('daily_portfolio')) reason = '이 지표는 일봉에서 쓸 수 없다'
      else if (def && !def.live) reason = def.live_reason || (def.live === undefined ? '이 지표의 일봉 실시간 지원 여부를 서버가 알려 주지 않았다' : '이 지표는 일봉 실시간을 지원하지 않는다(전일 확정만)')
      else if (def && def.volume_based && source !== 'krx') reason = def.live_reason || '거래량 계열 일봉 실시간은 KRX 분봉에서만 — 통합 분봉과 KRX 일봉을 섞으면 20~40% 부풀려진다'
    }
    return { value, label, disabled: reason !== null, reason }
  })
}

// ───────────── 연산자 ─────────────
export const OP_LABEL: Record<string, string> = {
  gt: '초과 (>)', gte: '이상 (≥)', lt: '미만 (<)', lte: '이하 (≤)', cross_above: '위로 돌파 (↗)', cross_below: '아래로 돌파 (↘)',
  is_true: '참이면 (1)', is_false: '거짓이면 (0)',
  cross_above_within: '최근 N봉 안에 위로 돌파', cross_below_within: '최근 N봉 안에 아래로 돌파',
}
export const opLabel = (o: string): string => OP_LABEL[o] ?? o

/** 조건 연산자가 오른쪽 값을 안 받는가(참이면·거짓이면) / 최근 k봉 안 크로스인가 — 서버 ast.py 의 UNARY_OPS·WITHIN_OPS 와 같은 뜻 */
export const isUnaryOp = (o: string): boolean => o === 'is_true' || o === 'is_false'
export const isWithinOp = (o: string): boolean => o.endsWith('_within')
export const DEFAULT_WITHIN = 3

/** 단위가 억 원인 지표 — 이것과 비교하는 숫자 칸에 "억" 을 붙인다(예: ≥ 20 = 20억) */
export const EOK_INDICATORS = new Set(['value_eok', 'value_sum_eok'])

export const POS_LABEL: Record<string, string> = {
  return_pct: '매수가 대비 수익률(%)', bars_held: '보유 봉 수', minutes_held: '보유 시간(분)', max_return_pct: '보유 중 최고 수익률(%)',
  drawdown_pct: '보유 중 고점 대비 하락(%)', entry_price: '매수가',
}
