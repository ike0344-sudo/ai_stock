// 결과·비교 화면 차트 옵션 — 순수 함수(입력 → echarts 옵션)라 jsdom 에서도 옵션 내용을 검사할 수 있다.
import type { EChartOption } from '@/components/charts/EChart'
import type { Analysis, Bar, EquityPoint, PeriodReturn, Trade } from '@/types/studio'

export const UP = '#f5222d' // 한국 관례: 상승 빨강
export const DOWN = '#1677ff' // 하락 파랑
export const SERIES_COLORS = ['#1677ff', '#f5222d', '#52c41a', '#fa8c16', '#722ed1']

const day = (ts: string) => ts.slice(0, 10)
const money = (v: number) => Math.round(v).toLocaleString('ko-KR')

// ───────────── 수익곡선 · 낙폭 ─────────────
export function equityOption(eq: EquityPoint[], opts: { log: boolean }): EChartOption {
  const x = eq.map((p) => day(p.ts))
  const series: unknown[] = [{ name: '내 전략', type: 'line', showSymbol: false, data: eq.map((p) => p.equity), lineStyle: { width: 2 }, color: SERIES_COLORS[0] }]
  const bench = [['benchmark_kospi', '코스피(같은 돈으로 지수)', '#8c8c8c'], ['benchmark_kosdaq', '코스닥', '#d4b106']] as const
  for (const [k, name, color] of bench) {
    const data = eq.map((p) => (p[k] ?? null) as number | null)
    if (data.some((v) => v !== null)) series.push({ name, type: 'line', showSymbol: false, data, lineStyle: { width: 1, type: 'dashed' }, color })
  }
  return {
    grid: { left: 72, right: 24, top: 36, bottom: 64 },
    legend: { top: 4 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => (v === null || v === undefined ? '—' : `${money(v)}원`) },
    xAxis: { type: 'category', data: x, boundaryGap: false },
    yAxis: { type: opts.log ? 'log' : 'value', scale: true, axisLabel: { formatter: (v: number) => `${Math.round(v / 10000).toLocaleString('ko-KR')}만` } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 8 }],
    series,
  }
}

export function drawdownOption(eq: EquityPoint[]): EChartOption {
  return {
    grid: { left: 72, right: 24, top: 16, bottom: 40 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v.toFixed(2)}%` },
    xAxis: { type: 'category', data: eq.map((p) => day(p.ts)), boundaryGap: false },
    yAxis: { type: 'value', max: 0, axisLabel: { formatter: '{value}%' } },
    dataZoom: [{ type: 'inside' }],
    series: [{ name: '낙폭', type: 'line', showSymbol: false, data: eq.map((p) => p.drawdown_pct), areaStyle: { color: '#f5222d33' }, lineStyle: { color: UP, width: 1 } }],
  }
}

// ───────────── 월별 히트맵 · 연도 막대 ─────────────
export function monthlyHeatmapOption(monthly: PeriodReturn[]): EChartOption {
  const years = [...new Set(monthly.map((m) => m.period.slice(0, 4)))]
  const data = monthly.map((m) => [Number(m.period.slice(5, 7)) - 1, years.indexOf(m.period.slice(0, 4)), +m.return_pct.toFixed(2)])
  const lim = Math.max(5, ...monthly.map((m) => Math.abs(m.return_pct)))
  return {
    grid: { left: 56, right: 16, top: 16, bottom: 56 },
    tooltip: { formatter: (p: { data: number[] }) => `${years[p.data[1]]}-${String(p.data[0] + 1).padStart(2, '0')}: ${p.data[2]}%` },
    xAxis: { type: 'category', data: Array.from({ length: 12 }, (_, i) => `${i + 1}월`), splitArea: { show: true } },
    yAxis: { type: 'category', data: years, splitArea: { show: true } },
    visualMap: { min: -lim, max: lim, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: [DOWN, '#ffffff', UP] } },
    series: [{ type: 'heatmap', data, label: { show: true, formatter: (p: { data: number[] }) => `${p.data[2]}` } }],
  }
}

export function yearlyBarOption(yearly: PeriodReturn[]): EChartOption {
  return {
    grid: { left: 56, right: 16, top: 16, bottom: 32 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v.toFixed(2)}%` },
    xAxis: { type: 'category', data: yearly.map((y) => y.period) },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [{ type: 'bar', data: yearly.map((y) => ({ value: +y.return_pct.toFixed(2), itemStyle: { color: y.return_pct >= 0 ? UP : DOWN } })), label: { show: true, position: 'top', formatter: '{c}%' } }],
  }
}

