// 분봉·틱 결과 패널 (§5.4 ResultPage, module-6): 출처 배너 · 분봉 커버리지 · 틱 표본 · 틱 정밀화 비교.
// 값이 없는 칸은 "없음"이라고 말하고 지어내지 않는다. 정보는 접지 않는다(종목별 보관 기간 표도 펼쳐 둔다).
import { Alert, Card, Col, Descriptions, Row, Space, Table, Tag, Typography } from 'antd'
import { KRX_WARNING } from '@/components/builder/ModePanels'
import { DASH, fmtDate, fmtNum } from '@/lib/format'
import type { DiffStats, IntradaySummary, RunDetail, TickRefineSummary, TickSummary } from '@/types/studio'

const won = (v: number | null | undefined) => (v === null || v === undefined ? DASH : `${fmtNum(Math.round(v))}원`)
const signColor = (v: number | null | undefined) => (v === null || v === undefined || v === 0 ? undefined : v > 0 ? '#f5222d' : '#1677ff')
const pct3 = (v: number | null | undefined) => (v === null || v === undefined ? DASH : `${v > 0 ? '+' : ''}${v.toFixed(3)}%`)

/** KRX 로 돌린 결과는 화면 맨 위에 크게 — 통합 결과와 섞어 읽지 않게. 통합이면 작은 태그 */
export function MinuteSourceBanner({ d }: { d: RunDetail }) {
  const src = d.meta.minute_source ?? (d.summary.intraday as IntradaySummary | undefined)?.minute_source
  if (!src) return null
  if (src === 'krx') {
    return <Alert type="warning" showIcon data-testid="krx-banner" message={<b style={{ fontSize: 16 }}>{KRX_WARNING}</b>}
      description="이 결과는 KRX 분봉으로 계산했다. 거래량·거래대금 조건의 임계값이 통합(NXT 포함) 결과와 같은 뜻이 아니므로 두 결과를 나란히 비교하지 마세요." />
  }
  return <Tag color="blue" data-testid="al-tag">분봉 출처: 통합(AL) — NXT 체결 포함</Tag>
}

function Stat({ title, value, sub }: { title: string; value: React.ReactNode; sub?: string }) {
  return (
    <Card size="small" style={{ height: '100%' }}>
      <Typography.Text type="secondary">{title}</Typography.Text><br />
      <Typography.Text strong style={{ fontSize: 20 }}>{value}</Typography.Text>
      {sub && <><br /><Typography.Text type="secondary" style={{ fontSize: 12 }}>{sub}</Typography.Text></>}
    </Card>
  )
}

/** 분봉 커버리지 — 기대 (날짜,종목) 쌍 중 분봉이 실제로 있던 쌍, 분봉이 아예 없던 종목, 종목별 보관 기간 */
export function IntradayCoverage({ s, name }: { s: IntradaySummary; name: (code: string) => string }) {
  const periods = Object.entries(s.code_periods ?? {}).map(([code, [a, b]]) => ({ code, first: a, last: b }))
  return (
    <Space direction="vertical" size="small" style={{ width: '100%' }} data-testid="intraday-coverage">
      <Typography.Text strong>분봉 표본 ({s.bar_minutes}분봉 · {s.minute_source === 'krx' ? 'KRX' : '통합'})</Typography.Text>
      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}><Stat title="분봉이 있던 (날짜, 종목) 쌍" value={`${fmtNum(s.used_pairs)} / ${fmtNum(s.expected_pairs)}`} sub={s.pairs_share === null ? '기대 쌍 없음' : `${(s.pairs_share * 100).toFixed(0)}% — 나머지는 거래 기회가 없었다`} /></Col>
        <Col xs={12} md={6}><Stat title="분봉이 있는 거래일" value={`${s.days_with_bars} / ${s.days_in_period}일`} sub="기간 안 거래일 대비" /></Col>
        <Col xs={12} md={6}><Stat title="분봉 있는 종목" value={`${s.codes_with_minutes} / ${s.codes_requested}종목`} sub={s.codes_without_minutes.length ? `없는 종목: ${s.codes_without_minutes.slice(0, 5).join(', ')}${s.codes_without_minutes.length > 5 ? ' 외' : ''}` : '모두 있음'} /></Col>
        <Col xs={12} md={6}><Stat title="지표 준비 구간" value={`${s.warmup_days}일`} sub="기간 앞에서 지표 계산용으로만 읽은 날" /></Col>
      </Row>
      {periods.length > 0 && (
        <Card size="small" title="쓴 종목별 그 출처의 보관 기간" data-testid="code-periods">
          <Table size="small" rowKey="code" dataSource={periods} pagination={{ pageSize: 10, hideOnSinglePage: true }}
            columns={[
              { title: '종목', dataIndex: 'code', render: (c: string) => <span>{name(c)} <Typography.Text type="secondary">{c}</Typography.Text></span> },
              { title: '보관 시작', dataIndex: 'first', render: fmtDate, sorter: (a, b) => a.first.localeCompare(b.first) },
              { title: '보관 끝', dataIndex: 'last', render: fmtDate, sorter: (a, b) => a.last.localeCompare(b.last) },
            ]} />
        </Card>
      )}
    </Space>
  )
}

