import { describe, expect, it } from 'vitest'
import { candleOption, compareOption, costSensitivityOption, equityOption, histogramOption, monthlyHeatmapOption, sliceAround } from '@/lib/chartOptions'
import { addToBasket, getBasket, MAX_COMPARE, removeFromBasket, setBasket } from '@/lib/compareBasket'
import { bestIndexes } from '@/lib/metrics'
import { addItem, collectParamNames, countConditions, defaultEntry, duplicateItem, errorsUnder, freshParamName, groupDepth, newGroup, newSpec, pruneParams, removeItem, switchMode, toParam } from '@/lib/spec'
import { RULE_TEXT, verdictOf } from '@/lib/verdicts'
import type { Bar, EquityPoint } from '@/types/studio'
import { realEquity, realTrades } from './fixtures/studioReal'

describe('verdictOf — §5.5 판정 기준 경계', () => {
  const cases: [string, number, string][] = [
    ['sharpe', 1.0, 'good'], ['sharpe', 0.999, 'mid'], ['sharpe', 0.5, 'mid'], ['sharpe', 0.499, 'bad'],
    ['sortino', 1.5, 'good'], ['sortino', 0.75, 'mid'], ['sortino', 0.74, 'bad'],
    ['max_drawdown_pct', 15, 'good'], ['max_drawdown_pct', 15.01, 'mid'], ['max_drawdown_pct', 30, 'mid'], ['max_drawdown_pct', 30.01, 'bad'],
    ['calmar', 1.0, 'good'], ['calmar', 0.3, 'mid'], ['calmar', 0.29, 'bad'],
    ['profit_factor', 1.5, 'good'], ['profit_factor', 1.0, 'mid'], ['profit_factor', 0.99, 'bad'],
    ['expectancy_pct', 0.31, 'good'], ['expectancy_pct', 0.3, 'mid'], ['expectancy_pct', 0.01, 'mid'], ['expectancy_pct', 0, 'bad'], ['expectancy_pct', -1, 'bad'],
    ['excess_return_pct', 0.01, 'good'], ['excess_return_pct', 0, 'bad'], ['excess_return_pct', -5, 'bad'],
    ['num_trades', 100, 'good'], ['num_trades', 99, 'mid'], ['num_trades', 30, 'mid'], ['num_trades', 29, 'bad'],
    ['wfe', 0.5, 'good'], ['wfe', 0.3, 'mid'], ['wfe', 0.29, 'bad'],
    ['neighbor_stability', 0.7, 'good'], ['neighbor_stability', 0.5, 'mid'], ['neighbor_stability', 0.49, 'bad'],
    ['breakeven_cost_mult', 2.0, 'good'], ['breakeven_cost_mult', 1.0, 'mid'], ['breakeven_cost_mult', 0.99, 'bad'],
  ]
  it.each(cases)('%s = %s → %s', (key, v, want) => expect(verdictOf(key, v)).toBe(want))

  it('값이 없거나 기준이 없는 지표는 판정 없음(지어내지 않는다)', () => {
    expect(verdictOf('sharpe', null)).toBeNull()
    expect(verdictOf('sharpe', undefined)).toBeNull()
    expect(verdictOf('sharpe', Number.NaN)).toBeNull()
    expect(verdictOf('win_rate_pct', 55)).toBeNull()
    expect(verdictOf('nope', 1)).toBeNull()
  })

  it('판정이 있는 지표마다 사람 말 기준 문구가 있다(툴팁)', () => {
    for (const k of ['sharpe', 'sortino', 'max_drawdown_pct', 'calmar', 'profit_factor', 'expectancy_pct', 'excess_return_pct', 'num_trades', 'wfe', 'neighbor_stability', 'breakeven_cost_mult']) {
      expect(RULE_TEXT[k]).toBeTruthy()
      expect(verdictOf(k, 1)).not.toBeNull()
    }
  })
})

