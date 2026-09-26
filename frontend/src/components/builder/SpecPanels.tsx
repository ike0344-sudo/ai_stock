// 명세 편집 패널들 (§5.4 BacktestPage): 유니버스 · 기간 · 청산 규칙 · 자금·배분 · 비용·체결 · 호환 모드 · 변수 표
// 각 패널은 SpecJson 의 한 부분만 받아 새 부분을 돌려준다(부모가 합친다) — 화면 상태는 명세 하나.
import { Alert, Button, Card, Checkbox, DatePicker, InputNumber, Radio, Select, Space, Switch, Table, Typography } from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useStockSearch } from '@/api/studio'
import { CodesSelect } from '@/components/hub/collect/CodesSelect'
import { fmtDate } from '@/lib/format'
import type { DataRanges, ParamRange, SpecJson, TakeProfitLevel } from '@/types/studio'
import { NumField } from './NumField'

type Part<K extends keyof SpecJson> = { value: SpecJson[K]; onChange: (v: SpecJson[K]) => void; disabled?: boolean }
const Row = ({ label, children, hint }: { label: string; children: React.ReactNode; hint?: React.ReactNode }) => (
  <div style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '4px 0', flexWrap: 'wrap' }}>
    <span style={{ width: 132, flexShrink: 0 }}>{label}</span>
    {children}
    {hint && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{hint}</Typography.Text>}
  </div>
)

// ───────────── 종목·유니버스 ─────────────
export function UniversePanel({ value: u, onChange, mode }: Part<'universe'> & { mode: SpecJson['mode'] }) {
  const single = mode === 'daily_single'
  const [q, setQ] = useState('')
  const hits = useStockSearch(q)
  return (
    <Card size="small" title={single ? '종목' : '종목 범위(유니버스)'} data-testid="panel-universe">
      {single ? (
        <Row label="종목 1개" hint="이름이나 코드로 검색">
          <Select showSearch style={{ width: 300 }} placeholder="종목명·코드 검색" filterOption={false} onSearch={setQ} data-testid="single-stock"
            value={u.codes[0]} loading={hits.isFetching}
            options={[
              ...(u.codes[0] && !hits.data?.some((h) => h.code === u.codes[0]) ? [{ value: u.codes[0], label: u.codes[0] }] : []),
              ...(hits.data ?? []).map((h) => ({ value: h.code, label: `${h.code} ${h.name ?? ''}` })),
            ]}
            onChange={(code) => onChange({ ...u, type: 'codes', codes: [code] })} />
        </Row>
      ) : (
        <>
          <Row label="대상">
            <Radio.Group value={u.type} onChange={(e) => onChange({ ...u, type: e.target.value })} data-testid="universe-type">
              <Radio.Button value="all">전체</Radio.Button>
              <Radio.Button value="top_value">거래대금 상위 N</Radio.Button>
              <Radio.Button value="codes">종목 지정</Radio.Button>
            </Radio.Group>
          </Row>
          {u.type === 'top_value' && (
            <Row label="상위 N · 평균 일수" hint={mode === 'intraday' ? '분봉 모드에서는 무시된다 — 아래 분봉 설정의 "전일 거래대금 상위 N" 이 유효 N' : '신호 봉 종가 기준 순위(전 봉 기준 아님 — 미래 참조 없음)'}>
              <InputNumber size="small" min={1} max={3000} value={u.n} disabled={mode === 'intraday'} onChange={(v) => onChange({ ...u, n: Number(v ?? 100) })} data-testid="universe-n" />
              <InputNumber size="small" min={1} max={60} value={u.lookback_days} addonAfter="일" onChange={(v) => onChange({ ...u, lookback_days: Number(v ?? 1) })} />
            </Row>
          )}
          {u.type === 'codes' && <Row label="종목 목록"><div style={{ minWidth: 320 }}><CodesSelect value={u.codes} onChange={(codes) => onChange({ ...u, codes })} /></div></Row>}
          <Row label="시장">
            <Checkbox.Group value={u.markets} options={['거래소', '코스닥']} onChange={(m) => onChange({ ...u, markets: (m.length ? m : u.markets) as typeof u.markets })} />
          </Row>
          <Row label="제외" hint="스팩 · 우선주 · 초대형주(삼성전자 등)">
            <Checkbox.Group value={u.exclude} onChange={(x) => onChange({ ...u, exclude: x as typeof u.exclude })}
              options={[{ value: 'spac', label: '스팩' }, { value: 'preferred', label: '우선주' }, { value: 'mega_cap', label: '초대형주' }]} />
          </Row>
        </>
      )}
    </Card>
  )
}

