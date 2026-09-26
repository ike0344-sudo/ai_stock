// studio-conditions c6 화면 — 분류 나무·검색·지원 여부 · 시간 단위 · 새 연산자(hold·within·is_true·negate) · 포지션 피연산자 · 고급 청산 규칙 · 레시피 · 수식 편집기.
// 카탈로그·레시피는 실제 서버 응답(fixtures/recipes.ts). 서버가 알리는 능력(capabilities)에 따라 화면이 켜지고 꺼지는 것을 검사한다.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { OP_LABEL, categoryOf, indicatorSupport, indicatorTree, isUnaryOp, isWithinOp, matchesQuery, timeframeOptions } from '@/lib/conditionMeta'
import { applyRecipe, changeOp, newSpec, setTickEntrySource } from '@/lib/spec'
import { BacktestPage } from '@/pages/BacktestPage'
import type { Condition, IndicatorCatalog, IndicatorDef, Recipe, SpecJson } from '@/types/studio'
import * as sx from './fixtures/studio'
import { realCatalog, realRecipes } from './fixtures/recipes'
import { mockApi, renderApp } from './helpers'

beforeEach(() => localStorage.clear())

const def = (name: string): IndicatorDef => realCatalog.indicators.find((d) => d.name === name)!
const RANGES = { ...sx.dataRanges, minute_al: ['2025-08-01', '2026-09-23'], minute_krx: ['2025-07-01', '2026-09-23'], tick_al: ['2026-08-04', '2026-09-23'] } as Record<string, [string, string]>

describe('조건 고르기 재료 (실제 카탈로그)', () => {
  it('서버가 준 분류(category_ko)를 쓰고, 분류 나무는 서버가 알린 순서를 따른다', () => {
    expect(categoryOf(def('sma'))).toBe('가격·이평·신고가')
    expect(categoryOf(def('macd'))).toBe('보조지표')
    expect(categoryOf(def('rank_in_theme'))).toBe('테마·업종·시장')
    const tree = indicatorTree(realCatalog, 'daily_portfolio')
    const order = realCatalog.categories!.map((c) => c.label)
    const seen = tree.map((g) => g.category)
    expect(seen).toEqual(order.filter((o) => seen.includes(o)))
    expect(seen[0]).toBe('가격·이평·신고가')
  })

  it('서버가 category 를 안 준 옛 카탈로그는 화면 자체 분류로 메운다', () => {
    const old = { ...def('sma'), category_ko: undefined, category: undefined }
    expect(categoryOf(old)).toBe('가격·이평·신고가')
    expect(categoryOf({ ...old, name: 'zzz_unknown' })).toBe('기타')
  })

  it('지원 안 되는 모드의 지표는 숨기지 않고 비활성 + 이유', () => {
    const daily = indicatorTree(realCatalog, 'daily_portfolio').flatMap((g) => g.options)
    const vwap = daily.find((o) => o.value === 'vwap')!
    expect(vwap.disabled).toBe(true)
    expect(vwap.reason).toBe('분봉 조건에서만 쓸 수 있다')
    expect(daily.find((o) => o.value === 'sma')!.disabled).toBe(false)
    const intra = indicatorTree(realCatalog, 'intraday').flatMap((g) => g.options)
    expect(intra.find((o) => o.value === 'vwap')!.disabled).toBe(false)
    expect(intra.find((o) => o.value === 'value_rank')!.reason).toBe('일봉 조건에서만 쓸 수 있다')
    expect(indicatorSupport({ ...def('sma'), compute: false }, 'daily_portfolio').reason).toContain('준비 중')
    expect(indicatorTree(realCatalog, 'tick').flatMap((g) => g.options).find((o) => o.value === 'sma')!.disabled).toBe(false) // 틱은 분봉 지표를 쓴다
  })

  it('검색은 이름·설명·분류·정의 식에서 찾고, 비활성 지표도 찾아낸다', () => {
    expect(matchesQuery(def('rsi'), 'rsi')).toBe(true)
    expect(matchesQuery(def('sma'), '이동평균')).toBe(true)
    expect(matchesQuery(def('macd'), '보조지표')).toBe(true) // 분류
    expect(matchesQuery(def('sma'), (def('sma').definition ?? '').slice(0, 6))).toBe(true) // 정의 식
    expect(matchesQuery(def('sma'), '없는말없는말')).toBe(false)
    const found = indicatorTree(realCatalog, 'daily_portfolio', 'vwap').flatMap((g) => g.options)
    expect(found.map((o) => o.value)).toContain('vwap')
    expect(found.every((o) => matchesQuery(o.def, 'vwap'))).toBe(true)
  })

  it('시간 단위: 일봉 실행이나 서버가 모르면 선택지가 없다', () => {
    expect(timeframeOptions(realCatalog.capabilities, def('sma'), 'daily_portfolio', 5, 'al')).toEqual([])
    expect(timeframeOptions({ ...realCatalog.capabilities!, timeframes: null }, def('sma'), 'intraday', 5, 'al')).toEqual([])
    expect(timeframeOptions(undefined, def('sma'), 'intraday', 5, 'al')).toEqual([])
  })

  it('시간 단위: N분봉은 실행 봉의 배수이면서 더 긴 것만, 일봉 실시간은 live·거래량 계열 규칙', () => {
    const opts = (d: Partial<IndicatorDef>, source: 'al' | 'krx' = 'al', bar = 5) => timeframeOptions(realCatalog.capabilities, { ...def('sma'), ...d }, 'intraday', bar, source)
    const by = (o: ReturnType<typeof opts>, v: string) => o.find((x) => x.value === v)!
    const o5 = opts({})
    expect(by(o5, 'bar').disabled).toBe(false)
    expect(by(o5, 'm1').reason).toContain('실행 봉(5분)보다 긴')
    expect(by(o5, 'm5').disabled).toBe(true) // 같은 길이는 "이 봉"과 같다
    expect(by(o5, 'm10').disabled).toBe(false)
    expect(by(o5, 'm15').disabled).toBe(false)
    expect(by(opts({}, 'al', 3), 'm10').reason).toContain('배수') // 3분 실행에 10분은 배수가 아니다
    expect(by(opts({}, 'al', 3), 'm15').disabled).toBe(false)
    expect(by(o5, 'daily_prev').disabled).toBe(false)
    expect(by(o5, 'daily_live').disabled).toBe(false) // sma 는 live
    expect(by(opts({ live: false }), 'daily_live').reason).toContain('전일 확정만')
    expect(by(opts({ live: undefined }), 'daily_live').reason).toContain('알려 주지 않았다')
    const vol = { live: true, volume_based: true }
    expect(by(opts(vol, 'al'), 'daily_live').reason).toContain('20~40% 부풀려진다') // 통합 분봉 + KRX 일봉 섞기 금지
    expect(by(opts(vol, 'krx'), 'daily_live').disabled).toBe(false)
    expect(by(opts({ modes: ['intraday'] }), 'daily_prev').reason).toBe('이 지표는 일봉에서 쓸 수 없다')
    expect(by(opts({ modes: ['daily_portfolio'] }), 'm15').reason).toBe('이 지표는 분봉에서 쓸 수 없다')
  })

  it('연산자 바꾸기: 참이면은 오른쪽이 없고, 최근 N봉 안 크로스는 within 이 생기며, 되돌리면 정리된다', () => {
    const c: Condition = { left: { kind: 'field', name: 'close' }, op: 'gt', right: { kind: 'const', value: 5 } }
    const u = changeOp(c, 'is_true')
    expect(u.op).toBe('is_true')
    expect('right' in u).toBe(false)
    const w = changeOp(u, 'cross_above_within')
    expect(w).toMatchObject({ op: 'cross_above_within', right: { kind: 'const', value: 0 }, within: 3 })
    expect(changeOp({ ...w, within: 7 }, 'cross_below_within').within).toBe(7) // 같은 종류면 k 유지
    const g = changeOp(w, 'gte')
    expect('within' in g).toBe(false)
    expect(g.right).toEqual({ kind: 'const', value: 0 })
    expect([isUnaryOp('is_false'), isUnaryOp('gt'), isWithinOp('cross_below_within'), isWithinOp('cross_below')]).toEqual([true, false, true, false])
    expect(OP_LABEL.is_true).toBe('참이면 (1)')
  })
})

describe('레시피 적용', () => {
  const rec = (id: string) => realRecipes.find((r) => r.id === id)!
  it('일봉 레시피: 진입·청산·변수·청산 규칙을 바꾸고 기본 이름이면 레시피 이름으로', () => {
    const s = applyRecipe(newSpec('daily_portfolio', { end: '2026-09-23' }), rec('new_high_20'))
    expect(s.strategy).toMatchObject({ source: 'builder', entry: rec('new_high_20').entry, exit: rec('new_high_20').exit })
    expect(s.name).toBe('20일 신고가 돌파')
    expect(s.mode).toBe('daily_portfolio')
    const named = applyRecipe({ ...newSpec('daily_portfolio'), name: '내 전략' }, rec('golden_cross'))
    expect(named.name).toBe('내 전략') // 사용자가 붙인 이름은 지키지 않는다고 덮어쓰지 않는다
  })

  it('모드가 안 맞으면 레시피 모드로 바뀌고 기간이 그 데이터 끝으로 다시 잡힌다', () => {
    const s = applyRecipe(newSpec('daily_portfolio', { end: '2026-09-25' }), rec('intraday_high_break'), ['2025-08-01', '2026-09-23'])
    expect(s.mode).toBe('intraday')
    expect(s.intraday?.source).toBe('al')
    expect(s.period).toEqual({ start: '2026-08-24', end: '2026-09-23' })
  })

  it('틱 조건 진입 상태에서 분봉 레시피를 불러오면 틱 정밀화 방식(조건식 사용)으로 바뀐다', () => {
    const t = newSpec('tick', { end: '2026-09-23' })
    const s = applyRecipe(t, rec('intraday_high_break'))
    // 분봉 레시피는 틱 모드에 그대로 맞지 않는다 → 분봉 모드로 옮겨 간다(틱 조건 진입엔 조건식이 없으므로)
    expect(['intraday', 'tick']).toContain(s.mode)
    expect(s.strategy?.source).toBe('builder')
    const refine = applyRecipe(setTickEntrySource(t, 'minute_refine'), rec('intraday_high_break'))
    expect(refine.mode).toBe('tick')
    expect(refine.tick?.entry_source).toBe('minute_refine')
  })

  it('레시피 파일은 서버가 실제로 아는 재료만 쓴다 — 실제 서버 응답에서 전부 사용 가능', () => {
    expect(realRecipes.length).toBeGreaterThanOrEqual(10)
    expect(realRecipes.every((r) => r.available && r.unavailable_reason === null)).toBe(true)
  })
})

const routes = (over: Record<string, Parameters<typeof mockApi>[0][string]> = {}, catalog: IndicatorCatalog = realCatalog) => ({
  'GET /api/meta/indicators': { data: catalog },
  'GET /api/meta/strategies': { data: sx.legacyDefs },
  'GET /api/meta/data-ranges': { data: RANGES },
  'GET /api/meta/intraday-sources': { data: { minute: { al: { total: 1, full: 1, partial: 0, range: ['2025-08-01', '2026-09-23'] }, krx: { total: 1, full: 1, partial: 0, range: ['2025-07-01', '2026-09-23'] } }, tick: { codes: 1, days: 1, first: '2026-09-01', last: '2026-09-23', days_in_range: 1 } } },
  'GET /api/meta/recipes': { data: realRecipes },
  'GET /api/presets': { data: sx.presetRows },
  'POST /api/conditions/validate': { data: sx.validOk },
  ...over,
})
const page = () => renderApp(<Routes><Route path="/backtest" element={<BacktestPage />} /><Route path="/results/:runId" element={<div />} /></Routes>, '/backtest')
const lastSpec = (calls: { path: string; body: unknown }[]): SpecJson => {
  const v = calls.filter((c) => c.path.startsWith('/api/conditions/validate'))
  return (v[v.length - 1].body as { spec: SpecJson }).spec
}
const toIntraday = async () => { await userEvent.click(await screen.findByRole('tab', { name: '분봉 단타' })); await screen.findByTestId('panel-intraday') }