describe('bestIndexes — 비교 표 강조', () => {
  it('높을수록 좋은 지표는 최댓값, 낮을수록 좋은 지표는 최솟값, 동률은 모두', () => {
    expect(bestIndexes('sharpe', [0.5, 1.2, 0.9])).toEqual([1])
    expect(bestIndexes('max_drawdown_pct', [20, 12, 30])).toEqual([1])
    expect(bestIndexes('total_return_pct', [10, 10, 3])).toEqual([0, 1])
  })
  it('null 은 빼고 보고, 좋고 나쁨이 없는 지표·후보가 1개면 강조 없음', () => {
    expect(bestIndexes('sharpe', [null, 1, 2])).toEqual([2])
    expect(bestIndexes('num_trades', [10, 200])).toEqual([])
    expect(bestIndexes('beta', [1, 2])).toEqual([])
    expect(bestIndexes('sharpe', [null, null, 1])).toEqual([])
  })
})

describe('명세 편집 도우미', () => {
  it('단일 종목 기본값은 최대 보유 1 · 비중 100% (D3-4), 포트폴리오는 5 · 25%', () => {
    const s = newSpec('daily_single', { end: '2026-09-23' })
    expect([s.portfolio.max_positions, s.portfolio.max_weight_pct, s.fills.volume_cap_pct, s.universe.type]).toEqual([1, 100, null, 'codes'])
    const p = newSpec('daily_portfolio', { end: '2026-09-23' })
    expect([p.portfolio.max_positions, p.portfolio.max_weight_pct, p.universe.type]).toEqual([5, 25, 'top_value'])
    expect(s.period.end).toBe('2026-09-23') // 데이터 기준일로
    expect(s.period.start).toBe('2023-09-23')
  })

  it('모드를 바꾸면 모드 의존 칸만 그 모드 기본으로, 조건식은 유지, 호환 모드는 단일에서만', () => {
    const s = newSpec('daily_single')
    s.compat.legacy = true
    s.name = '내 조건'
    const p = switchMode(s, 'daily_portfolio')
    expect(p.name).toBe('내 조건')
    expect([p.portfolio.max_positions, p.portfolio.max_weight_pct, p.compat.legacy]).toEqual([5, 25, false])
    expect(p.strategy).toEqual(s.strategy)
  })

  it('변수: 숫자 칸을 변수로 바꾸고 안 쓰는 변수는 실행 전에 뺀다', () => {
    const s = newSpec('daily_portfolio')
    const { spec: s2, ref } = toParam(s, 20, 'n')
    expect(ref).toEqual({ param: 'n' })
    expect(s2.params.n.default).toBe(20)
    expect(toParam(s2, 1.5, 'n').ref).toEqual({ param: 'n2' }) // 이름 충돌 회피
    expect(freshParamName({ a: { default: 1 }, a2: { default: 1 } }, 'a')).toBe('a3')
    expect(freshParamName({}, '7day')).toBe('p7day')
    // 아무 데도 안 쓰인 변수는 prune 으로 빠진다
    expect(pruneParams(s2).params).toEqual({})
    const used = { ...s2, exits: { ...s2.exits, stop_loss_pct: { param: 'n' } } }
    expect(Object.keys(pruneParams(used).params)).toEqual(['n'])
    expect([...collectParamNames({ a: [{ param: 'x' }, { b: { param: 'y' } }] })].sort()).toEqual(['x', 'y'])
  })

  it('조건 그룹: 추가·복제·삭제·깊이·개수', () => {
    let g = defaultEntry()
    expect(countConditions(g)).toBe(1)
    g = addItem(g, newGroup())
    expect([groupDepth(g), countConditions(g)]).toEqual([2, 2])
    g = duplicateItem(g, 0)
    expect(g.items).toHaveLength(3)
    expect(g.items[0]).toEqual(g.items[1])
    expect(g.items[0]).not.toBe(g.items[1]) // 복제는 깊은 복사
    g = removeItem(g, 2)
    expect(g.items).toHaveLength(2)
  })

  it('오류 경로: 조건 행(items.i) 아래를 가리키는 오류만 그 행에 붙는다', () => {
    const errs = [{ path: 'strategy.entry.items.0.right', message: 'a' }, { path: 'strategy.entry.items.1', message: 'b' }, { path: 'strategy.entry.items.10.left', message: 'c' }, { path: 'strategy.exit.items.0', message: 'd' }]
    expect(errorsUnder(errs, 'strategy.entry', 0)).toEqual(['a'])
    expect(errorsUnder(errs, 'strategy.entry', 1)).toEqual(['b'])
    expect(errorsUnder(errs, 'strategy.entry', 1)).not.toContain('c') // items.1 ≠ items.10
  })
})

