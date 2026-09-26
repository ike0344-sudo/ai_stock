// 검증 결과 패널 (§5.4 OptimizePage 결과 부분): 최적화 · 워크포워드 · 홀드아웃.
// 정보는 접지 않는다 — 조합 표는 무효·거래 부족 조합까지 전부 보여주고(되는 것만 보이지 않게), 홀드아웃은 열 때마다 횟수를 크게 말한다.
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Checkbox, Col, Modal, Row, Select, Space, Table, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { fetchHoldoutHistory, submitHoldout, useGrid, useRunDetail } from '@/api/studio'
import { RunModal } from '@/components/builder/RunModal'
import { EChart } from '@/components/charts/EChart'
import { DASH, fmtDate } from '@/lib/format'
import { METRIC_DEFS, fmtMetric } from '@/lib/metrics'
import { OBJECTIVES, foldsOption, gridVariables, heatmapData, heatmapOption, varyingVariables } from '@/lib/validation'
import { RULE_TEXT, VERDICT3_COLOR, VERDICT3_LABEL, verdictOf } from '@/lib/verdicts'
import { mv, type FoldsFile, type FullMetrics, type GridRow, type HoldoutSummary, type OptimizeSummary, type RunDetail, type SegmentInfo, type WalkforwardSummary } from '@/types/studio'

const objLabel = (k: string) => OBJECTIVES.find((o) => o.key === k)?.label ?? k
const metricDef = (k: string) => METRIC_DEFS.find((m) => m.key === k)
const KEY_METRICS = ['total_return_pct', 'cagr_pct', 'max_drawdown_pct', 'sharpe', 'sortino', 'calmar', 'profit_factor', 'expectancy_pct', 'num_trades', 'win_rate_pct']

/** 값 하나 + 판정 색 점(§5.5) — 기준이 없는 지표는 색 없이 숫자만 */
function V({ k, v }: { k: string; v: number | null }) {
  const def = metricDef(k)
  const verdict = verdictOf(k, v)
  return (
    <span data-verdict={verdict ?? 'none'}>
      {verdict && <span title={`${VERDICT3_LABEL[verdict]} — ${RULE_TEXT[k]}`} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 4, background: VERDICT3_COLOR[verdict], marginRight: 6 }} />}
      {def ? fmtMetric(def, v) : v === null ? DASH : v.toFixed(2)}
    </span>
  )
}

/** 구간별 성과를 나란히 — 학습(IS) · 검증(OOS) · (홀드아웃). 학습에서만 좋고 나머지에서 무너지면 과최적화 */
export function CompareTable({ cols, testid }: { cols: { title: string; sub?: string; metrics: FullMetrics | undefined }[]; testid: string }) {
  const rows = KEY_METRICS.map((k) => ({ k, label: metricDef(k)?.label ?? k }))
  return (
    <Table size="small" pagination={false} rowKey="k" dataSource={rows} data-testid={testid}
      columns={[
        { title: '지표', dataIndex: 'label' },
        ...cols.map((c, i) => ({
          title: <span>{c.title}{c.sub && <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, fontWeight: 400 }}>{c.sub}</Typography.Text>}</span>,
          key: `c${i}`, render: (_: unknown, r: { k: string }) => (c.metrics ? <V k={r.k} v={mv(c.metrics, r.k)} /> : DASH),
        })),
      ]} />
  )
}

const segText = (s: SegmentInfo | null) => (s ? `${fmtDate(s[0])} ~ ${fmtDate(s[1])} · ${s[2]}거래일` : '없음')

