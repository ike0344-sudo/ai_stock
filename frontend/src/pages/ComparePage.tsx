// 비교 (§5.4): 곡선 겹치기(시작=100) · 지표 비교 표(좋은 쪽 강조) · 조건 차이 문장. 주소 `#/compare?ids=a,b,c`(2~5개) — 없으면 담아 둔 바구니.
import { Alert, Button, Card, List, Space, Spin, Switch, Table, Tag, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { compareRuns } from '@/api/studio'
import { EChart } from '@/components/charts/EChart'
import { compareOption, SERIES_COLORS } from '@/lib/chartOptions'
import { getBasket } from '@/lib/compareBasket'
import { fmtDate } from '@/lib/format'
import { bestIndexes, fmtMetric, GROUPS, METRIC_DEFS } from '@/lib/metrics'
import { VERDICT3_COLOR, verdictOf } from '@/lib/verdicts'
import { mv, type CompareData } from '@/types/studio'

export function ComparePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const fromUrl = (params.get('ids') ?? '').split(',').filter(Boolean)
  const ids = fromUrl.length ? fromUrl : getBasket()
  const key = ids.join(',')
  const [data, setData] = useState<CompareData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [log, setLog] = useState(false)

  useEffect(() => {
    setData(null); setError(null)
    if (ids.length < 2) return
    let dead = false
    compareRuns(ids)
      .then((d) => { if (!dead) setData(d) })
      .catch((e) => { if (!dead) setError(e instanceof ApiError ? e.message : String(e)) })
    return () => { dead = true }
    // ids 는 key 로 비교한다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  const option = useMemo(() => (data ? compareOption(data.runs.map((r) => ({ name: r.name ?? r.run_id, equity: r.equity })), log) : null), [data, log])

  if (ids.length < 2) {
    return <Alert type="info" showIcon data-testid="compare-need-two" message="비교할 실행을 2개 이상 골라 주세요" description={<Space>실행 기록에서 체크하거나 결과 화면의 &quot;비교에 추가&quot;로 담으세요.<Button size="small" onClick={() => navigate('/runs')}>실행 기록으로</Button></Space>} />
  }
  if (error) return <Alert type="error" showIcon data-testid="compare-error" message={`비교하지 못했습니다: ${error}`} />
  if (!data) return <Spin data-testid="compare-loading" />

  const cols = data.runs
  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }} data-testid="compare-page">
      <Space wrap>
        {cols.map((r, i) => (
          <Tag key={r.run_id} color={SERIES_COLORS[i % SERIES_COLORS.length]} style={{ fontSize: 14, padding: '4px 10px' }}>
            {r.name ?? r.run_id} · {r.period ? `${fmtDate(r.period.start)} ~ ${fmtDate(r.period.end)}` : ''} <Link to={`/results/${r.run_id}`}>결과</Link>
          </Tag>
        ))}
      </Space>

      <Card size="small" title="수익곡선 겹치기 (시작 = 100)" extra={<Space>로그 축<Switch size="small" checked={log} onChange={setLog} /></Space>} data-testid="compare-chart">
        {option && <EChart option={option} height={380} />}
      </Card>

      <Card size="small" title="지표 비교 (초록 테두리 = 그 줄에서 가장 좋은 값)" data-testid="compare-metrics">
        <Table size="small" pagination={false} rowKey="key" dataSource={GROUPS.flatMap((g) => METRIC_DEFS.filter((m) => m.group === g))}
          columns={[
            { title: '지표', dataIndex: 'label', render: (l: string, m) => <span title={m.help}>{l}</span> },
            ...cols.map((r, i) => ({
              title: r.name ?? r.run_id, key: r.run_id,
              render: (_: unknown, m: (typeof METRIC_DEFS)[number]) => {
                const values = cols.map((c) => mv(c.metrics_all, m.key))
                const best = bestIndexes(m.key, values).includes(i)
                const v = verdictOf(m.key, values[i])
                return (
                  <span data-testid={`cmp-${m.key}-${i}`} data-best={best} data-verdict={v ?? 'none'}
                    style={{ padding: '2px 6px', borderRadius: 4, border: best ? '2px solid #52c41a' : '2px solid transparent', color: v ? VERDICT3_COLOR[v] : undefined, fontWeight: best ? 700 : undefined }}>
                    {fmtMetric(m, values[i])}
                  </span>
                )
              },
            })),
          ]} />
      </Card>

      <Card size="small" title={`조건 차이 (첫 번째 “${cols[0].name ?? cols[0].run_id}” 와 비교)`} data-testid="compare-diffs">
        {data.diffs.map((d) => {
          const r = cols.find((c) => c.run_id === d.run_id)!
          return (
            <div key={d.run_id} style={{ marginBottom: 12 }}>
              <Typography.Text strong>{r.name ?? r.run_id}</Typography.Text>
              {d.items.length === 0 ? <Typography.Paragraph type="secondary" style={{ margin: 0 }}>조건이 같습니다(이름만 다름)</Typography.Paragraph>
                : <List size="small" dataSource={d.items} renderItem={(it) => <List.Item style={{ padding: '2px 0' }} data-testid="diff-item">{it.text}</List.Item>} />}
            </div>
          )
        })}
      </Card>
    </Space>
  )
}
