// 결과 차트 묶음 (§5.4 ResultPage): 수익곡선(코스피/코스닥·로그 축·확대) · 낙폭 · 월별 히트맵 + 연도 막대 · 수익 분포 · MFE/MAE ·
// 보유기간 vs 수익 · 업종별 · 소피증권 테마 그룹별 · 청산 사유 · 비용 민감도(손익분기 배수) · 몬테카를로 · 집중도.
// 값이 없으면 "없음"이라고 쓴다 — 지어내지 않는다.
import { Alert, Card, Col, Empty, Row, Space, Switch, Table, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { EChart } from '@/components/charts/EChart'
import { DASH, fmtNum } from '@/lib/format'
import { costSensitivityOption, drawdownOption, equityOption, groupBarOption, histogramOption, holdingScatterOption, mfeMaeOption, monthlyHeatmapOption, yearlyBarOption } from '@/lib/chartOptions'
import { exitReason } from '@/lib/labels'
import { withBands, type Band } from '@/lib/validation'
import { VERDICT3_COLOR, VERDICT3_LABEL, verdictOf } from '@/lib/verdicts'
import type { Analysis, EquityPoint, GroupPerf, Robustness, Trade } from '@/types/studio'

const Panel = ({ title, children, testid }: { title: string; children: React.ReactNode; testid: string }) => (
  <Card size="small" title={title} data-testid={testid} style={{ height: '100%' }}>{children}</Card>
)
const none = (text: string) => <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={text} />

export function EquityPanel({ equity, bands }: { equity: EquityPoint[]; bands?: Band[] }) {
  const [log, setLog] = useState(false)
  const opt = useMemo(() => (bands ? withBands(equityOption(equity, { log }), equity, bands) : equityOption(equity, { log })), [equity, log, bands])
  return (
    <Card size="small" title="수익곡선 (내 전략 vs 코스피·코스닥)" data-testid="panel-equity"
      extra={<Space>로그 축<Switch size="small" checked={log} onChange={setLog} data-testid="log-switch" /></Space>}>
      {equity.length ? <EChart option={opt} height={380} /> : none('평가금 곡선이 없습니다')}
    </Card>
  )
}

export function DrawdownPanel({ equity }: { equity: EquityPoint[] }) {
  const opt = useMemo(() => drawdownOption(equity), [equity])
  return <Panel title="낙폭 (고점 대비 얼마나 빠져 있었나)" testid="panel-drawdown">{equity.length ? <EChart option={opt} height={220} /> : none('없음')}</Panel>
}

export function PeriodPanels({ analysis }: { analysis: Analysis }) {
  const heat = useMemo(() => monthlyHeatmapOption(analysis.monthly), [analysis.monthly])
  const bar = useMemo(() => yearlyBarOption(analysis.yearly), [analysis.yearly])
  return (
    <Row gutter={[12, 12]}>
      <Col xs={24} xl={14}><Panel title="월별 수익률" testid="panel-monthly">{analysis.monthly.length ? <EChart option={heat} height={Math.max(180, 60 + 34 * new Set(analysis.monthly.map((m) => m.period.slice(0, 4))).size)} /> : none('없음')}</Panel></Col>
      <Col xs={24} xl={10}><Panel title="연도별 수익률" testid="panel-yearly">{analysis.yearly.length ? <EChart option={bar} height={260} /> : none('없음')}</Panel></Col>
    </Row>
  )
}

export function DistributionPanels({ analysis, trades }: { analysis: Analysis; trades: Trade[] }) {
  const hist = useMemo(() => histogramOption(analysis.histogram), [analysis.histogram])
  const mm = useMemo(() => mfeMaeOption(trades), [trades])
  const hold = useMemo(() => holdingScatterOption(trades), [trades])
  return (
    <Row gutter={[12, 12]}>
      <Col xs={24} xl={8}><Panel title="거래 수익률 분포" testid="panel-hist">{analysis.histogram.counts.length ? <EChart option={hist} height={280} /> : none('거래 없음')}</Panel></Col>
      <Col xs={24} xl={8}><Panel title="MFE / MAE (거래 중 최고 이익 vs 최대 손실)" testid="panel-mfemae">{trades.length ? <EChart option={mm} height={280} /> : none('거래 없음')}</Panel></Col>
      <Col xs={24} xl={8}><Panel title="보유 기간 vs 수익" testid="panel-holding">{trades.length ? <EChart option={hold} height={280} /> : none('거래 없음')}</Panel></Col>
    </Row>
  )
}

function PerfTable({ rows }: { rows: GroupPerf[] }) {
  return (
    <Table<GroupPerf> size="small" rowKey="key" dataSource={rows} pagination={{ pageSize: 8, hideOnSinglePage: true }}
      columns={[
        { title: '이름', dataIndex: 'key' },
        { title: '거래', dataIndex: 'n', sorter: (a, b) => a.n - b.n },
        { title: '승률', dataIndex: 'win_rate_pct', render: (v: number) => `${v.toFixed(0)}%` },
        { title: '순손익', dataIndex: 'net_pnl', defaultSortOrder: 'descend', sorter: (a, b) => a.net_pnl - b.net_pnl, render: (v: number) => <span style={{ color: v >= 0 ? '#f5222d' : '#1677ff' }}>{fmtNum(Math.round(v))}원</span> },
        { title: '평균 수익률', dataIndex: 'avg_net_pct', render: (v: number) => `${v.toFixed(2)}%` },
      ]} />
  )
}

export function GroupPanels({ analysis }: { analysis: Analysis }) {
  const sector = useMemo(() => groupBarOption(analysis.by_sector), [analysis.by_sector])
  const theme = useMemo(() => groupBarOption(analysis.by_theme_group ?? []), [analysis.by_theme_group])
  return (
    <Row gutter={[12, 12]}>
      <Col xs={24} xl={12}>
        <Panel title="업종별 성과" testid="panel-sector">
          {analysis.by_sector.length ? <><EChart option={sector} height={300} /><PerfTable rows={analysis.by_sector} /></> : none('업종 정보가 없습니다')}
        </Panel>
      </Col>
      <Col xs={24} xl={12}>
        <Panel title="소피증권 테마 그룹별 성과" testid="panel-theme">
          {analysis.by_theme_group === null ? none('테마 그룹 매핑이 없어 계산하지 못했습니다')
            : analysis.by_theme_group.length ? <><EChart option={theme} height={300} /><PerfTable rows={analysis.by_theme_group} /></> : none('테마 그룹에 속한 거래가 없습니다')}
        </Panel>
      </Col>
    </Row>
  )
}

export function ExitReasonPanel({ analysis }: { analysis: Analysis }) {
  return (
    <Panel title="청산 사유" testid="panel-exit-reasons">
      {analysis.exit_reasons.length ? (
        <Table size="small" rowKey="reason" pagination={false} dataSource={analysis.exit_reasons}
          columns={[
            { title: '사유', dataIndex: 'reason', render: (r: string) => exitReason(r) },
            { title: '건수', dataIndex: 'n' },
            { title: '비율', dataIndex: 'share_pct', render: (v: number) => `${v.toFixed(1)}%` },
            { title: '평균 수익률', dataIndex: 'avg_net_pct', render: (v: number) => <span style={{ color: v >= 0 ? '#f5222d' : '#1677ff' }}>{v.toFixed(2)}%</span> },
          ]} />
      ) : none('거래 없음')}
    </Panel>
  )
}

/** 견고성(비용 민감도·몬테카를로·집중도) — backtest-agent 가 summary.robustness 에 넣는다. 없으면 "없음". */
export function RobustnessPanels({ r }: { r: Robustness | null }) {
  const cost = useMemo(() => (r?.cost_sensitivity ? costSensitivityOption(r.cost_sensitivity, r.breakeven_cost_mult) : null), [r])
  if (!r) return <Alert type="info" showIcon data-testid="panel-robustness-none" message="견고성 점검 없음" description="이 결과에는 비용 민감도·몬테카를로·집중도 값이 없습니다(거래가 없거나 옛 버전 결과)." />
  const be = r.breakeven_cost_mult
  const bv = verdictOf('breakeven_cost_mult', be)
  const mc = r.monte_carlo
  return (
    <Row gutter={[12, 12]} data-testid="panel-robustness">
      <Col xs={24} xl={10}>
        <Panel title="비용 민감도 (수수료·세금·슬리피지를 k배로 하면?)" testid="panel-cost">
          {cost ? <EChart option={cost} height={260} /> : none('호환 모드는 비용 민감도를 계산하지 않습니다')}
          <Space wrap>
            <Typography.Text>손익분기 비용 배수</Typography.Text>
            <Typography.Text strong data-testid="breakeven">{be === null || be === undefined ? DASH : `×${be.toFixed(2)}`}</Typography.Text>
            {bv && <Tag color={VERDICT3_COLOR[bv]}>{VERDICT3_LABEL[bv]}</Tag>}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>비용이 이 배수까지 늘어도 본전 — 클수록 비용에 강한 전략</Typography.Text>
          </Space>
          {r.cost_sensitivity_meta && <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>{r.cost_sensitivity_meta.approximation}</Typography.Paragraph>}
        </Panel>
      </Col>
      <Col xs={24} xl={7}>
        <Panel title="몬테카를로 (거래 순서를 1,000번 섞으면?)" testid="panel-montecarlo">
          {mc ? (
            <Table size="small" pagination={false} rowKey="k" dataSource={[
              { k: '최종 수익률', ...mc.final_return_pct }, { k: '최대 낙폭', ...mc.max_drawdown_pct },
            ]} columns={[{ title: '', dataIndex: 'k' }, { title: '나쁜 경우(5%)', dataIndex: 'p5', render: (v: number) => `${v.toFixed(1)}%` }, { title: '중간', dataIndex: 'p50', render: (v: number) => `${v.toFixed(1)}%` }, { title: '좋은 경우(95%)', dataIndex: 'p95', render: (v: number) => `${v.toFixed(1)}%` }]} />
          ) : none('거래가 5건 미만이라 계산하지 않았습니다')}
          {mc?.prob_mdd_gt_30 !== undefined && <Typography.Paragraph style={{ margin: '8px 0 0' }}>낙폭이 30%를 넘을 확률 {(mc.prob_mdd_gt_30 * 100).toFixed(0)}%</Typography.Paragraph>}
          {mc?.approximation && <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>{mc.approximation}</Typography.Paragraph>}
        </Panel>
      </Col>
      <Col xs={24} xl={7}>
        <Panel title="집중도 (몇 건만 빼도 뒤집히나?)" testid="panel-concentration">
          {r.concentration ? (
            <Table size="small" pagination={false} rowKey={(x) => `${x.axis}${x.k}`} dataSource={[
              ...r.concentration.by_code.map((x) => ({ ...x, axis: '종목' })), ...r.concentration.by_date.map((x) => ({ ...x, axis: '날짜' })),
            ]} columns={[
              { title: '뺀 것', render: (_, x) => <span>{x.axis} 상위 {x.k}<br /><Typography.Text type="secondary" style={{ fontSize: 12 }}>{x.removed.join(', ')}</Typography.Text></span> },
              { title: '나머지 순손익', dataIndex: 'net_pnl_excluding', render: (v: number) => `${fmtNum(Math.round(v))}원` },
              { title: '부호', dataIndex: 'sign_flipped', render: (f: boolean) => (f ? <Tag color="error">뒤집힘</Tag> : <Tag color="success">유지</Tag>) },
            ]} />
          ) : none('없음')}
        </Panel>
      </Col>
    </Row>
  )
}
