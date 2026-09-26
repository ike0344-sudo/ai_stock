// 조건의 단위 — 왼쪽이 가격이 아닌 값(거래대금·거래량·등락률(%)·RSI·순위·연속 봉 수·1/0 지표…)인데 오른쪽이 가격 지표면 비교가 안 맞는다.
// 그때 오른쪽을 단위가 붙은 숫자 입력칸으로 바꿔 주고(알맞은 기본값), 단위가 다른 비교는 경고한다. 서버 카탈로그엔 단위 정보가 없어 이름으로 분류한다(모르는 것은 건드리지 않는다).
import { isUnaryOp } from '@/lib/conditionMeta'
import type { Condition, Group, Operand, SpecJson } from '@/types/studio'

/** price 가격 · eok/won 금액 · shares 수량 · pct 퍼센트 · rank 순위 · count 봉/분/회 수 · ratio 배수 · flag 1/0 · plain 단위 없는 점수(RSI 등) */
export type Unit = 'price' | 'eok' | 'won' | 'shares' | 'pct' | 'rank' | 'count' | 'ratio' | 'flag' | 'plain'
export const UNIT_LABEL: Record<Unit, string> = { price: '원(가격)', eok: '억', won: '원', shares: '주', pct: '%', rank: '순위', count: '횟수', ratio: '배수', flag: '1/0', plain: '점수' }
/** 단위 이름 하나로 정해지는 숫자 칸 옆 표시 — 가격 단위는 붙이지 않는다(가격 옆 숫자는 다른 뜻일 수 있다). 횟수는 지표마다 봉·분·회로 다르다(META 의 suffix) */
export const SUFFIX: Partial<Record<Unit, string>> = { eok: '억', won: '원', shares: '주', pct: '%', rank: '위', ratio: '배' }
const HARD: Unit[] = ['price', 'eok', 'won', 'shares'] // 이 단위가 끼어 있고 서로 다르면 확실히 안 맞는 비교

interface Meta { unit: Unit; def: number | null; suffix?: string }
const m = (unit: Unit, def: number | null, suffix?: string): Meta => ({ unit, def, suffix })

const PRICE_INDS = new Set(['sma', 'ema', 'wma', 'vwma', 'highest', 'lowest', 'vwap', 'bb_upper', 'bb_lower', 'envelope_upper', 'envelope_lower', 'keltner_upper', 'keltner_lower', 'psar',
  'ichimoku_conv', 'ichimoku_base', 'ichimoku_span_a', 'ichimoku_span_b', 'ichimoku_cloud_top', 'ichimoku_cloud_bottom'])
const FLAGS = ['ma_aligned', 'ma_reversed', 'new_high', 'new_low', 'limit_up_hit', 'prev_high_break', 'long_bull', 'long_bear', 'doji', 'hammer', 'inverted_hammer', 'bull_engulfing', 'bear_engulfing',
  'inside_bar', 'outside_bar', 'gap_held', 'gap_filled', 'day_high_break', 'day_low_break']
const IND_META: Record<string, Meta> = {
  value_eok: m('eok', 20), value_sum_eok: m('eok', 60), cum_value: m('won', 1_000_000_000), first_n_value: m('won', 1_000_000_000),
  // 퍼센트 — 기본값은 "그럴듯한 첫 문턱"(고쳐 쓴다)
  change_pct: m('pct', 1), gap_pct: m('pct', 1), day_change_pct: m('pct', 1), open_change_pct: m('pct', 1), ma_slope: m('pct', 0), ma_disparity: m('pct', 105), vwap_disparity: m('pct', 1),
  high52_pct: m('pct', -10), low52_pct: m('pct', 30), box_pct: m('pct', 10), body_pct: m('pct', 3), range_pct: m('pct', 3), atr_pct: m('pct', 3), volatility: m('pct', 3), bb_width: m('pct', 10),
  roc: m('pct', 5), psy: m('pct', 50), vr: m('pct', 100), vol_change_pct: m('pct', 200), limit_up_pct: m('pct', 5), theme_change: m('pct', 1), sector_change: m('pct', 1),
  // 순위
  value_rank: m('rank', 20), volume_rank: m('rank', 20), cum_value_rank: m('rank', 20), theme_rank: m('rank', 5), sector_rank: m('rank', 5), rank_in_theme: m('rank', 3),
  // 봉·분·회 수
  bars_since_high: m('count', 5, '봉'), up_streak: m('count', 3, '봉'), down_streak: m('count', 3, '봉'), minutes_since_open: m('count', 30, '분'), top_value_count: m('count', 1, '회'), theme_top_count: m('count', 1, '개'),
  // 배수
  vol_ratio: m('ratio', 3), value_ratio: m('ratio', 3),
  // 단위 없는 점수·지수
  rsi: m('plain', 30), rsi_wilder: m('plain', 30), rsi_signal: m('plain', 30), stoch_k: m('plain', 20), stoch_d: m('plain', 20), mfi: m('plain', 20), williams_r: m('plain', -80), adx: m('plain', 25),
  plus_di: m('plain', 20), minus_di: m('plain', 20), cci: m('plain', 100), macd: m('plain', 0), macd_signal: m('plain', 0), macd_hist: m('plain', 0), momentum: m('plain', 0), obv: m('plain', 0), obv_signal: m('plain', 0),
  atr: m('plain', null), bb_pctb: m('plain', 0.8), upper_wick_ratio: m('plain', 0.5), lower_wick_ratio: m('plain', 0.5), time: m('plain', 930),
  ...Object.fromEntries(FLAGS.map((n) => [n, m('flag', 1)])),
  ...Object.fromEntries([...PRICE_INDS].map((n) => [n, m('price', null)])),
}
const FIELD_META: Record<string, Meta> = { volume: m('shares', null), value: m('won', 1_000_000_000) }

