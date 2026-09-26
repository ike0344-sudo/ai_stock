// 결과 화면 [재생] 과 실행 창 실시간 곡선의 순수 계산 — 새 계산 없이 이미 있는 결과 데이터(equity·trades·bars)만 쓴다.
// 화면 컴포넌트가 아니라 여기 둔 이유: 재생 위치·이벤트 묶음·옵션을 jsdom 에서 값으로 검사하려고.
import type { EChartOption } from '@/components/charts/EChart'
import { DOWN, UP } from '@/lib/chartOptions'
import type { LivePoint } from '@/types'
import type { Bar, EquityPoint, Trade } from '@/types/studio'

export const SPEEDS = [1, 4, 16] as const
export const BASE_DAYS_PER_SEC = 8 // 1배속 = 초당 8거래일(500거래일 ≈ 1분) — 4배속 15초, 16배속 4초
/** 분봉·틱 재생은 하루가 곧 한 화면(그날 분봉)이라 훨씬 느리게 넘어간다 — 1배속 = 초당 1거래일 */
export const FINE_DAYS_PER_SEC = 1
export const TICK_MS = 50 // 20fps 로 갱신한다(60fps 를 못 맞추는 큰 결과는 여러 봉을 묶어 한 번에 그린다)

export const dayOf = (ts: string): string => ts.slice(0, 10)
const won = (v: number) => `${Math.round(v).toLocaleString('ko-KR')}원`

/** 재생에 쓸 거래일 목록(곡선의 날짜, 오름차순·중복 없음) */
export function replayDays(equity: EquityPoint[]): string[] {
  const out: string[] = []
  for (const p of equity) {
    const d = dayOf(p.ts)
    if (out[out.length - 1] !== d) out.push(d)
  }
  return out
}

/** 재생 위치(소수)를 dt 만큼 전진 — 끝에서 멈춘다. 위치는 "지금 몇 번째 거래일까지 그렸나"(소수는 다음 봉으로 넘어가기 전 누적분) */
export function advance(pos: number, speed: number, dtMs: number, last: number, base: number = BASE_DAYS_PER_SEC): number {
  return Math.min(last, pos + (speed * base * dtMs) / 1000)
}

export interface DayEvents { bought: Trade[]; sold: Trade[] }

/** (from, to] 사이에 산·판 거래 — 배속이 빨라 한 프레임에 며칠씩 넘어가도 빠뜨리지 않게 구간으로 센다 */
export function eventsBetween(trades: Trade[], fromDay: string | null, toDay: string): DayEvents {
  const inRange = (d: string) => d <= toDay && (fromDay === null || d > fromDay)
  return {
    bought: trades.filter((t) => inRange(dayOf(t.entry_ts))),
    sold: trades.filter((t) => t.exit_ts !== null && inRange(dayOf(t.exit_ts))),
  }
}

/** 보유 구간(진입일, 청산일 — 아직 안 팔렸으면 끝날까지) */
export function holdingSpans(trades: Trade[], code: string, lastDay: string): [string, string][] {
  return trades.filter((t) => t.code === code).map((t) => [dayOf(t.entry_ts), t.exit_ts ? dayOf(t.exit_ts) : lastDay])
}

/** 그 날 거래가 있는 종목 하나 — 분봉 재생에서 그날 분봉을 보여 줄 종목(진입이 있으면 진입 종목 우선, 거래가 많은 순) */
export function focusCode(trades: Trade[], day: string): { code: string; name: string | null } | null {
  const count = new Map<string, { n: number; name: string | null }>()
  for (const t of trades) {
    if (dayOf(t.entry_ts) !== day && dayOf(t.exit_ts ?? '') !== day) continue
    const c = count.get(t.code) ?? { n: 0, name: t.name }
    c.n += dayOf(t.entry_ts) === day ? 2 : 1
    count.set(t.code, c)
  }
  const best = [...count.entries()].sort((a, b) => b[1].n - a[1].n || a[0].localeCompare(b[0]))[0]
  return best ? { code: best[0], name: best[1].name } : null
}

export interface ReplayStat { day: string; equity: number | null; returnPct: number | null; positions: number | null }

