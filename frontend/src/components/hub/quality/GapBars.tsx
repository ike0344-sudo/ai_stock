// 결측 거래일 막대 (§5.4): 최근 120거래일, 그날 데이터가 있는 종목 비율 — 기준(90%) 미만은 빨갛게 강조
import { Typography } from 'antd'
import { useMemo } from 'react'
import { EChart, type EChartOption } from '@/components/charts/EChart'
import type { GapsData } from '@/types/data'

export function gapOption(d: GapsData): EChartOption {
  return {
    grid: { left: 48, right: 72, top: 16, bottom: 40 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v}%` },
    xAxis: { type: 'category', data: d.rows.map((r) => r.date.slice(5)), axisLabel: { interval: Math.max(0, Math.floor(d.rows.length / 12) - 1) } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
    dataZoom: [{ type: 'inside' }],
    series: [
      {
        type: 'bar',
        data: d.rows.map((r) => ({ value: +(r.share * 100).toFixed(2), itemStyle: { color: r.share < d.threshold ? '#f5222d' : '#52c41a' } })),
        markLine: { symbol: 'none', data: [{ yAxis: d.threshold * 100 }], label: { formatter: `${d.threshold * 100}% 기준` } },
      },
    ],
  }
}

export function GapBars({ data }: { data: GapsData }) {
  const option = useMemo(() => gapOption(data), [data])
  const low = data.rows.filter((r) => r.share < data.threshold)
  return (
    <>
      <Typography.Text data-testid="gap-summary" type={low.length ? 'danger' : 'secondary'}>
        최근 {data.days}거래일 중 {Math.round(data.threshold * 100)}% 미만 {low.length}일{low.length ? ` — ${low.map((r) => r.date).join(', ')}` : ''}
      </Typography.Text>
      <EChart option={option} height={240} />
    </>
  )
}