// ───────────── 분포·산점도 ─────────────
export function histogramOption(h: Analysis['histogram']): EChartOption {
  const centers = h.counts.map((_, i) => (h.edges[i] + h.edges[i + 1]) / 2)
  return {
    grid: { left: 48, right: 16, top: 16, bottom: 40 },
    tooltip: { trigger: 'axis', formatter: (p: { dataIndex: number }[]) => `${h.edges[p[0].dataIndex].toFixed(1)}% ~ ${h.edges[p[0].dataIndex + 1].toFixed(1)}%: ${h.counts[p[0].dataIndex]}건` },
    xAxis: { type: 'category', data: centers.map((c) => `${c.toFixed(1)}%`), name: '거래 수익률' },
    yAxis: { type: 'value', name: '건수' },
    series: [{ type: 'bar', data: h.counts.map((c, i) => ({ value: c, itemStyle: { color: centers[i] >= 0 ? UP : DOWN } })) }],
  }
}

const closed = (t: Trade[]) => t.filter((x) => x.net_pct != null)

/** MFE(가장 좋았던 순간 수익률) vs MAE(가장 나빴던 순간 손실률) — 이긴 거래 빨강 / 진 거래 파랑 */
export function mfeMaeOption(trades: Trade[]): EChartOption {
  const pt = (win: boolean) => closed(trades).filter((t) => ((t.net_pct ?? 0) > 0) === win && t.mfe_pct != null && t.mae_pct != null).map((t) => [t.mae_pct, t.mfe_pct, t.name ?? t.code])
  return {
    grid: { left: 56, right: 16, top: 32, bottom: 40 }, legend: { top: 0 },
    tooltip: { formatter: (p: { data: (string | number)[] }) => `${p.data[2]}<br/>MAE ${Number(p.data[0]).toFixed(1)}% · MFE ${Number(p.data[1]).toFixed(1)}%` },
    xAxis: { type: 'value', name: 'MAE(최대 손실 %)', axisLabel: { formatter: '{value}%' } }, yAxis: { type: 'value', name: 'MFE(최대 이익 %)', axisLabel: { formatter: '{value}%' } },
    series: [{ name: '이긴 거래', type: 'scatter', data: pt(true), color: UP, symbolSize: 6 }, { name: '진 거래', type: 'scatter', data: pt(false), color: DOWN, symbolSize: 6 }],
  }
}

export function holdingScatterOption(trades: Trade[]): EChartOption {
  const pts = closed(trades).map((t) => [t.bars_held, +((t.net_pct ?? 0) * 100).toFixed(2), t.name ?? t.code])
  return {
    grid: { left: 56, right: 16, top: 16, bottom: 40 },
    tooltip: { formatter: (p: { data: (string | number)[] }) => `${p.data[2]}<br/>${p.data[0]}봉 보유 · ${p.data[1]}%` },
    xAxis: { type: 'value', name: '보유 봉 수' }, yAxis: { type: 'value', name: '수익률', axisLabel: { formatter: '{value}%' } },
    series: [{ type: 'scatter', data: pts, symbolSize: 6, itemStyle: { color: (p: { data: (string | number)[] }) => (Number(p.data[1]) >= 0 ? UP : DOWN) } }],
  }
}

// ───────────── 그룹별 성과 · 비용 민감도 ─────────────
export function groupBarOption(rows: { key: string; net_pnl: number }[]): EChartOption {
  const r = [...rows].sort((a, b) => a.net_pnl - b.net_pnl).slice(-15)
  return {
    grid: { left: 110, right: 24, top: 8, bottom: 24 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v: number) => `${money(v)}원` },
    xAxis: { type: 'value', axisLabel: { formatter: (v: number) => `${Math.round(v / 10000)}만` } },
    yAxis: { type: 'category', data: r.map((x) => x.key) },
    series: [{ type: 'bar', data: r.map((x) => ({ value: Math.round(x.net_pnl), itemStyle: { color: x.net_pnl >= 0 ? UP : DOWN } })) }],
  }
}

