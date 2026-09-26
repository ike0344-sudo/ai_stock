// 데이터셋 카드 11개 (§5.4 개요): 이름·기준·판정 색·종목 수·최신일(기준/기대)·밀린 수·소피증권 유니버스 밀린 수·
// 마지막 쓰기·잠금 상태·보관 규칙 배지. **정보를 접지 않는다** — 값이 있는 칸은 전부 그대로 보여준다.
import { Badge, Card, Col, Descriptions, Row, Tag, Typography } from 'antd'
import type { ReactNode } from 'react'
import { basisLabel, DASH, DATASET_BASIS_COLOR, fmtNum, fmtPct, fmtTs, retentionBadge, VERDICT_COLOR, VERDICT_LABEL } from '@/lib/format'
import type { DailyCatchup, DatasetStatus, TickWindowData } from '@/types/data'

type Row_ = [string, ReactNode]

/** 규칙별 칸 — 키가 있는 것만(계약의 `?` 칸). 값이 null 이면 "—". */
export function datasetRows(d: DatasetStatus): Row_[] {
  const r: Row_[] = []
  if (d.n_codes !== undefined) r.push(['종목 수', fmtNum(d.n_codes)])
  if (d.reference_date !== undefined || d.expected_date !== undefined) {
    r.push(['최신일(기준 / 기대)', `${d.reference_date ?? DASH} / ${d.expected_date ?? DASH}`])
  }
  if (d.stale_count !== undefined) {
    r.push(['밀린 종목', `${fmtNum(d.stale_count)}${d.stale_inactive_count ? ` (거래중단 ${fmtNum(d.stale_inactive_count)})` : ''}`])
  }
  if (d.sophie_stale_count !== undefined) {
    r.push(['소피증권 유니버스 밀림', <Typography.Text key="s" type={d.sophie_stale_count > 0 ? 'danger' : undefined}>{fmtNum(d.sophie_stale_count)}</Typography.Text>])
  }
  if (d.last_date_mode !== undefined) r.push(['최빈 최신일', `${d.last_date_mode} (${fmtNum(d.age_days)}일 전)`])
  if (d.behind_share !== undefined) r.push(['5일↑ 뒤처진 파일', fmtPct(d.behind_share)])
  if (d.codes_cache !== undefined) r.push(['캐시 / 보관소 종목', `${fmtNum(d.codes_cache)} / ${fmtNum(d.codes_archive)}`])
  if (d.missing_vs_cache !== undefined) r.push(['보관 누락(캐시 대비)', fmtNum(d.missing_vs_cache)])
  if (d.window_missing !== undefined) r.push(['조회창 빠진 쌍', fmtNum(d.window_missing)])
  if (d.min_days_left !== undefined) r.push(['가장 먼저 사라질 날짜', d.min_days_left === null ? DASH : `${d.min_days_left}거래일 남음`])
  if (d.in_sync !== undefined) r.push(['data / dist 동기', d.in_sync ? '같음' : `다름 (${(d.diff_files ?? []).join(', ') || DASH})`])
  if (d.data_updated !== undefined) r.push(['data / dist 수정', `${fmtTs(d.data_updated)} / ${fmtTs(d.dist_updated)}`])
  if (d.backup_date !== undefined) r.push(['백업 기준일', `${d.backup_date} (${(d.found ?? []).length ? '있음' : '없음'})`])
  if (d.updated) r.push(['파일 수정', fmtTs(d.updated)])
  return r
}

interface Props {
  datasets: DatasetStatus[]
  catchup: DailyCatchup | null
  tick: { loading: boolean; unavailable: boolean; data?: TickWindowData }
}

export function DatasetCards({ datasets, catchup, tick }: Props) {
  return (
    <Row gutter={[16, 16]} data-testid="dataset-cards">
      {datasets.map((d) => {
        const lw = d.last_write
        const ret = retentionBadge(d.retention)
        return (
          <Col key={d.id} xs={24} md={12} xl={8} id={`ds-${d.id}`}>
            <Card
              size="small"
              data-testid={`card-${d.id}`}
              data-verdict={d.verdict}
              style={{ borderLeft: `4px solid ${VERDICT_COLOR[d.verdict]}`, height: '100%' }}
              title={<><Badge color={VERDICT_COLOR[d.verdict]} /> {d.label} <Tag color={DATASET_BASIS_COLOR[d.basis] ?? 'default'}>{basisLabel(d.basis)}</Tag></>}
              extra={<Tag color={VERDICT_COLOR[d.verdict]}>{VERDICT_LABEL[d.verdict]}</Tag>}
            >
              <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>{d.reason}</Typography.Paragraph>
              <Descriptions size="small" column={1} colon={false} items={[
                ...datasetRows(d).map(([label, children]) => ({ label, children })),
                { label: '마지막 쓰기', children: lw ? `${lw.source} · ${lw.writer ?? DASH} · ${fmtTs(lw.ts)} · ${lw.ok === null ? DASH : lw.ok ? '성공' : '실패'}` : DASH },
                { label: '잠금', children: d.lock ? `${d.lock.resource} — ${d.lock.held ? '사용 중' : '비어 있음'}` : '없음' },
                { label: '보관 규칙', children: <Tag color={ret.color}>{ret.text}</Tag> },
              ]} />
              {d.id === 'minute_al' && (
                <Typography.Paragraph type="warning" style={{ marginTop: 8, marginBottom: 0 }}>
                  소피증권 기준선용 20거래일 창 — <strong>갱신 때 덮어씀</strong>. 이력은 <a href="#ds-minute_al_archive">통합 1분봉 보관소</a> 카드로.
                </Typography.Paragraph>
              )}
              {d.id === 'tick_al' && <TickExtra tick={tick} />}
              {d.id === 'daily' && <CatchupExtra catchup={catchup} />}
            </Card>
          </Col>
        )
      })}
    </Row>
  )
}

function TickExtra({ tick }: { tick: Props['tick'] }) {
  if (tick.loading) return null
  if (tick.unavailable || !tick.data) return <Typography.Text type="secondary" data-testid="tick-extra-unavailable">자동 수집 상태: 허브 API 준비 중</Typography.Text>
  const a = tick.data.auto
  const soonest = tick.data.dates.find((x) => x.missing_count > 0 && x.status !== 'pending')
  return (
    <div style={{ marginTop: 8 }} data-testid="tick-extra">
      <div>가장 먼저 사라질 날짜: {soonest ? `${soonest.date} (${soonest.days_left}거래일 남음)` : '없음'}</div>
      <div>자동 수집: <Tag color={a.enabled ? 'green' : 'default'}>{a.enabled ? '켜짐' : '꺼짐'}</Tag> 다음 실행 {fmtTs(a.next_run)}</div>
    </div>
  )
}

function CatchupExtra({ catchup }: { catchup: DailyCatchup | null }) {
  return (
    <div style={{ marginTop: 8 }} data-testid="catchup-extra">
      {catchup === null ? (
        <Typography.Text type="secondary">아침 따라잡기: 오늘은 돌지 않음</Typography.Text>
      ) : (
        <Typography.Text>
          아침 따라잡기({catchup.date}): 받은 {fmtNum(catchup.received)} · 못 받은 {fmtNum(catchup.remaining)}
          {catchup.sophie_remaining > 0 && <Typography.Text type="danger"> (소피증권 영향 {catchup.sophie_remaining})</Typography.Text>}
        </Typography.Text>
      )}
    </div>
  )
}

