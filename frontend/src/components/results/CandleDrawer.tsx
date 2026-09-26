// 거래 캔들 서랍 (§5.4, §8.4 #9): 진입·청산 표시 + 진입가·손절선·익절선, 진입 앞 30봉 ~ 청산 뒤 30봉. 봉은 /api/stocks/{code}/bars(일봉).
import { Alert, Descriptions, Drawer, Spin, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { useMemo } from 'react'
import { useBars } from '@/api/studio'
import { EChart } from '@/components/charts/EChart'
import { candleOption, sliceAround } from '@/lib/chartOptions'
import { fmtNum } from '@/lib/format'
import { exitReason } from '@/lib/labels'
import { StockName } from '@/lib/stockNames'
import { isParam, type Num, type SpecJson, type Trade } from '@/types/studio'

const PAD = 30
const resolve = (v: Num | null | undefined, params: Record<string, number>): number | null =>
  v === null || v === undefined ? null : isParam(v) ? params[v.param] ?? null : v

export function CandleDrawer({ trade, spec, params, onClose }: { trade: Trade | null; spec: SpecJson; params: Record<string, number>; onClose: () => void }) {
  // 일봉: 앞뒤 30봉을 확보하려고 달력으로 넉넉히(약 3개월) 받아서 자른다.
  // 분봉·틱: 그 거래의 분봉(틱 거래는 1분봉 — 체결 봉은 없다)을 며칠 앞부터 받아 자른다. 분봉의 t 는 봉 끝 시각.
  const fine = spec.mode === 'intraday' || spec.mode === 'tick'
  const interval = spec.mode === 'intraday' ? `${spec.intraday?.bar_minutes ?? 5}m` : spec.mode === 'tick' ? (spec.tick?.entry_source === 'minute_refine' ? `${spec.intraday?.bar_minutes ?? 1}m` : '1m') : '1d'
  const source = spec.intraday?.source ?? 'al'
  const start = trade ? dayjs(trade.entry_ts).subtract(fine ? 4 : 100, 'day').format('YYYY-MM-DD') : undefined
  const end = trade ? dayjs(trade.exit_ts ?? trade.entry_ts).add(fine ? 0 : 100, 'day').format('YYYY-MM-DD') : undefined
  const bars = useBars(trade?.code ?? null, start, end, interval, source)

  const built = useMemo(() => {
    if (!trade || !bars.data) return null
    // 분봉 t 는 "YYYY-MM-DD HH:MM"(봉 끝 라벨). 분봉 거래의 시각은 그 봉 라벨이라 분 단위로 같은 봉에 얹고,
    // 틱 조건 거래는 실제 체결 초라서 초까지 비교해 그 체결이 든 봉(끝이 그 뒤인 첫 봉)에 얹는다.
    const secs = spec.mode === 'tick' && spec.tick?.entry_source === 'catalog'
    const key = (ts: string) => (fine ? ts.replace('T', ' ').slice(0, secs ? 19 : 16) : ts.slice(0, 10))
    const s = sliceAround(bars.data.bars, key(trade.entry_ts), trade.exit_ts ? key(trade.exit_ts) : null, PAD)
    const stopPct = resolve(spec.exits.stop_loss_pct, params)
    const tpPct = resolve(spec.exits.take_profit_pct, params)
    const lines = { entry: trade.entry_price, stop: stopPct ? trade.entry_price * (1 - stopPct / 100) : null, target: tpPct ? trade.entry_price * (1 + tpPct / 100) : null }
    return { s, option: candleOption(s.bars, s.entryIdx, s.exitIdx, lines, trade.exit_price), lines }
  }, [trade, bars.data, spec, params, fine])

  return (
    <Drawer open={!!trade} onClose={onClose} size="large" title={trade ? <span><StockName code={trade.code} name={trade.name} /> 거래</span> : ''} destroyOnHidden data-testid="candle-drawer">
      {trade && (
        <>
          <Descriptions size="small" column={2} style={{ marginBottom: 12 }} items={[
            { label: '진입', children: `${fine ? trade.entry_ts.replace('T', ' ') : trade.entry_ts.slice(0, 10)} · ${fmtNum(trade.entry_price)}원` },
            { label: '청산', children: trade.exit_ts ? `${fine ? trade.exit_ts.replace('T', ' ') : trade.exit_ts.slice(0, 10)} · ${fmtNum(trade.exit_price ?? 0)}원` : '아직 안 팔림' },
            { label: '순손익', children: trade.net_pnl === null ? '—' : `${fmtNum(Math.round(trade.net_pnl))}원 (${((trade.net_pct ?? 0) * 100).toFixed(2)}%)` },
            { label: '청산 사유', children: <Tag>{exitReason(trade.exit_reason)}</Tag> },
          ]} />
          {bars.isPending && <Spin data-testid="candle-loading" />}
          {bars.isError && <Alert type="error" showIcon message="차트 봉을 못 불러왔습니다" description={bars.error.message} data-testid="candle-error" />}
          {built && built.s.bars.length > 0 && (
            <div data-testid="candle-chart">
              <EChart option={built.option} height={440} />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                진입 앞 {PAD}봉 ~ 청산 뒤 {PAD}봉({fine ? `${interval.replace('m', '분')}봉 · ${source === 'krx' ? 'KRX' : '통합'} · 봉 끝 시각 라벨 기준${spec.mode === 'tick' ? ' · 틱 거래는 초 단위 체결이라 1분봉으로 보여 준다' : ''}` : '일봉'}). 손절선·익절선은 이 실행의 청산 규칙으로 계산한 값이며, 조건식 청산이나 트레일링은 선으로 그리지 않습니다.
              </Typography.Text>
            </div>
          )}
          {built && built.s.bars.length === 0 && <Alert type="warning" showIcon message={`이 기간의 ${fine ? '분봉' : '일봉'}이 없습니다`} />}
        </>
      )}
    </Drawer>
  )
}