export function costSensitivityOption(rows: { mult: number; net_return_pct: number }[], breakeven: number | null): EChartOption {
  return {
    grid: { left: 56, right: 24, top: 24, bottom: 40 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v.toFixed(2)}%` },
    xAxis: { type: 'category', data: rows.map((r) => `비용 ×${r.mult}`) },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [{
      type: 'bar', data: rows.map((r) => ({ value: +r.net_return_pct.toFixed(2), itemStyle: { color: r.net_return_pct >= 0 ? UP : DOWN } })),
      label: { show: true, position: 'top', formatter: '{c}%' },
      markLine: breakeven !== null ? { symbol: 'none', data: [{ yAxis: 0 }], label: { formatter: `손익분기 ×${breakeven.toFixed(2)}` } } : undefined,
    }],
  }
}

// ───────────── 비교: 곡선 겹치기 ─────────────
export function compareOption(runs: { name: string; equity: EquityPoint[] }[], log: boolean): EChartOption {
  const dates = [...new Set(runs.flatMap((r) => r.equity.map((p) => day(p.ts))))].sort()
  return {
    grid: { left: 56, right: 24, top: 40, bottom: 64 }, legend: { top: 4 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => (v === null || v === undefined ? '—' : v.toFixed(1)) },
    xAxis: { type: 'category', data: dates, boundaryGap: false },
    yAxis: { type: log ? 'log' : 'value', scale: true, name: '시작=100' },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 8 }],
    series: runs.map((r, i) => {
      const map = new Map(r.equity.map((p) => [day(p.ts), p.rel ?? null]))
      return { name: r.name, type: 'line', showSymbol: false, connectNulls: true, color: SERIES_COLORS[i % SERIES_COLORS.length], data: dates.map((d) => map.get(d) ?? null) }
    }),
  }
}

// ───────────── 캔들 서랍 ─────────────
/** 진입일 앞 pad 봉 ~ 청산일 뒤 pad 봉만 잘라낸다(청산일이 없으면 마지막 봉까지). */
export function sliceAround(bars: Bar[], entryDate: string, exitDate: string | null, pad = 30): { bars: Bar[]; entryIdx: number; exitIdx: number | null } {
  if (!bars.length) return { bars: [], entryIdx: -1, exitIdx: null }
  const idxOf = (d: string, fallbackLast = false) => {
    const i = bars.findIndex((b) => b.t >= d)
    return i === -1 ? (fallbackLast ? bars.length - 1 : -1) : i
  }
  const e = Math.max(0, idxOf(entryDate))
  const x = exitDate ? idxOf(exitDate, true) : null
  const lo = Math.max(0, e - pad)
  const hi = Math.min(bars.length - 1, (x ?? e) + pad)
  return { bars: bars.slice(lo, hi + 1), entryIdx: e - lo, exitIdx: x === null ? null : x - lo }
}

export interface CandleLines { entry: number; stop?: number | null; target?: number | null }

export function candleOption(bars: Bar[], entryIdx: number, exitIdx: number | null, lines: CandleLines, exitPrice: number | null): EChartOption {
  const lineOf = (name: string, y: number, color: string) => ({ yAxis: y, name, lineStyle: { color, type: 'dashed' }, label: { formatter: `${name} ${money(y)}`, position: 'insideEndTop' } })
  const markLines = [lineOf('진입가', lines.entry, '#595959'),
    ...(lines.stop ? [lineOf('손절선', lines.stop, DOWN)] : []), ...(lines.target ? [lineOf('익절선', lines.target, UP)] : [])]
  const points = [
    ...(entryIdx >= 0 ? [{ name: '진입', coord: [entryIdx, lines.entry], value: '진입', itemStyle: { color: '#52c41a' } }] : []),
    ...(exitIdx !== null && exitPrice !== null ? [{ name: '청산', coord: [exitIdx, exitPrice], value: '청산', itemStyle: { color: '#722ed1' } }] : []),
  ]
  return {
    grid: { left: 64, right: 24, top: 24, bottom: 40 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    xAxis: { type: 'category', data: bars.map((b) => b.t) },
    yAxis: { type: 'value', scale: true },
    series: [{
      type: 'candlestick', data: bars.map((b) => [b.o, b.c, b.l, b.h]),
      itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
      markLine: { symbol: 'none', data: markLines }, markPoint: { symbolSize: 46, data: points },
    }],
  }
}
