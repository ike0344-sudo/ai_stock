// 결과 화면 [재생] — 이미 나온 결과(equity·trades·bars)를 시간 순으로 다시 보여 준다. 새 계산 없음.
//  · 포트폴리오: 수익곡선이 그려져 나가고 그날 산·판 종목 목록이 바뀐다
//  · 단일 종목: 캔들 창이 옆으로 흐르고 매수·매도가 그 시점에 찍히며 보유 구간이 음영
//  · 분봉·틱: 날 단위로 넘어가며 그날 거래가 있던 종목의 분봉을 보여 준다
// 별도 패널이라 결과 화면의 다른 정보를 가리지 않는다. 속도 1·4·16배, 일시정지, 날짜 슬라이더.
import { CaretRightOutlined, PauseOutlined, VideoCameraOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Col, Radio, Row, Slider, Space, Tag, Typography } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useBars } from '@/api/studio'
import { EChart } from '@/components/charts/EChart'
import { fmtDate } from '@/lib/format'
import { advance, dayOf, FINE_DAYS_PER_SEC, eventsBetween, focusCode, replayCandleOption, replayDays, replayEquityOption, replayMinuteOption, SPEEDS, statAt, TICK_MS } from '@/lib/replay'
import { StockName, stockLabel, useStockNames } from '@/lib/stockNames'
import type { EquityPoint, RunDetail, Trade } from '@/types/studio'

const MAX_LIST = 10
const won = (v: number | null) => (v === null ? '—' : `${Math.round(v).toLocaleString('ko-KR')}원`)

