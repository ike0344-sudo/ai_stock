// 최적화 화면 (§5.4 OptimizePage): 기준 명세 → 변수 범위·조합 수 → 목표·분할·홀드아웃 자물쇠 → 워크포워드 → 사전 판정 기준 → 실행.
// 결과(조합 표·히트맵·이웃 안정성·폴드·홀드아웃 패널)는 결과 화면(#/results/:id)에 종류별로 펼친다.
// 정보는 접지 않는다: 조합 수가 500 을 넘으면 경고를, 5,000 을 넘으면 사유와 함께 실행을 막는다(서버도 같은 규칙 — GRID_TOO_LARGE).
import { PlayCircleOutlined, LockOutlined, UnlockOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Checkbox, Col, Input, InputNumber, Popconfirm, Radio, Row, Select, Space, Table, Tag, Typography } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, apiGet } from '@/api/client'
import { fetchGridInfo, getPreset, submitOptimize, submitWalkforward, usePresets, useRuns, validateSpec } from '@/api/studio'
import { RunModal } from '@/components/builder/RunModal'
import { ParamsTable } from '@/components/builder/SpecPanels'
import { fmtTs } from '@/lib/format'
import { KIND_LABEL } from '@/lib/labels'
import { METRIC_DEFS } from '@/lib/metrics'
import { clone, normalizeSpec, pruneParams } from '@/lib/spec'
import { OBJECTIVES, criteriaDirection, defaultForm, formFromSpec, rangeVariables, toConfig, toWalkforward, withValidation, type ValidationForm } from '@/lib/validation'
import type { RunDetail, SpecJson } from '@/types/studio'

