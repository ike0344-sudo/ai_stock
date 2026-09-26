// 실행 기록 (§5.4): 별표·이름·모드·기간·총수익·CAGR·MDD·샤프·거래 수·메모·생성 시각 · 정렬·검색·필터 · 인라인 편집 ·
// 다중 선택 → [비교](2~5) · [삭제](확인 — 실행 결과만, 데이터는 안 지운다)
import { DeleteOutlined, StarFilled, StarOutlined, SwapOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Card, Input, Popconfirm, Select, Space, Switch, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { deleteRun, patchRun, useRuns } from '@/api/studio'
import { getBasket, MAX_COMPARE, setBasket } from '@/lib/compareBasket'
import { DASH, fmtDate } from '@/lib/format'
import { KIND_LABEL_RUN, MODE_LABEL } from '@/lib/labels'
import { fmtMetric, METRIC_DEFS } from '@/lib/metrics'
import { VERDICT3_COLOR, verdictOf } from '@/lib/verdicts'
import type { RunRow } from '@/types/studio'

const def = (k: string) => METRIC_DEFS.find((m) => m.key === k)!

function MetricCell({ k, v }: { k: string; v: number | null | undefined }) {
  const verdict = verdictOf(k, v)
  return <span data-verdict={verdict ?? 'none'} style={{ color: verdict ? VERDICT3_COLOR[verdict] : undefined, fontWeight: verdict ? 600 : undefined }}>{fmtMetric(def(k), v)}</span>
}

/** 글자를 눌러 고치는 칸 — 포커스를 잃거나 Enter 로 저장한다 */
function InlineEdit({ value, placeholder, onSave, testid }: { value: string | null; placeholder?: string; onSave: (v: string) => void; testid?: string }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(value ?? '')
  if (!editing) {
    return (
      <span data-testid={testid} style={{ cursor: 'text', minWidth: 60, display: 'inline-block' }} onClick={() => { setText(value ?? ''); setEditing(true) }}>
        {value || <Typography.Text type="secondary">{placeholder ?? '—'}</Typography.Text>}
      </span>
    )
  }
  const done = () => { setEditing(false); if (text !== (value ?? '')) onSave(text) }
  return <Input size="small" autoFocus value={text} onChange={(e) => setText(e.target.value)} onBlur={done} onPressEnter={done} data-testid={testid ? `${testid}-input` : undefined} />
}

export function RunsPage() {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [mode, setMode] = useState<string | undefined>()
  const [kind, setKind] = useState<string | undefined>()
  const [starredOnly, setStarredOnly] = useState(false)
  const [sel, setSel] = useState<string[]>([])
  const runs = useRuns({ q: q || undefined, mode, kind, starred: starredOnly ? true : undefined })
  const basket = getBasket()

  const refresh = () => { void qc.invalidateQueries({ queryKey: ['runs'] }) }
  const save = async (id: string, body: { name?: string; memo?: string | null; starred?: boolean }) => {
    try { await patchRun(id, body); refresh() } catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
  }
  const remove = async () => {
    try {
      await Promise.all(sel.map(deleteRun))
      message.success(`${sel.length}개 실행 결과를 삭제했습니다(데이터는 그대로)`)
      setBasket(getBasket().filter((id) => !sel.includes(id)))
      setSel([]); refresh()
    } catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
  }
  const canCompare = sel.length >= 2 && sel.length <= MAX_COMPARE

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="runs-page">
      <Card size="small">
        <Space wrap>
          <Input.Search allowClear placeholder="이름·메모·번호 검색" style={{ width: 240 }} onSearch={setQ} data-testid="runs-search" />
          <Select allowClear placeholder="모드" style={{ width: 170 }} value={mode} onChange={setMode} options={Object.entries(MODE_LABEL).map(([v, label]) => ({ value: v, label }))} />
          <Select allowClear placeholder="종류" style={{ width: 140 }} value={kind} onChange={setKind} options={Object.entries(KIND_LABEL_RUN).map(([v, label]) => ({ value: v, label }))} />
          <span>별표만 <Switch size="small" checked={starredOnly} onChange={setStarredOnly} data-testid="runs-starred-only" /></span>
          <span style={{ width: 16 }} />
          <Button type="primary" icon={<SwapOutlined />} disabled={!canCompare} data-testid="compare-btn" onClick={() => navigate(`/compare?ids=${sel.join(',')}`)}>비교 ({sel.length})</Button>
          <Popconfirm title={`${sel.length}개 삭제`} description="실행 결과(거래·곡선·지표)만 지웁니다. 시장 데이터는 지우지 않습니다." okText="삭제" cancelText="취소" onConfirm={remove} disabled={!sel.length}>
            <Button danger icon={<DeleteOutlined />} disabled={!sel.length} data-testid="delete-btn">삭제 ({sel.length})</Button>
          </Popconfirm>
          {basket.length >= 2 && <Button onClick={() => navigate(`/compare?ids=${basket.join(',')}`)} data-testid="basket-compare">담아 둔 {basket.length}개 비교</Button>}
        </Space>
        {sel.length > MAX_COMPARE && <Typography.Text type="danger"> 비교는 최대 {MAX_COMPARE}개까지입니다</Typography.Text>}
      </Card>
      {runs.isError && <Alert type="error" showIcon message={`실행 기록을 못 불러옴: ${runs.error.message}`} />}
      <Table<RunRow> size="small" data-testid="runs-table" rowKey="run_id" loading={runs.isPending} dataSource={runs.data ?? []}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        rowSelection={{ selectedRowKeys: sel, onChange: (k) => setSel(k as string[]) }}
        locale={{ emptyText: '실행 기록이 없습니다 — 백테스트를 한 번 돌려 보세요' }}
        columns={[
          { title: '', width: 40, render: (_, r) => <Button type="text" size="small" aria-label={r.starred ? '별표 해제' : '별표'} icon={r.starred ? <StarFilled style={{ color: '#fadb14' }} /> : <StarOutlined />} onClick={() => save(r.run_id, { starred: !r.starred })} data-testid={`star-${r.run_id}`} /> },
          { title: '이름', dataIndex: 'name', sorter: (a, b) => (a.name ?? '').localeCompare(b.name ?? ''), render: (_, r) => (
            <Space direction="vertical" size={0}>
              <InlineEdit value={r.name} testid={`name-${r.run_id}`} onSave={(v) => v.trim() && save(r.run_id, { name: v })} />
              <Link to={`/results/${r.run_id}`} style={{ fontSize: 12 }}>결과 보기 · {r.run_id}</Link>
            </Space>) },
          { title: '종류', dataIndex: 'kind', render: (k: string) => <Tag>{KIND_LABEL_RUN[k] ?? k}</Tag> },
          { title: '모드', dataIndex: 'mode', render: (m: RunRow['mode']) => (m ? MODE_LABEL[m] : DASH) },
          { title: '기간', render: (_, r) => (r.period ? `${fmtDate(r.period.start)} ~ ${fmtDate(r.period.end)}` : DASH) },
          { title: '총수익', sorter: (a, b) => (a.metrics.total_return_pct ?? -1e9) - (b.metrics.total_return_pct ?? -1e9), render: (_, r) => <MetricCell k="total_return_pct" v={r.metrics.total_return_pct} /> },
          { title: 'CAGR', sorter: (a, b) => (a.metrics.cagr_pct ?? -1e9) - (b.metrics.cagr_pct ?? -1e9), render: (_, r) => <MetricCell k="cagr_pct" v={r.metrics.cagr_pct} /> },
          { title: 'MDD', sorter: (a, b) => (a.metrics.max_drawdown_pct ?? 1e9) - (b.metrics.max_drawdown_pct ?? 1e9), render: (_, r) => <MetricCell k="max_drawdown_pct" v={r.metrics.max_drawdown_pct} /> },
          { title: '샤프', sorter: (a, b) => (a.metrics.sharpe ?? -1e9) - (b.metrics.sharpe ?? -1e9), render: (_, r) => <MetricCell k="sharpe" v={r.metrics.sharpe} /> },
          { title: '거래', sorter: (a, b) => (a.metrics.num_trades ?? 0) - (b.metrics.num_trades ?? 0), render: (_, r) => <MetricCell k="num_trades" v={r.metrics.num_trades} /> },
          { title: '메모', dataIndex: 'memo', render: (_, r) => <InlineEdit value={r.memo} placeholder="메모 추가" testid={`memo-${r.run_id}`} onSave={(v) => save(r.run_id, { memo: v || null })} /> },
          { title: '생성', dataIndex: 'created_at', defaultSortOrder: 'descend', sorter: (a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''), render: (t: string | null) => (t ? t.replace('T', ' ').slice(0, 16) : DASH) },
        ]} />
    </Space>
  )
}