function TradeList({ title, rows, kind, testid }: { title: string; rows: Trade[]; kind: 'buy' | 'sell'; testid: string }) {
  return (
    <Card size="small" title={<Space><Tag color={kind === 'buy' ? 'red' : 'blue'}>{title}</Tag><span data-testid={`${testid}-n`}>{rows.length}건</span></Space>} data-testid={testid} styles={{ body: { minHeight: 64 } }}>
      {rows.length === 0 && <Typography.Text type="secondary">없음</Typography.Text>}
      {rows.slice(0, MAX_LIST).map((t, i) => (
        <div key={`${t.code}|${t.entry_ts}|${t.slice ?? 1}|${i}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <StockName code={t.code} name={t.name} />
          <span style={{ color: kind === 'sell' && t.net_pct != null ? (t.net_pct >= 0 ? '#f5222d' : '#1677ff') : undefined }}>
            {kind === 'buy' ? `${Math.round(t.entry_price).toLocaleString('ko-KR')}원` : t.net_pct == null ? '' : `${(t.net_pct * 100).toFixed(2)}%`}
          </span>
        </div>
      ))}
      {rows.length > MAX_LIST && <Typography.Text type="secondary" style={{ fontSize: 12 }}>외 {rows.length - MAX_LIST}건</Typography.Text>}
    </Card>
  )
}

export function ReplayPanel({ d, equity, trades }: { d: RunDetail; equity: EquityPoint[]; trades: Trade[] }) {
  const names = useStockNames()
  const [open, setOpen] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<number>(4)
  const [pos, setPos] = useState(0)
  const spec = d.spec
  const single = spec.mode === 'daily_single'
  const fine = spec.mode === 'intraday' || spec.mode === 'tick'
  const code = single ? spec.universe.codes[0] : null
  const bars = useBars(open && single ? code : null, spec.period.start, spec.period.end)

  const days = useMemo(() => (single ? (bars.data?.bars ?? []).filter((b) => b.t >= spec.period.start && b.t <= spec.period.end).map((b) => b.t) : replayDays(equity)), [single, bars.data, equity, spec.period.start, spec.period.end])
  const last = Math.max(0, days.length - 1)
  const idx = Math.min(Math.floor(pos), last)
  const day = days[idx] ?? ''

  useEffect(() => {
    // 단일 종목은 봉을 불러오는 동안 days 가 비어(last=0) — 그때 멈추면 로딩이 끝나도 재생이 안 시작된다. 준비될 때까지 기다렸다가 흘린다
    if (!playing || last <= 0) return
    const h = setInterval(() => {
      setPos((p) => {
        const n = advance(p, speed, TICK_MS, last, fine ? FINE_DAYS_PER_SEC : undefined)
        if (n >= last) setPlaying(false)
        return n
      })
    }, TICK_MS)
    return () => clearInterval(h)
  }, [playing, speed, last, fine])

  // 그날(또는 배속이 빨라 넘어간 구간)의 산·판 종목 — 슬라이더로 멀리 뛰면 그 날 하루만
  const prevIdx = useRef(0)
  const events = useMemo(() => {
    const from = idx - prevIdx.current > 0 && idx - prevIdx.current <= 30 ? days[prevIdx.current] : days[idx - 1] ?? null
    return day ? eventsBetween(trades, from ?? null, day) : { bought: [], sold: [] }
  }, [idx, day, days, trades])
  useEffect(() => { prevIdx.current = idx }, [idx])

  const initial = spec.portfolio.initial_capital
  const stat = statAt(equity, days, idx, initial)
  // 분봉은 날이 멈춰 선 뒤에만 불러온다(빠르게 넘어가는 날마다 요청하면 서버에 요청이 쌓인다)
  const [settled, setSettled] = useState('')
  useEffect(() => { const h = setTimeout(() => setSettled(day), 250); return () => clearTimeout(h) }, [day])
  const focus = fine && settled ? focusCode(trades, settled) : null
  const interval = spec.mode === 'intraday' ? `${spec.intraday?.bar_minutes ?? 5}m` : '1m'
  const minute = useBars(open && fine && focus ? focus.code : null, settled, settled, interval, spec.intraday?.source ?? 'al')

  const equityOpt = useMemo(() => replayEquityOption(equity, days, idx), [equity, days, idx])
  const candleOpt = useMemo(() => (single && bars.data ? replayCandleOption(bars.data.bars, trades, bars.data.bars.findIndex((b) => b.t === day) >= 0 ? bars.data.bars.findIndex((b) => b.t === day) : 0) : null), [single, bars.data, trades, day])
  const minuteOpt = useMemo(() => (fine && minute.data ? replayMinuteOption(minute.data.bars, trades, settled) : null), [fine, minute.data, trades, settled])

  const start = () => { setPos(0); prevIdx.current = 0; setPlaying(true); setOpen(true) }
  if (!open) {
    return (
      <Card size="small" title="재생" data-testid="replay-card" extra={<Button type="primary" icon={<VideoCameraOutlined />} onClick={start} data-testid="replay-open">▶ 재생</Button>}>
        <Typography.Text type="secondary">
          {single ? '캔들이 옆으로 흐르며 매수·매도가 그 시점에 찍힙니다.' : fine ? '날 단위로 넘어가며 그날 거래가 있던 종목의 분봉을 보여 줍니다.' : '수익곡선이 그려져 나가며 그날 산·판 종목이 바뀝니다.'} 이미 나온 결과를 다시 보여 주는 것이라 새로 계산하지 않습니다.
        </Typography.Text>
      </Card>
    )
  }
  const ready = days.length > 0
  return (
    <Card size="small" title={`재생 — ${day ? fmtDate(day) : '준비 중'}`} data-testid="replay-panel" extra={<Button size="small" onClick={() => { setPlaying(false); setOpen(false) }} data-testid="replay-close">닫기</Button>}>
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Space wrap>
          <Button type="primary" icon={playing ? <PauseOutlined /> : <CaretRightOutlined />} disabled={!ready}
            onClick={() => { if (!playing && pos >= last) setPos(0); setPlaying(!playing) }} data-testid="replay-toggle">{playing ? '일시정지' : pos >= last && last > 0 ? '처음부터' : '재생'}</Button>
          <Radio.Group value={speed} onChange={(e) => setSpeed(e.target.value)} optionType="button" data-testid="replay-speed" options={SPEEDS.map((s) => ({ value: s, label: `${s}배` }))} />
          <Typography.Text data-testid="replay-day">{day ? fmtDate(day) : '—'}</Typography.Text>
          <Typography.Text data-testid="replay-equity">평가금 {won(stat.equity)}{stat.returnPct !== null && <span style={{ color: stat.returnPct >= 0 ? '#f5222d' : '#1677ff' }}> ({stat.returnPct >= 0 ? '+' : ''}{stat.returnPct.toFixed(2)}%)</span>}</Typography.Text>
          <Typography.Text type="secondary" data-testid="replay-positions">보유 {stat.positions ?? '—'}종목</Typography.Text>
        </Space>
        <Slider min={0} max={last} value={idx} disabled={!ready} onChange={(v) => { setPlaying(false); setPos(v) }} tooltip={{ formatter: (v) => (v === undefined ? '' : days[v] ?? '') }} data-testid="replay-slider" />
        {single && bars.isPending && <Typography.Text type="secondary">차트 봉을 불러오는 중…</Typography.Text>}
        {single && bars.isError && <Alert type="error" showIcon message={`차트 봉을 못 불러와 재생할 수 없다: ${bars.error.message}`} />}
        {ready && (single ? (candleOpt && <div data-testid="replay-candle"><EChart option={candleOpt} height={340} /></div>) : (
          <div data-testid="replay-equity-chart"><EChart option={equityOpt} height={fine ? 220 : 340} /></div>
        ))}
        {fine && (
          <div data-testid="replay-minute">
            <Typography.Text type="secondary">{!settled || settled !== day ? `${day ? fmtDate(day) : ''} — 날짜가 멈추면 그날 분봉을 보여 준다` : focus ? `${fmtDate(day)} · ${stockLabel(names, focus.code, focus.name)} 의 ${interval.replace('m', '분')}봉` : `${fmtDate(day)} — 이 날은 거래가 없어 보여 줄 분봉이 없다`}</Typography.Text>
            {minute.isError && <Alert type="warning" showIcon message="그날 분봉을 못 불러옴" />}
            {minuteOpt && <EChart option={minuteOpt} height={260} />}
          </div>
        )}
        <Row gutter={[12, 12]}>
          <Col xs={24} md={12}><TradeList title="산 종목" rows={events.bought} kind="buy" testid="replay-bought" /></Col>
          <Col xs={24} md={12}><TradeList title="판 종목" rows={events.sold} kind="sell" testid="replay-sold" /></Col>
        </Row>
      </Space>
    </Card>
  )
}

export { dayOf }