function Segments({ seg }: { seg: OptimizeSummary['segments'] }) {
  return (
    <Row gutter={[12, 12]} data-testid="segments">
      <Col xs={24} md={8}><Card size="small" title={<Tag>학습(IS)</Tag>}><Typography.Text>{segText(seg.is)}</Typography.Text><br /><Typography.Text type="secondary">조합을 고르는 데만 쓴 구간</Typography.Text></Card></Col>
      <Col xs={24} md={8}><Card size="small" title={<Tag color="blue">검증(OOS)</Tag>}><Typography.Text>{segText(seg.oos)}</Typography.Text><br /><Typography.Text type="secondary">고른 조합이 처음 보는 구간 — 여기서도 좋아야 믿을 만하다</Typography.Text></Card></Col>
      <Col xs={24} md={8}><Card size="small" title={<Tag color="orange">홀드아웃(잠김)</Tag>}><Typography.Text>{segText(seg.holdout)}</Typography.Text><br /><Typography.Text type="secondary">최적화·선택에 쓰지 않았다 — 아래 버튼으로만 연다</Typography.Text></Card></Col>
    </Row>
  )
}

const STATUS_COLOR: Record<string, string> = { ok: 'success', few_trades: 'warning' }

const COL_LABEL: Record<string, string> = { sharpe: '샤프', cagr: '연수익', calmar: '칼마', profit_factor: '손익비', expectancy: '기대값', trades: '거래 수', return_pct: '수익률(%)', mdd_pct: '낙폭(%)' }
const PREFIX: Record<string, string> = { is_: '학습 ', oos_: '검증 ', full_: '전체 ' }
function colLabel(k: string): string {
  for (const [p, name] of Object.entries(PREFIX)) if (k.startsWith(p)) return `${name}${COL_LABEL[k.slice(p.length)] ?? k.slice(p.length)}`
  return { status: '상태', rank_is: '학습 순위', selected: '선택', chosen_folds: '뽑힌 폴드' }[k] ?? k
}

/** 조합 표 — 전 조합(무효·거래 부족 포함). 선택된 조합은 ★ 와 굵은 글씨 */
export function GridTable({ rows, objective }: { rows: GridRow[]; objective: string }) {
  const vars = gridVariables(rows)
  const perf = rows.length ? Object.keys(rows[0]).filter((k) => !vars.includes(k) && k !== 'status' && k !== 'selected') : []
  const order = [`is_${objective}`, `oos_${objective}`, 'is_trades', 'oos_trades', 'is_return_pct', 'oos_return_pct', 'is_mdd_pct', 'oos_mdd_pct', 'rank_is']
  const perfCols = [...order.filter((k) => perf.includes(k)), ...perf.filter((k) => !order.includes(k))]
  const num = (k: string) => (a: GridRow, b: GridRow) => Number(a[k] ?? -Infinity) - Number(b[k] ?? -Infinity)
  return (
    <Table<GridRow> size="small" data-testid="grid-table" rowKey={(r) => vars.map((v) => String(r[v])).join('|')} dataSource={rows}
      rowClassName={(r) => (r.selected ? 'grid-selected' : '')} onRow={(r) => ({ style: r.selected ? { fontWeight: 700, background: 'rgba(22,119,255,0.10)' } : undefined })}
      scroll={{ x: 'max-content' }} pagination={{ pageSize: 15, showSizeChanger: true, pageSizeOptions: [15, 50, 100], showTotal: (t) => `조합 ${t}개` }}
      columns={[
        { title: '', dataIndex: 'selected', width: 28, render: (s: boolean) => (s ? <span title="학습 구간 기준으로 고른 조합">★</span> : null) },
        ...vars.map((v) => ({ title: v, dataIndex: v, sorter: num(v) })),
        { title: '상태', dataIndex: 'status', filters: [...new Set(rows.map((r) => String(r.status)))].map((s) => ({ text: s, value: s })), onFilter: (v: unknown, r: GridRow) => r.status === v,
          render: (s: string) => <Tag color={STATUS_COLOR[s] ?? 'error'}>{s === 'ok' ? '정상' : s === 'few_trades' ? '거래 부족' : s}</Tag> },
        ...perfCols.map((k) => ({ title: colLabel(k), dataIndex: k, sorter: num(k), defaultSortOrder: k === 'rank_is' ? ('ascend' as const) : undefined,
          render: (v: number | null) => (v === null || v === undefined ? DASH : Number.isInteger(v) ? v.toLocaleString('ko-KR') : v.toFixed(2)) })),
      ]} />
  )
}