const useDebounced = <T,>(value: T, ms: number): T => {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

type Job = { spec: SpecJson; kind: 'optimize' | 'walkforward' }

export function OptimizePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [spec, setSpec] = useState<SpecJson | null>(null)
  const [form, setForm] = useState<ValidationForm>(defaultForm)
  const [note, setNote] = useState<string | null>(null)
  const [holdoutLocked, setHoldoutLocked] = useState(true)
  const [job, setJob] = useState<Job | null>(null)
  const presets = usePresets()
  const backtests = useRuns({ kind: 'backtest' })
  const past = useRuns()

  const load = useCallback((s: SpecJson, why: string) => {
    const n = normalizeSpec(clone(s))
    setSpec(n); setForm(formFromSpec(n)); setHoldoutLocked(true); setNote(why)
  }, [])

  const from = params.get('from')
  const presetName = params.get('preset')
  useEffect(() => {
    let dead = false
    ;(async () => {
      try {
        if (from) {
          const d = await apiGet<RunDetail>(`/api/runs/${from}`)
          if (!dead) load(d.spec, `실행 ${from} 의 조건을 불러왔습니다`)
        } else if (presetName) {
          const r = await getPreset(presetName)
          if (!dead) load(r.spec, `프리셋 "${presetName}" 을 불러왔습니다`)
        }
      } catch (e) {
        if (!dead) setNote(`불러오기 실패: ${e instanceof ApiError ? e.message : String(e)}`)
      }
    })()
    return () => { dead = true }
  }, [from, presetName, load])

  const rangeVars = useMemo(() => (spec ? rangeVariables(spec.params) : []), [spec])
  // 훑을 변수: 체크를 다 켜 두면 서버 기본(범위가 다 있는 변수 전부)이라 vary 를 안 보낸다
  const chosen = form.vary ?? rangeVars
  const request = useMemo(() => (spec ? withValidation(pruneParams(spec), form) : null), [spec, form])
  const key = useDebounced(request ? JSON.stringify({ r: request, v: form.vary }) : '', 400)
  const settled = !request || key === JSON.stringify({ r: request, v: form.vary })
  const info = useQuery({
    queryKey: ['grid-info', key], enabled: !!request && !!key, retry: false, staleTime: 30_000,
    queryFn: () => { const { r, v } = JSON.parse(key) as { r: SpecJson; v: string[] | null }; return fetchGridInfo(r, v ?? undefined) },
  })
  const valid = useQuery({
    queryKey: ['opt-validate', key], enabled: !!request && !!key, retry: false, staleTime: 30_000,
    queryFn: () => validateSpec((JSON.parse(key) as { r: SpecJson }).r),
  })

  if (!spec || !request) {
    return (
      <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="optimize-page">
        <Typography.Title level={4} style={{ margin: 0 }}>최적화</Typography.Title>
        <Alert type="info" showIcon message="먼저 어떤 전략을 최적화할지 고르세요" description="프리셋이나 이미 돌린 백테스트 결과의 조건을 가져옵니다. 최적화할 변수는 조건의 숫자를 백테스트 화면에서 '변수로' 바꿔 둔 것입니다." />
        {note && <Typography.Text type="warning" data-testid="load-note">{note}</Typography.Text>}
        <SourcePicker presets={presets.data?.map((p) => p.name) ?? []} runs={backtests.data ?? []} onPreset={async (n) => { try { load((await getPreset(n)).spec, `프리셋 "${n}" 을 불러왔습니다`) } catch (e) { setNote(String(e)) } }}
          onRun={(id) => navigate(`/optimize?from=${id}`)} />
        <PastRuns rows={past.data ?? []} />
      </Space>
    )
  }

  const set = (patch: Partial<ValidationForm>) => setForm((f) => ({ ...f, ...patch }))
  const gi = info.data
  const noVars = rangeVars.length === 0
  const blockReason = noVars ? '훑을 변수가 없다 — 변수 표에서 최소·최대·간격을 채워라'
    : chosen.length === 0 ? '훑을 변수를 하나 이상 골라라'
    : info.isError ? `조합 수를 확인하지 못함: ${info.error.message}`
    : gi?.too_large ? `조합이 ${gi.n.toLocaleString('ko-KR')}개 — ${gi.limit.toLocaleString('ko-KR')}개를 넘어 실행할 수 없다(간격을 늘리거나 변수를 줄여라)`
    : gi && gi.n < 2 ? '조합이 1개뿐이다 — 훑을 범위를 넓혀라'
    : valid.data && !valid.data.ok ? '조건에 오류가 있다(백테스트 화면에서 확인)'
    : !gi || !settled || info.isFetching ? '조합 수를 세는 중…' : null
  const cfgKey = `${form.trainPct}`

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="optimize-page">
      <Space wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>최적화</Typography.Title>
        <Typography.Text strong data-testid="opt-spec-name">{spec.name}</Typography.Text>
        {note && <Typography.Text type="secondary" data-testid="load-note">{note}</Typography.Text>}
      </Space>
      <SourcePicker presets={presets.data?.map((p) => p.name) ?? []} runs={backtests.data ?? []} onPreset={async (n) => { try { load((await getPreset(n)).spec, `프리셋 "${n}" 을 불러왔습니다`) } catch (e) { setNote(String(e)) } }}
        onRun={(id) => navigate(`/optimize?from=${id}`)} />

      <Row gutter={16}>
        <Col xs={24} xl={13}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {Object.keys(spec.params).length === 0 ? (
              <Alert type="warning" showIcon data-testid="no-params" message="이 명세엔 변수가 없다" description={<span>조건의 숫자를 <Link to="/backtest">백테스트 화면</Link>에서 &quot;변수로&quot; 바꾼 뒤 다시 오세요. 변수마다 최소·최대·간격을 채우면 그 범위를 훑습니다.</span>} />
            ) : (
              <ParamsTable value={spec.params} onChange={(p) => setSpec((s) => (s ? { ...s, params: p } : s))} />
            )}
            <Card size="small" title="훑을 변수와 조합 수" data-testid="grid-card">
              <Space direction="vertical" size="small" style={{ width: '100%' }}>
                <Checkbox.Group data-testid="vary-group" value={chosen} options={rangeVars.map((v) => ({ value: v, label: `${v}${gi?.axes[v] ? ` (${gi.axes[v]}칸)` : ''}` }))}
                  onChange={(v) => set({ vary: v.length === rangeVars.length ? null : (v as string[]) })} />
                {rangeVars.length < Object.keys(spec.params).length && <Typography.Text type="secondary" style={{ fontSize: 12 }}>최소·최대·간격이 다 있는 변수만 훑는다 — 나머지는 기본값으로 고정</Typography.Text>}
                <Space>
                  <Typography.Text>조합</Typography.Text>
                  <Typography.Text strong style={{ fontSize: 22 }} data-testid="combo-count">{gi ? gi.n.toLocaleString('ko-KR') : '…'}</Typography.Text>
                  <Typography.Text>개</Typography.Text>
                  {gi && !gi.too_large && !gi.warn && gi.n >= 2 && <Tag color="success">괜찮음</Tag>}
                  {gi?.warn && !gi.too_large && <Tag color="warning" data-testid="combo-warn">{gi.warn_over}개 넘음 — 오래 걸림</Tag>}
                  {gi?.too_large && <Tag color="error" data-testid="combo-toolarge">{gi.limit.toLocaleString('ko-KR')}개 넘음 — 실행 불가</Tag>}
                </Space>
                {gi?.warn && !gi.too_large && <Alert type="warning" showIcon message={`조합이 ${gi.warn_over}개를 넘는다 — 실행은 되지만 오래 걸리고, 조합이 많을수록 우연히 좋아 보이는 조합이 나올 확률이 커진다(과최적화)`} />}
                {blockReason && <Typography.Text type="danger" data-testid="block-reason">{blockReason}</Typography.Text>}
              </Space>
            </Card>
          </Space>
        </Col>

        <Col xs={24} xl={11}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Card size="small" title="목표와 구간 나누기" data-testid="settings-card">
              <Space direction="vertical" size="small" style={{ width: '100%' }}>
                <Space wrap>
                  <span>목표 지표</span>
                  <Select style={{ width: 200 }} value={form.objective} onChange={(v) => set({ objective: v })} data-testid="objective"
                    options={OBJECTIVES.map((o) => ({ value: o.key, label: `${o.label} — ${o.help}` }))} />
                </Space>
                <Space wrap>
                  <span>최소 거래 수</span>
                  <InputNumber min={1} value={form.minTrades} onChange={(v) => v && set({ minTrades: Math.round(v) })} data-testid="min-trades" />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>이보다 거래가 적은 조합은 후보에서 뺀다(우연)</Typography.Text>
                </Space>
                <Space wrap>
                  <span>학습 비율</span>
                  <Radio.Group value={form.splitDate ? 'date' : 'pct'} onChange={(e) => set({ splitDate: e.target.value === 'date' ? (spec.period.start.slice(0, 4) + '-12-31') : null })} options={[{ value: 'pct', label: '거래일 비율' }, { value: 'date', label: '날짜로' }]} />
                  {form.splitDate ? <Input type="date" style={{ width: 150 }} value={form.splitDate} onChange={(e) => set({ splitDate: e.target.value || null })} data-testid="split-date" />
                    : <InputNumber min={1} max={99} addonAfter="%" value={form.trainPct} onChange={(v) => v && set({ trainPct: v })} data-testid="train-pct" />}
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>홀드아웃을 뺀 앞부분 중 학습 몫, 나머지는 검증(OOS)</Typography.Text>
                </Space>
                <Space wrap>
                  <span>홀드아웃</span>
                  <InputNumber min={0} max={50} addonAfter="%" disabled={holdoutLocked} value={form.holdoutPct} onChange={(v) => v !== null && set({ holdoutPct: v })} data-testid="holdout-pct" />
                  {holdoutLocked ? (
                    <Popconfirm title="홀드아웃 비율을 바꿀까요?" description="마지막 몇 %를 시험지로 떼어 두는 값입니다. 결과를 본 뒤에 바꾸면 시험지가 아니게 됩니다." okText="풀기" cancelText="그대로" onConfirm={() => setHoldoutLocked(false)}>
                      <Button icon={<LockOutlined />} data-testid="holdout-lock">잠김 — 풀기</Button>
                    </Popconfirm>
                  ) : <Button icon={<UnlockOutlined />} onClick={() => { setHoldoutLocked(true); set({ holdoutPct: 20 }) }} data-testid="holdout-relock">기본 20% 로 되돌리고 잠그기</Button>}
                </Space>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>마지막 {form.holdoutPct}% 거래일은 최적화·선택·검증 어디에도 쓰지 않고, 결과 화면의 홀드아웃 버튼으로만 연다.</Typography.Text>
              </Space>
            </Card>

            <Card size="small" title="사전 판정 기준 (실행 전에 정한다 — 실행 뒤엔 못 고칩니다)" data-testid="criteria-card">
              <Space direction="vertical" size="small" style={{ width: '100%' }}>
                {form.criteria.map((c, i) => (
                  <Space key={i} wrap data-testid={`criteria-row-${i}`}>
                    <Select style={{ width: 200 }} showSearch optionFilterProp="label" value={c.metric || undefined} placeholder="지표" onChange={(m) => set({ criteria: form.criteria.map((x, j) => (j === i ? { ...x, metric: m } : x)) })}
                      options={METRIC_DEFS.map((m) => ({ value: m.key, label: m.label }))} />
                    <Tag>{c.metric ? (criteriaDirection(c.metric) === 'max' ? '이하여야 통과' : '이상이어야 통과') : '—'}</Tag>
                    <InputNumber value={c.value} onChange={(v) => set({ criteria: form.criteria.map((x, j) => (j === i ? { ...x, value: v } : x)) })} />
                    <Button size="small" onClick={() => set({ criteria: form.criteria.filter((_, j) => j !== i) })}>삭제</Button>
                  </Space>
                ))}
                <Button size="small" onClick={() => set({ criteria: [...form.criteria, { metric: 'sharpe', value: 0.5 }] })} data-testid="criteria-add">기준 추가</Button>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>검증(OOS) 구간 성과로 통과·미달을 판정한다. 결과를 본 뒤 기준을 바꾸면 자기 합리화가 되므로 결과 화면에선 못 고친다.</Typography.Text>
              </Space>
            </Card>

            <Card size="small" title="워크포워드 (구간을 밀어 가며 반복 검증)" data-testid="wf-card">
              <Space wrap>
                <span>학습</span><InputNumber min={1} addonAfter="거래일" value={form.wf.train} onChange={(v) => v && set({ wf: { ...form.wf, train: Math.round(v) } })} data-testid="wf-train" />
                <span>검증</span><InputNumber min={1} addonAfter="거래일" value={form.wf.test} onChange={(v) => v && set({ wf: { ...form.wf, test: Math.round(v) } })} data-testid="wf-test" />
                <span>이동</span><InputNumber min={form.wf.test} placeholder={`${form.wf.test}(검증과 같게)`} addonAfter="거래일" value={form.wf.step} onChange={(v) => set({ wf: { ...form.wf, step: v ? Math.round(v) : null } })} data-testid="wf-step" />
                <Radio.Group value={form.wf.mode} onChange={(e) => set({ wf: { ...form.wf, mode: e.target.value } })} options={[{ value: 'rolling', label: '롤링(학습 창 이동)' }, { value: 'anchored', label: '누적(시작 고정)' }]} data-testid="wf-mode" />
              </Space>
            </Card>

            <Space wrap>
              <Button type="primary" size="large" icon={<PlayCircleOutlined />} disabled={!!blockReason} onClick={() => setJob({ spec: request, kind: 'optimize' })} data-testid="run-optimize">최적화 실행</Button>
              <Button size="large" icon={<PlayCircleOutlined />} disabled={!!blockReason} onClick={() => setJob({ spec: request, kind: 'walkforward' })} data-testid="run-walkforward">워크포워드 실행</Button>
              {blockReason && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{blockReason}</Typography.Text>}
            </Space>
          </Space>
        </Col>
      </Row>

      <PastRuns rows={past.data ?? []} />
      <RunModal spec={job?.spec ?? null} title={job?.kind === 'walkforward' ? '워크포워드 실행' : '최적화 실행'} onClose={() => setJob(null)}
        request={(s) => (job?.kind === 'walkforward' ? submitWalkforward(s, toConfig(form), toWalkforward(form)) : submitOptimize(s, toConfig(form)))} />
      <span hidden data-testid="cfg-key">{cfgKey}</span>
    </Space>
  )
}