export function statAt(equity: EquityPoint[], days: string[], idx: number, initial: number): ReplayStat {
  const day = days[Math.min(idx, days.length - 1)] ?? ''
  const p = [...equity].reverse().find((e) => dayOf(e.ts) <= day) // 그 날(또는 그 전) 마지막 값
  const e = p && Number.isFinite(p.equity) ? p.equity : null
  return { day, equity: e, returnPct: e === null || !initial ? null : (e / initial - 1) * 100, positions: p?.n_positions ?? null }
}

const AXIS = { axisLabel: { formatter: (v: number) => `${Math.round(v / 10000).toLocaleString('ko-KR')}만` }, scale: true }

/** 수익곡선 재생: x 축은 전체 날짜로 고정하고 곡선만 cursor 까지 그린다(오른쪽으로 자라는 모습). animation 끔 — 프레임은 우리가 몰고 간다 */
export function replayEquityOption(equity: EquityPoint[], days: string[], idx: number): EChartOption {
  const byDay = new Map(equity.map((p) => [dayOf(p.ts), p]))
  const upto = days.slice(0, idx + 1)
  const data = upto.map((d) => byDay.get(d)?.equity ?? null)
  const bench = (k: 'benchmark_kospi' | 'benchmark_kosdaq') => upto.map((d) => (byDay.get(d)?.[k] ?? null) as number | null)
  const series: unknown[] = [{ id: 'eq', name: '내 전략', type: 'line', showSymbol: false, data, lineStyle: { width: 2 }, areaStyle: { opacity: 0.08 }, color: '#1677ff',
    markPoint: data.length ? { symbol: 'circle', symbolSize: 9, data: [{ coord: [upto[upto.length - 1], data[data.length - 1]] }], label: { show: false } } : undefined }]
  const kospi = bench('benchmark_kospi')
  if (kospi.some((v) => v !== null)) series.push({ id: 'kospi', name: '코스피', type: 'line', showSymbol: false, data: kospi, lineStyle: { width: 1, type: 'dashed' }, color: '#8c8c8c' })
  return {
    animation: false,
    grid: { left: 72, right: 24, top: 24, bottom: 32 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => (v === null || v === undefined ? '—' : won(v)) },
    xAxis: { type: 'category', data: days, boundaryGap: false },
    yAxis: { type: 'value', ...AXIS },
    series,
  }
}

const candle = (b: Bar) => [b.o, b.c, b.l, b.h]

