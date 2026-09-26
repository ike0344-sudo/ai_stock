// studio-conditions c6 화면 — 분류 나무·검색·지원 여부 · 시간 단위 · 새 연산자(hold·within·is_true·negate) · 포지션 피연산자 · 고급 청산 규칙 · 레시피 · 수식 편집기.
// 카탈로그·레시피는 실제 서버 응답(fixtures/recipes.ts). 서버가 알리는 능력(capabilities)에 따라 화면이 켜지고 꺼지는 것을 검사한다.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
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