describe('비교 바구니', () => {
  it('최대 5개, 중복 없음, 가득 차면 담지 않는다', () => {
    localStorage.clear()
    for (let i = 0; i < MAX_COMPARE; i += 1) expect(addToBasket(`id${i}`)).toBe(true)
    expect(addToBasket('id0')).toBe(true)
    expect(addToBasket('extra')).toBe(false)
    expect(getBasket()).toHaveLength(MAX_COMPARE)
    removeFromBasket('id0')
    expect(getBasket()).not.toContain('id0')
    localStorage.setItem('studio.compare', '{깨진 값')
    expect(getBasket()).toEqual([])
    setBasket(['a', 'a', 'b'])
    expect(getBasket()).toEqual(['a', 'b'])
  })
})

describe('차트 옵션 (실제 결과 값으로)', () => {
  const eq = realEquity as EquityPoint[]

  it('수익곡선: 로그 축 · 코스피/코스닥 겹침 · 확대(dataZoom)', () => {
    const o = equityOption(eq, { log: true }) as { yAxis: { type: string }; series: { name: string; data: unknown[] }[]; dataZoom: unknown[] }
    expect(o.yAxis.type).toBe('log')
    expect(o.series.map((s) => s.name)).toEqual(['내 전략', '코스피(같은 돈으로 지수)', '코스닥'])
    expect(o.series[0].data).toHaveLength(eq.length)
    expect(o.dataZoom.length).toBeGreaterThan(0)
    expect((equityOption(eq, { log: false }) as { yAxis: { type: string } }).yAxis.type).toBe('value')
    const noBench = equityOption(eq.map((p) => ({ ...p, benchmark_kospi: null, benchmark_kosdaq: null })), { log: false }) as { series: unknown[] }
    expect(noBench.series).toHaveLength(1) // 지수 값이 없으면 선을 만들지 않는다
  })

  it('월별 히트맵: 연·월 좌표와 값', () => {
    const o = monthlyHeatmapOption([{ period: '2025-01', return_pct: -1.5 }, { period: '2025-03', return_pct: 4 }, { period: '2026-02', return_pct: 2 }]) as { series: { data: number[][] }[]; yAxis: { data: string[] } }
    expect(o.yAxis.data).toEqual(['2025', '2026'])
    expect(o.series[0].data).toEqual([[0, 0, -1.5], [2, 0, 4], [1, 1, 2]])
  })

  it('히스토그램·비용 민감도', () => {
    const h = histogramOption({ edges: [-10, 0, 10], counts: [3, 5] }) as { series: { data: { value: number; itemStyle: { color: string } }[] }[] }
    expect(h.series[0].data.map((d) => d.value)).toEqual([3, 5])
    expect(h.series[0].data[0].itemStyle.color).not.toBe(h.series[0].data[1].itemStyle.color) // 손실/이익 색이 다르다
    const c = costSensitivityOption([{ mult: 1, net_return_pct: 9.7 }, { mult: 2, net_return_pct: -6.5 }], 1.6) as { series: { markLine?: unknown }[] }
    expect(c.series[0].markLine).toBeTruthy()
    expect((costSensitivityOption([], null) as { series: { markLine?: unknown }[] }).series[0].markLine).toBeUndefined()
  })

  it('비교: 날짜를 합쳐 한 축에 맞춘다(없는 날은 null)', () => {
    const a = [{ ts: '2025-01-02T00:00:00', equity: 1, drawdown_pct: 0, rel: 100 }, { ts: '2025-01-03T00:00:00', equity: 1, drawdown_pct: 0, rel: 101 }] as EquityPoint[]
    const b = [{ ts: '2025-01-03T00:00:00', equity: 1, drawdown_pct: 0, rel: 50 }, { ts: '2025-01-06T00:00:00', equity: 1, drawdown_pct: 0, rel: 55 }] as EquityPoint[]
    const o = compareOption([{ name: 'A', equity: a }, { name: 'B', equity: b }], false) as { xAxis: { data: string[] }; series: { data: (number | null)[] }[] }
    expect(o.xAxis.data).toEqual(['2025-01-02', '2025-01-03', '2025-01-06'])
    expect(o.series[0].data).toEqual([100, 101, null])
    expect(o.series[1].data).toEqual([null, 50, 55])
  })

  it('실제 거래가 산점도·분포 입력으로 쓸 수 있는 모양이다', () => {
    expect(realTrades.length).toBeGreaterThan(5)
    expect(realTrades.every((t) => typeof t.entry_price === 'number' && typeof t.bars_held === 'number')).toBe(true)
  })
})

