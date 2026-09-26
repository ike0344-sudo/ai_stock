// 명세 편집 도우미 — 순수 함수. 화면 상태는 SpecJson 하나(JSON)이고 편집은 항상 새 객체를 만든다.
import type { Condition, Group, IndicatorCatalog, IndOperand, IntradayCfg, Mode, Num, Operand, ParamRange, SpecJson, TickCfg } from '@/types/studio'
import { isGroup, isParam } from '@/types/studio'

export const clone = <T,>(v: T): T => structuredClone(v)

// ───────────── 기본 명세 ─────────────
const HIGHEST: IndOperand = { kind: 'ind', name: 'highest', params: { src: 'high', n: 20 } }
const LOWEST: IndOperand = { kind: 'ind', name: 'lowest', params: { src: 'low', n: 10 } }

export function defaultEntry(): Group {
  return { logic: 'all', items: [{ left: { kind: 'field', name: 'close' }, op: 'gt', right: clone(HIGHEST) }] }
}
export function defaultExit(): Group {
  return { logic: 'any', items: [{ left: { kind: 'field', name: 'close' }, op: 'lt', right: clone(LOWEST) }] }
}

export const defaultIntraday = (): IntradayCfg => ({ bar_minutes: 5, source: 'al', prefilter: null, prefilter_top_value: 30, eod_time: '15:20' })
export const defaultTick = (): TickCfg => ({
  entry_source: 'catalog', catalog: { breakout_min: 5, value_speed: null, buy_ratio: null, time_from: '09:05', time_to: '15:00' },
  cooldown_sec: 300, exclude_gap_open_pct: 5, time_stop_sec: 600, eod_time: '15:19:59',
})
const isFine = (m: Mode) => m === 'intraday' || m === 'tick' // 분봉·틱: 데이터가 짧아 기본 기간도 짧다

/** 새 명세. 일봉 단일 종목은 자본 전부를 한 종목에 쓰도록 **최대 보유 1 · 비중 100%** 가 기본이다(점검 D3-4 — 서버 기본은 20% 만 쓴다). */
const shiftDays = (iso: string, d: number): string => {
  const t = new Date(`${iso}T00:00:00Z`)
  t.setUTCDate(t.getUTCDate() + d)
  return t.toISOString().slice(0, 10)
}

export function newSpec(mode: Mode, range?: { end?: string }): SpecJson {
  const single = mode === 'daily_single'
  const end = range?.end ?? new Date().toISOString().slice(0, 10)
  const start = isFine(mode) ? shiftDays(end, -30) : `${Number(end.slice(0, 4)) - 3}${end.slice(4)}`
  return {
    version: 1,
    name: single ? '새 백테스트 (단일 종목)' : mode === 'intraday' ? '새 백테스트 (분봉)' : mode === 'tick' ? '새 백테스트 (틱)' : '새 백테스트',
    mode,
    period: { start, end },
    universe: single
      ? { type: 'codes', n: 100, lookback_days: 1, markets: ['거래소', '코스닥'], exclude: [], codes: [] }
      : { type: 'top_value', n: 100, lookback_days: 1, markets: ['거래소', '코스닥'], exclude: ['spac', 'preferred', 'mega_cap'], codes: [] },
    strategy: mode === 'tick' ? null : { source: 'builder', entry: defaultEntry(), exit: defaultExit() }, // 틱 조건 진입은 전략 조건식이 없다
    market_filter: null,
    exits: { stop_loss_pct: null, take_profit_pct: null, trailing_stop_pct: null, max_holding_bars: null },
    portfolio: {
      initial_capital: 10_000_000, max_positions: single ? 1 : 5, sizing: 'equal_slot_fixed', fixed_amount: null, risk_pct: null,
      max_weight_pct: single ? 100 : 25, rank_by: 'value', random_seed: 42,
    },
    costs: { commission_rate: 0.00015, tax_rate: 0.0023, slippage_mode: 'max_rate_tick', slippage_rate: 0.001, slippage_ticks: 1 },
    fills: { same_bar_policy: 'stop_first', volume_cap_pct: single ? null : 10 },
    compat: { legacy: false },
    intraday: mode === 'intraday' ? defaultIntraday() : null,
    tick: mode === 'tick' ? defaultTick() : null,
    params: {},
    validation: null,
  }
}

/**
 * 모드를 바꿀 때 — 종목 지정·비중 같은 모드 의존 칸을 그 모드 기본에 맞춘다(조건식은 유지).
 * dataRange: 새 모드 데이터의 [처음, 끝] — 분봉·틱은 데이터가 짧아 기간을 그 끝에서 30일로 다시 잡는다(일봉으로 돌아오면 3년).
 */