/** 2변수 히트맵 — 변수를 고르면 그 두 축으로 그린다. 셋 이상이면 나머지는 최고값으로 접었다고 밝힌다 */
export function GridHeatmap({ rows, objective }: { rows: GridRow[]; objective: string }) {
  const vary = useMemo(() => varyingVariables(rows), [rows])
  const [x, setX] = useState<string>(vary[0] ?? '')
  const [y, setY] = useState<string>(vary[1] ?? '')
  const cols = useMemo(() => [`is_${objective}`, `oos_${objective}`, 'is_return_pct', 'oos_return_pct', 'is_mdd_pct', 'oos_mdd_pct'].filter((c) => rows.length && c in rows[0]), [rows, objective])
  const [col, setCol] = useState<string>(`oos_${objective}`)
  const valueCol = cols.includes(col) ? col : cols[0]
  const data = useMemo(() => (x && y && x !== y && valueCol ? heatmapData(rows, x, y, valueCol) : null), [rows, x, y, valueCol])
  const opt = useMemo(() => (data ? heatmapOption(data, x, y, colLabel(valueCol)) : null), [data, x, y, valueCol])
  if (vary.length < 2) return <Card size="small" title="2변수 히트맵" data-testid="panel-heatmap"><Typography.Text type="secondary">훑은 변수가 하나뿐이라 히트맵을 그리지 않는다(위 조합 표가 전부다)</Typography.Text></Card>
  const opts = (except: string) => vary.filter((v) => v !== except).map((v) => ({ value: v, label: v }))
  return (
    <Card size="small" title="2변수 히트맵 (굵은 테두리 = 고른 조합)" data-testid="panel-heatmap"
      extra={<Space wrap>가로<Select size="small" value={x} options={opts(y)} onChange={setX} style={{ width: 110 }} data-testid="heat-x" />세로<Select size="small" value={y} options={opts(x)} onChange={setY} style={{ width: 110 }} data-testid="heat-y" />
        값<Select size="small" value={valueCol} options={cols.map((c) => ({ value: c, label: colLabel(c) }))} onChange={setCol} style={{ width: 130 }} data-testid="heat-col" /></Space>}>
      {data?.folded && <Alert type="info" showIcon style={{ marginBottom: 8 }} message="변수가 셋 이상이라 나머지 변수는 칸마다 가장 좋은 값으로 접었다 — 한 칸이 여러 조합의 최고값이다" />}
      {opt ? <EChart option={opt} height={Math.max(260, 70 + 44 * (data?.ys.length ?? 0))} /> : null}
    </Card>
  )
}

/** 이웃 안정성 — 고른 조합 옆 칸들이 함께 좋은가(절벽 위의 뾰족한 점이면 과최적화) */
function Stability({ s }: { s: OptimizeSummary['neighbor_stability'] }) {
  const v = verdictOf('neighbor_stability', s.ratio)
  return (
    <Card size="small" title="이웃 안정성" data-testid="stability" style={{ borderTop: `3px solid ${v ? VERDICT3_COLOR[v] : '#d9d9d9'}`, height: '100%' }}>
      <Space direction="vertical" size={2}>
        <Space>
          <Typography.Text strong style={{ fontSize: 20 }} data-testid="stability-value">{s.ratio === null ? DASH : s.ratio.toFixed(2)}</Typography.Text>
          {v && <Tag color={VERDICT3_COLOR[v]}>{VERDICT3_LABEL[v]}</Tag>}
          {s.warn && <Tag color="warning">주의</Tag>}
        </Space>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>고른 조합의 옆 칸 {s.n_neighbors}개 목표값의 중앙값 ÷ 최고값. {RULE_TEXT.neighbor_stability}</Typography.Text>
        {s.reason && <Typography.Text type="warning">{s.reason}</Typography.Text>}
      </Space>
    </Card>
  )
}

