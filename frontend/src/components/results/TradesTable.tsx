// 거래 표 (§5.4): 정렬·검색·페이지 → 행 클릭 → 캔들 서랍(진입·청산·손절·익절선, 앞뒤 30봉)
import { Input, Space, Table, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { DASH, fmtNum } from '@/lib/format'
import { exitReason } from '@/lib/labels'
import type { SpecJson, Trade } from '@/types/studio'
import { CandleDrawer } from './CandleDrawer'

const pctColor = (v: number | null) => (v == null ? undefined : v > 0 ? '#f5222d' : v < 0 ? '#1677ff' : undefined)
const d10 = (s: string | null) => (s ? s.slice(0, 10) : DASH)
/** 분봉·틱은 시각까지(MM-DD HH:mm 또는 :ss) */
const dt = (withSec: boolean) => (s: string | null) => (s ? s.slice(5, withSec ? 19 : 16).replace('T', ' ') : DASH)
const diff = (v: number | null | undefined) => (v == null ? DASH : `${v > 0 ? '+' : ''}${v.toFixed(3)}%`)

export function TradesTable({ trades, spec, params }: { trades: Trade[]; spec: SpecJson; params: Record<string, number> }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<Trade | null>(null)
  const rows = useMemo(() => {
    const n = q.trim().toLowerCase()
    return n ? trades.filter((t) => t.code.toLowerCase().includes(n) || (t.name ?? '').toLowerCase().includes(n)) : trades
  }, [trades, q])
  const fine = spec.mode === 'intraday' || spec.mode === 'tick'
  const showTs = dt(spec.mode === 'tick')
  const refined = trades.some((t) => t.tick_refined != null)
  const num = (k: keyof Trade) => (a: Trade, b: Trade) => Number(a[k] ?? -Infinity) - Number(b[k] ?? -Infinity)
  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid="trades-section">
      <Space wrap>
        <Input.Search allowClear placeholder="종목명·코드 검색" style={{ width: 240 }} onChange={(e) => setQ(e.target.value)} data-testid="trade-search" />
        <Typography.Text type="secondary">{fmtNum(rows.length)} / {fmtNum(trades.length)}건 · 행을 누르면 그 거래의 차트가 열립니다</Typography.Text>
      </Space>
      <Table<Trade> size="small" data-testid="trades-table" rowKey={(t) => `${t.code}|${t.entry_ts}`} dataSource={rows} pagination={{ pageSize: 20, showSizeChanger: false }}
        onRow={(t) => ({ onClick: () => setOpen(t), style: { cursor: 'pointer' } })}
        columns={[
          { title: '종목', render: (_, t) => <span>{t.name ?? t.code} <Typography.Text type="secondary">{t.code}</Typography.Text></span>, sorter: (a, b) => (a.name ?? a.code).localeCompare(b.name ?? b.code) },
          { title: fine ? '진입 시각' : '진입일', dataIndex: 'entry_ts', render: fine ? showTs : d10, sorter: (a, b) => a.entry_ts.localeCompare(b.entry_ts), defaultSortOrder: 'ascend' },
          { title: '진입가', dataIndex: 'entry_price', render: (v: number) => fmtNum(v), sorter: num('entry_price') },
          { title: fine ? '청산 시각' : '청산일', dataIndex: 'exit_ts', render: fine ? showTs : d10 },
          { title: '청산가', dataIndex: 'exit_price', render: (v: number | null) => (v == null ? DASH : fmtNum(v)) },
          { title: '수량', dataIndex: 'qty', render: (v: number) => fmtNum(v) },
          { title: '순손익', dataIndex: 'net_pnl', sorter: num('net_pnl'), render: (v: number | null) => (v == null ? DASH : <span style={{ color: pctColor(v) }}>{fmtNum(Math.round(v))}원</span>) },
          { title: '수익률', dataIndex: 'net_pct', sorter: num('net_pct'), render: (v: number | null) => (v == null ? DASH : <span style={{ color: pctColor(v) }}>{(v * 100).toFixed(2)}%</span>) },
          { title: '청산 사유', dataIndex: 'exit_reason', render: (r: string | null) => <Tag>{exitReason(r)}</Tag> },
          { title: '보유', dataIndex: 'bars_held', sorter: num('bars_held'), render: (v: number) => (spec.mode === 'tick' ? `${fmtNum(v)}초` : `${v}봉`) },
          { title: 'MFE', dataIndex: 'mfe_pct', sorter: num('mfe_pct'), render: (v: number | null) => (v == null ? DASH : `${v.toFixed(1)}%`) },
          { title: 'MAE', dataIndex: 'mae_pct', sorter: num('mae_pct'), render: (v: number | null) => (v == null ? DASH : `${v.toFixed(1)}%`) },
          ...(refined ? [
            { title: '진입가 차이(틱÷봉)', dataIndex: 'entry_diff_pct', sorter: num('entry_diff_pct'), render: diff },
            { title: '청산가 차이(틱÷봉)', dataIndex: 'exit_diff_pct', sorter: num('exit_diff_pct'), render: diff },
            { title: '틱 기준 순손익', dataIndex: 'net_pnl_tick', sorter: num('net_pnl_tick'), render: (v: number | null | undefined) => (v == null ? DASH : <span style={{ color: pctColor(v) }}>{fmtNum(Math.round(v))}원</span>) },
            { title: '정밀화', dataIndex: 'tick_refined', render: (v: boolean | null | undefined) => (v ? <Tag color="green">틱</Tag> : <Tag>봉 그대로</Tag>) },
          ] : []),
        ]} />
      <CandleDrawer trade={open} spec={spec} params={params} onClose={() => setOpen(null)} />
    </Space>
  )
}
