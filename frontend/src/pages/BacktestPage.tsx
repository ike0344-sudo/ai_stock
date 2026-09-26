// 백테스트 화면 (§5.4 BacktestPage): 모드 탭 · 전략 소스 · 종목 · 기간 · 조건 편집기 · 청산 · 자금 · 비용 · 호환 모드 ·
// 풀이 문장 · [검증] · [오늘 조건 맞는 종목] · [백테스트 실행](진행 모달 → 결과).
// 화면 상태는 명세(SpecJson) 하나 — 모든 편집은 함수형 갱신이라 "변수로" 같은 연쇄 갱신이 서로 덮어쓰지 않는다.
import { PlayCircleOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Col, Input, Row, Space, Spin, Switch, Tabs, Typography, theme } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getPreset, previewSpec, useDataRanges, useIndicators, useLegacyStrategies, validateSpec } from '@/api/studio'
import { ApiError, apiGet } from '@/api/client'
import { ConditionGroupEditor } from '@/components/builder/ConditionGroupEditor'
import { NarrationPanel, PreviewTable, ValidationPanel } from '@/components/builder/CheckPanels'
import { ParamsContext, type ParamsApi } from '@/components/builder/ParamsContext'
import { RunModal } from '@/components/builder/RunModal'
import { CompatPanel, CostsPanel, ExitsPanel, ParamsTable, PeriodPanel, PortfolioPanel, UniversePanel, rangeKeyOf } from '@/components/builder/SpecPanels'
import { IntradayPanel, TickPanel } from '@/components/builder/ModePanels'
import { LegacyForm, PresetBar, StrategySourceSwitch } from '@/components/builder/StrategyPanels'
import { clampPeriodToRange, clone, newGroup, newSpec, normalizeSpec, pruneParams, setTickEntrySource, switchMode, toParam } from '@/lib/spec'
import type { PreviewResult, RunDetail, SpecJson, StrategySpec } from '@/types/studio'

const MODE_TABS: { key: SpecJson['mode']; label: string; disabled?: boolean }[] = [
  { key: 'daily_single', label: '일봉 · 단일 종목' },
  { key: 'daily_portfolio', label: '일봉 · 포트폴리오' },
  { key: 'intraday', label: '분봉 단타' },
  { key: 'tick', label: '체결(틱)' },
]

