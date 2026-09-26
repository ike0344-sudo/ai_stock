// 결과 화면 (§5.4 ResultPage) — 헤더 · 경고 · 지표 카드 · 기존 CLI 줄 · 차트 · 거래 표 · 견고성 · 사전 판정 기준.
// 정보는 접지 않는다: 위에서 아래로 전부 펼쳐 둔다. 값이 없는 칸은 "없음"으로 말한다.
import { Alert, Space, Spin, Typography } from 'antd'
import { useParams } from 'react-router-dom'
import { useEquity, useFolds, useRunDetail, useTrades } from '@/api/studio'
import { CriteriaTable, LegacyLine, MetricCards, WarningBadges } from '@/components/results/MetricCards'
import { DistributionPanels, DrawdownPanel, EquityPanel, ExitReasonPanel, GroupPanels, PeriodPanels, RobustnessPanels } from '@/components/results/ResultCharts'
import { ResultHeader } from '@/components/results/ResultHeader'
import { TradesTable } from '@/components/results/TradesTable'
import { IntradayCoverage, MinuteSourceBanner, TickRefineCard, TickSample } from '@/components/results/IntradayResult'
import { HoldoutSection, OptimizeSection, WalkforwardSection } from '@/components/results/ValidationPanels'
import { segmentBands } from '@/lib/validation'
import type { IntradaySummary, OptimizeSummary, TickRefineSummary, TickSummary } from '@/types/studio'

export function ResultPage() {
  const { runId } = useParams()
  const detail = useRunDetail(runId)
  const equity = useEquity(runId)
  const trades = useTrades(runId)
  const kind = detail.data?.meta.kind ?? 'backtest'
  const folds = useFolds(runId, kind === 'walkforward')

  if (detail.isPending) return <Spin data-testid="result-loading" />
  if (detail.isError) {
    return <Alert type="error" showIcon data-testid="result-error" message={detail.error.status === 404 ? '이 실행 결과를 찾을 수 없습니다' : `결과를 못 불러옴: ${detail.error.message}`}
      description={detail.error.status === 404 ? '삭제됐거나 번호가 틀렸습니다. 실행 기록에서 골라 주세요.' : undefined} />
  }
  const d = detail.data
  const codeName = new Map((trades.data ?? []).map((t) => [t.code, t.name ?? t.code]))
  const analysis = d.analysis
  const warnings = [...new Set([...(d.warnings ?? []), ...(d.summary.warnings ?? [])])]

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }} data-testid="result-page">
      <MinuteSourceBanner d={d} />
      <ResultHeader d={d} />
      {d.narration && <Alert type="info" message="이 조건을 말로 풀면" description={<span style={{ whiteSpace: 'pre-line' }} data-testid="result-narration">{d.narration}</span>} />}
      <WarningBadges warnings={warnings} />
      {d.summary.intraday ? <IntradayCoverage s={d.summary.intraday as IntradaySummary} name={(c) => codeName.get(c) ?? c} /> : null}
      {d.summary.tick ? <TickSample t={d.summary.tick as TickSummary} /> : null}
      {d.summary.tick_refine ? <TickRefineCard r={d.summary.tick_refine as TickRefineSummary} /> : null}
      {kind === 'optimize' && d.summary.optimize ? <OptimizeSection d={d} /> : null}
      {kind === 'walkforward' && d.summary.walkforward ? <WalkforwardSection d={d} folds={folds.data} /> : null}
      {kind === 'holdout_check' && d.summary.holdout ? <HoldoutSection d={d} /> : null}
      <LegacyLine legacy={d.summary.legacy_metrics} />
      <MetricCards metrics={d.summary.metrics} />
      {kind === 'optimize' ? null : <CriteriaTable rows={d.summary.criteria} />}

      {equity.isError ? <Alert type="error" showIcon message={`곡선을 못 불러옴: ${equity.error.message}`} /> : equity.data ? (
        <>
          <EquityPanel equity={equity.data} bands={kind === 'optimize' && d.summary.optimize ? segmentBands((d.summary.optimize as OptimizeSummary).segments) : undefined} />
          <DrawdownPanel equity={equity.data} />
        </>
      ) : <Spin />}

      {analysis.error ? <Alert type="error" showIcon message={`결과 분해 실패: ${analysis.error}`} data-testid="analysis-error" /> : (
        <>
          <PeriodPanels analysis={analysis} />
          <DistributionPanels analysis={analysis} trades={trades.data ?? []} />
          <GroupPanels analysis={analysis} />
          <ExitReasonPanel analysis={analysis} />
        </>
      )}

      <RobustnessPanels r={d.summary.robustness} />

      <div>
        <Typography.Title level={5}>거래 내역</Typography.Title>
        {trades.isError ? <Alert type="error" showIcon message={`거래를 못 불러옴: ${trades.error.message}`} />
          : trades.data ? <TradesTable trades={trades.data} spec={d.spec} params={d.meta.params ?? {}} /> : <Spin />}
      </div>
    </Space>
  )
}
