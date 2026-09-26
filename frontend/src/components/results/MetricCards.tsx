// 지표 카드 (§5.4 ResultPage) — 접지 않는다: 전 지표를 그룹별로 다 보여주고 §5.5 판정 색을 붙인다. + 기존 CLI 기준 줄 · 경고 배지 · 사전 판정 기준 표
import { Alert, Card, Col, Row, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { DASH } from '@/lib/format'
import { fmtMetric, GROUPS, LEGACY_LABELS, METRIC_DEFS, type MetricDef } from '@/lib/metrics'
import { RULE_TEXT, VERDICT3_COLOR, VERDICT3_LABEL, verdictOf } from '@/lib/verdicts'
import { mv, type CriteriaRow, type FullMetrics } from '@/types/studio'

export function MetricCard({ def, value, infinite = false }: { def: MetricDef; value: number | null | undefined; infinite?: boolean }) {
  const v = infinite ? 'good' : verdictOf(def.key, value)
  return (
    <Card size="small" data-testid={`metric-${def.key}`} data-verdict={v ?? 'none'} style={{ borderTop: `3px solid ${v ? VERDICT3_COLOR[v] : '#d9d9d9'}`, height: '100%' }}>
      <Space direction="vertical" size={2} style={{ width: '100%' }}>
        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
          <Typography.Text type="secondary">{def.label}</Typography.Text>
          {v && <Tooltip title={RULE_TEXT[def.key]}><Tag color={VERDICT3_COLOR[v]} style={{ marginInlineEnd: 0 }}>{VERDICT3_LABEL[v]}</Tag></Tooltip>}
        </Space>
        <Typography.Text strong style={{ fontSize: 20 }} data-testid={`metric-${def.key}-value`}>{infinite ? '∞ (손실 없음)' : fmtMetric(def, value)}</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{def.help}</Typography.Text>
      </Space>
    </Card>
  )
}

export function MetricCards({ metrics }: { metrics: FullMetrics }) {
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="metric-cards">
      {GROUPS.map((g) => (
        <div key={g}>
          <Typography.Text strong>{g}</Typography.Text>
          <Row gutter={[12, 12]} style={{ marginTop: 6 }}>
            {METRIC_DEFS.filter((m) => m.group === g).map((def) => (
              <Col key={def.key} xs={12} md={8} xl={6} xxl={4}><MetricCard def={def} value={mv(metrics, def.key)} infinite={def.key === 'profit_factor' && mv(metrics, 'profit_factor') === null && (mv(metrics, 'win_rate_pct') ?? 0) > 0} /></Col>
            ))}
          </Row>
        </div>
      ))}
    </Space>
  )
}

/** 호환 모드: 기존 CLI(`backtesting.metrics.compute`) 정의로 계산한 값 한 줄 — 표준 지표와 정의가 다르다 */
export function LegacyLine({ legacy }: { legacy: Record<string, number | null> | null }) {
  if (!legacy) return null
  return (
    <Alert type="info" showIcon data-testid="legacy-line" message="기존 CLI 기준 (호환 모드)"
      description={LEGACY_LABELS.map(([k, label, fmt]) => `${label} ${legacy[k] === null || legacy[k] === undefined ? DASH : fmt(legacy[k] as number)}`).join(' · ')} />
  )
}

/** 경고는 배지로 전부 그대로 — 요약하거나 접지 않는다 */
export function WarningBadges({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null
  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }} data-testid="warning-badges">
      {warnings.map((w) => <Alert key={w} type="warning" showIcon banner message={w} />)}
    </Space>
  )
}

/** 사전 판정 기준(spec.validation.criteria) — 실행 전에 정한 값 그대로, 전체 구간 지표로 통과 여부 */
export function CriteriaTable({ rows }: { rows: CriteriaRow[] }) {
  if (!rows.length) return null
  return (
    <Card size="small" title="사전 판정 기준 (실행 전에 정한 값 — 실행 뒤엔 못 고칩니다)" data-testid="criteria-table">
      <Table<CriteriaRow> size="small" rowKey="metric" pagination={false} dataSource={rows}
        columns={[
          { title: '지표', dataIndex: 'metric', render: (m: string) => METRIC_DEFS.find((d) => d.key === m)?.label ?? m },
          { title: '기준', render: (_, r) => `${r.direction === 'max' ? '≤' : '≥'} ${r.threshold}` },
          { title: '결과', dataIndex: 'value', render: (v: number | null) => (v === null ? DASH : Number(v).toFixed(2)) },
          { title: '판정', dataIndex: 'passed', render: (p: boolean) => <Tag color={p ? 'success' : 'error'}>{p ? '통과' : '미달'}</Tag> },
        ]} />
    </Card>
  )
}
