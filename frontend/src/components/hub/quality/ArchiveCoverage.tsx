// 보관소 커버리지 (§5.4): 종목 수, 종목별 기간 분포, 캐시 대비 누락
import { Descriptions, Space, Tag, Typography } from 'antd'
import { useMemo } from 'react'
import { EChart, type EChartOption } from '@/components/charts/EChart'
import { DASH, fmtNum, fmtTs, VERDICT_COLOR, VERDICT_LABEL } from '@/lib/format'
import type { ArchiveData } from '@/types/data'

export function ArchiveCoverage({ data }: { data: ArchiveData }) {
  const option = useMemo<EChartOption>(() => ({
    grid: { left: 48, right: 16, top: 16, bottom: 32 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: data.span_buckets.map((b) => b.label) },
    yAxis: { type: 'value', name: '종목' },
    series: [{ type: 'bar', data: data.span_buckets.map((b) => b.codes), itemStyle: { color: '#1677ff' } }],
  }), [data])
  return (
    <Space direction="vertical" size="small" style={{ width: '100%' }} data-testid="archive-coverage">
      <Descriptions size="small" column={2} items={[
        { label: '판정', children: <Tag color={VERDICT_COLOR[data.verdict]}>{VERDICT_LABEL[data.verdict]}</Tag> },
        { label: '이유', children: data.reason },
        { label: '캐시 종목', children: fmtNum(data.codes_cache) },
        { label: '보관소 종목', children: fmtNum(data.codes_archive) },
        { label: '캐시 대비 누락', children: fmtNum(data.missing_vs_cache) },
        { label: '마지막 병합', children: fmtTs(data.last_merge_at) },
        { label: '보관 기간', children: `${data.first_date ?? DASH} ~ ${data.last_date ?? DASH}` },
      ]} />
      <Typography.Text type="secondary">종목별 보관 기간 분포</Typography.Text>
      <EChart option={option} height={200} />
      {data.missing_codes.length > 0 && <Typography.Text type="secondary">누락 종목(앞 {data.missing_codes.length}개): {data.missing_codes.join(', ')}</Typography.Text>}
    </Space>
  )
}
