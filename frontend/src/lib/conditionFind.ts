// 조건 고르기 — 종류와 상관없이 찾기 · "거래대금(억)" 을 가격·거래량 쪽에 노출 · 자주 쓰는 조건 바로 넣기. 순수 함수.
import { categoryOf, indicatorSupport } from '@/lib/conditionMeta'
import { indOperand } from '@/lib/spec'
import type { Condition, FieldName, IndicatorCatalog, Mode, Operand } from '@/types/studio'

export const FIELD_LABEL: Record<string, string> = { open: '시가', high: '고가', low: '저가', close: '종가', volume: '거래량', value: '거래대금' }
/** "가격·거래량" 목록에 끼워 넣는 억 단위 항목 — 고르면 지표 value_eok 로 바뀐다(원 단위 value 필드와 혼동하지 않게 이름을 갈랐다) */
export const EOK_KEY = 'ind:value_eok'
export const PRICE_GROUP = '가격·거래량'
const FIELD_ALIAS: Record<string, string> = { volume: 'volume 주식 수 거래량', value: 'value 원 단위 거래대금 체결대금' }

export interface FindOption { value: string; label: string; group: string; text: string; disabled: boolean; reason: string | null }

/** 조건 한쪽에 들어갈 수 있는 것 전부(필드·지표)를 한 목록으로 — 검색은 이름·영문 이름·설명·분류·정의 식을 함께 본다("거래대금" → 원·억·합·배수·순위 전부) */
export function operandFindOptions(cat: IndicatorCatalog, mode: Mode): FindOption[] {
  const out: FindOption[] = []
  const eokAvail = cat.indicators.some((d) => d.name === 'value_eok' && d.compute)
  // 원 단위 field:value 는 목록에서 숨긴다 — 억 기준 "거래대금" 하나만(옛 명세의 field:value 는 불러올 때 억으로 바꿔 보인다). 억 지표가 없는 서버면 그대로 둔다
  for (const f of cat.fields.filter((x) => !(x === 'value' && eokAvail))) out.push({ value: `field:${f}`, label: FIELD_LABEL[f] ?? f, group: PRICE_GROUP, text: `${FIELD_LABEL[f] ?? f} ${f} ${FIELD_ALIAS[f] ?? ''}`, disabled: false, reason: null })
  const eok = cat.indicators.find((d) => d.name === 'value_eok')
  if (eok) {
    const s = indicatorSupport(eok, mode)
    out.push({ value: EOK_KEY, label: '거래대금', group: PRICE_GROUP, text: `거래대금 거래대금(억) 억 원 체결대금 value value_eok ${eok.desc}`, disabled: !s.ok, reason: s.reason })
  }
  for (const d of cat.indicators) {
    if (d.name === 'value_eok') continue // 위 "가격·거래량" 그룹에 있다
    const s = indicatorSupport(d, mode)
    out.push({ value: `ind:${d.name}`, label: d.label, group: categoryOf(d), text: `${d.label} ${d.name} ${d.desc} ${categoryOf(d)} ${d.definition ?? ''}`, disabled: !s.ok, reason: s.reason })
  }
  return out
}

export const matchesFind = (o: FindOption, q: string): boolean => {
  const n = q.trim().toLowerCase()
  return !n || o.text.toLowerCase().includes(n)
}

/** 찾기에서 고른 것으로 피연산자를 바꾼다. 이전 조건의 "며칠 전"·배수·시간 단위는 유지(같은 자리를 다른 값으로 바꾸는 것이므로) */
export function pickOperand(cat: IndicatorCatalog, key: string, prev: Operand): Operand {
  const keep = prev.kind === 'field' || prev.kind === 'ind' ? { offset: prev.offset, mul: prev.mul, tf: prev.tf } : ({} as { offset?: number; mul?: unknown; tf?: string })
  const clean = (o: Record<string, unknown>) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined))
  if (key.startsWith('field:')) return clean({ kind: 'field', name: key.slice(6) as FieldName, ...keep }) as unknown as Operand
  const base = indOperand(cat, key.slice(4), prev.kind === 'ind' ? prev : undefined)
  return clean({ ...base, offset: keep.offset ?? base.offset, mul: keep.mul ?? base.mul, tf: keep.tf }) as unknown as Operand
}

export interface QuickCondition { key: string; label: string; hint: string; modes: Mode[]; build: (barMinutes: number, hasTf: boolean) => Condition }
const C = (v: number) => ({ kind: 'const' as const, value: v })
const F = (name: FieldName): Operand => ({ kind: 'field', name })
const ALL: Mode[] = ['intraday', 'daily_portfolio', 'daily_single']

/** 자주 쓰는 조건 — 누르면 진입 조건 행 하나가 채워져 들어간다(값은 고쳐 쓴다). 분봉은 실행 봉보다 긴 5분봉이 가능하면 "5분봉" 으로 */
export const QUICK_CONDITIONS: QuickCondition[] = [
  { key: 'value_eok', label: 'N분봉 거래대금 X억 이상', hint: '거래대금이 20억 이상(분봉이면 5분봉 기준)', modes: ALL,
    build: (bar, hasTf) => ({ left: { kind: 'ind', name: 'value_eok', params: {}, ...(hasTf && bar < 5 && 5 % bar === 0 ? { tf: 'm5' } : {}) }, op: 'gte', right: C(20) }) },
  { key: 'new_high', label: 'N일 신고가 돌파', hint: '종가가 20일 최고가를 넘음(분봉이면 전일까지 일봉)', modes: ALL,
    build: (_b, hasTf) => ({ left: F('close'), op: 'gt', right: { kind: 'ind', name: 'highest', params: { src: 'high', n: 20 }, ...(hasTf ? { tf: 'daily_prev' } : {}) } }) },
  { key: 'above_ma', label: '이평 위', hint: '종가가 20이동평균 위', modes: ALL,
    build: () => ({ left: F('close'), op: 'gt', right: { kind: 'ind', name: 'sma', params: { src: 'close', n: 20 } } }) },
  { key: 'vol_ratio', label: '거래량 급증', hint: '거래량이 20봉 평균의 3배 이상', modes: ALL,
    build: () => ({ left: { kind: 'ind', name: 'vol_ratio', params: { n: 20 } }, op: 'gte', right: C(3) }) },
  { key: 'above_vwap', label: 'VWAP 위', hint: '종가가 그날 VWAP 위', modes: ['intraday'],
    build: () => ({ left: F('close'), op: 'gt', right: { kind: 'ind', name: 'vwap' } }) },
]

/** 이 카탈로그·모드에서 실제로 넣을 수 있는 빠른 조건만(카탈로그에 없는 지표를 쓰는 것은 뺀다) */
export function quickConditionsFor(cat: IndicatorCatalog, mode: Mode): QuickCondition[] {
  const has = (n: string) => cat.indicators.some((d) => d.name === n && d.compute)
  const needs: Record<string, string> = { value_eok: 'value_eok', vol_ratio: 'vol_ratio', above_vwap: 'vwap', above_ma: 'sma', new_high: 'highest' }
  return QUICK_CONDITIONS.filter((q) => q.modes.includes(mode === 'tick' ? 'intraday' : mode) && has(needs[q.key]))
}