describe('조건 편집기 (분봉·시간 단위)', () => {
  it('일봉 실행에는 시간 단위 선택기가 없고, 분봉 실행에서만 나타난다', async () => {
    mockApi(routes())
    page()
    await screen.findByTestId('group-strategy.entry')
    expect(screen.queryByTestId('operand-left-tf')).not.toBeInTheDocument()
    await toIntraday()
    expect((await screen.findAllByTestId('operand-left-tf')).length).toBeGreaterThan(0)
  })

  it('서버가 시간 단위를 모르면(capabilities.timeframes=null) 분봉에서도 선택기를 보내지 않는다', async () => {
    mockApi(routes({}, { ...realCatalog, capabilities: { ...realCatalog.capabilities!, timeframes: null } }))
    page()
    await toIntraday()
    expect(screen.queryByTestId('operand-left-tf')).not.toBeInTheDocument()
  })

  it('시간 단위를 고르면 그 피연산자에 tf 가 실리고, "이 봉"으로 되돌리면 칸이 사라진다', async () => {
    const { calls } = mockApi(routes())
    page()
    await toIntraday()
    const entry = screen.getByTestId('group-strategy.entry')
    // 왼쪽은 종가(field) 오른쪽은 지표 — 오른쪽(지표)의 시간 단위를 바꾼다
    const rightTf = within(entry).getAllByTestId('operand-right-tf')[0]
    await userEvent.click(within(rightTf).getByRole('combobox'))
    await userEvent.click(await screen.findByText('일봉(전일 확정)'))
    await waitFor(() => expect((lastSpec(calls).strategy as { entry: { items: { right: { tf?: string } }[] } }).entry.items[0].right.tf).toBe('daily_prev'))
    await userEvent.click(within(within(entry).getAllByTestId('operand-right-tf')[0]).getByRole('combobox'))
    await userEvent.click(await screen.findByText('이 봉', { selector: '.ant-select-item-option-content span, .ant-select-item-option-content' }))
    await waitFor(() => expect('tf' in (lastSpec(calls).strategy as { entry: { items: { right: object }[] } }).entry.items[0].right).toBe(false))
  })

  it('실행 봉 5분이면 1·3분봉은 비활성이고 이유가 붙는다', async () => {
    mockApi(routes())
    page()
    await toIntraday()
    const entry = screen.getByTestId('group-strategy.entry')
    await userEvent.click(within(within(entry).getAllByTestId('operand-right-tf')[0]).getByRole('combobox'))
    const one = (await screen.findAllByText(/1분봉 — 실행 봉\(5분\)보다 긴 단위만/))[0]
    expect(one.closest('.ant-select-item-option')).toHaveAttribute('aria-disabled', 'true')
  })

  it('지표 선택창을 열면 분류 이름 아래에 지표가 나뉘어 보인다(검색·비활성 이유는 라이브 E2E 에서 화면으로 확인)', async () => {
    mockApi(routes())
    page()
    const entry = await screen.findByTestId('group-strategy.entry')
    const ind = within(entry).getAllByTestId('operand-right-ind')[0]
    await userEvent.click(within(ind).getByRole('combobox'))
    expect((await screen.findAllByText('가격·이평·신고가')).length).toBeGreaterThan(0) // 첫 분류 이름(목록은 화면에 보이는 만큼만 그린다)
    expect(screen.getAllByText('이동평균').length).toBeGreaterThan(0)
  })
})

describe('새 연산자·hold·negate·포지션', () => {
  it('참이면(is_true) 를 고르면 오른쪽 값 칸이 사라지고 명세엔 right 가 없다', async () => {
    const { calls } = mockApi(routes())
    page()
    const entry = await screen.findByTestId('group-strategy.entry')
    expect(within(entry).getAllByTestId('operand-right').length).toBeGreaterThan(0)
    await userEvent.click(within(within(entry).getAllByTestId('op-select')[0]).getByRole('combobox'))
    await userEvent.click(await screen.findByText('참이면 (1)'))
    await waitFor(() => expect(within(entry).queryAllByTestId('operand-right')).toHaveLength(0))
    await waitFor(() => {
      const c = (lastSpec(calls).strategy as { entry: { items: Condition[] } }).entry.items[0]
      expect(c.op).toBe('is_true')
      expect('right' in c).toBe(false)
    })
  })

  it('최근 N봉 안 크로스를 고르면 N 칸이 생기고 값이 명세에 실린다', async () => {
    const { calls } = mockApi(routes())
    page()
    const entry = await screen.findByTestId('group-strategy.entry')
    await userEvent.click(within(within(entry).getAllByTestId('op-select')[0]).getByRole('combobox'))
    await userEvent.click(await screen.findByText('최근 N봉 안에 위로 돌파'))
    const w = await within(entry).findByTestId('within-input')
    fireEvent.change(w, { target: { value: '5' } })
    await waitFor(() => expect((lastSpec(calls).strategy as { entry: { items: Condition[] } }).entry.items[0]).toMatchObject({ op: 'cross_above_within', within: 5 }))
  })

  it('연속 k봉(hold)·그룹 뒤집기(negate)는 서버가 알릴 때만 보이고, 값이 명세에 실린다', async () => {
    const { calls } = mockApi(routes())
    page()
    const entry = await screen.findByTestId('group-strategy.entry')
    fireEvent.change(within(entry).getAllByTestId('hold-input')[0], { target: { value: '3' } })
    await waitFor(() => expect((lastSpec(calls).strategy as { entry: { items: Condition[] } }).entry.items[0].hold).toBe(3))
    await userEvent.click(within(entry).getByTestId('group-strategy.entry-negate'))
    await waitFor(() => expect((lastSpec(calls).strategy as { entry: { negate?: boolean } }).entry.negate).toBe(true))
  })

  it('능력이 없으면(옛 서버) hold·negate 칸이 안 보인다', async () => {
    const { capabilities: _c, ...noCaps } = realCatalog
    void _c
    mockApi(routes({}, noCaps as IndicatorCatalog))
    page()
    const entry = await screen.findByTestId('group-strategy.entry')
    expect(within(entry).queryByTestId('hold-input')).not.toBeInTheDocument()
    expect(within(entry).queryByTestId('group-strategy.entry-negate')).not.toBeInTheDocument()
    expect(screen.getByTestId('exits-advanced-pending')).toBeInTheDocument()
  })

  it('포지션 피연산자는 청산 조건에서만 고를 수 있다', async () => {
    mockApi(routes())
    page()
    const exit = await screen.findByTestId('group-strategy.exit')
    await userEvent.click(within(within(exit).getAllByTestId('operand-left-kind')[0]).getByRole('combobox'))
    await userEvent.click(await screen.findByText('포지션'))
    expect(await within(exit).findByTestId('operand-left-pos')).toBeInTheDocument()
    // 진입 조건의 종류 목록엔 포지션이 없다
    const entry = screen.getByTestId('group-strategy.entry')
    await userEvent.click(within(within(entry).getAllByTestId('operand-left-kind')[0]).getByRole('combobox'))
    await screen.findAllByText('가격·거래량')
    const shown = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')] as HTMLElement[]
    const open = shown[shown.length - 1] // 방금 연 목록(닫힌 목록은 DOM 에 남는다)
    expect(open).toHaveTextContent('가격·거래량')
    expect(open).not.toHaveTextContent('포지션')
  })
})

describe('청산 규칙 (고급)', () => {
  it('서버가 청산 새 칸을 알리면 분할 익절 표·익절 방식·발동·본전·시간 청산이 나타나고 값이 명세에 실린다', async () => {
    const caps = { ...realCatalog.capabilities!, exit_fields: ['take_profit_levels', 'take_profit_mode', 'trail_activate_pct', 'breakeven_after_pct', 'max_holding_minutes'] }
    const { calls } = mockApi(routes({}, { ...realCatalog, capabilities: caps }))
    page()
    const panel = await screen.findByTestId('panel-exits')
    expect(within(panel).queryByTestId('exits-advanced-pending')).not.toBeInTheDocument()
    await userEvent.click(within(panel).getByTestId('exit-levels-on'))
    await waitFor(() => expect(lastSpec(calls).exits.take_profit_levels).toEqual([{ pct: 5, fraction: 0.5 }, { pct: 10, fraction: 1 }]))
    fireEvent.change(within(panel).getByTestId('level-pct-0'), { target: { value: '4' } })
    fireEvent.change(within(panel).getByTestId('level-fraction-0'), { target: { value: '30' } })
    await userEvent.click(within(panel).getByTestId('level-add'))
    await waitFor(() => expect(lastSpec(calls).exits.take_profit_levels).toEqual([{ pct: 4, fraction: 0.3 }, { pct: 10, fraction: 1 }, { pct: 15, fraction: 1 }]))
    await userEvent.click(within(panel).getByText('종가 확인 뒤 다음 봉 시가'))
    await userEvent.click(within(panel).getByTestId('exit-trail_activate_pct-on'))
    await userEvent.click(within(panel).getByTestId('exit-breakeven_after_pct-on'))
    await waitFor(() => expect(lastSpec(calls).exits).toMatchObject({ take_profit_mode: 'close', trail_activate_pct: 5, breakeven_after_pct: 3 }))
    expect(within(panel).getByText(/조각 행/)).toBeInTheDocument() // 분할 청산은 진입 기준으로 센다는 설명
    expect(within(panel).getAllByText(/남은 수량/).length).toBeGreaterThan(0) // fraction 은 남은 수량 기준(c2 확정)
    expect(within(panel).queryByTestId('exit-max_holding_minutes-on')).not.toBeInTheDocument() // 시간 청산(분)은 분봉 모드에서만(서버가 다른 모드는 거부)
  })

  const caps2 = { ...realCatalog.capabilities!, exit_fields: ['take_profit_levels', 'take_profit_mode', 'trail_activate_pct', 'breakeven_after_pct', 'max_holding_minutes'] }

  it('분할 익절을 켜면 단일 익절이 꺼지고, 단일 익절을 켜면 분할 익절이 꺼진다(서버는 둘을 같이 못 쓴다)', async () => {
    const { calls } = mockApi(routes({}, { ...realCatalog, capabilities: caps2 }))
    page()
    const panel = await screen.findByTestId('panel-exits')
    await userEvent.click(within(panel).getByTestId('exit-take_profit_pct-on'))
    await waitFor(() => expect(lastSpec(calls).exits.take_profit_pct).toBe(15))
    await userEvent.click(within(panel).getByTestId('exit-levels-on'))
    await waitFor(() => expect(lastSpec(calls).exits).toMatchObject({ take_profit_pct: null, take_profit_levels: [{ pct: 5, fraction: 0.5 }, { pct: 10, fraction: 1 }] }))
    await userEvent.click(within(panel).getByTestId('exit-take_profit_pct-on'))
    await waitFor(() => expect(lastSpec(calls).exits).toMatchObject({ take_profit_pct: 15, take_profit_levels: null }))
  })

  it('시간 청산(분)은 분봉 모드에서만, 틱 모드는 새 청산 칸과 포지션 피연산자를 전부 숨긴다', async () => {
    mockApi(routes({}, { ...realCatalog, capabilities: caps2 }))
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '분봉 단타' }))
    await screen.findByTestId('panel-intraday')
    expect(within(screen.getByTestId('panel-exits')).getByTestId('exit-max_holding_minutes-on')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: '체결(틱)' }))
    await screen.findByTestId('panel-tick')
    const panel = screen.getByTestId('panel-exits')
    for (const id of ['exit-levels-on', 'exit-tp-mode', 'exit-trail_activate_pct-on', 'exit-breakeven_after_pct-on', 'exit-max_holding_minutes-on']) expect(within(panel).queryByTestId(id)).not.toBeInTheDocument()
  })

  it('서버가 청산 새 칸을 안 알리면 "서버 준비 중"만 보이고 아무것도 보내지 않는다', async () => {
    const { calls } = mockApi(routes())
    page()
    expect(await screen.findByTestId('exits-advanced-pending')).toHaveTextContent('서버 준비 중')
    await waitFor(() => expect(calls.some((c) => c.path.startsWith('/api/conditions/validate'))).toBe(true))
    expect(Object.keys(lastSpec(calls).exits).sort()).toEqual(['max_holding_bars', 'stop_loss_pct', 'take_profit_pct', 'trailing_stop_pct'])
  })
})

