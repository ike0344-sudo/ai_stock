// 실행 창의 실시간 수익곡선 — 서버가 진행 중에 보내는 live_curve(하루 한 점)로 곡선이 오른쪽으로 그려져 나간다.
// 곡선이 없으면(옛 작업·그리드·워크포워드) 이 컴포넌트는 그려지지 않고 진행 막대만 남는다. 정보를 가리지 않게 진행 막대·단계 문구는 그대로 둔다.
import { Descriptions, Typography } from 'antd'
import { useMemo } from 'react'
import { EChart } from '@/components/charts/EChart'
import { fmtDate } from '@/lib/format'
import { liveCurveOption } from '@/lib/replay'
import { StockName } from '@/lib/stockNames'
import type { LivePoint } from '@/types'
import type { SpecJson } from '@/types/studio'

const won = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v).toLocaleString('ko-KR')}원`)

export function LiveCurve({ points, spec }: { points: LivePoint[]; spec: SpecJson }) {
  const initial = spec.portfolio.initial_capital
  const option = useMemo(() => liveCurveOption(points, spec.period, initial), [points, spec.period, initial])
  const last = points[points.length - 1]
  const ret = last?.equity ? (last.equity / initial - 1) * 100 : null
  const ev = last?.last_event
  return (
    <div data-testid="live-curve">
      <EChart option={option} height={220} merge />
      <Descriptions size="small" column={2} data-testid="live-stats" items={[
        { label: '지금 날짜', children: <span data-testid="live-date">{last ? fmtDate(last.date) : '—'}</span> },
        { label: '평가금', children: <span data-testid="live-equity">{won(last?.equity)}{ret !== null && <Typography.Text type={ret >= 0 ? 'danger' : 'secondary'} style={{ color: ret >= 0 ? '#f5222d' : '#1677ff' }}> ({ret >= 0 ? '+' : ''}{ret.toFixed(2)}%)</Typography.Text>}</span> },
        { label: '거래 수', children: <span data-testid="live-trades">{last?.n_trades ?? '—'}</span> },
        { label: '보유 종목', children: <span data-testid="live-positions">{last?.n_positions ?? '—'}</span> },
        ...(ev ? [{ label: '방금', children: <span data-testid="live-event">{ev.side === 'buy' ? '매수' : '매도'} <StockName code={ev.code} name={ev.name} /></span> }] : []),
      ]} />
    </div>
  )
}