function CriteriaOos({ rows }: { rows: OptimizeSummary['criteria_on_oos'] }) {
  if (!rows.length) return null
  return (
    <Card size="small" title="사전 판정 기준 — 검증(OOS) 구간 지표로 판정 (실행 전에 정한 값 · 실행 뒤엔 못 고칩니다)" data-testid="criteria-oos">
      <Table size="small" rowKey="metric" pagination={false} dataSource={rows}
        columns={[
          { title: '지표', dataIndex: 'metric', render: (m: string) => metricDef(m)?.label ?? m },
          { title: '기준', render: (_, r) => `${r.direction === 'max' ? '≤' : '≥'} ${r.threshold}` },
          { title: '검증 구간 값', dataIndex: 'value', render: (v: number | null) => (v === null ? DASH : Number(v).toFixed(2)) },
          { title: '판정', dataIndex: 'passed', render: (p: boolean) => <Tag color={p ? 'success' : 'error'}>{p ? '통과' : '미달'}</Tag> },
        ]} />
    </Card>
  )
}

/** 홀드아웃 열기 — 열기 전에 확인 대화상자. 이미 연 적이 있으면(골격 기준) 강한 경고를 먼저 보여 준다 */
export function HoldoutOpener({ d }: { d: RunDetail }) {
  const opt = d.summary.optimize as OptimizeSummary | undefined
  const seg = opt?.segments.holdout ?? null
  const [confirm, setConfirm] = useState(false)
  const [understood, setUnderstood] = useState(false)
  const [run, setRun] = useState<RunDetail['spec'] | null>(null)
  const hist = useQuery({ queryKey: ['holdout-history', d.run_id, confirm], queryFn: () => fetchHoldoutHistory(d.spec), enabled: confirm, staleTime: 0, retry: false })
  if (!opt) return null
  const opens = hist.data?.count ?? 0
  const need = opens > 0 && !understood
  return (
    <Card size="small" title="홀드아웃 패널" data-testid="holdout-panel" style={{ borderColor: '#fa8c16' }}>
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Typography.Text>
          홀드아웃 {segText(seg)} — 조합을 고르는 데 한 번도 쓰지 않은 시험지다. 여기서도 성과가 유지돼야 진짜다.
          <b> 열어서 결과를 보고 조건을 고치면 그 순간부터 홀드아웃이 아니다.</b>
        </Typography.Text>
        <Button danger disabled={!seg} onClick={() => { setUnderstood(false); setConfirm(true) }} data-testid="holdout-open-btn">
          이 조합({Object.entries(opt.selected.params).map(([k, v]) => `${k}=${v}`).join(', ')})으로 홀드아웃 열기
        </Button>
        {!seg && <Typography.Text type="secondary">홀드아웃 비율이 0% 라 남겨 둔 구간이 없다</Typography.Text>}
      </Space>
      <Modal open={confirm} title="홀드아웃을 엽니다 — 되돌릴 수 없습니다" onCancel={() => setConfirm(false)} destroyOnHidden data-testid="holdout-confirm"
        okText="홀드아웃 열기" cancelText="취소" okButtonProps={{ danger: true, disabled: hist.isPending || hist.isError || need, 'data-testid': 'holdout-confirm-ok' } as never}
        onOk={() => { setConfirm(false); setRun(structuredClone(d.spec)) }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text>구간 {segText(seg)} · 조합 {Object.entries(opt.selected.params).map(([k, v]) => `${k}=${v}`).join(', ')}</Typography.Text>
          {hist.isPending && <Typography.Text type="secondary">열람 이력을 확인하는 중…</Typography.Text>}
          {hist.isError && <Alert type="error" showIcon message={`열람 이력을 확인하지 못해 열 수 없습니다: ${hist.error.message}`} />}
          {hist.data && !hist.data.ledger_connected && <Alert type="warning" showIcon message="열람 장부가 연결돼 있지 않아 횟수를 셀 수 없다" />}
          {hist.data && opens === 0 && hist.data.ledger_connected && <Alert type="info" showIcon message="이 전략 골격으로 홀드아웃을 여는 것은 처음이다" data-testid="holdout-first" />}
          {opens > 0 && (
            <Alert type="error" showIcon data-testid="holdout-warn" message={`이 전략 골격으로 이미 ${opens}번 열었다 — 이번이 ${opens + 1}번째`}
              description={<div>
                <div>손절 값이나 조건 숫자를 고쳐 가며 홀드아웃을 반복해 열면, 홀드아웃이 사실상 최적화 데이터가 된다(엿보기). 열 수는 있지만 결과의 신뢰는 그만큼 깎인다.</div>
                <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{hist.data?.opens.map((o, i) => <li key={o.open_id ?? i}>{o.opened_at.replace('T', ' ')} · {Object.entries(o.params ?? {}).map(([k, v]) => `${k}=${v}`).join(', ') || '조합 미기록'}</li>)}</ul>
              </div>} />
          )}
          {opens > 0 && <Checkbox checked={understood} onChange={(e) => setUnderstood(e.target.checked)} data-testid="holdout-understood">위 내용을 이해하고 그래도 연다</Checkbox>}
        </Space>
      </Modal>
      <RunModal spec={run} title="홀드아웃 열기" onClose={() => setRun(null)} request={(s) => submitHoldout(s, opt.selected.params, d.run_id)} />
    </Card>
  )
}

/** 최적화 결과 — 구간 · 학습/검증 성과 · 이웃 안정성 · 판정 기준 · 조합 표 · 히트맵 · 홀드아웃 */
export function OptimizeSection({ d }: { d: RunDetail }) {
  const opt = d.summary.optimize as OptimizeSummary
  const grid = useGrid(d.run_id, d.has_grid)
  const sel = opt.selected
  const overfit = sel.is_objective !== null && sel.oos_objective !== null && sel.oos_objective < sel.is_objective * 0.5 && sel.is_objective > 0
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="optimize-section">
      <Alert type="info" showIcon message={`최적화 결과 — 목표 ${objLabel(opt.objective)} · 조합 ${opt.n_combos}개(정상 ${opt.n_valid}, 무효·거래 부족 ${opt.n_invalid}) · 최소 거래 ${opt.min_trades}건`}
        description={<span>고른 조합: <b data-testid="selected-params">{Object.entries(sel.params).map(([k, v]) => `${k}=${v}`).join(', ')}</b> ({sel.selected_by}). 아래 지표 카드·곡선은 이 조합을 최적화 구간 전체(학습+검증)에 돌린 값이라 <b>학습 구간이 섞여 있다</b> — 믿을 값은 아래 &quot;학습 vs 검증&quot; 표다.</span>} />
      {overfit && <Alert type="warning" showIcon data-testid="overfit-warn" message="학습 구간 성과의 절반도 검증 구간에서 안 나왔다 — 과최적화 의심" />}
      <Segments seg={opt.segments} />
      <Row gutter={[12, 12]}>
        <Col xs={24} xl={16}>
          <Card size="small" title="학습 vs 검증 — 고른 조합의 성과" data-testid="is-oos-card">
            <CompareTable testid="is-oos-table" cols={[{ title: '학습(IS)', sub: segText(opt.segments.is), metrics: sel.is }, { title: '검증(OOS)', sub: segText(opt.segments.oos), metrics: sel.oos }]} />
          </Card>
        </Col>
        <Col xs={24} xl={8}><Stability s={opt.neighbor_stability} /></Col>
      </Row>
      <CriteriaOos rows={opt.criteria_on_oos} />
      {opt.selection_note && <Typography.Text type="secondary">{opt.selection_note}</Typography.Text>}
      <Card size="small" title="조합 표 (무효·거래 부족 조합까지 전부)" data-testid="panel-grid">
        {grid.isError ? <Alert type="error" showIcon message={`조합 표를 못 불러옴: ${grid.error.message}`} /> : grid.data ? <GridTable rows={grid.data} objective={opt.objective} /> : <Typography.Text type="secondary">불러오는 중…</Typography.Text>}
      </Card>
      {grid.data && <GridHeatmap rows={grid.data} objective={opt.objective} />}
      <HoldoutOpener d={d} />
    </Space>
  )
}