describe('레시피', () => {
  it('분류별로 펼쳐 보이고 검색되며, 쓸 수 없는 것은 이유와 함께 비활성', async () => {
    const recipes: Recipe[] = realRecipes.map((r) => (r.id === 'macd_cross' ? { ...r, available: false, unavailable_reason: '서버가 아직 지원하지 않는다: 지표 macd' } : r))
    mockApi(routes({ 'GET /api/meta/recipes': { data: recipes } }))
    page()
    await userEvent.click(await screen.findByTestId('recipe-open'))
    const modal = await screen.findByTestId('recipe-modal')
    expect(within(modal).getByTestId('recipe-cat-신고가')).toBeInTheDocument()
    expect(within(modal).getByTestId('recipe-cat-분봉')).toBeInTheDocument()
    expect(within(modal).getByTestId('recipe-new_high_20')).toHaveAttribute('data-available', 'true')
    expect(within(modal).getByTestId('recipe-macd_cross')).toHaveAttribute('data-available', 'false')
    expect(within(modal).getByTestId('recipe-macd_cross-reason')).toHaveTextContent('지표 macd')
    expect(within(modal).getByTestId('recipe-macd_cross-apply')).toBeDisabled()
    await userEvent.type(within(modal).getByPlaceholderText('레시피·설명·분류 검색'), '골든크로스')
    await waitFor(() => expect(within(modal).queryByTestId('recipe-new_high_20')).not.toBeInTheDocument())
    expect(within(modal).getByTestId('recipe-golden_cross')).toBeInTheDocument()
  })

  it('불러오기: 진입·청산 조건 행이 그 레시피로 풀리고 안내 문구가 뜬다(분봉 레시피는 분봉 탭으로)', async () => {
    const { calls } = mockApi(routes())
    page()
    await userEvent.click(await screen.findByTestId('recipe-open'))
    await userEvent.click(await screen.findByTestId('recipe-golden_cross-apply'))
    await waitFor(() => expect(screen.getByTestId('load-note')).toHaveTextContent('레시피 "이평 골든크로스" 을 불러왔습니다'))
    await waitFor(() => {
      const st = lastSpec(calls).strategy as { entry: { items: Condition[] } }
      expect(st.entry.items[0]).toMatchObject({ op: 'cross_above', left: { name: 'sma', params: { n: 5 } }, right: { name: 'sma', params: { n: 20 } } })
    })
    await userEvent.click(await screen.findByTestId('recipe-open'))
    expect(await screen.findByTestId('recipe-intraday_high_break')).toBeInTheDocument()
    expect(within(screen.getByTestId('recipe-intraday_high_break')).getByText(/분봉 단타 모드로 바뀝니다/)).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('recipe-intraday_high_break-apply'))
    await screen.findByTestId('panel-intraday')
    await waitFor(() => expect(lastSpec(calls).mode).toBe('intraday'))
    expect(lastSpec(calls).period).toEqual({ start: '2026-08-24', end: '2026-09-23' })
    expect(((lastSpec(calls).strategy as { entry: { items: Condition[] } }).entry.items).length).toBe(2) // 신고가 + VWAP 위
  })
})

describe('수식 편집기', () => {
  it('서버에 수식 라우터가 없으면 요청을 보내지 않고 "서버 준비 중"만 보인다', async () => {
    const { calls } = mockApi(routes())
    page()
    expect(await screen.findByTestId('formula-pending')).toHaveTextContent('서버 준비 중')
    expect(screen.queryByTestId('formula-text')).not.toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/formulas'))).toBe(false) // 콘솔에 404 가 안 쌓인다
  })

  const withFormulas = (over: Record<string, Parameters<typeof mockApi>[0][string]> = {}) =>
    routes({
      'GET /api/formulas': { data: [{ name: '내신고가', description: '분봉 신고가', created_at: '2026-09-26T10:00:00' }] },
      [`GET /api/formulas/${encodeURIComponent('내신고가')}`]: { data: { name: '내신고가', description: '분봉 신고가', created_at: '2026-09-26T10:00:00', text: 'C > D.HIGHEST(H,20)' } },
      [`PUT /api/formulas/${encodeURIComponent('새수식')}`]: { data: { name: '새수식', description: null, created_at: '2026-09-26T11:00:00' } },
      ...over,
    }, { ...realCatalog, capabilities: { ...realCatalog.capabilities!, formulas: true } })

  it('검사 성공: 풀이 문장이 보이고 [진입 조건에 넣기] 로 조건 행이 늘어난다', async () => {
    const ast = { logic: 'all', formula: 'C > D.HIGHEST(H,20)', items: [{ left: { kind: 'field', name: 'close' }, op: 'gt', right: { kind: 'ind', name: 'highest', params: { src: 'high', n: 20 }, tf: 'daily_prev' } }] }
    const { calls } = mockApi(withFormulas({ 'POST /api/formulas/check': { data: { ok: true, ast, narration: '종가가 전일까지 20일 최고가를 넘으면' } } }))
    page()
    const box = await screen.findByTestId('formula-text')
    await userEvent.type(box, 'C > D.HIGHEST(H,20)')
    await userEvent.click(screen.getByTestId('formula-check'))
    expect(await screen.findByTestId('formula-ok')).toHaveTextContent('종가가 전일까지 20일 최고가를 넘으면')
    const chk = calls.find((c) => c.path === '/api/formulas/check')!.body as { text: string; mode: string }
    expect(chk).toMatchObject({ text: 'C > D.HIGHEST(H,20)', mode: 'daily_portfolio' })
    const before = (lastSpec(calls).strategy as { entry: { items: unknown[] } }).entry.items.length
    await userEvent.click(screen.getByTestId('formula-insert-entry'))
    await waitFor(() => expect((lastSpec(calls).strategy as { entry: { items: unknown[] } }).entry.items.length).toBe(before + 1))
    expect(await screen.findByText('수식: C > D.HIGHEST(H,20)')).toBeInTheDocument() // 수식으로 만든 그룹은 원문이 제목으로 보인다
  })

  it('문법 오류: 줄·칸 위치에 ^ 표시와 "여기엔 무엇이 와야 한다"', async () => {
    mockApi(withFormulas({ 'POST /api/formulas/check': { status: 422, error: { code: 'FORMULA_INVALID', message: '식이 끝나지 않았다', details: { line: 1, col: 9, expected: '숫자나 지표' } } } }))
    page()
    await userEvent.type(await screen.findByTestId('formula-text'), 'C > 20 AND')
    await userEvent.click(screen.getByTestId('formula-check'))
    const err = await screen.findByTestId('formula-error')
    expect(err).toHaveTextContent('식이 끝나지 않았다')
    const caret = within(err).getByTestId('formula-caret').textContent!
    expect(caret).toContain('1줄 9칸')
    expect(caret).toContain('C > 20 AND')
    expect(caret).toContain('        ^ 여기엔 숫자나 지표 이(가) 와야 한다') // 8칸 띄우고 ^
    expect(screen.getByTestId('formula-insert-entry')).toBeDisabled() // 검사를 통과하기 전엔 못 넣는다
  })

  it('저장·불러오기·예시 채우기', async () => {
    const { calls } = mockApi(withFormulas())
    page()
    await userEvent.click(await screen.findByTestId('formula-load-내신고가'))
    await waitFor(() => expect((screen.getByTestId('formula-text') as HTMLTextAreaElement).value).toBe('C > D.HIGHEST(H,20)'))
    expect((screen.getByTestId('formula-name') as HTMLInputElement).value).toBe('내신고가')
    await userEvent.click(within(screen.getByTestId('formula-examples')).getAllByText('입력칸에 채우기')[1])
    await waitFor(() => expect((screen.getByTestId('formula-text') as HTMLTextAreaElement).value).toContain('M5.C > M5.MA(C,20)'))
    fireEvent.change(screen.getByTestId('formula-name'), { target: { value: '새수식' } })
    await userEvent.click(screen.getByTestId('formula-save'))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT' && c.path === '/api/formulas/%EC%83%88%EC%88%98%EC%8B%9D')).toBe(true))
    const put = calls.find((c) => c.method === 'PUT')!.body as { text: string }
    expect(put.text).toContain('DL.MA(C,20)')
  })

  it('조립기 전략이 아니면(틱 조건 진입) 조건에 넣을 수 없다고 알린다', async () => {
    mockApi(withFormulas())
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '체결(틱)' }))
    await screen.findByTestId('panel-tick')
    expect(await screen.findByText(/조건 조립기 전략\(틱 조건 진입 제외\)에서만 넣을 수 있다/)).toBeInTheDocument()
  })
})

describe('분할 익절 결과 (c2)', () => {
  it('진입 한 건이 조각 행 여럿이어도 행 키가 겹치지 않고 "조각 1/2" 로 보인다', async () => {
    const { realDetail, realTrades } = await import('./fixtures/studioReal')
    const { ResultPage } = await import('@/pages/ResultPage')
    const base = realTrades[0]
    const trades = [{ ...base, entry_id: 0, slice: 1, exit_ts: '2025-02-10T00:00:00' }, { ...base, entry_id: 0, slice: 2, exit_ts: '2025-02-12T00:00:00' }, { ...realTrades[1], entry_id: 1, slice: 1 }]
    mockApi({ [`GET /api/runs/${realDetail.run_id}`]: { data: realDetail }, [`GET /api/runs/${realDetail.run_id}/equity`]: { data: [] }, [`GET /api/runs/${realDetail.run_id}/trades`]: { data: trades } })
    renderApp(<Routes><Route path="/results/:runId" element={<ResultPage />} /></Routes>, `/results/${realDetail.run_id}`)
    const table = await screen.findByTestId('trades-table')
    await waitFor(() => expect(within(table).getAllByTestId('slice-tag').map((e) => e.textContent)).toEqual(['1/2', '2/2', '1/1']))
  })
})