function metaOf(op: Operand | null | undefined): Meta | null {
  if (!op) return null
  if (op.kind === 'field') return FIELD_META[op.name] ?? m('price', null)
  if (op.kind === 'ind') return IND_META[op.name] ?? null
  return null
}

/** 피연산자의 단위. 모르면(산술·포지션·테마 대금 등) null — 모르는 것은 경고도 자동 전환도 하지 않는다 */
export const operandUnit = (op: Operand | null | undefined): Unit | null => metaOf(op)?.unit ?? null
/** 숫자 칸 옆에 붙일 단위 글자(없으면 undefined) */
export function operandSuffix(op: Operand | null | undefined): string | undefined {
  const x = metaOf(op)
  return x ? x.suffix ?? SUFFIX[x.unit] : undefined
}

const DEFAULT_RIGHT: Operand = { kind: 'ind', name: 'highest', params: { src: 'high', n: 20 } }
const isPriceish = (u: Unit | null) => u === 'price' || u === null

/**
 * 왼쪽을 바꾼 결과의 오른쪽·연산자 정리.
 * - 왼쪽이 가격이 아닌 단위이고 오른쪽이 가격 지표·필드(또는 모르는 값)면 → 오른쪽을 그 지표에 맞는 기본값 숫자로(억 20 · 등락률 1 · RSI 30 · 순위 20 …). 1/0 지표는 "참이면"(is_true).
 * - 우리가 자동으로 바꿔 둔 것(auto)만: 왼쪽이 가격 계열로 돌아오면 원래 기본값(N봉 최고값, 연산자 초과)으로, 다른 비가격 지표로 바뀌면 그 지표의 기본값으로.
 * - 사용자가 오른쪽을 직접 골랐으면(picked) 아무것도 안 건드린다.
 */
export function harmonizeRight(next: Condition, prevLeft: Operand, state: { picked: boolean; auto: boolean }): { cond: Condition; auto: boolean; switched: boolean } {
  if (state.picked) return { cond: next, auto: state.auto, switched: false }
  const lm = metaOf(next.left)
  const lu = lm?.unit ?? null
  let cond = next
  let auto = state.auto
  // 1) 자동으로 바꿨던 것을 되돌린다 — 1/0 "참이면" 이었는데 1/0 이 아니게 되면 연산자를 초과로
  if (auto && isUnaryOp(cond.op) && lu !== 'flag') { cond = { ...cond, op: 'gt', right: cond.right ?? structuredClone(DEFAULT_RIGHT) }; auto = false }
  // 2) 왼쪽이 1/0 지표 → "참이면"
  if (lu === 'flag') {
    if (isUnaryOp(cond.op)) return { cond, auto, switched: false }
    const { right: _r, within: _w, ...rest } = cond; void _r; void _w
    return { cond: { ...rest, op: 'is_true' }, auto: true, switched: true }
  }
  if (!cond.right) return { cond, auto, switched: false }
  const ru = operandUnit(cond.right)
  // 3) 가격이 아닌 왼쪽 + 안 맞는 오른쪽(가격·모름) → 숫자 기본값. 이미 우리가 넣은 숫자면 왼쪽 지표가 달라졌을 때만 새 기본값으로
  if (lm && lu !== 'price') {
    const changedKind = auto && cond.right.kind === 'const' && metaOf(prevLeft) !== lm
    if ((cond.right.kind !== 'const' && ru !== lu && isPriceish(ru)) || changedKind) return { cond: { ...cond, right: { kind: 'const', value: lm.def as number } }, auto: true, switched: true }
    return { cond, auto, switched: false }
  }
  // 4) 가격 계열(또는 모름)로 돌아옴 → 자동으로 넣었던 숫자만 원래 기본값으로
  if (auto && cond.right.kind === 'const' && isPriceish(lu) && operandUnit(prevLeft) !== lu) {
    return { cond: { ...cond, right: structuredClone(DEFAULT_RIGHT) }, auto: false, switched: false }
  }
  return { cond, auto, switched: false }
}