/** 워크포워드 결과 — WFE · 폴드 표 · 폴드별 학습/검증 · 변수 변화 */
export function WalkforwardSection({ d, folds }: { d: RunDetail; folds: FoldsFile | undefined }) {
  const w = d.summary.walkforward as WalkforwardSummary
  const wfeV = verdictOf('wfe', w.wfe)
  const drift = Object.entries(w.params_drift)
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="walkforward-section">
      <Alert type="info" showIcon message={`워크포워드 결과 — 폴드 ${w.n_folds}개(검증 ${w.n_validated}개) · 조합 ${w.n_combos}개 · 목표 ${objLabel(w.objective)}`}
        description={`${w.note ?? ''} 아래 지표 카드·곡선은 검증 구간만 이은 값이다(학습 구간은 건너뜀).`} />
      <Row gutter={[12, 12]}>
        <Col xs={12} md={8} xl={6}>
          <Card size="small" data-testid="wfe-card" data-verdict={wfeV ?? 'none'} style={{ borderTop: `3px solid ${wfeV ? VERDICT3_COLOR[wfeV] : '#d9d9d9'}`, height: '100%' }}>
            <Typography.Text type="secondary">WFE (검증 수익 ÷ 학습 수익)</Typography.Text><br />
            <Space><Typography.Text strong style={{ fontSize: 20 }} data-testid="wfe-value">{w.wfe === null ? '없음' : w.wfe.toFixed(2)}</Typography.Text>{wfeV && <Tag color={VERDICT3_COLOR[wfeV]}>{VERDICT3_LABEL[wfeV]}</Tag>}</Space><br />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{w.wfe === null ? '학습 구간 평균 수익이 0 이하라 비율이 뜻이 없다. ' : ''}{RULE_TEXT.wfe}</Typography.Text>
          </Card>
        </Col>
        <Col xs={12} md={8} xl={6}>
          <Card size="small" data-testid="positive-folds-card" style={{ height: '100%' }}>
            <Typography.Text type="secondary">수익 난 검증 구간</Typography.Text><br />
            <Typography.Text strong style={{ fontSize: 20 }}>{w.positive_folds} / {w.n_validated}</Typography.Text><br />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>검증 구간이 플러스로 끝난 폴드 수</Typography.Text>
          </Card>
        </Col>
        {folds && (
          <Col xs={24} md={8} xl={12}>
            <Card size="small" style={{ height: '100%' }}>
              <Typography.Text type="secondary">설정</Typography.Text><br />
              <Typography.Text>학습 {folds.config.train_days}일 · 검증 {folds.config.test_days}일 · 이동 {folds.config.step_days}일 · {folds.config.mode === 'rolling' ? '롤링' : '누적'}</Typography.Text>
            </Card>
          </Col>
        )}
      </Row>
      {folds ? (
        <>
          <Card size="small" title="폴드별 학습 vs 검증 (목표 지표)" data-testid="folds-chart"><EChart option={foldsOption(folds.folds, objLabel(w.objective))} height={260} /></Card>
          <Card size="small" title="폴드 표" data-testid="folds-table">
            <Table size="small" rowKey="fold" pagination={false} scroll={{ x: 'max-content' }} dataSource={folds.folds}
              columns={[
                { title: '폴드', dataIndex: 'fold', render: (f: number) => f + 1 },
                { title: '학습 구간', dataIndex: 'train', render: (t: [string, string]) => `${fmtDate(t[0])} ~ ${fmtDate(t[1])}` },
                { title: '검증 구간', dataIndex: 'test', render: (t: [string, string]) => `${fmtDate(t[0])} ~ ${fmtDate(t[1])}` },
                { title: '고른 변수', dataIndex: 'params', render: (p?: Record<string, number>) => (p ? Object.entries(p).map(([k, v]) => `${k}=${v}`).join(', ') : DASH) },
                { title: '학습 목표값', dataIndex: 'is_objective', render: (v?: number | null) => (v === null || v === undefined ? DASH : v.toFixed(2)) },
                { title: '검증 목표값', dataIndex: 'oos_objective', render: (v?: number | null) => (v === null || v === undefined ? DASH : <b>{v.toFixed(2)}</b>) },
                { title: '검증 수익률', dataIndex: 'oos', render: (m?: FullMetrics) => <V k="total_return_pct" v={mv(m, 'total_return_pct')} /> },
                { title: '검증 낙폭', dataIndex: 'oos', key: 'mdd', render: (m?: FullMetrics) => <V k="max_drawdown_pct" v={mv(m, 'max_drawdown_pct')} /> },
                { title: '검증 거래', dataIndex: 'oos', key: 'n', render: (m?: FullMetrics) => <V k="num_trades" v={mv(m, 'num_trades')} /> },
                { title: '비고', dataIndex: 'skipped', render: (s?: string) => (s ? <Tag color="warning">{s}</Tag> : null) },
              ]} />
          </Card>
        </>
      ) : <Typography.Text type="secondary">폴드 자료를 불러오는 중…</Typography.Text>}
      <Card size="small" title="폴드마다 고른 변수 값이 얼마나 바뀌었나" data-testid="params-drift">
        <Table size="small" rowKey="name" pagination={false} dataSource={drift.map(([name, x]) => ({ name, ...x }))}
          columns={[
            { title: '변수', dataIndex: 'name' },
            { title: '폴드별 값', dataIndex: 'values', render: (v: number[]) => v.join(' → ') },
            { title: '서로 다른 값', dataIndex: 'n_distinct' },
            { title: '범위', render: (_, r) => `${r.min} ~ ${r.max}` },
          ]} />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>폴드마다 고른 값이 크게 흔들리면 시기마다 최적점이 다르다는 뜻 — 어느 한 값을 믿기 어렵다.</Typography.Text>
      </Card>
    </Space>
  )
}