describe('틱 탭의 분봉·일봉 조건 묶음 (c8)', () => {
  const tickCaps = { ...realCatalog.capabilities!, tick_fields: ['filter', 'prefilter'] }
  const openTick = async (catalog: IndicatorCatalog = { ...realCatalog, capabilities: tickCaps }) => {
    const r = mockApi(routes({}, catalog))
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '체결(틱)' }))
    await screen.findByTestId('panel-tick')
    return r
  }

  it('서버가 알리지 않으면(tick_fields 없음) 필터 카드가 없다', async () => {
    await openTick(realCatalog)
    expect(screen.queryByTestId('tick-filter-card')).not.toBeInTheDocument()
  })

  it('서버가 알리면 카드가 나오고 표본 감소 경고가 보이며, 켜면 명세 tick.filter 에 기본 조건이 실린다', async () => {
    const { calls } = await openTick()
    const card = await screen.findByTestId('tick-filter-card')
    expect(within(card).getByTestId('tick-filter-sample-warning')).toHaveTextContent('실측 16%')
    expect(within(card).getByText(/마감된 마지막 1분봉/)).toBeInTheDocument()
    await userEvent.click(within(card).getByTestId('tick-filter-switch'))
    await waitFor(() => expect(lastSpec(calls).tick?.filter).toMatchObject({ logic: 'all', items: [{ left: { name: 'close' }, op: 'gt', right: { name: 'vwap' } }] }))
    expect(await within(card).findByTestId('row-tick.filter.items.0')).toBeInTheDocument()
    await userEvent.click(within(card).getByTestId('tick-prefilter-switch'))
    await waitFor(() => expect(lastSpec(calls).tick?.prefilter?.items).toHaveLength(1))
    expect(await within(card).findByTestId('row-tick.prefilter.items.0')).toBeInTheDocument()
  })

  it('분봉+틱 정밀화로 바꾸면 필터·사전 필터가 사라지고 카드도 없어진다(서버는 catalog 에서만 받는다)', async () => {
    const { calls } = await openTick()
    await userEvent.click(within(await screen.findByTestId('tick-filter-card')).getByTestId('tick-filter-switch'))
    await waitFor(() => expect(lastSpec(calls).tick?.filter).toBeTruthy())
    await userEvent.click(within(screen.getByTestId('tick-entry-source')).getByText('분봉 신호 + 틱 정밀화'))
    await waitFor(() => expect(lastSpec(calls).tick).toMatchObject({ entry_source: 'minute_refine', filter: null, prefilter: null }))
    expect(screen.queryByTestId('tick-filter-card')).not.toBeInTheDocument()
  })

  it('필터의 시간 단위는 1분봉 실행 기준이라 m1 은 못 고른다(3~60분·일봉만)', () => {
    const o = timeframeOptions(realCatalog.capabilities, def('sma'), 'tick', 1, 'al')
    expect(o.find((x) => x.value === 'm1')!.disabled).toBe(true)
    expect(o.find((x) => x.value === 'bar')!.disabled).toBe(false)
    expect(o.find((x) => x.value === 'm3')!.disabled).toBe(false)
    expect(o.find((x) => x.value === 'daily_prev')!.disabled).toBe(false)
  })

  it('결과 카드: 분봉이 없어 빠진 쌍·사전 필터로 제외한 쌍을 보여 준다', async () => {
    const { tickDetail } = await import('./fixtures/studioReal6')
    const { ResultPage } = await import('@/pages/ResultPage')
    const d = { ...tickDetail, summary: { ...tickDetail.summary, tick: { ...(tickDetail.summary.tick as object), expected_pairs: 1000, filter_pairs_without_minutes: 310, prefilter_pairs_skipped: 120 } } }
    mockApi({ [`GET /api/runs/${d.run_id}`]: { data: d }, [`GET /api/runs/${d.run_id}/equity`]: { data: [] }, [`GET /api/runs/${d.run_id}/trades`]: { data: [] } })
    renderApp(<Routes><Route path="/results/:runId" element={<ResultPage />} /></Routes>, `/results/${d.run_id}`)
    const s = await screen.findByTestId('tick-summary')
    expect(s).toHaveTextContent('310')
    expect(s).toHaveTextContent('31%')
    expect(s).toHaveTextContent('사전 필터로 제외한')
    expect(s).toHaveTextContent('120')
  })
})

describe('수식 → 틱 분봉·일봉 조건 (c8)', () => {
  it('틱 조건 진입에서 검사를 통과한 수식을 필터로 넣는다(비어 있으면 그 그룹이 필터, 있으면 AND 항목)', async () => {
    const ast = { logic: 'all', formula: 'M5.C > M5.MA(C,20)', items: [{ left: { kind: 'field', name: 'close', tf: 'm5' }, op: 'gt', right: { kind: 'ind', name: 'sma', params: { src: 'close', n: 20 }, tf: 'm5' } }] }
    const catalog = { ...realCatalog, capabilities: { ...realCatalog.capabilities!, tick_fields: ['filter', 'prefilter'], formulas: true } }
    const { calls } = mockApi(routes({ 'GET /api/formulas': { data: [] }, 'POST /api/formulas/check': { data: { ok: true, ast, narration: '5분봉 종가가 20선 위' } } }, catalog))
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '체결(틱)' }))
    await userEvent.type(await screen.findByTestId('formula-text'), 'M5.C > M5.MA(C,20)')
    expect(screen.getByTestId('formula-insert-filter')).toBeDisabled() // 검사 전엔 못 넣는다
    await userEvent.click(screen.getByTestId('formula-check'))
    await screen.findByTestId('formula-ok')
    expect((calls.find((c) => c.path === '/api/formulas/check')!.body as { mode: string }).mode).toBe('tick')
    await userEvent.click(screen.getByTestId('formula-insert-filter'))
    await waitFor(() => expect(lastSpec(calls).tick?.filter).toMatchObject({ logic: 'all', formula: 'M5.C > M5.MA(C,20)', items: [{ left: { tf: 'm5' } }] }))
    await userEvent.click(screen.getByTestId('formula-insert-filter')) // 두 번째는 있는 필터에 AND 항목으로
    await waitFor(() => expect((lastSpec(calls).tick?.filter as { items: unknown[] }).items).toHaveLength(2))
  })
})

describe('거래대금(억)·새 틱 조건·틱 레시피 (c9)', () => {
  const tickRecipe: Recipe = {
    id: 'tick_value_burst', category: '거래량·거래대금', title: '틱 최근 1분 체결대금 급증', description: 'd', modes: ['tick'], needs: [], available: true, unavailable_reason: null,
    entry: { logic: 'all', items: [] }, exit: { logic: 'any', items: [] },
    tick: { entry_source: 'catalog', catalog: { breakout_min: null, value_window: { w: 1, min_eok: 10 }, time_from: '09:05', time_to: '15:00' }, cooldown_sec: 300, exclude_gap_open_pct: 5, time_stop_sec: 600, eod_time: '15:19:59' },
  }

  it('틱 레시피는 조건 행이 아니라 틱 탭 칸을 채운다(다른 틱 조건은 끄고 전략 조건식은 없앤다)', () => {
    const s = applyRecipe(newSpec('daily_portfolio', { end: '2026-09-23' }), tickRecipe, ['2026-08-04', '2026-09-23'])
    expect(s.mode).toBe('tick')
    expect(s.strategy).toBeNull()
    expect(s.tick?.entry_source).toBe('catalog')
    expect(s.tick?.catalog).toMatchObject({ breakout_min: null, value_speed: null, buy_ratio: null, value_window: { w: 1, min_eok: 10 }, time_from: '09:05' })
    expect(s.period.end).toBe('2026-09-23')
    // 이미 틱 조건 진입이면 그 자리에서 조건만 바뀐다(모드 안 바뀜)
    const t = newSpec('tick', { end: '2026-09-23' })
    const s2 = applyRecipe({ ...t, tick: { ...t.tick!, catalog: { ...t.tick!.catalog, buy_ratio: { w: 1, min: 0.6 } } } }, tickRecipe)
    expect(s2.tick?.catalog.buy_ratio).toBeNull()
    expect(s2.tick?.catalog.value_window).toEqual({ w: 1, min_eok: 10 })
    // 틱 정밀화 상태에서 불러오면 틱 조건 진입으로 돌아온다(서버는 정밀화에 틱 조건 칸이 없다)
    const s3 = applyRecipe(setTickEntrySource(t, 'minute_refine'), tickRecipe)
    expect(s3.tick?.entry_source).toBe('catalog')
    expect(s3.tick?.catalog.value_window).toBeTruthy()
  })

  it('틱 레시피는 틱 조건 진입 상태에서만 "그대로" 맞고, 아니면 모드가 바뀐다는 안내가 나온다', async () => {
    mockApi(routes({ 'GET /api/meta/recipes': { data: [...realRecipes, tickRecipe] } }))
    page()
    await userEvent.click(await screen.findByTestId('recipe-open'))
    const card = await screen.findByTestId('recipe-tick_value_burst')
    expect(within(card).getByText(/체결\(틱\) 모드로 바뀝니다/)).toBeInTheDocument()
  })

  const withEok = (): IndicatorCatalog => ({ ...realCatalog, indicators: [...realCatalog.indicators, { name: 'value_eok', label: '거래대금(억)', desc: '봉 거래대금(억 원)', params: [], modes: ['daily_single', 'daily_portfolio', 'intraday'], timing: 't 포함', compute: true, category: 'volume', category_ko: '거래량·순위', live: true, volume_based: true }] })

  it('거래대금(억) 지표와 비교하는 숫자 칸에는 "억" 이 붙는다', async () => {
    const { ConditionGroupEditor } = await import('@/components/builder/ConditionGroupEditor')
    const g = { logic: 'all' as const, items: [{ left: { kind: 'ind' as const, name: 'value_eok', params: {} }, op: 'gte' as const, right: { kind: 'const' as const, value: 20 } }] }
    renderApp(<ConditionGroupEditor title="t" path="strategy.entry" group={g} cat={withEok()} mode="intraday" errors={[]} onChange={() => {}} />)
    const right = await screen.findByTestId('operand-right')
    expect(within(right).getByText('억')).toBeInTheDocument()
    // 다른 지표와 비교하는 숫자에는 붙지 않는다
    const g2 = { logic: 'all' as const, items: [{ left: { kind: 'ind' as const, name: 'sma', params: { src: 'close', n: 20 } }, op: 'gte' as const, right: { kind: 'const' as const, value: 20 } }] }
    const { unmount } = renderApp(<ConditionGroupEditor title="t2" path="strategy.exit" group={g2} cat={withEok()} mode="intraday" errors={[]} onChange={() => {}} />)
    await waitFor(() => expect(screen.getAllByTestId('operand-right').length).toBeGreaterThan(1))
    expect(within(screen.getAllByTestId('operand-right')[1]).queryByText('억')).not.toBeInTheDocument()
    unmount()
  })

  const fullCaps = { ...realCatalog.capabilities!, tick_catalog_fields: ['breakout_min', 'value_speed', 'buy_ratio', 'trade_strength', 'block_trades', 'daily_breakout', 'value_window', 'time_from', 'time_to'] }
  const openTick2 = async (caps = fullCaps) => {
    const r = mockApi(routes({}, { ...realCatalog, capabilities: caps }))
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '체결(틱)' }))
    await screen.findByTestId('panel-tick')
    return r
  }

  it('서버가 알리면 체결강도·대량 체결·일봉 신고가 돌파·최근 체결대금(억) 조건이 나오고 값이 명세에 실린다', async () => {
    const { calls } = await openTick2()
    await userEvent.click(screen.getByTestId('tick-vwin-on'))
    await waitFor(() => expect(lastSpec(calls).tick?.catalog.value_window).toEqual({ w: 1, min_eok: 10 }))
    fireEvent.change(screen.getByTestId('tick-vwin-eok'), { target: { value: '25' } })
    await waitFor(() => expect(lastSpec(calls).tick?.catalog.value_window?.min_eok).toBe(25))
    await userEvent.click(screen.getByTestId('tick-block-on'))
    await waitFor(() => expect(lastSpec(calls).tick?.catalog.block_trades).toEqual({ w: 60, min_value: 100_000_000, min_count: 1 }))
    fireEvent.change(screen.getByTestId('tick-block-value'), { target: { value: '2' } }) // 억 → 원 으로 저장
    await waitFor(() => expect(lastSpec(calls).tick?.catalog.block_trades?.min_value).toBe(200_000_000))
    await userEvent.click(screen.getByTestId('tick-strength-on'))
    await userEvent.click(screen.getByTestId('tick-dbreak-on'))
    await waitFor(() => expect(lastSpec(calls).tick?.catalog).toMatchObject({ trade_strength: { w: 60, min: 150 }, daily_breakout: { n: 20 } }))
  })

  it('새 조건 하나만 켜도 "틱 조건이 하나도 없다" 오류가 뜨지 않는다(전에는 앞 세 조건만 세서 잘못 떴다)', async () => {
    await openTick2()
    await userEvent.click(screen.getByTestId('tick-breakout-on')) // 기본 고점 돌파 끄기
    expect(await screen.findByTestId('tick-no-cond')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('tick-vwin-on'))
    expect(screen.queryByTestId('tick-no-cond')).not.toBeInTheDocument()
  })

  it('서버가 알리지 않으면 새 조건 칸이 안 보인다(옛 서버)', async () => {
    const { tick_catalog_fields: _t, ...old } = fullCaps
    void _t
    await openTick2(old as typeof fullCaps)
    expect(screen.queryByTestId('tick-vwin-on')).not.toBeInTheDocument()
    expect(screen.queryByTestId('tick-block-on')).not.toBeInTheDocument()
  })
})

