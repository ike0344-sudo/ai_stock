// 분봉·틱 입력 패널 (§5.4 BacktestPage 분봉 탭·틱 탭, module-6).
// 정보는 접지 않는다: 출처별 사용 가능 기간·종목 수, 표본 길이, 근사 규칙을 그 자리에 다 보여준다.
import { Alert, Card, Input, InputNumber, Radio, Space, Switch, Table, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { useIntradaySources } from '@/api/studio'
import { ConditionGroupEditor } from '@/components/builder/ConditionGroupEditor'
import { fmtDate } from '@/lib/format'
import { BAR_MINUTES, type Group, type IndicatorCatalog, type IntradayCfg, type IntradaySources, type MinuteSource, type SpecJson, type TickCfg, type ValidationIssue } from '@/types/studio'

const Row = ({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) => (
  <div style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '4px 0', flexWrap: 'wrap' }}>
    <span style={{ width: 132, flexShrink: 0 }}>{label}</span>
    {children}
    {hint && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{hint}</Typography.Text>}
  </div>
)

export const SOURCE_LABEL: Record<MinuteSource, string> = { al: '통합(AL) — NXT 체결 포함', krx: 'KRX 전용 — NXT 체결 제외' }
export const KRX_WARNING = 'KRX 기준(NXT 제외, 거래량·거래대금이 통합보다 20~40% 작음)'

/** 분봉 출처별 사용 가능 기간과 기간 안 종목 수 — 출처를 고를 근거. 통합은 종목별로 1~2개월, KRX 는 2025-07~ 로 길다 */
export function SourceAvailability({ info, chosen, loading, error }: { info?: IntradaySources; chosen: MinuteSource; loading: boolean; error?: string }) {
  if (loading) return <Typography.Text type="secondary" data-testid="source-loading">출처별 보관 기간을 확인하는 중…</Typography.Text>
  if (error || !info) return <Alert type="warning" showIcon message={`출처별 보관 기간을 못 불러옴${error ? `: ${error}` : ''}`} />
  const rows = (['al', 'krx'] as const).map((k) => ({ key: k, ...info.minute[k] }))
  const chosenRow = info.minute[chosen]
  return (
    <div data-testid="source-availability">
      <Table size="small" pagination={false} rowKey="key" dataSource={rows}
        columns={[
          { title: '분봉 출처', dataIndex: 'key', render: (k: MinuteSource) => <span>{SOURCE_LABEL[k]} {k === chosen && <Tag color="blue">선택됨</Tag>}</span> },
          { title: '전체 보관 기간', dataIndex: 'range', render: (r: [string, string] | null) => (r ? `${fmtDate(r[0])} ~ ${fmtDate(r[1])}` : '없음') },
          { title: '보관 종목', dataIndex: 'total' },
          { title: '이 기간을 다 덮는 종목', dataIndex: 'full', render: (v: number) => <b>{v}</b> },
          { title: '일부만 덮는 종목', dataIndex: 'partial' },
        ]} />
      {chosenRow.full === 0 && chosenRow.partial === 0 && <Alert type="error" showIcon style={{ marginTop: 8 }} data-testid="source-none" message={`고른 출처(${chosen === 'al' ? '통합' : 'KRX'})에 이 기간의 분봉이 하나도 없다 — 기간을 옮기거나 다른 출처를 고르세요`} />}
      {chosenRow.full === 0 && chosenRow.partial > 0 && <Alert type="warning" showIcon style={{ marginTop: 8 }} data-testid="source-partial" message={`고른 출처(${chosen === 'al' ? '통합' : 'KRX'})가 이 기간 전체를 덮는 종목은 없고, ${chosenRow.partial}종목이 일부만 덮는다 — 보관된 날에만 거래 기회가 있다(결과의 "분봉 커버리지"에 쌍 수로 나온다)`} />}
      {chosenRow.full > 0 && chosenRow.partial > 0 && <Typography.Text type="secondary" style={{ fontSize: 12 }}>기간을 일부만 덮는 {chosenRow.partial}종목은 보관된 날만 거래 기회가 있다(결과의 "분봉 커버리지"에 쌍 수로 나온다)</Typography.Text>}
      <div><Typography.Text type="secondary" style={{ fontSize: 12 }}>통합 분봉은 종목별로 1~2개월치만 있다. 더 긴 기간은 KRX 를 고르되 NXT 체결이 빠진다. 수집 현황은 <Link to="/hub/overview">데이터 허브</Link>.</Typography.Text></div>
    </div>
  )
}

