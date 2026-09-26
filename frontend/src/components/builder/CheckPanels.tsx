// 조건 풀이 문장 · 검증 오류 · [오늘 조건 맞는 종목] 표 (§5.4)
import { Alert, Card, Empty, List, Space, Table, Tag, Typography } from 'antd'
import { fmtNum } from '@/lib/format'
import type { PreviewResult, PreviewRow, ValidateResult } from '@/types/studio'

export function NarrationPanel({ result, loading }: { result?: ValidateResult; loading: boolean }) {
  return (
    <Card size="small" title="이 조건을 말로 풀면" loading={loading && !result} data-testid="narration-panel">
      {result?.narration ? (
        <Typography.Paragraph data-testid="narration" style={{ whiteSpace: 'pre-line', marginBottom: 0 }}>{result.narration}</Typography.Paragraph>
      ) : (
        <Typography.Text type="secondary">{result && !result.ok ? '오류를 고치면 풀이가 나옵니다' : '조건을 만들면 여기에 문장으로 풀어 줍니다'}</Typography.Text>
      )}
    </Card>
  )
}

export function ValidationPanel({ result, error, unitWarnings = [] }: { result?: ValidateResult; error?: string; unitWarnings?: string[] }) {
  if (error) return <Alert type="error" showIcon message="검증을 못 함" description={error} data-testid="validation-error" />
  if (!result) return null
  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid="validation-panel">
      {result.ok ? <Alert type="success" showIcon message="검증 통과 — 실행할 수 있습니다" data-testid="validation-ok" /> : (
        <Alert type="error" showIcon message={`오류 ${result.errors.length}건 — 고쳐야 실행할 수 있습니다`}
          description={<List size="small" data-testid="validation-errors" dataSource={result.errors}
            renderItem={(e) => <List.Item style={{ padding: '2px 0' }}><Typography.Text type="danger"><code>{e.path || '(전체)'}</code> — {e.message}</Typography.Text></List.Item>} />} />
      )}
      {unitWarnings.length > 0 && (
        <Alert type="warning" showIcon message={`단위가 안 맞는 비교 ${unitWarnings.length}건`} data-testid="unit-warnings"
          description={<ul style={{ margin: 0, paddingLeft: 18 }}>{unitWarnings.map((w, i) => <li key={i}>{w}</li>)}</ul>} />
      )}
      {result.warnings.length > 0 && (
        <Alert type="warning" showIcon message={`주의 ${result.warnings.length}건`}
          description={<ul style={{ margin: 0, paddingLeft: 18 }}>{result.warnings.map((w) => <li key={w.message}>{w.message}</li>)}</ul>} data-testid="validation-warnings" />
      )}
    </Space>
  )
}

export function PreviewTable({ data, loading, error }: { data?: PreviewResult; loading: boolean; error?: string }) {
  return (
    <Card size="small" title={data ? `오늘(${data.date}) 조건에 맞는 종목 ${data.matched}개 / 대상 ${fmtNum(data.universe_size)}종목` : '오늘 조건에 맞는 종목'}
      loading={loading} data-testid="preview-panel">
      {error && <Alert type="error" showIcon message={error} />}
      {data && (
        <Table<PreviewRow> size="small" rowKey="code" dataSource={data.rows} pagination={{ pageSize: 10, hideOnSinglePage: true }}
          locale={{ emptyText: <Empty description="오늘 이 조건에 걸리는 종목이 없습니다" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          expandable={{ rowExpandable: (r) => !!r.operands?.length, expandedRowRender: (r) => (
            <ul style={{ margin: 0, paddingLeft: 18 }}>{r.operands!.map((o) => <li key={o.text}>{o.text} — {fmtNum(o.left)} vs {fmtNum(o.right)}</li>)}</ul>) }}
          columns={[
            { title: '종목', render: (_, r) => `${r.code} ${r.name ?? ''}` },
            { title: '종가', dataIndex: 'close', render: (v: number) => fmtNum(v) },
            { title: '등락률', dataIndex: 'change_pct', render: (v: number | null) => (v === null ? '—' : <span style={{ color: v > 0 ? '#f5222d' : v < 0 ? '#1677ff' : undefined }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</span>) },
            { title: '거래대금', dataIndex: 'value', render: (v: number) => `${fmtNum(Math.round(v / 1e8))}억` },
            { title: '순위', dataIndex: 'value_rank', render: (v: number | null) => (v === null ? '—' : <Tag>{v}위</Tag>) },
          ]} />
      )}
      {data?.truncated && <Typography.Text type="secondary">상위 일부만 보여줍니다</Typography.Text>}
    </Card>
  )
}