describe('거래대금(억)을 찾기 쉽게 (17:15 사용자 요청)', () => {
  const eokDef = (name: string, label: string, extra: Partial<IndicatorDef> = {}): IndicatorDef => ({ name, label, desc: `${label} 설명`, params: [], modes: ['daily_single', 'daily_portfolio', 'intraday'], timing: 't 포함', compute: true, category: 'volume', category_ko: '거래량·순위', live: true, volume_based: true, ...extra })
  const eokCatalog = (): IndicatorCatalog => ({ ...realCatalog, indicators: [...realCatalog.indicators, eokDef('value_eok', '거래대금(억)'), eokDef('value_sum_eok', '거래대금 합(억)', { params: [{ name: 'n', kind: 'int', default: 3, lo: 1, hi: 500, choices: null, label: '기간' }] }), eokDef('value_ratio', '거래대금 배수')] })

  it('"거래대금" 을 치면 원·억·합·배수가 종류와 상관없이 함께 나오고, 첫 그룹은 가격·거래량이다', async () => {
    const { operandFindOptions, matchesFind } = await import('@/lib/conditionFind')
    const all = operandFindOptions(eokCatalog(), 'intraday')
    expect(all[0].group).toBe('가격·거래량')
    const hit = all.filter((o) => matchesFind(o, '거래대금')).map((o) => o.label)
    expect(hit).toEqual(expect.arrayContaining(['거래대금', '거래대금 합(억)', '거래대금 배수']))
    expect(all.filter((o) => matchesFind(o, 'value')).map((o) => o.label)).toContain('거래대금') // 영문 필드 이름으로도
    expect(all.filter((o) => o.label === '거래대금')).toHaveLength(1) // 원·억 중복 없이 하나만
    expect(all.filter((o) => matchesFind(o, '없는말없는말'))).toEqual([])
  })

  it('찾기로 고르면 이전 조건의 시간 단위·며칠 전·배수를 유지한 채 바뀐다(필드 ↔ 억 ↔ 지표)', async () => {
    const { pickOperand } = await import('@/lib/conditionFind')
    const cat = eokCatalog()
    const prev = { kind: 'field' as const, name: 'close' as const, tf: 'm5', offset: 1, mul: 2 }
    const eok = pickOperand(cat, 'ind:value_eok', prev)
    expect(eok).toMatchObject({ kind: 'ind', name: 'value_eok', tf: 'm5', offset: 1, mul: 2 })
    const back = pickOperand(cat, 'field:value', eok)
    expect(back).toEqual({ kind: 'field', name: 'value', tf: 'm5', offset: 1, mul: 2 })
    expect('tf' in pickOperand(cat, 'field:high', { kind: 'field', name: 'close' })).toBe(false) // 없던 칸은 만들지 않는다
    expect(pickOperand(cat, 'ind:value_sum_eok', { kind: 'field', name: 'close' })).toMatchObject({ kind: 'ind', name: 'value_sum_eok', params: { n: 3 } }) // 기본 파라미터
  })

  it('빠른 조건: 모드에 맞는 것만, 분봉은 5분봉/전일 일봉 시간 단위를 붙인다(서버가 알릴 때)', async () => {
    const { quickConditionsFor } = await import('@/lib/conditionFind')
    const cat = eokCatalog()
    expect(quickConditionsFor(cat, 'daily_portfolio').map((q) => q.key)).toEqual(['value_eok', 'new_high', 'above_ma', 'vol_ratio']) // VWAP 은 분봉 전용
    const intra = quickConditionsFor(cat, 'intraday')
    expect(intra.map((q) => q.key)).toContain('above_vwap')
    const v = intra.find((q) => q.key === 'value_eok')!
    expect(v.build(1, true)).toMatchObject({ left: { name: 'value_eok', tf: 'm5' }, op: 'gte', right: { value: 20 } })
    expect('tf' in v.build(5, true).left).toBe(false) // 실행 봉이 5분이면 "이 봉" 이 5분봉
    expect('tf' in v.build(1, false).left).toBe(false) // 서버가 시간 단위를 모르면 안 붙인다
    expect(intra.find((q) => q.key === 'new_high')!.build(5, true)).toMatchObject({ right: { name: 'highest', tf: 'daily_prev' } })
    expect(quickConditionsFor({ ...cat, indicators: cat.indicators.filter((d) => d.name !== 'value_eok') }, 'intraday').map((q) => q.key)).not.toContain('value_eok') // 카탈로그에 없는 지표는 뺀다
  })

  it('버튼 하나로 진입 조건 행이 채워져 들어간다(분봉 5분봉 거래대금 20억)', async () => {
    const { calls } = mockApi(routes({}, eokCatalog()))
    page()
    await userEvent.click(await screen.findByRole('tab', { name: '분봉 단타' }))
    await screen.findByTestId('panel-intraday')
    await userEvent.click(within(screen.getByTestId('bar-minutes')).getByText('1분')) // 실행 봉 1분 → "5분봉" 시간 단위가 붙는다
    await waitFor(() => expect(lastSpec(calls).intraday?.bar_minutes).toBe(1))
    const before = (lastSpec(calls).strategy as { entry: { items: unknown[] } }).entry.items.length
    await userEvent.click(await screen.findByTestId('quick-value_eok'))
    await waitFor(() => {
      const items = (lastSpec(calls).strategy as { entry: { items: Condition[] } }).entry.items
      expect(items).toHaveLength(before + 1)
      expect(items[items.length - 1]).toMatchObject({ left: { kind: 'ind', name: 'value_eok', tf: 'm5' }, op: 'gte', right: { kind: 'const', value: 20 } })
    })
    expect(screen.getByTestId('quick-above_vwap')).toBeInTheDocument()
  })

  it('"가격·거래량" 목록에 "거래대금" 하나만(억 기준) 보이고, 고르면 지표 value_eok 로 바뀐다(원 단위는 숨김)', async () => {
    const { calls } = mockApi(routes({}, eokCatalog()))
    page()
    await screen.findByTestId('group-strategy.entry')
    const left = within(screen.getByTestId('group-strategy.entry')).getAllByTestId('operand-left-field')[0]
    await userEvent.click(within(left).getByRole('combobox'))
    const shown = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')].pop() as HTMLElement
    expect(shown).not.toHaveTextContent('거래대금(원)') // 원 단위 필드는 목록에서 숨김
    expect(shown).toHaveTextContent('거래대금')
    await userEvent.click(within(shown).getAllByText('거래대금').find((e) => e.closest('.ant-select-item-option'))!)
    await waitFor(() => expect((lastSpec(calls).strategy as { entry: { items: Condition[] } }).entry.items[0].left).toMatchObject({ kind: 'ind', name: 'value_eok' }))
    // 바뀐 뒤에도 "가격·거래량" 쪽에 그대로 보인다(종류 칸도 가격·거래량)
    const entry = screen.getByTestId('group-strategy.entry')
    await waitFor(() => expect(within(within(entry).getAllByTestId('operand-left')[0]).getAllByText('거래대금').length).toBeGreaterThan(0))
  })

  it('조건 한쪽의 "찾아서 고르기" 에서 "거래대금" 을 검색해 억을 고른다', async () => {
    const { calls } = mockApi(routes({}, eokCatalog()))
    page()
    await screen.findByTestId('group-strategy.entry')
    const find = within(screen.getByTestId('group-strategy.entry')).getAllByTestId('operand-left-find')[0]
    await userEvent.click(within(find).getByRole('combobox'))
    await userEvent.type(within(find).getByRole('combobox'), '거래대금')
    const shown = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')].pop() as HTMLElement
    await waitFor(() => expect(shown).toHaveTextContent('거래대금'))
    expect(shown).not.toHaveTextContent('거래대금(원)')
    expect(shown).not.toHaveTextContent('종가') // 검색어와 무관한 것은 걸러진다
    await userEvent.click(within(shown).getAllByText('거래대금').find((e) => e.closest('.ant-select-item-option'))!)
    await waitFor(() => expect((lastSpec(calls).strategy as { entry: { items: Condition[] } }).entry.items[0].left).toMatchObject({ kind: 'ind', name: 'value_eok' }))
  })
})