describe('캔들 서랍 — 앞뒤 30봉', () => {
  const bars: Bar[] = Array.from({ length: 200 }, (_, i) => {
    const d = new Date(Date.UTC(2025, 0, 1 + i)).toISOString().slice(0, 10)
    return { t: d, o: 100 + i, h: 105 + i, l: 95 + i, c: 101 + i, v: 1000 }
  })

  it('진입 앞 30봉 ~ 청산 뒤 30봉으로 자르고 진입·청산 위치를 잘린 봉 기준으로 돌려준다', () => {
    const s = sliceAround(bars, bars[80].t, bars[90].t, 30)
    expect(s.bars).toHaveLength(30 + 11 + 30)
    expect(s.bars[s.entryIdx].t).toBe(bars[80].t)
    expect(s.bars[s.exitIdx as number].t).toBe(bars[90].t)
    expect(s.entryIdx).toBe(30)
  })

  it('경계: 데이터 시작 근처·끝 근처·청산 없음', () => {
    const start = sliceAround(bars, bars[5].t, bars[8].t, 30)
    expect(start.entryIdx).toBe(5)
    expect(start.bars[0].t).toBe(bars[0].t)
    const end = sliceAround(bars, bars[195].t, bars[199].t, 30)
    expect(end.bars[end.bars.length - 1].t).toBe(bars[199].t)
    const open = sliceAround(bars, bars[100].t, null, 30)
    expect(open.exitIdx).toBeNull()
    expect(sliceAround([], '2025-01-01', null).bars).toEqual([])
  })

  it('옵션: 진입가·손절선·익절선 선과 진입·청산 점', () => {
    const o = candleOption(bars.slice(50, 100), 30, 40, { entry: 1000, stop: 930, target: 1150 }, 1120) as
      { series: { markLine: { data: { name: string; yAxis: number }[] }; markPoint: { data: { name: string; coord: number[] }[] } }[] }
    const lines = o.series[0].markLine.data
    expect(lines.map((l) => [l.name, l.yAxis])).toEqual([['진입가', 1000], ['손절선', 930], ['익절선', 1150]])
    expect(o.series[0].markPoint.data.map((p) => [p.name, p.coord])).toEqual([['진입', [30, 1000]], ['청산', [40, 1120]]])
    const bare = candleOption(bars.slice(0, 10), 2, null, { entry: 100 }, null) as { series: { markLine: { data: unknown[] }; markPoint: { data: unknown[] } }[] }
    expect(bare.series[0].markLine.data).toHaveLength(1) // 규칙이 없으면 손절·익절선을 그리지 않는다
    expect(bare.series[0].markPoint.data).toHaveLength(1)
  })
})