// 넓은 화면(≥1400px)이면 조건 편집기는 왼쪽, 설정 칸은 오른쪽 단으로 나눈다(좁으면 종전 배치)
const WIDE_QUERY = '(min-width: 1400px)'
function useWide(): boolean {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE_QUERY).matches)
  useEffect(() => {
    const mq = window.matchMedia(WIDE_QUERY)
    const on = () => setWide(mq.matches)
    on()
    mq.addEventListener?.('change', on)
    return () => mq.removeEventListener?.('change', on)
  }, [])
  return wide
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export function BacktestPage() {
  const [params] = useSearchParams()
  const [spec, setSpec] = useState<SpecJson>(() => newSpec('daily_portfolio'))
  const specRef = useRef(spec)
  specRef.current = spec
  const pristine = useRef(true)
  const periodEdited = useRef(false) // 사용자가 기간을 직접 고르거나 명세를 불러왔으면 자동으로 옮기지 않는다
  const [runSpec, setRunSpec] = useState<SpecJson | null>(null)
  const [preview, setPreview] = useState<{ data?: PreviewResult; loading: boolean; error?: string }>({ loading: false })
  const [loadNote, setLoadNote] = useState<string | null>(null)
  const wide = useWide()
  const { token } = theme.useToken()

  const cat = useIndicators()
  const legacy = useLegacyStrategies()
  const ranges = useDataRanges()

  const edit = useCallback((fn: (s: SpecJson) => SpecJson) => { pristine.current = false; setSpec(fn) }, [])
  const patch = useCallback(<K extends keyof SpecJson>(k: K) => (v: SpecJson[K]) => edit((s) => ({ ...s, [k]: v })), [edit])

  // 기본 종료일 = 데이터 기준일 (아직 손대지 않았을 때만)
  const dailyEnd = ranges.data?.daily?.[1]
  useEffect(() => {
    if (dailyEnd && pristine.current) setSpec(newSpec('daily_portfolio', { end: dailyEnd }))
  }, [dailyEnd])

  // 불러오기: #/backtest?from=<runId>(복제해서 수정) · ?preset=<이름>
  const from = params.get('from')
  const presetName = params.get('preset')
  useEffect(() => {
    let dead = false
    ;(async () => {
      try {
        if (from) {
          const d = await apiGet<RunDetail>(`/api/runs/${from}`)
          if (dead) return
          pristine.current = false
          periodEdited.current = true
          setSpec({ ...normalizeSpec(clone(d.spec)), name: `${d.spec.name} (복사)` })
          setLoadNote(`실행 ${from} 의 조건을 복제했습니다 — 고쳐서 다시 돌리세요`)
        } else if (presetName) {
          const r = await getPreset(presetName)
          if (dead) return
          pristine.current = false
          periodEdited.current = true
          setSpec(normalizeSpec(r.spec))
          setLoadNote(`프리셋 "${presetName}" 을 불러왔습니다`)
        }
      } catch (e) {
        if (!dead) setLoadNote(`불러오기 실패: ${e instanceof ApiError ? e.message : String(e)}`)
      }
    })()
    return () => { dead = true }
  }, [from, presetName])

  // 검증 — 명세가 바뀌고 0.5초 조용하면 서버에 묻는다(오류 경로로 행을 강조하고 풀이 문장을 받는다)
  const pruned = useMemo(() => pruneParams(spec), [spec])
  const key = useDebounced(JSON.stringify(pruned), 500)
  const validation = useQuery({ queryKey: ['validate', key], queryFn: () => validateSpec(JSON.parse(key) as SpecJson), staleTime: 30_000, retry: false })
  const result = validation.data
  const settled = key === JSON.stringify(pruned)
  const canRun = !!result?.ok && settled && !validation.isFetching
  const fine = spec.mode === 'intraday' || spec.mode === 'tick' // 분봉·틱
  // 분봉·틱 탭을 데이터 범위가 오기 전에 켰거나 기간을 손대지 않았는데 끝이 데이터 밖이면 데이터 끝으로 당긴다
  const fineRange = ranges.data?.[rangeKeyOf(spec.mode, spec.intraday?.source ?? 'al')]
  useEffect(() => {
    if (!fine || !fineRange || periodEdited.current) return
    setSpec((s) => { const p = clampPeriodToRange(s.period, fineRange); return p === s.period ? s : { ...s, period: p } })
  }, [fine, fineRange])

  const doPreview = async () => {
    setPreview({ loading: true })
    try {
      setPreview({ loading: false, data: await previewSpec(pruned, 50) })
    } catch (e) {
      setPreview({ loading: false, error: e instanceof ApiError ? `${e.code} — ${e.message}` : String(e) })
    }
  }

  const paramsApi: ParamsApi = useMemo(() => ({
    params: spec.params,
    makeParam: (current, hint) => {
      const { spec: next, ref } = toParam(specRef.current, current, hint)
      setSpec(next); pristine.current = false
      specRef.current = next
      return ref
    },
    fixParam: (name) => specRef.current.params[name]?.default ?? 0,
  }), [spec.params])

  if (cat.isPending || legacy.isPending) return <Spin data-testid="builder-loading" />
  if (cat.isError) return <Alert type="error" showIcon message="조립기 재료를 못 불러옴" description={cat.error.message} data-testid="builder-error" />
  const catalog = cat.data
  const strategy = spec.strategy
  const single = spec.mode === 'daily_single'
  const compat = spec.compat.legacy
  const errors = result?.errors ?? []
  const setStrategy = (fn: (s: StrategySpec) => StrategySpec) => edit((s) => ({ ...s, strategy: s.strategy ? fn(s.strategy) : s.strategy }))

  const setCompat = (on: boolean) => edit((s) => on
    ? { ...s, compat: { legacy: true }, exits: { stop_loss_pct: null, take_profit_pct: null, trailing_stop_pct: null, max_holding_bars: null },
        portfolio: { ...s.portfolio, max_positions: 1, max_weight_pct: 100, sizing: 'equal_slot_fixed' }, fills: { ...s.fills, volume_cap_pct: null } }
    : { ...s, compat: { legacy: false } })

  const presetBar = <PresetBar spec={pruned} onLoad={(s, name) => { periodEdited.current = true; edit(() => normalizeSpec(s)); setLoadNote(`프리셋 "${name}" 을 불러왔습니다`) }} />
  const universe = <UniversePanel value={spec.universe} onChange={patch('universe')} mode={spec.mode} />
  const period = <PeriodPanel value={spec.period} onChange={(p) => { periodEdited.current = true; patch('period')(p) }} ranges={ranges.data} holdoutPct={fine ? undefined : spec.validation?.holdout_pct} rangeKey={rangeKeyOf(spec.mode, spec.intraday?.source ?? 'al')} />
  const strategyBlock = (
    <div>
      <Space style={{ marginBottom: 8 }}>
        <Typography.Text strong>전략</Typography.Text>
        {!(spec.mode === 'tick' && spec.tick?.entry_source === 'catalog') && <StrategySourceSwitch strategy={strategy} legacy={legacy.data ?? []} noLegacy={fine} onChange={(s) => edit((x) => ({ ...x, strategy: s }))} />}
      </Space>
      {spec.mode === 'tick' && spec.tick?.entry_source === 'catalog' ? (
        <Alert type="info" showIcon data-testid="tick-no-strategy" message="틱 조건 진입은 전략 조건식이 없습니다" description="아래 틱 설정의 조건(고점 돌파·체결대금 속도·매수 비중)으로 진입하고, 청산은 손절·익절·트레일링·시간 손절·장마감으로 합니다. 조건식 청산이 필요하면 진입 방식을 '분봉 신호 + 틱 정밀화' 로 바꾸세요." />
      ) : strategy?.source === 'legacy' ? (
        <LegacyForm strategy={strategy} defs={legacy.data ?? []} onChange={(s) => setStrategy(() => s)} />
      ) : strategy?.source === 'builder' ? (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <ConditionGroupEditor title="진입 조건 (이 조건이 참이면 다음 봉 시가에 산다)" path="strategy.entry" group={strategy.entry} required cat={catalog} mode={spec.mode} errors={errors}
            onChange={(g) => setStrategy((s) => (s.source === 'builder' ? { ...s, entry: g } : s))} />
          <ConditionGroupEditor title="청산 조건 (이 조건이 참이면 다음 봉 시가에 판다)" path="strategy.exit" group={strategy.exit} cat={catalog} mode={spec.mode} errors={errors}
            onChange={(g) => setStrategy((s) => (s.source === 'builder' ? { ...s, exit: g } : s))} />
        </Space>
      ) : null}
    </div>
  )
  const marketBlock = (
    <div>
      <Space style={{ marginBottom: 8 }}>
        <Typography.Text strong>시장 필터</Typography.Text>
        <Switch checked={spec.market_filter !== null} onChange={(on) => edit((s) => ({ ...s, market_filter: on ? { logic: 'all', items: [{ left: { kind: 'market', index: 'kospi', name: 'close' }, op: 'gt', right: { kind: 'market', index: 'kospi', name: 'sma', params: { n: 20 } } }] } : null }))} data-testid="market-filter-switch" />
        <Typography.Text type="secondary">지수 조건을 진입에만 겹쳐 씁니다(예: 코스피가 20일선 위일 때만)</Typography.Text>
      </Space>
      {spec.market_filter && (
        <ConditionGroupEditor title="시장 조건" path="market_filter" group={spec.market_filter} cat={catalog} mode={spec.mode} errors={errors} allowMarket
          onChange={(g) => patch('market_filter')(g.items.length ? g : newGroup())} />
      )}
    </div>
  )
  const settings = [
    <ExitsPanel key="exits" value={spec.exits} onChange={patch('exits')} disabled={compat} mode={spec.mode} />,
    <PortfolioPanel key="pf" value={spec.portfolio} onChange={patch('portfolio')} disabled={compat} single={single} mode={spec.mode} />,
    <CostsPanel key="costs" costs={spec.costs} fills={spec.fills} onCosts={patch('costs')} onFills={patch('fills')} compat={compat} disabled={compat} mode={spec.mode} />,
    single ? <CompatPanel key="compat" on={compat} onChange={setCompat} /> : null,
  ]
  const paramsTable = <ParamsTable value={spec.params} onChange={patch('params')} />
  const showIntraday = (spec.mode === 'intraday' || (spec.mode === 'tick' && spec.tick?.entry_source === 'minute_refine')) && !!spec.intraday
  const modeBlock = fine ? (
    <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="mode-block">
      {spec.mode === 'tick' && spec.tick && <TickPanel value={spec.tick} spec={spec} onChange={(t) => edit((s) => (t.entry_source !== s.tick?.entry_source ? setTickEntrySource({ ...s, tick: t }, t.entry_source) : { ...s, tick: t }))} />}
      {showIntraday && spec.intraday && <IntradayPanel value={spec.intraday} spec={spec} mode={spec.mode} cat={catalog} errors={errors} onChange={(i) => edit((s) => ({ ...s, intraday: i }))} />}
    </Space>
  ) : null
  const actions = (
    <Space wrap>
      <Button icon={<SearchOutlined />} onClick={doPreview} loading={preview.loading} disabled={!result?.ok || fine} title={fine ? '오늘 조건 맞는 종목은 일봉 모드에서만 볼 수 있다' : undefined} data-testid="preview-btn">오늘 조건 맞는 종목</Button>
      <Button type="primary" size="large" icon={<PlayCircleOutlined />} disabled={!canRun} onClick={() => setRunSpec(clone(pruned))} data-testid="run-btn">백테스트 실행</Button>
    </Space>
  )
  const checks = (
    <>
      <NarrationPanel result={result} loading={validation.isFetching || !settled} />
      <ValidationPanel result={result} error={validation.isError ? validation.error.message : undefined} />
      {(preview.data || preview.loading || preview.error) && <PreviewTable {...preview} />}
    </>
  )
  const stack = (nodes: React.ReactNode) => <Space direction="vertical" size="middle" style={{ width: '100%' }}>{nodes}</Space>

  const body = wide ? (
    // 넓은 화면: 왼쪽 = 조건 편집기(넓게) · 오른쪽 = 풀이·검증 + 유니버스·기간·청산·자금·비용·변수. 실행 버튼 줄은 오른쪽 위에 붙어 따라온다.
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)', gap: 16, alignItems: 'start' }} data-testid="layout-wide">
      {stack(<>{presetBar}{modeBlock}{strategyBlock}{marketBlock}{paramsTable}</>)}
      <div>
        <div style={{ position: 'sticky', top: 0, zIndex: 5, padding: '8px 0', background: token.colorBgLayout }} data-testid="action-bar">{actions}</div>
        {stack(<>{checks}{universe}{period}{settings}</>)}
      </div>
    </div>
  ) : (
    <Row gutter={16}>
      <Col xs={24} xl={15}>{stack(<>{presetBar}{universe}{period}{modeBlock}{strategyBlock}{marketBlock}{settings}{paramsTable}</>)}</Col>
      <Col xs={24} xl={9}>
        <div style={{ position: 'sticky', top: 8 }}>
          {stack(<><NarrationPanel result={result} loading={validation.isFetching || !settled} /><ValidationPanel result={result} error={validation.isError ? validation.error.message : undefined} />{actions}{(preview.data || preview.loading || preview.error) && <PreviewTable {...preview} />}</>)}
        </div>
      </Col>
    </Row>
  )

  return (
    <ParamsContext.Provider value={paramsApi}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="backtest-page">
        <Space wrap>
          <Typography.Text strong>이름</Typography.Text>
          <Input style={{ width: 360 }} value={spec.name} maxLength={100} onChange={(e) => patch('name')(e.target.value)} data-testid="spec-name" />
          {loadNote && <Typography.Text type="secondary" data-testid="load-note">{loadNote}</Typography.Text>}
        </Space>
        <Tabs type="card" activeKey={spec.mode} data-testid="mode-tabs"
          items={MODE_TABS.map((t) => ({ key: t.key, label: t.label, disabled: t.disabled }))}
          onChange={(k) => { periodEdited.current = false; edit((s) => switchMode(s, k as SpecJson['mode'], ranges.data?.[rangeKeyOf(k as SpecJson['mode'], s.intraday?.source ?? 'al')])) }} />
        {body}
        <RunModal spec={runSpec} onClose={() => setRunSpec(null)} />
      </Space>
    </ParamsContext.Provider>
  )
}