describe('금액·수량 왼쪽이면 오른쪽이 숫자 입력칸으로 자동 전환 (17:50 긴급)', () => {
  const eokDef = (name: string, label: string): IndicatorDef => ({ name, label, desc: label, params: [], modes: ['daily_single', 'daily_portfolio', 'intraday'], timing: 't 포함', compute: true, category: 'volume', category_ko: '거래량·순위', live: true, volume_based: true })
  const eokCatalog = (): IndicatorCatalog => ({ ...realCatalog, indicators: [...realCatalog.indicators, eokDef('value_eok', '거래대금(억)')] })
  const sm = { kind: 'ind' as const, name: 'sma', params: { src: 'close', n: 20 } }
  const cond = (left: Condition['left'], right: Condition['right']): Condition => ({ left, op: 'gt', right })
  type Calls = { path: string; body: unknown }[]
  const items = (calls: Calls) => (lastSpec(calls).strategy as { entry: { items: Condition[] } }).entry.items

  it('단위 판별: 가격·억·원·주, 모르면 null', async () => {
    const { operandUnit } = await import('@/lib/conditionUnits')
    expect([operandUnit({ kind: 'field', name: 'close' }), operandUnit({ kind: 'field', name: 'value' }), operandUnit({ kind: 'field', name: 'volume' }), operandUnit({ kind: 'ind', name: 'value_eok' }), operandUnit(sm), operandUnit({ kind: 'ind', name: 'rsi', params: { n: 14 } }), operandUnit({ kind: 'const', value: 3 })])
      .toEqual(['price', 'won', 'shares', 'eok', 'price', 'plain', null])
  })

  it('왼쪽이 거래대금(억)으로 바뀌면 안 맞는 오른쪽(가격 지표)은 숫자 20 으로, 거래량은 비운 숫자로', async () => {
    const { harmonizeRight } = await import('@/lib/conditionUnits')
    const st = () => ({ picked: false, auto: false })
    const r = harmonizeRight(cond({ kind: 'ind', name: 'value_eok' }, sm), { kind: 'field', name: 'close' }, st())
    expect(r.cond.right).toEqual({ kind: 'const', value: 20 })
    expect(r.switched && r.auto).toBe(true)
    const won = harmonizeRight(cond({ kind: 'field', name: 'value' }, sm), { kind: 'field', name: 'close' }, st())
    expect(won.cond.right).toEqual({ kind: 'const', value: 1_000_000_000 })
    const vol = harmonizeRight(cond({ kind: 'field', name: 'volume' }, { kind: 'field', name: 'close' }), { kind: 'field', name: 'close' }, st())
    expect(vol.cond.right).toEqual({ kind: 'const', value: null })
    expect(harmonizeRight(cond({ kind: 'ind', name: 'value_eok' }, { kind: 'const', value: 5 }), { kind: 'field', name: 'close' }, st()).cond.right).toEqual({ kind: 'const', value: 5 })
    expect(harmonizeRight(cond({ kind: 'ind', name: 'value_eok' }, { kind: 'ind', name: 'value_eok' }), { kind: 'field', name: 'close' }, st()).switched).toBe(false)
  })

  it('사용자가 오른쪽을 직접 고른 뒤에는 덮어쓰지 않고, 자동으로 바꿔 둔 것만 가격 계열로 돌아오면 되돌린다', async () => {
    const { harmonizeRight } = await import('@/lib/conditionUnits')
    const picked = harmonizeRight(cond({ kind: 'ind', name: 'value_eok' }, sm), { kind: 'field', name: 'close' }, { picked: true, auto: false })
    expect(picked.cond.right).toEqual(sm)
    const back = harmonizeRight(cond({ kind: 'field', name: 'close' }, { kind: 'const', value: 20 }), { kind: 'ind', name: 'value_eok' }, { picked: false, auto: true })
    expect(back.cond.right).toMatchObject({ kind: 'ind', name: 'highest' })
    expect(back.auto).toBe(false)
    expect(harmonizeRight(cond({ kind: 'field', name: 'close' }, { kind: 'const', value: 20 }), { kind: 'ind', name: 'value_eok' }, { picked: false, auto: false }).cond.right).toEqual({ kind: 'const', value: 20 })
  })

  it('단위가 다른 두 값을 비교하면 경고 문구, 상수·모르는 단위는 통과', async () => {
    const { unitMismatch, specUnitWarnings } = await import('@/lib/conditionUnits')
    expect(unitMismatch(cond({ kind: 'ind', name: 'value_eok' }, sm))).toContain('왼쪽은 억, 오른쪽은 원(가격)')
    expect(unitMismatch(cond({ kind: 'ind', name: 'value_eok' }, { kind: 'const', value: 20 }))).toBeNull()
    expect(unitMismatch(cond({ kind: 'ind', name: 'rsi', params: { n: 14 } }, { kind: 'const', value: 30 }))).toBeNull()
    expect(unitMismatch(cond({ kind: 'ind', name: 'rsi', params: { n: 14 } }, sm))).toContain('가격') // 점수 vs 가격
    expect(unitMismatch(cond({ kind: 'ind', name: 'change_pct', params: { n: 1 } }, { kind: 'ind', name: 'rsi', params: { n: 14 } }))).toBeNull() // 점수·퍼센트끼리는 뜻이 넓어 경고 안 함
    const s = newSpec('intraday')
    s.strategy = { source: 'builder', entry: { logic: 'all', items: [cond({ kind: 'ind', name: 'value_eok' }, sm)] }, exit: { logic: 'any', items: [] } }
    expect(specUnitWarnings(s)).toHaveLength(1)
  })

  const pickLeft = async (_calls: Calls, label: string) => {
    const entry = await screen.findByTestId('group-strategy.entry')
    const left = within(entry).getAllByTestId('operand-left-field')[0]
    await userEvent.click(within(left).getByRole('combobox'))
    const shown = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')].pop() as HTMLElement
    await userEvent.click(within(shown).getAllByText(label).find((e) => e.closest('.ant-select-item-option'))!)
    return entry
  }

  it('화면: 거래대금(억)을 고르면 오른쪽이 바로 "[20] 억" 입력칸이 되고 포커스가 간다 — 30 으로 고치면 명세에 실린다', async () => {
    const { calls } = mockApi(routes({}, eokCatalog()))
    page()
    const entry = await pickLeft(calls, '거래대금')
    await waitFor(() => expect(items(calls)[0].left).toMatchObject({ kind: 'ind', name: 'value_eok' }))
    const c = () => within(entry).getAllByTestId('operand-right-const')[0] as HTMLInputElement
    await waitFor(() => expect(c()).toBeInTheDocument())
    expect(c().value).toBe('20')
    await waitFor(() => expect(document.activeElement).toBe(c()))
    expect(within(within(entry).getAllByTestId('operand-right')[0]).getByText('억')).toBeInTheDocument()
    expect(items(calls)[0].right).toEqual({ kind: 'const', value: 20 })
    fireEvent.change(c(), { target: { value: '30' } })
    await waitFor(() => expect(items(calls)[0].right).toEqual({ kind: 'const', value: 30 }))
    expect(screen.queryByTestId('unit-warning')).not.toBeInTheDocument()
  })

  it('화면: 왼쪽을 종가로 되돌리면 자동으로 바꿔 둔 오른쪽이 원래 N봉 최고값으로 돌아온다', async () => {
    const { calls } = mockApi(routes({}, eokCatalog()))
    page()
    await pickLeft(calls, '거래대금')
    await waitFor(() => expect(items(calls)[0].left).toMatchObject({ name: 'value_eok' }))
    await pickLeft(calls, '종가')
    await waitFor(() => expect(items(calls)[0].right).toMatchObject({ kind: 'ind', name: 'highest' }))
  })

  it('화면: 사용자가 오른쪽을 직접 골라 둔 뒤엔 왼쪽을 억으로 바꿔도 덮어쓰지 않고 경고가 뜬다(행 + 검증 패널)', async () => {
    const { calls } = mockApi(routes({}, eokCatalog()))
    page()
    const entry = await screen.findByTestId('group-strategy.entry')
    const rk = within(entry).getAllByTestId('operand-right-ind')[0]
    await userEvent.click(within(rk).getByRole('combobox'))
    const dd = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')].pop() as HTMLElement
    await userEvent.click(within(dd).getAllByText('N봉 최저값').find((e) => e.closest('.ant-select-item-option'))!)
    await waitFor(() => expect(items(calls)[0].right).toMatchObject({ name: 'lowest' }))
    await pickLeft(calls, '거래대금')
    await waitFor(() => expect(items(calls)[0].left).toMatchObject({ name: 'value_eok' }))
    expect(items(calls)[0].right).toMatchObject({ kind: 'ind', name: 'lowest' })
    expect(await screen.findByTestId('unit-warning')).toHaveTextContent('단위가 다른 값을 비교')
    expect(screen.getByTestId('unit-warnings')).toHaveTextContent('1건')
  })
})


describe('옛 명세의 거래대금(원) 조건은 불러올 때 억으로 바꿔 보인다 (17:58 lead 요청)', () => {
  const eokDef: IndicatorDef = { name: 'value_eok', label: '거래대금(억)', desc: '거래대금(억)', params: [], modes: ['daily_single', 'daily_portfolio', 'intraday'], timing: 't 포함', compute: true, category: 'volume', category_ko: '거래량·순위', live: true, volume_based: true }
  const eokCatalog = (): IndicatorCatalog => ({ ...realCatalog, indicators: [...realCatalog.indicators, eokDef] })
  const legacy = (): SpecJson => {
    const s = newSpec('daily_portfolio')
    s.strategy = { source: 'builder', entry: { logic: 'all', items: [
      { left: { kind: 'field', name: 'value', tf: 'daily' }, op: 'gte', right: { kind: 'const', value: 3_000_000_000 } },
      { left: { kind: 'const', value: 1_000_000_000 }, op: 'lt', right: { kind: 'field', name: 'value' } },
      { left: { kind: 'field', name: 'close' }, op: 'gt', right: { kind: 'field', name: 'open' } },
    ] }, exit: { logic: 'any', items: [] } }
    return s
  }

  it('field:value vs 숫자는 value_eok vs 숫자÷1억 로(시간 단위 유지), 그 밖의 조건·변수 숫자는 그대로', async () => {
    const { modernizeLegacyValue } = await import('@/lib/conditionUnits')
    const s = legacy()
    const r = modernizeLegacyValue(s, () => true)
    const it = (r.spec.strategy as { entry: { items: Condition[] } }).entry.items
    expect(r.changed).toBe(2)
    expect(it[0]).toMatchObject({ left: { kind: 'ind', name: 'value_eok', tf: 'daily' }, right: { kind: 'const', value: 30 } })
    expect(it[1]).toMatchObject({ left: { kind: 'const', value: 10 }, right: { kind: 'ind', name: 'value_eok' } })
    expect(it[2]).toEqual((s.strategy as { entry: { items: Condition[] } }).entry.items[2])
    expect(modernizeLegacyValue(s, () => false).changed).toBe(0) // 억 지표를 못 쓰는 모드·서버면 손대지 않는다
    expect(modernizeLegacyValue(r.spec, () => true).changed).toBe(0) // 두 번 돌려도 그대로
    const p = legacy(); const pi = (p.strategy as { entry: { items: Condition[] } }).entry.items
    pi[0].right = { kind: 'const', value: { param: 'min_value' } } as never
    expect(modernizeLegacyValue(p, () => true).changed).toBe(1) // 변수 숫자(param)는 못 바꿔 그대로 둔다
  })

  it('화면: 프리셋으로 불러오면 조건이 억 기준 "거래대금 ≥ 30억" 으로 보이고 안내가 뜬다', async () => {
    const { calls } = mockApi(routes({ 'GET /api/presets/old_value': { data: { name: 'old_value', spec: legacy() } } }, eokCatalog()))
    renderApp(<Routes><Route path="/backtest" element={<BacktestPage />} /></Routes>, '/backtest?preset=old_value')
    expect(await screen.findByTestId('load-note')).toHaveTextContent('억 단위로 바꿔')
    await waitFor(() => expect((lastSpec(calls).strategy as { entry: { items: Condition[] } }).entry.items[0]).toMatchObject({ left: { kind: 'ind', name: 'value_eok' }, right: { kind: 'const', value: 30 } }))
    const entry = screen.getByTestId('group-strategy.entry')
    expect(within(within(entry).getAllByTestId('operand-right')[0]).getByText('억')).toBeInTheDocument()
  })
})