/** 양쪽 단위가 모두 알려졌고 확실히 안 맞으면 경고 문구(가격 vs 거래대금, 가격 vs 등락률 등). 상수는 단위가 없어 통과. 점수·퍼센트·순위끼리는 섞어도 경고하지 않는다(뜻이 넓다) */
export function unitMismatch(c: Condition): string | null {
  const a = operandUnit(c.left)
  const b = c.right && !isUnaryOp(c.op) ? operandUnit(c.right) : null
  if (!a || !b || a === b || !(HARD.includes(a) || HARD.includes(b))) return null
  const sfx = operandSuffix(c.left) ?? '값'
  return `단위가 다른 값을 비교하고 있다 — 왼쪽은 ${UNIT_LABEL[a]}, 오른쪽은 ${UNIT_LABEL[b]}. 오른쪽을 "숫자" 로 바꿔 ${sfx} 단위로 입력하세요`
}

const conditionsOf = (g: Group | null | undefined): Condition[] =>
  (g?.items ?? []).flatMap((i) => ('logic' in i ? conditionsOf(i) : [i]))

/** 명세 전체의 단위 경고 — 검증 패널 위에 모아 보인다. 조건 행에도 같은 문구가 붙는다 */
export function specUnitWarnings(spec: SpecJson): string[] {
  const groups: (Group | null | undefined)[] = [spec.strategy?.source === 'builder' ? spec.strategy.entry : null, spec.strategy?.source === 'builder' ? spec.strategy.exit : null, spec.market_filter, spec.tick?.filter]
  return groups.flatMap((g) => conditionsOf(g)).map(unitMismatch).filter((w): w is string => !!w)
}

// ───────────── 옛 명세의 field:value(원) → 거래대금(억) ─────────────
const EOK = 100_000_000

function modernizeGroup(g: Group): { group: Group; changed: number } {
  let changed = 0
  const items = g.items.map((it) => {
    if ('logic' in it) { const r = modernizeGroup(it); changed += r.changed; return r.group }
    const isVal = (o?: Operand | null) => o?.kind === 'field' && o.name === 'value'
    const isNum = (o?: Operand | null) => o?.kind === 'const' && typeof o.value === 'number'
    const toEok = (o: Operand): Operand => { const { name: _n, ...rest } = o as Extract<Operand, { kind: 'field' }>; void _n; return { ...rest, kind: 'ind', name: 'value_eok', params: {} } as Operand }
    const scale = (o: Operand): Operand => ({ kind: 'const', value: (o as { value: number }).value / EOK })
    if (isVal(it.left) && isNum(it.right) && it.right) { changed++; return { ...it, left: toEok(it.left), right: scale(it.right) } }
    if (isNum(it.left) && isVal(it.right) && it.right) { changed++; return { ...it, left: scale(it.left), right: toEok(it.right) } }
    return it
  })
  return { group: { ...g, items }, changed }
}

/**
 * 옛 명세·레시피의 `거래대금(원) 필드 vs 숫자` 비교를 `거래대금(억) 지표 vs 숫자÷1억` 로 바꿔 보인다(결과는 같다 — 둘 다 종가×거래량 기준 원 단위 값).
 * 숫자가 변수({param})이거나 상대가 지표·필드면 못 바꾸므로 그대로 둔다(그 경우 필드 선택칸에 "거래대금"이 옛 값으로 남아 있다).
 * 억 지표가 카탈로그에 없거나 그 모드에서 못 쓰면 아무것도 안 한다.
 */
export function modernizeLegacyValue(spec: SpecJson, hasEok: (mode: SpecJson['mode']) => boolean): { spec: SpecJson; changed: number } {
  if (!hasEok(spec.mode)) return { spec, changed: 0 }
  let changed = 0
  const wrap = (g: Group | null | undefined): Group | null | undefined => { if (!g) return g; const r = modernizeGroup(g); changed += r.changed; return r.group }
  const next: SpecJson = { ...spec }
  if (spec.strategy?.source === 'builder') next.strategy = { ...spec.strategy, entry: wrap(spec.strategy.entry) as Group, exit: wrap(spec.strategy.exit) as Group }
  next.market_filter = (wrap(spec.market_filter) ?? null) as Group | null
  if (spec.tick?.filter) next.tick = { ...spec.tick, filter: wrap(spec.tick.filter) as Group }
  if (spec.intraday?.prefilter) next.intraday = { ...spec.intraday, prefilter: wrap(spec.intraday.prefilter) as Group } // 사전 필터는 일봉 조건이라 value_eok 도 일봉 모드 지원 — 서버가 거절하면 검증 오류로 보인다
  return { spec: changed ? next : spec, changed }
}