export function switchMode(spec: SpecJson, mode: Mode, dataRange?: [string, string]): SpecJson {
  const base = newSpec(mode, { end: dataRange?.[1] ?? spec.period.end })
  const s = clone(spec)
  const was = spec.mode
  s.mode = mode
  s.universe = base.universe
  s.portfolio.max_positions = base.portfolio.max_positions
  s.portfolio.max_weight_pct = base.portfolio.max_weight_pct
  s.fills.volume_cap_pct = base.fills.volume_cap_pct
  if (mode !== 'daily_single') s.compat = { legacy: false }
  s.intraday = mode === 'intraday' ? (spec.intraday ?? base.intraday) : mode === 'tick' ? spec.intraday ?? null : null
  s.tick = mode === 'tick' ? (spec.tick ?? base.tick) : null
  if (mode === 'tick') {
    if (s.tick && s.tick.entry_source === 'catalog') s.strategy = null
    else if (!s.strategy) s.strategy = base.strategy ?? { source: 'builder', entry: defaultEntry(), exit: defaultExit() }
    if (s.strategy?.source === 'legacy') s.strategy = null
  } else if (!s.strategy || (isFine(mode) && s.strategy.source === 'legacy')) {
    s.strategy = { source: 'builder', entry: defaultEntry(), exit: defaultExit() } // 분봉·틱은 조건 조립기만
  }
  if (mode === 'intraday' && s.strategy?.source === 'builder' && s.strategy.exit.items.length === 0) s.strategy = { ...s.strategy, exit: defaultExit() }
  if (isFine(mode) || isFine(was)) s.period = base.period
  return s
}

/** 기간 끝이 그 데이터의 끝을 넘어 있으면(데이터 범위가 늦게 도착했을 때 남는 "오늘") 데이터 끝에서 30일로 당긴다. 이미 안이면 같은 객체를 돌려준다. */
export function clampPeriodToRange(period: SpecJson['period'], range: [string, string]): SpecJson['period'] {
  if (period.end <= range[1]) return period
  const start = shiftDays(range[1], -30)
  return { start: start < range[0] ? range[0] : start, end: range[1] }
}

/** 틱 진입 방식을 바꿀 때 — 틱 조건이면 전략 조건식이 없고, 분봉+틱 정밀화면 분봉 조건 전략이 필요하다 */
export function setTickEntrySource(spec: SpecJson, src: TickCfg['entry_source']): SpecJson {
  if (!spec.tick) return spec
  const s = clone(spec)
  s.tick = { ...s.tick!, entry_source: src }
  if (src === 'catalog') s.strategy = null
  else {
    if (!s.strategy || s.strategy.source !== 'builder') s.strategy = { source: 'builder', entry: defaultEntry(), exit: defaultExit() }
    if (!s.intraday) s.intraday = defaultIntraday()
  }
  return s
}

// ───────────── 변수({"param":..}) ─────────────
export function collectParamNames(node: unknown, out = new Set<string>()): Set<string> {
  if (Array.isArray(node)) node.forEach((n) => collectParamNames(n, out))
  else if (typeof node === 'object' && node !== null) {
    if (isParam(node)) out.add(node.param)
    else for (const v of Object.values(node)) collectParamNames(v, out)
  }
  return out
}

/** 쓰이지 않는 변수 정의를 뺀 사본 — 서버 검증·최적화 격자에 잡음이 안 가게 */
export function pruneParams(spec: SpecJson): SpecJson {
  const { params, ...rest } = spec
  const used = collectParamNames(rest)
  return { ...rest, params: Object.fromEntries(Object.entries(params).filter(([k]) => used.has(k))) } as SpecJson
}

export function freshParamName(params: Record<string, ParamRange>, hint: string): string {
  const base = (hint.replace(/[^A-Za-z0-9_]/g, '_') || 'p').replace(/^(\d)/, 'p$1')
  if (!(base in params)) return base
  let i = 2
  while (`${base}${i}` in params) i += 1
  return `${base}${i}`
}

/** 숫자 칸 → 변수 칸. 지금 값이 변수의 기본값이 된다. */
export function toParam(spec: SpecJson, current: number, hint: string): { spec: SpecJson; ref: Num } {
  const s = clone(spec)
  const name = freshParamName(s.params, hint)
  s.params[name] = { default: current, min: null, max: null, step: null }
  return { spec: s, ref: { param: name } }
}