function SourcePicker({ presets, runs, onPreset, onRun }: { presets: string[]; runs: { run_id: string; name: string | null }[]; onPreset: (n: string) => void; onRun: (id: string) => void }) {
  return (
    <Space wrap data-testid="source-picker">
      <span>기준 명세</span>
      <Select style={{ width: 240 }} placeholder="프리셋 고르기" options={presets.map((p) => ({ value: p, label: p }))} onChange={onPreset} data-testid="pick-preset" />
      <Select style={{ width: 320 }} showSearch optionFilterProp="label" placeholder="돌려 본 백테스트에서 가져오기" data-testid="pick-run"
        options={runs.map((r) => ({ value: r.run_id, label: `${r.name ?? '(이름 없음)'} · ${r.run_id}` }))} onChange={onRun} />
    </Space>
  )
}

/** 지금까지 돌린 검증(최적화·워크포워드·홀드아웃) — 결과 화면으로 */
function PastRuns({ rows }: { rows: { run_id: string; name: string | null; kind: string; created_at: string | null }[] }) {
  const v = rows.filter((r) => r.kind !== 'backtest')
  return (
    <Card size="small" title="지금까지 돌린 검증" data-testid="past-runs">
      <Table size="small" rowKey="run_id" dataSource={v} pagination={{ pageSize: 8, hideOnSinglePage: true }} locale={{ emptyText: '아직 없음' }}
        columns={[
          { title: '종류', dataIndex: 'kind', render: (k: string) => <Tag color="purple">{KIND_LABEL[k] ?? k}</Tag> },
          { title: '이름', dataIndex: 'name', render: (n: string | null, r) => <Link to={`/results/${r.run_id}`}>{n ?? r.run_id}</Link> },
          { title: '실행 시각', dataIndex: 'created_at', render: (t: string | null) => fmtTs(t) },
        ]} />
    </Card>
  )
}