// ───────────── 기간 ─────────────
/** 모드별 기간 기준 데이터: 일봉 / 분봉(출처별) / 체결 */
export const rangeKeyOf = (mode: SpecJson['mode'], source: 'al' | 'krx' = 'al') => (mode === 'intraday' ? `minute_${source}` : mode === 'tick' ? 'tick_al' : 'daily')
const RANGE_LABEL = (key: string) => (key === 'daily' ? '일봉' : key === 'tick_al' ? '통합 체결' : key === 'minute_krx' ? 'KRX 분봉' : '통합 분봉')

export function PeriodPanel({ value: p, onChange, ranges, holdoutPct, rangeKey = 'daily', rangesStatus = 'ok', onRetryRanges }: Part<'period'> & { ranges?: DataRanges; holdoutPct?: number; rangeKey?: string; rangesStatus?: 'loading' | 'error' | 'ok'; onRetryRanges?: () => void }) {
  const r = ranges?.[rangeKey]
  const outside = (d: dayjs.Dayjs) => !!r && (d.isBefore(dayjs(r[0]), 'day') || d.isAfter(dayjs(r[1]), 'day'))
  return (
    <Card size="small" title="기간" data-testid="panel-period">
      <Row label="시작 ~ 종료" hint={r ? `${RANGE_LABEL(rangeKey)} 데이터 ${fmtDate(r[0])} ~ ${fmtDate(r[1])}${rangeKey === 'daily' ? ' (허브 기준일)' : ' — 종목마다 더 짧을 수 있다'}` : rangesStatus === 'loading' ? <span data-testid="ranges-loading">데이터 범위 불러오는 중…</span>
          : <span data-testid="ranges-error">데이터 범위를 못 불러옴 {onRetryRanges && <a onClick={onRetryRanges} data-testid="ranges-retry">다시 시도</a>}</span>}>
        <DatePicker.RangePicker value={[dayjs(p.start), dayjs(p.end)]} disabledDate={outside} allowClear={false} data-testid="period-range"
          onChange={(v) => v && v[0] && v[1] && onChange({ start: v[0].format('YYYY-MM-DD'), end: v[1].format('YYYY-MM-DD') })} />
      </Row>
      {!!holdoutPct && holdoutPct > 0 && (
        <div data-testid="holdout-bar" style={{ display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden', marginTop: 6 }}>
          <div style={{ flex: 100 - holdoutPct, background: '#1677ff' }} />
          <div style={{ flex: holdoutPct, background: '#bfbfbf' }} title="홀드아웃 — 최적화 단계에서 한 번만 여는 구간" />
        </div>
      )}
      {!!holdoutPct && holdoutPct > 0 && <Typography.Text type="secondary" style={{ fontSize: 12 }}>회색 = 마지막 {holdoutPct}% 홀드아웃(최적화 화면에서만 엽니다)</Typography.Text>}
    </Card>
  )
}

// ───────────── 청산 규칙 ─────────────
type BasicExit = 'stop_loss_pct' | 'take_profit_pct' | 'trailing_stop_pct' | 'max_holding_bars'
const EXIT_FIELDS: { key: BasicExit; label: string; hint: string; max: number; suffix?: string }[] = [
  { key: 'stop_loss_pct', label: '손절', hint: '진입가 대비 이만큼 떨어지면 판다', max: 100, suffix: '%' },
  { key: 'take_profit_pct', label: '익절', hint: '진입가 대비 이만큼 오르면 판다', max: 1000, suffix: '%' },
  { key: 'trailing_stop_pct', label: '트레일링', hint: '고점에서 이만큼 밀리면 판다', max: 100, suffix: '%' },
  { key: 'max_holding_bars', label: '최대 보유 봉', hint: '이 봉 수를 넘기면 판다', max: 5000 },
]

/** 서버가 알리는 고급 청산 칸(capabilities.exit_fields)만 그린다 — 서버가 모르는 칸을 보내면 검증 오류이기 때문 */
export const ADVANCED_EXITS = ['take_profit_levels', 'take_profit_mode', 'trail_activate_pct', 'breakeven_after_pct', 'max_holding_minutes'] as const

export function ExitsPanel({ value: ex, onChange, disabled, mode, extra: serverExtra = [] }: Part<'exits'> & { mode?: SpecJson['mode']; extra?: string[] }) {
  // 틱 모드는 새 청산 칸을 전부 거부하고(서버), 시간 청산(분)은 분봉 모드에서만 된다 — 서버가 거절할 칸은 화면이 처음부터 안 보인다
  const extra = mode === 'tick' ? [] : serverExtra.filter((k) => k !== 'max_holding_minutes' || mode === 'intraday')
  const has = (k: string) => extra.includes(k)
  const levels = ex.take_profit_levels ?? []
  // 분할 익절과 단일 익절은 같이 쓸 수 없다(서버 규칙) — 한쪽을 켜면 다른 쪽을 끈다
  const setLevels = (l: TakeProfitLevel[]) => onChange({ ...ex, take_profit_levels: l.length ? l : null, ...(l.length ? { take_profit_pct: null } : {}) })
  const numRow = (key: 'trail_activate_pct' | 'breakeven_after_pct' | 'max_holding_minutes', label: string, hint: string, def: number, suffix: string) => (
    <Row key={key} label={label} hint={hint}>
      <Switch size="small" checked={ex[key] != null} disabled={disabled} data-testid={`exit-${key}-on`} onChange={(x) => onChange({ ...ex, [key]: x ? def : null })} />
      {ex[key] != null && <NumField hint={key.replace('_pct', '')} value={ex[key]} min={0} max={key === 'max_holding_minutes' ? 600 : 1000} step={key === 'max_holding_minutes' ? 1 : 0.5}
        disabled={disabled} suffix={suffix} onChange={(x) => onChange({ ...ex, [key]: x })} data-testid={`exit-${key}`} />}
    </Row>
  )
  return (
    <Card size="small" title="청산 규칙 (조건식 청산과 함께 적용)" data-testid="panel-exits">
      {disabled && <Alert type="info" showIcon style={{ marginBottom: 8 }} message="호환 모드에서는 손절·익절·트레일링·보유기간을 쓸 수 없습니다(기존 CLI 는 이 규칙이 없음)" />}
      {mode === 'tick' && <Alert type="info" showIcon style={{ marginBottom: 8 }} message="틱 모드는 '최대 보유 봉' 대신 틱 설정의 '시간 손절(초)' 을 씁니다" />}
      {EXIT_FIELDS.filter((f) => !(mode === 'tick' && f.key === 'max_holding_bars')).map((f) => {
        const v = ex[f.key]
        const on = v !== null && v !== undefined
        return (
          <Row key={f.key} label={f.label} hint={mode === 'intraday' && f.key === 'max_holding_bars' ? '이 분봉 수를 넘기면 판다(당일 안에서만)' : f.hint}>
            <Switch size="small" checked={on} disabled={disabled} data-testid={`exit-${f.key}-on`}
              onChange={(x) => onChange({ ...ex, [f.key]: x ? (f.key === 'max_holding_bars' ? 20 : f.key === 'take_profit_pct' ? 15 : 7) : null, ...(x && f.key === 'take_profit_pct' ? { take_profit_levels: null } : {}) })} />
            {on && <NumField hint={f.key.replace('_pct', '')} value={v} min={0} max={f.max} step={f.key === 'max_holding_bars' ? 1 : 0.5} disabled={disabled}
              suffix={f.suffix} onChange={(x) => onChange({ ...ex, [f.key]: x })} data-testid={`exit-${f.key}`} />}
          </Row>
        )
      })}
      {has('take_profit_levels') && (
        <div data-testid="exit-levels">
          <Row label="분할 익절" hint="각 선에 닿을 때 남은 수량의 비율만큼 판다 — 예: +5% 에 절반, +10% 에 나머지 전부(비중 100%). 단일 익절과는 같이 못 쓴다">
            <Switch size="small" checked={levels.length > 0} disabled={disabled} data-testid="exit-levels-on" onChange={(x) => setLevels(x ? [{ pct: 5, fraction: 0.5 }, { pct: 10, fraction: 1 }] : [])} />
          </Row>
          {levels.length > 0 && (
            <Table size="small" pagination={false} rowKey={(_, i) => String(i)} dataSource={levels} style={{ marginBottom: 8 }}
              columns={[
                { title: '수익률 도달(%)', render: (_, l, i) => <InputNumber size="small" min={0.1} value={l.pct} disabled={disabled} data-testid={`level-pct-${i}`} onChange={(v) => v && setLevels(levels.map((x, j) => (j === i ? { ...x, pct: Number(v) } : x)))} /> },
                { title: '그때 파는 비중(남은 수량 기준 %)', render: (_, l, i) => <InputNumber size="small" min={1} max={100} value={Math.round(l.fraction * 100)} disabled={disabled} data-testid={`level-fraction-${i}`} onChange={(v) => v && setLevels(levels.map((x, j) => (j === i ? { ...x, fraction: Number(v) / 100 } : x)))} /> },
                { title: '', render: (_, __, i) => <Button size="small" disabled={disabled} onClick={() => setLevels(levels.filter((_x, j) => j !== i))}>삭제</Button> },
              ]} footer={() => <Button size="small" disabled={disabled} data-testid="level-add" onClick={() => setLevels([...levels, { pct: (levels[levels.length - 1]?.pct ?? 5) + 5, fraction: 1 }])}>단계 추가</Button>} />
          )}
          {levels.length > 0 && <Typography.Text type="secondary" style={{ fontSize: 12 }}>분할 청산은 거래 한 건을 조각 행으로 남긴다 — 승률·기대값은 진입 기준으로 합쳐서 센다(조각을 따로 세지 않는다).</Typography.Text>}
        </div>
      )}
      {has('take_profit_mode') && (
        <Row label="익절 방식" hint="익절(단일 또는 분할)이 켜져 있어야 한다 — 익절 가격에 닿은 것을 언제 확정하나">
          <Radio.Group size="small" value={ex.take_profit_mode ?? 'intrabar'} disabled={disabled} data-testid="exit-tp-mode" onChange={(e) => onChange({ ...ex, take_profit_mode: e.target.value })}>
            <Radio.Button value="intrabar">봉 안에서 즉시</Radio.Button><Radio.Button value="close">종가 확인 뒤 다음 봉 시가</Radio.Button>
          </Radio.Group>
        </Row>
      )}
      {has('trail_activate_pct') && numRow('trail_activate_pct', '트레일링 발동', '트레일링이 켜져 있어야 한다 — 최고 수익률이 이 % 를 넘은 뒤부터 작동한다', 5, '%')}
      {has('breakeven_after_pct') && numRow('breakeven_after_pct', '본전 손절', '최고 수익률이 이 % 에 닿으면 손절선을 매수가로 올린다', 3, '%')}
      {has('max_holding_minutes') && mode !== 'tick' && numRow('max_holding_minutes', '시간 청산(분)', '분봉에서 이 시간(분)을 넘기면 판다', 60, '분')}
      {extra.length === 0 && <Typography.Text type="secondary" style={{ fontSize: 12 }} data-testid="exits-advanced-pending">분할 익절·익절 방식·트레일링 발동 수익·본전 손절·시간 청산(분)은 서버 준비 중이다(studio-conditions c2 대기) — 서버가 알리면 여기에 나타난다.</Typography.Text>}
    </Card>
  )
}

// ───────────── 자금·배분 ─────────────
export function PortfolioPanel({ value: p, onChange, disabled, single, mode }: Part<'portfolio'> & { single: boolean; mode?: SpecJson['mode'] }) {
  return (
    <Card size="small" title="자금·배분" data-testid="panel-portfolio">
      {single && <Alert type="info" showIcon style={{ marginBottom: 8 }} message="단일 종목은 기본이 최대 보유 1 · 비중 100% 입니다(자본 전부를 씁니다)" />}
      <Row label="초기 자금"><InputNumber size="small" style={{ width: 170 }} min={1} step={1_000_000} value={p.initial_capital} disabled={disabled} suffix="원" formatter={(v) => `${v ?? ''}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')} parser={(v) => Number((v ?? '').replace(/,/g, ''))}
        onChange={(v) => onChange({ ...p, initial_capital: Number(v ?? 10_000_000) })} data-testid="initial-capital" /></Row>
      <Row label="최대 보유 종목"><NumField hint="max_pos" min={1} max={100} value={p.max_positions} disabled={disabled} onChange={(v) => onChange({ ...p, max_positions: v ?? 1 })} data-testid="max-positions" /></Row>
      <Row label="배분 방식">
        <Select size="small" style={{ width: 230 }} value={p.sizing} disabled={disabled} data-testid="sizing"
          options={[
            { value: 'equal_slot_fixed', label: '자리별 균등(초기자금 기준)' }, { value: 'equal_slot_compound', label: '자리별 균등(복리)' },
            { value: 'fixed_amount', label: '고정 금액' }, { value: 'risk_pct', label: '위험 비율(손절 기준)' },
          ]}
          onChange={(sizing) => onChange({ ...p, sizing })} />
      </Row>
      {p.sizing === 'fixed_amount' && <Row label="고정 금액"><NumField hint="amount" min={1} step={100_000} width={130} value={p.fixed_amount ?? 1_000_000} onChange={(v) => onChange({ ...p, fixed_amount: v })} /></Row>}
      {p.sizing === 'risk_pct' && <Row label="위험 비율(%)" hint="손절 %가 꼭 필요합니다"><NumField hint="risk" min={0.1} max={100} step={0.1} value={p.risk_pct ?? 1} onChange={(v) => onChange({ ...p, risk_pct: v })} /></Row>}
      <Row label="종목당 최대 비중"><NumField hint="weight" min={1} max={100} value={p.max_weight_pct} disabled={disabled} suffix="%" onChange={(v) => onChange({ ...p, max_weight_pct: v ?? 25 })} data-testid="max-weight" /></Row>
      <Row label="우선순위" hint={mode === 'tick' ? '틱 모드는 진입 시각 순이라 이 값을 무시한다' : '같은 날 신호가 자리보다 많을 때'}>
        <Select size="small" style={{ width: 150 }} value={p.rank_by} disabled={disabled || mode === 'tick'} options={[{ value: 'value', label: '거래대금 큰 순' }, { value: 'change_pct', label: '등락률 큰 순' }, { value: 'random', label: '무작위' }]}
          onChange={(rank_by) => onChange({ ...p, rank_by })} />
        {p.rank_by === 'random' && <InputNumber size="small" addonBefore="시드" value={p.random_seed} onChange={(v) => onChange({ ...p, random_seed: Number(v ?? 42) })} />}
      </Row>
    </Card>
  )
}

// ───────────── 비용·체결 ─────────────
export function CostsPanel({ costs, fills, onCosts, onFills, compat, disabled, mode }: {
  costs: SpecJson['costs']; fills: SpecJson['fills']; onCosts: (c: SpecJson['costs']) => void; onFills: (f: SpecJson['fills']) => void; compat: boolean; disabled?: boolean; mode?: SpecJson['mode']
}) {
  return (
    <Card size="small" title="비용·체결" data-testid="panel-costs">
      <Row label="수수료율"><InputNumber size="small" style={{ width: 130 }} min={0} max={5} step={0.005} value={+(costs.commission_rate * 100).toFixed(4)} suffix="%" onChange={(v) => onCosts({ ...costs, commission_rate: Number(v ?? 0) / 100 })} /></Row>
      <Row label="세금(매도)"><InputNumber size="small" style={{ width: 130 }} min={0} max={5} step={0.01} value={+(costs.tax_rate * 100).toFixed(4)} suffix="%" onChange={(v) => onCosts({ ...costs, tax_rate: Number(v ?? 0) / 100 })} /></Row>
      <Row label="슬리피지" hint={compat ? '호환 모드는 비율만 적용합니다' : undefined}>
        <Select size="small" style={{ width: 200 }} value={costs.slippage_mode} options={[{ value: 'rate', label: '비율' }, { value: 'ticks', label: '호가 수' }, { value: 'max_rate_tick', label: '비율·1호가 중 큰 쪽' }]}
          onChange={(slippage_mode) => onCosts({ ...costs, slippage_mode })} />
        {costs.slippage_mode !== 'ticks' && <InputNumber size="small" style={{ width: 110 }} min={0} max={5} step={0.01} value={+(costs.slippage_rate * 100).toFixed(4)} suffix="%" onChange={(v) => onCosts({ ...costs, slippage_rate: Number(v ?? 0) / 100 })} />}
        {costs.slippage_mode !== 'rate' && <InputNumber size="small" style={{ width: 100 }} min={0} max={20} value={costs.slippage_ticks} suffix="호가" onChange={(v) => onCosts({ ...costs, slippage_ticks: Number(v ?? 1) })} />}
      </Row>
      <Row label="같은 봉 손절·익절" hint="둘 다 닿았을 때 무엇이 먼저였나(모르므로 보수적으로 손절 먼저)">
        <Radio.Group size="small" value={fills.same_bar_policy} disabled={disabled} onChange={(e) => onFills({ ...fills, same_bar_policy: e.target.value })}>
          <Radio.Button value="stop_first">손절 먼저</Radio.Button><Radio.Button value="target_first">익절 먼저</Radio.Button>
        </Radio.Group>
      </Row>
      <Row label="거래량 한도" hint={mode === 'tick' ? '틱 모드는 거래량 한도를 적용하지 않는다' : '그날 거래량의 이 %까지만 체결'}>
        <Switch size="small" checked={fills.volume_cap_pct !== null} disabled={disabled || mode === 'tick'} onChange={(on) => onFills({ ...fills, volume_cap_pct: on ? 10 : null })} />
        {fills.volume_cap_pct !== null && <InputNumber size="small" min={0.1} max={100} value={fills.volume_cap_pct} suffix="%" disabled={disabled} onChange={(v) => onFills({ ...fills, volume_cap_pct: Number(v ?? 10) })} />}
      </Row>
    </Card>
  )
}

// ───────────── 호환 모드 ─────────────
export function CompatPanel({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <Card size="small" title="호환 모드 (단일 종목만)" data-testid="panel-compat">
      <Space>
        <Switch checked={on} onChange={onChange} data-testid="compat-switch" />
        <Typography.Text>기존 CLI(<code>simulator.run</code>)와 같은 규칙으로 돌립니다 — 연구 결과와 숫자를 이어 볼 때</Typography.Text>
      </Space>
      {on && <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0' }} data-testid="compat-note">
        켜면 손절·익절·트레일링·보유기간, 배분·비중, 거래량 한도가 잠깁니다. 결과에 &quot;기존 CLI 기준&quot; 줄이 함께 나옵니다.
      </Typography.Paragraph>}
    </Card>
  )
}

// ───────────── 변수 표 ─────────────
export function ParamsTable({ value, onChange }: { value: Record<string, ParamRange>; onChange: (p: Record<string, ParamRange>) => void }) {
  const rows = Object.entries(value).map(([name, r]) => ({ name, ...r }))
  if (!rows.length) return null
  const set = (name: string, patch: Partial<ParamRange>) => onChange({ ...value, [name]: { ...value[name], ...patch } })
  return (
    <Card size="small" title="변수 (최적화 때 이 범위를 훑습니다)" data-testid="panel-params">
      <Table size="small" pagination={false} rowKey="name" dataSource={rows}
        columns={[
          { title: '이름', dataIndex: 'name' },
          ...(['default', 'min', 'max', 'step'] as const).map((k) => ({
            title: { default: '기본값', min: '최소', max: '최대', step: '간격' }[k], dataIndex: k,
            render: (_: unknown, r: (typeof rows)[number]) => <InputNumber size="small" style={{ width: 90 }} value={r[k] ?? null} onChange={(v) => set(r.name, { [k]: v === null ? null : Number(v) })} />,
          })),
        ]} />
    </Card>
  )
}