describe('가격이 아닌 단위 지표 전부 — 오른쪽이 숫자칸으로 자동 전환 (18:20 lead 요청: "1분봉에 1% 상승시 진입")', () => {
  const sm = { kind: 'ind' as const, name: 'sma', params: { src: 'close', n: 20 } }
  const cond = (left: Condition['left'], right: Condition['right'], op: Condition['op'] = 'gt'): Condition => ({ left, op, right })
  const fresh = () => ({ picked: false, auto: false })
  const items = (calls: { path: string; body: unknown }[]) => (lastSpec(calls).strategy as { entry: { items: Condition[] } }).entry.items
  const close = { kind: 'field' as const, name: 'close' as const }

  it('지표별 기본값·단위 글자: 등락률 1% · 몸통 3% · RSI 30 · 순위 20위 · 연속 봉 3봉 · 거래량 배수 3배', async () => {
    const { harmonizeRight, operandSuffix } = await import('@/lib/conditionUnits')
    const rows: [string, number, string | undefined][] = [['change_pct', 1, '%'], ['body_pct', 3, '%'], ['rsi', 30, undefined], ['value_rank', 20, '위'], ['up_streak', 3, '봉'], ['vol_ratio', 3, '배'], ['minutes_since_open', 30, '분'], ['day_change_pct', 1, '%']]
    for (const [name, def, suffix] of rows) {
      const left = { kind: 'ind' as const, name, params: {} }
      const r = harmonizeRight(cond(left, sm), close, fresh())
      expect([name, r.cond.right]).toEqual([name, { kind: 'const', value: def }])
      expect([name, r.auto, operandSuffix(left)]).toEqual([name, true, suffix])
    }
  })

  it('1/0 지표(정배열 등)는 "참이면" 연산자로 — 가격 쪽으로 돌아오면 초과 + 기본 오른쪽으로', async () => {
    const { harmonizeRight } = await import('@/lib/conditionUnits')
    const flag = harmonizeRight(cond({ kind: 'ind', name: 'ma_aligned', params: {} }, sm), close, fresh())
    expect(flag.cond.op).toBe('is_true')
    expect(flag.cond.right).toBeUndefined()
    expect(flag.auto).toBe(true)
    const back = harmonizeRight({ ...flag.cond, left: close }, { kind: 'ind', name: 'ma_aligned', params: {} }, { picked: false, auto: true })
    expect(back.cond.op).toBe('gt')
    expect(back.cond.right).toMatchObject({ kind: 'ind', name: 'highest' })
    expect(back.auto).toBe(false)
    const own = harmonizeRight(cond({ kind: 'ind', name: 'ma_aligned', params: {} }, sm, 'is_true'), close, fresh()) // 사용자가 직접 "참이면" 을 골랐으면 그대로
    expect(own.switched).toBe(false)
  })

  it('가격 단위(종가·이평·최고가)면 지표 비교 그대로, 직접 고른 오른쪽은 안 덮고, 자동으로 넣은 숫자는 다른 지표로 바꾸면 그 지표 기본값으로', async () => {
    const { harmonizeRight } = await import('@/lib/conditionUnits')
    expect(harmonizeRight(cond(close, sm), { kind: 'ind', name: 'rsi', params: {} }, fresh()).cond.right).toEqual(sm)
    expect(harmonizeRight(cond({ kind: 'ind', name: 'rsi', params: {} }, sm), close, { picked: true, auto: false }).cond.right).toEqual(sm)
    const rsi = { kind: 'ind' as const, name: 'rsi', params: {} }
    const first = harmonizeRight(cond(rsi, sm), close, fresh())
    const next = harmonizeRight({ ...first.cond, left: { kind: 'ind', name: 'change_pct', params: { n: 1 } } }, rsi, { picked: false, auto: first.auto })
    expect(next.cond.right).toEqual({ kind: 'const', value: 1 })
    const same = harmonizeRight({ ...first.cond, left: { ...rsi, params: { n: 9 } } }, rsi, { picked: false, auto: first.auto }) // 같은 지표의 기간만 바꾸면 그대로
    expect(same.cond.right).toEqual({ kind: 'const', value: 30 })
  })

  const pickFind = async (label: string) => {
    const entry = await screen.findByTestId('group-strategy.entry')
    const find = within(entry).getAllByTestId('operand-left-find')[0]
    await userEvent.click(within(find).getByRole('combobox'))
    await userEvent.type(within(find).getByRole('combobox'), label)
    const shown = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')].pop() as HTMLElement
    await userEvent.click(within(shown).getAllByText(label).find((e) => e.closest('.ant-select-item-option'))!)
    return entry
  }

  it.each([['N봉 등락률(%)', 'change_pct', '1', '%'], ['RSI', 'rsi', '30', null], ['몸통(%)', 'body_pct', '3', '%']])('화면: %s 를 고르면 오른쪽이 바로 숫자칸(기본 %s)이 된다', async (label, name, def, suffix) => {
    const body: IndicatorDef = { name: 'body_pct', label: '몸통(%)', desc: '몸통 크기', params: [], modes: ['daily_single', 'daily_portfolio', 'intraday'], timing: 't 포함', compute: true, category: 'trend', category_ko: '추세', live: true, volume_based: false }
    const { calls } = mockApi(routes({}, { ...realCatalog, indicators: [...realCatalog.indicators, body] }))
    page()
    const entry = await pickFind(label)
    await waitFor(() => expect(items(calls)[0].left).toMatchObject({ kind: 'ind', name }))
    const c = () => within(entry).getAllByTestId('operand-right-const')[0] as HTMLInputElement
    await waitFor(() => expect(c().value).toBe(def))
    if (suffix) expect(within(within(entry).getAllByTestId('operand-right')[0]).getByText(suffix)).toBeInTheDocument()
    expect(items(calls)[0].right).toEqual({ kind: 'const', value: Number(def) })
    fireEvent.change(c(), { target: { value: '2' } })
    await waitFor(() => expect(items(calls)[0].right).toEqual({ kind: 'const', value: 2 }))
  })

  it('화면: 정배열(1/0) 을 고르면 연산자가 "참이면" 이 되고 오른쪽 칸이 없어진다', async () => {
    const { calls } = mockApi(routes())
    page()
    const entry = await pickFind('정배열(1/0)')
    await waitFor(() => expect(items(calls)[0].op).toBe('is_true'))
    expect(within(entry).queryAllByTestId('operand-right')).toHaveLength(0)
  })
})