/** 단일 종목 캔들 재생: 창(최근 window 봉)이 옆으로 흐르고, 그 시점까지의 매수·매도가 찍히며 보유 구간이 음영. */
export function replayCandleOption(bars: Bar[], trades: Trade[], idx: number, window = 60): EChartOption {
  const hi = Math.min(idx, bars.length - 1)
  const lo = Math.max(0, hi - window + 1)
  const view = bars.slice(lo, hi + 1)
  const first = view[0]?.t
  const last = view[view.length - 1]?.t
  const inView = (d: string) => first !== undefined && d >= first && d <= (last ?? d)
  const pts: unknown[] = []
  for (const t of trades) {
    const e = dayOf(t.entry_ts)
    if (inView(e)) pts.push({ name: '매수', coord: [e, t.entry_price], value: '매수', itemStyle: { color: UP }, symbol: 'triangle', symbolSize: 14 })
    if (t.exit_ts && inView(dayOf(t.exit_ts)) && t.exit_price !== null) pts.push({ name: '매도', coord: [dayOf(t.exit_ts), t.exit_price], value: '매도', itemStyle: { color: DOWN }, symbol: 'pin', symbolSize: 26 })
  }
  const spans = last === undefined ? [] : holdingSpans(trades, trades[0]?.code ?? '', last)
    .filter(([a, b]) => b >= (first ?? a) && a <= last)
    .map(([a, b]) => [{ xAxis: a < first! ? first! : a, itemStyle: { color: 'rgba(250,173,20,0.12)' } }, { xAxis: b > last ? last : b }])
  return {
    animation: false,
    grid: { left: 64, right: 24, top: 24, bottom: 32 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    xAxis: { type: 'category', data: view.map((b) => b.t), boundaryGap: true },
    yAxis: { type: 'value', scale: true },
    series: [{ type: 'candlestick', data: view.map(candle), itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
      markPoint: { data: pts, label: { fontSize: 10 } }, markArea: { silent: true, data: spans } }],
  }
}

/** 분봉 재생: 그날 분봉 캔들 + 그날 매수·매도 표시. 봉 시각은 봉 끝 라벨("YYYY-MM-DD HH:MM") */
export function replayMinuteOption(bars: Bar[], trades: Trade[], day: string): EChartOption {
  const t = (ts: string) => ts.replace('T', ' ').slice(0, 16)
  const label = (ts: string) => t(ts).slice(11)
  const nearest = (ts: string) => bars.find((b) => b.t >= t(ts))?.t
  const pts: unknown[] = []
  for (const tr of trades) {
    const e = nearest(tr.entry_ts)
    if (dayOf(tr.entry_ts) === day && e) pts.push({ coord: [label(e), tr.entry_price], value: '매수', itemStyle: { color: UP }, symbol: 'triangle', symbolSize: 14 })
    const x = tr.exit_ts ? nearest(tr.exit_ts) : undefined
    if (tr.exit_ts && dayOf(tr.exit_ts) === day && x && tr.exit_price !== null) pts.push({ coord: [label(x), tr.exit_price], value: '매도', itemStyle: { color: DOWN }, symbol: 'pin', symbolSize: 26 })
  }
  return {
    animation: false,
    grid: { left: 64, right: 24, top: 24, bottom: 32 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    xAxis: { type: 'category', data: bars.map((b) => label(b.t)) },
    yAxis: { type: 'value', scale: true },
    series: [{ type: 'candlestick', data: bars.map(candle), itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN }, markPoint: { data: pts, label: { fontSize: 10 } } }],
  }
}

// ───────────── 실행 중 실시간 곡선 ─────────────
/** 서버가 준 점 중 쓸 수 있는 것만(날짜·평가금이 있는 것), 날짜 순 — NaN/None 점은 건너뛴다 */
export function usableLivePoints(raw: unknown): LivePoint[] {
  const arr = Array.isArray(raw) ? raw : raw && typeof raw === 'object' && Array.isArray((raw as { points?: unknown }).points) ? (raw as { points: unknown[] }).points : []
  return (arr as LivePoint[]).filter((p) => p && typeof p.date === 'string' && typeof p.equity === 'number' && Number.isFinite(p.equity)).sort((a, b) => a.date.localeCompare(b.date))
}

/** 실시간 곡선: x 축은 기간 전체로 미리 잡아 두고(곡선이 그 틀 안에서 오른쪽으로 자란다), 시작 자본선을 점선으로. */
export function liveCurveOption(points: LivePoint[], period: { start: string; end: string }, initial: number): EChartOption {
  const last = points[points.length - 1]
  const up = !last || (last.equity as number) >= initial
  const color = up ? UP : DOWN
  return {
    animation: true,
    animationDurationUpdate: 900,
    animationEasingUpdate: 'linear',
    grid: { left: 72, right: 24, top: 20, bottom: 28 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => (v === null || v === undefined ? '—' : won(v)) },
    xAxis: { type: 'time', min: period.start, max: period.end },
    yAxis: { type: 'value', scale: true, axisLabel: { formatter: (v: number) => `${Math.round(v / 10000).toLocaleString('ko-KR')}만` } },
    series: [{ id: 'live', type: 'line', showSymbol: false, data: points.map((p) => [p.date, p.equity]), lineStyle: { width: 2, color }, itemStyle: { color }, areaStyle: { color, opacity: 0.08 },
      markLine: { silent: true, symbol: 'none', label: { formatter: '시작 자본' }, lineStyle: { type: 'dashed', color: '#8c8c8c' }, data: [{ yAxis: initial }] },
      markPoint: last ? { symbol: 'circle', symbolSize: 9, itemStyle: { color }, data: [{ coord: [last.date, last.equity] }], label: { show: false } } : undefined }],
  }
}