// ───────────── 조건 그룹 편집 ─────────────
export function newCondition(): Condition {
  return { left: { kind: 'field', name: 'close' }, op: 'gt', right: { kind: 'const', value: 0 } }
}
export function newGroup(): Group {
  return { logic: 'all', items: [newCondition()] }
}
export function groupDepth(g: Group): number {
  return 1 + Math.max(0, ...g.items.filter(isGroup).map(groupDepth))
}
export function countConditions(g: Group | null | undefined): number {
  return g ? g.items.reduce((n, i) => n + (isGroup(i) ? countConditions(i) : 1), 0) : 0
}
export const MAX_DEPTH = 2 // 서버 규칙(설계서 §5.4: 하위 그룹 1단계까지)

export function addItem(g: Group, item: Condition | Group): Group {
  return { ...g, items: [...g.items, item] }
}
export function removeItem(g: Group, i: number): Group {
  return { ...g, items: g.items.filter((_, k) => k !== i) }
}
export function duplicateItem(g: Group, i: number): Group {
  const items = [...g.items]
  items.splice(i + 1, 0, clone(items[i]))
  return { ...g, items }
}
export function replaceItem(g: Group, i: number, item: Condition | Group): Group {
  const items = [...g.items]
  items[i] = item
  return { ...g, items }
}

// ───────────── 피연산자 ─────────────
/** 카탈로그 기본값으로 채운 지표 피연산자 */
export function indOperand(cat: IndicatorCatalog, name: string, keep?: IndOperand): IndOperand {
  const def = cat.indicators.find((d) => d.name === name)
  const params: Record<string, number | string | boolean> = {}
  for (const p of def?.params ?? []) params[p.name] = p.default as number | string | boolean
  return { kind: 'ind', name, params, offset: keep?.offset ?? 0, mul: keep?.mul ?? 1 }
}

export function operandKindDefault(kind: Operand['kind'], cat?: IndicatorCatalog): Operand {
  switch (kind) {
    case 'field': return { kind: 'field', name: 'close' }
    case 'ind': return cat ? indOperand(cat, 'sma') : { kind: 'ind', name: 'sma', params: { src: 'close', n: 20 } }
    case 'market': return { kind: 'market', index: 'kospi', name: 'close' }
    default: return { kind: 'const', value: 0 }
  }
}

// ───────────── 오류 경로 ─────────────
/** 서버 검증 오류 경로(strategy.entry.items.0.right ...)가 base 아래 items[i] 를 가리키나 */
export function errorsUnder(errors: { path: string; message: string }[], base: string, i: number): string[] {
  const prefix = `${base}.items.${i}`
  return errors.filter((e) => e.path === prefix || e.path.startsWith(`${prefix}.`)).map((e) => e.message)
}
export const errorsAt = (errors: { path: string; message: string }[], path: string): string[] =>
  errors.filter((e) => e.path === path || e.path.startsWith(`${path}.`)).map((e) => e.message)

/** 어떤 출처의 명세든(옛 프리셋 파일·부분 명세) 화면이 쓰기 전에 빠진 칸을 기본값으로 채운다. 서버가 이미 채워 주지만 방어선을 하나 더 둔다. */
export function normalizeSpec(raw: Partial<SpecJson>): SpecJson {
  const base = newSpec((raw.mode as Mode) ?? 'daily_portfolio', { end: raw.period?.end })
  return {
    ...base, ...raw,
    period: { ...base.period, ...raw.period },
    universe: { ...base.universe, ...raw.universe },
    exits: { ...base.exits, ...raw.exits },
    portfolio: { ...base.portfolio, ...raw.portfolio },
    costs: { ...base.costs, ...raw.costs },
    fills: { ...base.fills, ...raw.fills },
    compat: { ...base.compat, ...raw.compat },
    params: raw.params ?? {},
    market_filter: raw.market_filter ?? null,
    strategy: raw.strategy === undefined ? base.strategy : raw.strategy === null && raw.mode !== 'tick' ? base.strategy : raw.strategy,
    intraday: raw.intraday ? { ...defaultIntraday(), ...raw.intraday } : (base.intraday ?? (raw.tick?.entry_source === 'minute_refine' ? defaultIntraday() : null)),
    tick: raw.tick ? { ...defaultTick(), ...raw.tick, catalog: { ...defaultTick().catalog, ...raw.tick.catalog } } : base.tick,
    validation: raw.validation ?? null,
  } as SpecJson
}