describe('문장 빈칸 채우기 카드 (설계서 §5.5, c10)', () => {
  const tf = { name: 'tf', kind: 'tf', label: '어떤 봉으로 볼까요?', default: 'bar', choices: [{ value: 'bar', label: '지금 보는 봉', enabled: true, reason: null }, { value: 'm5', label: '5분봉', enabled: true, reason: null }, { value: 'daily_live', label: '오늘 지금까지 반영한 일봉', enabled: false, reason: '통합 분봉에서는 못 써요' }] }
  const TPLS = {
    mode: 'daily_portfolio', bar_minutes: 5, source: 'al',
    categories: [{ key: 'volume', label: '거래량·거래대금' }, { key: 'candle', label: '오르내림·캔들' }, { key: 'exit', label: '팔 때(청산)' }],
    templates: [
      { id: 'value_eok', category: 'volume', category_label: '거래량·거래대금', sentence: '{tf}거래대금이 {x}억 {cmp}', example: '거래대금이 20억 이상이다', hint: '한 봉 동안 오간 돈이에요.', warn: '', tags: ['거래대금', '억'], role: 'both', available: true, reason: '',
        slots: [tf, { name: 'x', kind: 'number', label: '몇 억', default: 20, unit: '억', lo: 0.1, hi: 100000, integer: false }, { name: 'cmp', kind: 'choice', label: '이상 / 이하', default: 'gte', choices: [{ value: 'gte', label: '이상이다', enabled: true, reason: null }, { value: 'lte', label: '이하다', enabled: true, reason: null }] }] },
      { id: 'change_up', category: 'candle', category_label: '오르내림·캔들', sentence: '{tf}가격이 직전 {봉}보다 {x}% 이상 올랐다', example: '가격이 직전 봉보다 1% 이상 올랐다', hint: '바로 앞 봉보다 몇 % 올랐는지 봐요.', warn: '', tags: ['급등'], role: 'both', available: true, reason: '',
        slots: [{ name: 'x', kind: 'number', label: '몇 %', default: 1, unit: '%', lo: 0.1, hi: 30, integer: false }] },
      { id: 'pos_profit', category: 'exit', category_label: '팔 때(청산)', sentence: '산 가격보다 {x}% 이상 올랐다(수익)', example: '산 가격보다 5% 이상 올랐다(수익)', hint: '수익이 나면 팔아요.', warn: '', tags: ['익절'], role: 'exit', available: true, reason: '',
        slots: [{ name: 'x', kind: 'number', label: '몇 %', default: 5, unit: '%', lo: 0.1, hi: 1000, integer: false }] },
      { id: 'env_up', category: 'candle', category_label: '오르내림·캔들', sentence: '{tf}가격이 엔벨로프({n}봉) 위쪽 선을 넘었다', example: '가격이 엔벨로프(20봉) 위쪽 선을 넘었다', hint: '엔벨로프 위쪽 선을 뚫으면 참이에요.', warn: '', tags: ['엔벨로프', 'envelope_upper'], role: 'both', available: true, reason: '', auto: true,
        slots: [{ name: 'n', kind: 'number', label: '몇 봉', default: 20, unit: '봉', lo: 2, hi: 500, integer: true }] },
      { id: 'cum_value', category: 'volume', category_label: '거래량·거래대금', sentence: '오늘 지금까지 거래대금이 {x}억 이상이다', example: '오늘 지금까지 거래대금이 100억 이상이다', hint: '오늘 누적이에요.', warn: '', tags: ['누적'], role: 'both', available: false, reason: '분봉 실행에서만 쓸 수 있어요', slots: [] },
    ],
  }
  const eokCond = (x: number, cmp = 'gte'): Condition => ({ left: { kind: 'ind', name: 'value_eok', params: {} }, op: cmp as Condition['op'], right: { kind: 'const', value: x } })
  const num = (c: Condition) => (c.right as { value: number }).value
  const tplRoutes = (over: Record<string, Parameters<typeof mockApi>[0][string]> = {}) => routes({
    'GET /api/meta/condition-templates': { data: TPLS },
    'POST /api/meta/condition-templates/build': (call) => {
      const b = call.body as { id: string; values?: Record<string, number | string> }
      const v = { x: b.id === 'change_up' ? 1 : 20, cmp: 'gte', ...b.values } as Record<string, number | string>
      if (b.id === 'value_eok') return { data: { condition: eokCond(v.x as number, String(v.cmp)), sentence: `거래대금이 ${v.x}억 이상이다`, values: v } }
      return { data: { condition: { left: { kind: 'ind', name: 'change_pct', params: { n: 1 } }, op: 'gte', right: { kind: 'const', value: v.x as number } }, sentence: `가격이 직전 봉보다 ${v.x}% 이상 올랐다`, values: v } }
    },
    'POST /api/meta/condition-templates/match': (call) => ({
      data: (call.body as { conditions: Condition[] }).conditions.map((c) => (c.left.kind === 'ind' && c.left.name === 'value_eok' ? { id: 'value_eok', category: 'volume', values: { x: num(c), cmp: c.op }, sentence: `거래대금이 ${num(c)}억 이상이다` }
        : c.right?.kind === 'ind' && c.right.name === 'envelope_upper' ? { id: 'env_up', category: 'candle', values: { n: 20 }, sentence: '가격이 엔벨로프(20봉) 위쪽 선을 넘었다' }
        : c.left.kind === 'ind' && c.left.name === 'change_pct' ? { id: 'change_up', category: 'candle', values: { x: num(c) }, sentence: '가격이 직전 봉보다 이상 올랐다' } : null)),
    }),
    ...over,
  })
  const entryItems = (calls: { path: string; body: unknown }[]) => (lastSpec(calls).strategy as { entry: { items: Condition[] } }).entry.items
  const pickTemplate = async (search: string, id: string) => {
    await userEvent.click(await screen.findByTestId('cards-strategy.entry-add'))
    const picker = await screen.findByTestId('tpl-picker')
    await userEvent.type(within(picker).getByRole('searchbox'), search)
    await userEvent.click(await within(picker).findByTestId(`tpl-${id}`))
  }

  it('서버가 문장 카드를 지원하면 카드 화면이 기본 — "모두 만족하면 산다", 문장에 안 맞는 옛 조건은 그대로 고칠 수 있는 행으로', async () => {
    mockApi(tplRoutes())
    page()
    const box = await screen.findByTestId('cards-strategy.entry')
    expect(box).toHaveTextContent('모두 만족하면 산다')
    expect(await screen.findByTestId('cards-strategy.exit')).toHaveTextContent('모두 만족하면 판다')
    expect(await within(box).findByTestId('card-strategy.entry.0-plain')).toHaveTextContent('문장 카드로 나타낼 수 없는')
    expect(screen.queryByTestId('group-strategy.entry')).not.toBeInTheDocument()
  })

  it('[조건 추가] → 검색 → 문장을 고르면 카드가 붙고 명세에 조건이 실린다 · 빈칸을 고치면 서버가 만든 조건으로 바뀐다', async () => {
    const { calls } = mockApi(tplRoutes())
    page()
    await pickTemplate('거래대금', 'value_eok')
    const card = await screen.findByTestId('card-value_eok')
    expect(within(card).getByTestId('card-sentence')).toHaveTextContent('거래대금이')
    const x = within(card).getByTestId('card-slot-x') as HTMLInputElement
    await waitFor(() => expect(x.value).toBe('20'))
    expect(card).toHaveTextContent('억')
    expect(card).toHaveTextContent('한 봉 동안 오간 돈이에요.') // 서버가 준 쉬운 설명
    await waitFor(() => expect(entryItems(calls).some((c) => c.left.kind === 'ind' && c.left.name === 'value_eok')).toBe(true))
    fireEvent.change(x, { target: { value: '30' } })
    await waitFor(() => expect(entryItems(calls).find((c) => c.left.kind === 'ind' && c.left.name === 'value_eok')?.right).toEqual({ kind: 'const', value: 30 }), { timeout: 4000 })
    const built = calls.filter((c) => c.path.endsWith('/build')).pop()!.body as { id: string; values: Record<string, number> }
    expect([built.id, built.values.x]).toEqual(['value_eok', 30])
  })

  it('못 쓰는 문장은 회색 + 이유, 청산 전용 문장은 진입 목록엔 없고 청산 목록에만 있다, 검색으로 좁혀진다', async () => {
    mockApi(tplRoutes())
    page()
    await userEvent.click(await screen.findByTestId('cards-strategy.entry-add'))
    const picker = await screen.findByTestId('tpl-picker')
    // 처음 열면 분류를 접지 않고 전부 보인다(사용자 규칙: 정보는 접지 말고 다 보여주기)
    for (const id of ['value_eok', 'change_up', 'env_up', 'cum_value']) expect(within(picker).getByTestId(`tpl-${id}`)).toBeInTheDocument()
    expect(within(picker).getByTestId('tpl-count')).toHaveTextContent('전부 아래에')
    expect(within(picker).getByTestId('tpl-cum_value')).toHaveAttribute('aria-disabled', 'true')
    expect(within(picker).queryByTestId('tpl-pos_profit')).not.toBeInTheDocument()
    await userEvent.type(within(picker).getByRole('searchbox'), '급등')
    expect(within(picker).queryByTestId('tpl-value_eok')).not.toBeInTheDocument()
    expect(within(picker).getByTestId('tpl-change_up')).toBeInTheDocument()
  })

  it('청산 자리의 [조건 추가] 목록에는 청산 전용 문장이 나온다', async () => {
    mockApi(tplRoutes())
    page()
    await userEvent.click(await screen.findByTestId('cards-strategy.exit-add'))
    expect(await screen.findByTestId('tpl-pos_profit')).toBeInTheDocument()
  })

  it('분류 버튼은 그 분류로 스크롤만 한다 — 다른 분류를 숨기지 않는다', async () => {
    mockApi(tplRoutes())
    page()
    await userEvent.click(await screen.findByTestId('cards-strategy.entry-add'))
    const picker = await screen.findByTestId('tpl-picker')
    const scrollTo = vi.fn()
    ;(within(picker).getByTestId('tpl-list') as HTMLElement).scrollTo = scrollTo
    await userEvent.click(within(picker).getByTestId('tpl-cat-candle'))
    expect(scrollTo).toHaveBeenCalledTimes(1)
    for (const g of ['volume', 'candle']) expect(within(picker).getByTestId(`tpl-group-${g}`)).toBeInTheDocument()
    expect(within(picker).getByTestId('tpl-value_eok')).toBeInTheDocument()
    expect(within(picker).getByTestId('tpl-cat-volume')).toHaveTextContent('거래량·거래대금 (')
  })

  it('검색: 낱말이 전부 들어간 문장만(태그의 지표 이름도), 맞는 분류는 저절로 펼쳐지고 자동 문장에는 "기본 문장" 표시 — 고르면 카드에도 표시', async () => {
    mockApi(tplRoutes({ 'POST /api/meta/condition-templates/build': (call) => (call.body as { id: string }).id === 'env_up'
      ? { data: { condition: { left: { kind: 'field', name: 'close' }, op: 'gt', right: { kind: 'ind', name: 'envelope_upper', params: { n: 20 } } }, sentence: '가격이 엔벨로프(20봉) 위쪽 선을 넘었다', values: { n: 20 } } } : { data: { condition: eokCond(20), sentence: 'x', values: {} } } }))
    page()
    await userEvent.click(await screen.findByTestId('cards-strategy.entry-add'))
    const picker = await screen.findByTestId('tpl-picker')
    await userEvent.type(within(picker).getByRole('searchbox'), 'ENVELOPE_upper 위쪽')
    const row = await within(picker).findByTestId('tpl-env_up')
    expect(row).toHaveTextContent('기본 문장')
    expect(within(picker).queryByTestId('tpl-value_eok')).not.toBeInTheDocument()
    expect(within(picker).getByTestId('tpl-count')).toHaveTextContent('1개 문장이 맞아요')
    await userEvent.click(row)
    const card = await screen.findByTestId('card-env_up', {}, { timeout: 4000 })
    expect(within(card).getByTestId('card-auto')).toHaveTextContent('기본 문장')
  })

  it('빈칸 값이 틀리면 서버가 알린 쉬운 말이 카드에 빨갛게 뜨고 명세는 안 바뀐다', async () => {
    const { calls } = mockApi(tplRoutes({ 'POST /api/meta/condition-templates/build': (call) => {
      const b = call.body as { values?: { x?: number } }
      return (b.values?.x ?? 0) >= 77 ? { status: 400, error: { code: 'VALIDATION_ERROR', message: '요청 값이 올바르지 않음', details: { fieldErrors: { x: '이 값은 너무 커요' } } } }
        : { data: { condition: eokCond(b.values?.x ?? 20), sentence: '거래대금이 20억 이상이다', values: { x: b.values?.x ?? 20, cmp: 'gte' } } }
    } }))
    page()
    await pickTemplate('거래대금', 'value_eok')
    const card = await screen.findByTestId('card-value_eok')
    await waitFor(() => expect((within(card).getByTestId('card-slot-x') as HTMLInputElement).value).toBe('20'))
    await waitFor(() => expect(entryItems(calls).some((c) => c.left.kind === 'ind' && c.left.name === 'value_eok')).toBe(true))
    fireEvent.change(within(card).getByTestId('card-slot-x'), { target: { value: '77' } })
    expect(await within(card).findByTestId('card-error', {}, { timeout: 4000 })).toHaveTextContent('이 값은 너무 커요')
    expect(entryItems(calls).find((c) => c.left.kind === 'ind' && c.left.name === 'value_eok')?.right).toEqual({ kind: 'const', value: 20 })
  })

  it('"직접 조립(고급)" 으로 바꾸면 옛 조립기가 그대로 나오고, 다시 문장으로 돌아올 수 있다', async () => {
    mockApi(tplRoutes())
    page()
    const box = await screen.findByTestId('cards-strategy.entry')
    await userEvent.click(within(within(box).getByTestId('cards-strategy.entry-view')).getByText('직접 조립(고급)'))
    expect(await screen.findByTestId('group-strategy.entry')).toBeInTheDocument()
    await userEvent.click(within(screen.getByTestId('cards-strategy.entry-view')).getByText('문장으로 만들기'))
    expect(await screen.findByTestId('cards-strategy.entry-add')).toBeInTheDocument()
  })

  it('서버가 문장 카드를 모르면(404) 옛 조립기가 그대로 나온다', async () => {
    mockApi(routes())
    page()
    expect(await screen.findByTestId('group-strategy.entry')).toBeInTheDocument()
    expect(screen.queryByTestId('cards-strategy.entry')).not.toBeInTheDocument()
  })
})


describe('기간 칸 데이터 범위 표시 (19:22) — 불러오는 중과 진짜 실패를 구분', () => {
  it('범위 응답을 기다리는 동안은 "불러오는 중…", 도착하면 범위 문구로 바뀐다(못 불러옴이 아니다)', async () => {
    let open!: () => void
    const gate = new Promise<void>((r) => { open = r })
    const { fetchMock } = mockApi(routes())
    const orig = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation(async (i: RequestInfo | URL, init?: RequestInit) => { if (String(i).includes('data-ranges')) await gate; return orig(i, init) })
    page()
    expect(await screen.findByTestId('ranges-loading')).toHaveTextContent('불러오는 중')
    expect(screen.queryByTestId('ranges-error')).not.toBeInTheDocument()
    open()
    await waitFor(() => expect(screen.getByTestId('panel-period')).toHaveTextContent('데이터 2'))
    expect(screen.queryByTestId('ranges-loading')).not.toBeInTheDocument()
  })

  it('진짜 실패(서버 오류)일 때만 "못 불러옴" + [다시 시도] — 누르면 다시 요청해 범위가 채워진다', async () => {
    let fail = true
    const { calls } = mockApi(routes({ 'GET /api/meta/data-ranges': () => (fail ? { status: 500, error: { code: 'INTERNAL', message: '서버 오류' } } : { data: RANGES }) }))
    page()
    expect(await screen.findByTestId('ranges-error')).toHaveTextContent('못 불러옴')
    fail = false
    await userEvent.click(screen.getByTestId('ranges-retry'))
    await waitFor(() => expect(screen.getByTestId('panel-period')).toHaveTextContent('데이터 2'))
    expect(calls.filter((c) => c.path.startsWith('/api/meta/data-ranges')).length).toBeGreaterThanOrEqual(2)
  })
})


describe('파라미터 라벨 단위 (22:06 execution-agent c12 편지)', () => {
  it('일봉 실행이면 서버 라벨 끝의 "(봉)" 이 "(일)" 로, 분봉 실행이면 "(봉)" 그대로 — 한글 라벨은 서버 값 그대로', async () => {
    const cat = { ...realCatalog, indicators: realCatalog.indicators.map((d) => (d.name === 'lowest' ? { ...d, params: d.params.map((p) => (p.name === 'n' ? { ...p, label: '가장 긴 평균 기간(봉)' } : p)) } : d)) }
    mockApi(routes({}, cat))
    page()
    const exit = await screen.findByTestId('group-strategy.exit')
    expect(exit).toHaveTextContent('가장 긴 평균 기간(일)')
    await toIntraday()
    await waitFor(() => expect(screen.getByTestId('group-strategy.exit')).toHaveTextContent('가장 긴 평균 기간(봉)'))
  })
})