const DEFAULT_PREFILTER: Group = { logic: 'all', items: [{ left: { kind: 'field', name: 'close' }, op: 'gt', right: { kind: 'ind', name: 'sma', params: { src: 'close', n: 20 } } }] }

export function IntradayPanel({ value: v, onChange, spec, cat, errors, mode }: {
  value: IntradayCfg; onChange: (v: IntradayCfg) => void; spec: SpecJson; cat: IndicatorCatalog; errors: ValidationIssue[]; mode: SpecJson['mode']
}) {
  const info = useIntradaySources(spec.period.start, spec.period.end)
  const set = (p: Partial<IntradayCfg>) => onChange({ ...v, ...p })
  return (
    <Card size="small" title={mode === 'tick' ? '분봉 신호 설정 (틱 정밀화의 재료)' : '분봉 설정'} data-testid="panel-intraday">
      <Row label="봉 길이" hint="분봉을 몇 분 단위로 묶어 조건을 보나">
        <Radio.Group value={v.bar_minutes} onChange={(e) => set({ bar_minutes: e.target.value })} data-testid="bar-minutes"
          options={BAR_MINUTES.map((m) => ({ value: m, label: `${m}분` }))} optionType="button" />
      </Row>
      <Row label="분봉 출처" hint="기본은 통합(NXT 포함). KRX 는 기간이 길지만 거래량이 작게 잡힌다">
        <Radio.Group value={v.source} onChange={(e) => set({ source: e.target.value })} data-testid="minute-source" optionType="button"
          options={[{ value: 'al', label: '통합(AL)' }, { value: 'krx', label: 'KRX 전용' }]} />
      </Row>
      {v.source === 'krx' && <Alert type="warning" showIcon data-testid="krx-warning" style={{ margin: '4px 0 8px' }} message={KRX_WARNING}
        description="가격은 거의 같지만 거래량·거래대금 조건의 임계값이 같아도 더 엄격해진다. 통합 결과와 섞어 해석하지 마세요. 결과 화면에도 같은 표시가 붙는다." />}
      <SourceAvailability info={info.data} chosen={v.source} loading={info.isPending} error={info.isError ? info.error.message : undefined} />
      <Row label="전일 거래대금 상위 N" hint="분봉 모드에서는 이 값이 유니버스의 N 이다(유니버스의 '상위 N' 은 무시). 전일(D−1) 순위라 미래 참조가 없다">
        <InputNumber size="small" min={1} max={500} value={v.prefilter_top_value} onChange={(x) => x && set({ prefilter_top_value: Math.round(x) })} data-testid="prefilter-top" />
      </Row>
      <Row label="장마감 청산 시각" hint="이 시각에 남은 물량을 정리한다(15:30 종가 단일가 봉은 거래하지 않는다)">
        <Input type="time" style={{ width: 120 }} value={v.eod_time} onChange={(e) => e.target.value && set({ eod_time: e.target.value })} data-testid="eod-time" />
      </Row>
      <Row label="일봉 사전 필터" hint="전일(D−1) 일봉 조건으로 종목을 먼저 거른다 — 예: 전일 종가가 20일선 위">
        <Switch checked={v.prefilter !== null} onChange={(on) => set({ prefilter: on ? structuredClone(DEFAULT_PREFILTER) : null })} data-testid="prefilter-switch" />
      </Row>
      {v.prefilter && (
        <ConditionGroupEditor title="사전 필터 (전일 일봉 기준 — 진입 조건 아님)" path="intraday.prefilter" group={v.prefilter} cat={cat} mode="daily_portfolio" errors={errors} required
          onChange={(g) => set({ prefilter: g })} />
      )}
    </Card>
  )
}