export function TickSample({ t }: { t: TickSummary }) {
  return (
    <Space direction="vertical" size="small" style={{ width: '100%' }} data-testid="tick-summary">
      <Typography.Text strong>틱(체결) 표본</Typography.Text>
      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}><Stat title="체결 데이터 (날짜, 종목) 쌍" value={`${fmtNum(t.used_pairs)} / ${fmtNum(t.expected_pairs)}`} sub={`${t.days}거래일 · ${t.codes}종목`} /></Col>
        <Col xs={12} md={6}><Stat title="신호 수" value={fmtNum(t.signals)} sub={`진입 체결이 없어 버린 신호 ${t.signals_without_entry_tick}건`} /></Col>
        <Col xs={12} md={6}><Stat title="갭 시작으로 거른 (날, 종목)" value={fmtNum(t.gap_open_days_skipped)} /></Col>
        <Col xs={12} md={6}><Stat title="장마감 청산" value={t.eod_time} sub="초 단위 시각" /></Col>
      </Row>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>거래의 보유 기간은 초 단위다(분봉·일봉 결과의 "봉"과 단위가 다르다).</Typography.Text>
    </Space>
  )
}

const diffRows = (r: TickRefineSummary): { key: string; label: string; s: DiffStats }[] => [
  { key: 'entry', label: '진입가', s: r.entry_diff_pct }, { key: 'exit', label: '청산가', s: r.exit_diff_pct },
]

/** 틱 정밀화 비교 — 봉 기준가 대신 실제 틱 체결가로 다시 잡았을 때 체결가·손익이 얼마나 달라졌나(SC-7) */
export function TickRefineCard({ r }: { r: TickRefineSummary }) {
  const delta = r.net_pnl_bar !== null && r.net_pnl_tick !== null ? r.net_pnl_tick - r.net_pnl_bar : null
  return (
    <Card size="small" title="틱 정밀화 비교 — 봉 기준가 vs 실제 틱 체결가" data-testid="tick-refine">
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Descriptions size="small" column={{ xs: 1, md: 2, xl: 4 }} items={[
          { label: '거래 수', children: fmtNum(r.n_trades) },
          { label: '틱으로 다시 잡은 거래', children: <b data-testid="n-refined">{fmtNum(r.n_refined)}</b> },
          { label: '틱 데이터가 없어 못 잡은 거래', children: fmtNum(r.n_without_ticks) },
          { label: '맞는 체결을 못 찾은 거래', children: fmtNum(r.n_no_matching_tick) },
        ]} />
        {(r.n_without_ticks > 0 || r.n_no_matching_tick > 0) && <Alert type="warning" showIcon message={`${fmtNum(r.n_without_ticks + r.n_no_matching_tick)}건은 봉 기준가 그대로다 — 아래 비교엔 다시 잡은 거래만 들어간다`} />}
        <Table size="small" pagination={false} rowKey="key" dataSource={diffRows(r)} data-testid="diff-stats"
          columns={[
            { title: '체결가 차이(틱 ÷ 봉 − 1, 슬리피지 전)', dataIndex: 'label' },
            { title: '평균', render: (_, x) => pct3(x.s.mean) }, { title: '중앙값', render: (_, x) => pct3(x.s.median) },
            { title: '하위 5%', render: (_, x) => pct3(x.s.p5) }, { title: '상위 95%', render: (_, x) => pct3(x.s.p95) },
            { title: '표본', render: (_, x) => fmtNum(x.s.n) },
          ]} />
        <Row gutter={[12, 12]}>
          <Col xs={24} md={8}><Stat title="순손익 — 봉 기준" value={<span style={{ color: signColor(r.net_pnl_bar) }}>{won(r.net_pnl_bar)}</span>} /></Col>
          <Col xs={24} md={8}><Stat title="순손익 — 틱 기준(같은 비용 모델로 다시 계산)" value={<span style={{ color: signColor(r.net_pnl_tick) }} data-testid="pnl-tick">{won(r.net_pnl_tick)}</span>} /></Col>
          <Col xs={24} md={8}><Stat title="차이(틱 − 봉)" value={<span style={{ color: signColor(delta) }} data-testid="pnl-delta">{delta === null ? DASH : `${delta > 0 ? '+' : ''}${fmtNum(Math.round(delta))}원`}</span>}
            sub={delta === null ? undefined : delta < 0 ? '봉 기준 백테스트가 체결을 실제보다 좋게 봤다' : delta > 0 ? '봉 기준 백테스트가 체결을 실제보다 나쁘게 봤다' : '차이 없음'} /></Col>
        </Row>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{r.definition}</Typography.Text>
      </Space>
    </Card>
  )
}