/** 홀드아웃 결과 — 몇 번째 열람인지 · 이전 열람 · 학습/검증과 나란히 */
export function HoldoutSection({ d }: { d: RunDetail }) {
  const h = d.summary.holdout as HoldoutSummary
  const src = useRunDetail(h.source_run_id ?? undefined)
  const so = src.data?.summary.optimize as OptimizeSummary | undefined
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="holdout-section">
      <Alert type={h.nth_open >= 2 ? 'error' : 'info'} showIcon data-testid="holdout-nth"
        message={h.nth_open >= 2 ? `이 전략 골격의 ${h.nth_open}번째 홀드아웃 열람 — 신뢰가 깎였다` : '홀드아웃 첫 열람'}
        description={<div>
          <div>구간 {segText(h.period)} · 조합 {Object.entries(h.params).map(([k, v]) => `${k}=${v}`).join(', ')}{h.nth_open_structure !== undefined && h.nth_open_structure !== h.nth_open ? ` · 구조 해시 기준으로는 ${h.nth_open_structure}번째` : ''}</div>
          {h.note && <div>{h.note}</div>}
          {h.previous_opens.length > 0 && <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{h.previous_opens.map((o, i) => <li key={o.open_id ?? i}>{o.opened_at.replace('T', ' ')} 에 연 적 있음 · {Object.entries(o.params ?? {}).map(([k, v]) => `${k}=${v}`).join(', ')}</li>)}</ul>}
        </div>} />
      {so && (
        <Card size="small" title="학습 · 검증 · 홀드아웃 — 같은 조합, 세 구간" data-testid="three-way">
          <CompareTable testid="three-way-table" cols={[
            { title: '학습(IS)', sub: segText(so.segments.is), metrics: so.selected.is },
            { title: '검증(OOS)', sub: segText(so.segments.oos), metrics: so.selected.oos },
            { title: '홀드아웃', sub: segText(h.period), metrics: d.summary.metrics },
          ]} />
        </Card>
      )}
      {h.source_run_id && !so && !src.isPending && <Typography.Text type="secondary">출처 최적화 결과({h.source_run_id})를 찾을 수 없어 나란히 비교하지 못한다</Typography.Text>}
      <Alert type="warning" showIcon message="아래 지표 카드·곡선은 홀드아웃 구간만의 결과다" />
    </Space>
  )
}