export function TickPanel({ value: v, onChange, spec }: { value: TickCfg; onChange: (v: TickCfg) => void; spec: SpecJson }) {
  const info = useIntradaySources(spec.period.start, spec.period.end)
  const set = (p: Partial<TickCfg>) => onChange({ ...v, ...p })
  const cset = (p: Partial<TickCfg['catalog']>) => onChange({ ...v, catalog: { ...v.catalog, ...p } })
  const c = v.catalog
  const t = info.data?.tick
  return (
    <Card size="small" title="틱(체결) 설정" data-testid="panel-tick">
      <Alert type="info" showIcon style={{ marginBottom: 8 }} data-testid="tick-sample" message={
        t ? `체결 표본: ${t.days}거래일(${t.first ? fmtDate(t.first) : '—'} ~ ${t.last ? fmtDate(t.last) : '—'}) · ${t.codes}종목 — 고른 기간 안에는 ${t.days_in_range}거래일`
          : info.isPending ? '체결 표본을 확인하는 중…' : '체결 표본을 못 불러옴'}
        description="틱 결과는 표본이 짧다(수집 조회창 20거래일) — 통계적 의미가 약하다. 체결 파일 상당수는 같은 초 안 체결 순서가 불확실하다." />
      {t && t.days_in_range === 0 && <Alert type="error" showIcon style={{ marginBottom: 8 }} data-testid="tick-none" message="고른 기간에 체결 데이터가 있는 날이 하나도 없다 — 기간을 체결 표본 안으로 옮기세요" />}
      <Row label="진입 방식">
        <Radio.Group value={v.entry_source} onChange={(e) => set({ entry_source: e.target.value })} data-testid="tick-entry-source" optionType="button"
          options={[{ value: 'catalog', label: '틱 조건으로 바로 진입' }, { value: 'minute_refine', label: '분봉 신호 + 틱 정밀화' }]} />
      </Row>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        {v.entry_source === 'catalog'
          ? '아래 틱 조건을 모두 만족한 순간의 다음 체결에 산다(신호 초보다 엄격히 뒤).'
          : '분봉 조건(아래 전략)으로 신호를 내되, 체결가를 봉 기준가 대신 실제 틱 체결가로 다시 잡아 차이를 비교한다(진입은 봉 신호와 같다).'}
      </Typography.Paragraph>
      {v.entry_source === 'catalog' && (
        <div data-testid="tick-catalog">
          <Row label="N분 고점 돌파" hint="직전 N분 최고가(현재 체결 제외)를 넘으면">
            <Switch checked={c.breakout_min !== null} onChange={(on) => cset({ breakout_min: on ? 5 : null })} data-testid="tick-breakout-on" />
            {c.breakout_min !== null && <InputNumber size="small" min={1} max={60} addonAfter="분" value={c.breakout_min} onChange={(x) => x && cset({ breakout_min: Math.round(x) })} data-testid="tick-breakout" />}
          </Row>
          <Row label="체결대금 속도" hint="최근 창의 체결대금이 인과적 누적 평균의 몇 배 이상">
            <Switch checked={c.value_speed !== null} onChange={(on) => cset({ value_speed: on ? { w: 1, ratio: 3 } : null })} data-testid="tick-speed-on" />
            {c.value_speed && <Space>
              <InputNumber size="small" min={1} max={60} addonAfter="분 창" value={c.value_speed.w} onChange={(x) => x && cset({ value_speed: { ...c.value_speed!, w: Math.round(x) } })} data-testid="tick-speed-w" />
              <InputNumber size="small" min={0.1} step={0.5} addonAfter="배 이상" value={c.value_speed.ratio} onChange={(x) => x && cset({ value_speed: { ...c.value_speed!, ratio: x } })} data-testid="tick-speed-ratio" />
            </Space>}
          </Row>
          <Row label="매수 체결 비중" hint="틱룰로 가른 매수 체결 비율이 이 이상">
            <Switch checked={c.buy_ratio !== null} onChange={(on) => cset({ buy_ratio: on ? { w: 1, min: 0.6 } : null })} data-testid="tick-buy-on" />
            {c.buy_ratio && <Space>
              <InputNumber size="small" min={1} max={60} addonAfter="분 창" value={c.buy_ratio.w} onChange={(x) => x && cset({ buy_ratio: { ...c.buy_ratio!, w: Math.round(x) } })} data-testid="tick-buy-w" />
              <InputNumber size="small" min={0} max={1} step={0.05} addonAfter="이상" value={c.buy_ratio.min} onChange={(x) => x !== null && cset({ buy_ratio: { ...c.buy_ratio!, min: x } })} data-testid="tick-buy-min" />
            </Space>}
          </Row>
          {c.breakout_min === null && !c.value_speed && !c.buy_ratio && <Alert type="error" showIcon data-testid="tick-no-cond" style={{ marginBottom: 6 }} message="틱 조건이 하나도 없다 — 하나 이상 켜세요" />}
          <Row label="진입 허용 시간대" hint="이 시간 사이에만 진입한다">
            <Input type="time" style={{ width: 120 }} value={c.time_from} onChange={(e) => e.target.value && cset({ time_from: e.target.value })} data-testid="tick-time-from" />
            <span>~</span>
            <Input type="time" style={{ width: 120 }} value={c.time_to} onChange={(e) => e.target.value && cset({ time_to: e.target.value })} data-testid="tick-time-to" />
          </Row>
        </div>
      )}
      <Row label="쿨다운" hint="같은 종목에서 다시 신호를 내기까지 기다리는 시간(초)">
        <InputNumber size="small" min={0} addonAfter="초" value={v.cooldown_sec} onChange={(x) => x !== null && set({ cooldown_sec: Math.round(x) })} data-testid="tick-cooldown" />
      </Row>
      <Row label="갭 시작 종목 제외" hint="시가가 전일 종가보다 이만큼 이상 벌어져 시작한 날은 그 종목을 거르기">
        <Switch checked={v.exclude_gap_open_pct !== null} onChange={(on) => set({ exclude_gap_open_pct: on ? 5 : null })} data-testid="tick-gap-on" />
        {v.exclude_gap_open_pct !== null && <InputNumber size="small" min={0} step={0.5} addonAfter="%" value={v.exclude_gap_open_pct} onChange={(x) => x !== null && set({ exclude_gap_open_pct: x })} data-testid="tick-gap" />}
      </Row>
      <Row label="시간 손절" hint="산 뒤 이 시간이 지나면 판다(분봉 모드의 '최대 보유 봉' 대신)">
        <Switch checked={v.time_stop_sec !== null} onChange={(on) => set({ time_stop_sec: on ? 600 : null })} data-testid="tick-timestop-on" />
        {v.time_stop_sec !== null && <InputNumber size="small" min={1} addonAfter="초" value={v.time_stop_sec} onChange={(x) => x && set({ time_stop_sec: Math.round(x) })} data-testid="tick-timestop" />}
      </Row>
      <Row label="장마감 청산 시각" hint="이 시각(초 단위)에 남은 물량을 정리한다">
        <Input type="time" step={1} style={{ width: 140 }} value={v.eod_time} onChange={(e) => e.target.value && set({ eod_time: e.target.value.length === 5 ? `${e.target.value}:00` : e.target.value })} data-testid="tick-eod" />
      </Row>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        틱 모드 근사: 거래량 한도 미적용 · 상하한가에 잠긴 가격으로도 청산 · 보유 기간은 초 단위 · 우선순위는 진입 시각 순(위 자금 설정의 우선순위는 무시).
      </Typography.Text>
    </Card>
  )
}
