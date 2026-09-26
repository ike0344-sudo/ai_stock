// 소피증권 탭 (§5.4): 엔진 · 운영 시간 · 분봉 기준선 갱신 · 기준 데이터 · 유니버스 일봉 · 재기동 기록 · 연계 계약 요약
import { Alert, Card, Col, Descriptions, Row, Tag, Typography } from 'antd'
import { DASH, fmtNum, fmtTs } from '@/lib/format'
import type { SophieData } from '@/types/data'

export function SophiePanel({ d }: { d: SophieData }) {
  const e = d.engine
  const r = d.restart
  return (
    <Row gutter={[16, 16]} data-testid="sophie-panel">
      {e.stale_day && (
        <Col span={24}>
          <Alert data-testid="stale-day" type="error" showIcon message="어제 상태로 떠 있음 — 재기동 필요"
            description={`거래일인데 엔진 시작(${fmtTs(e.started_at)})이 오늘 00:00 이전입니다. 전일 종가가 하루 밀려 있습니다.`} />
        </Col>
      )}
      <Col xs={24} xl={12}>
        <Card size="small" title="엔진">
          <Descriptions size="small" column={1} items={[
            { label: '가동', children: e.up ? <Tag color="green">가동 중 (헬스체크 {e.healthz})</Tag> : <Tag color="red">꺼져 있음 ({e.healthz ?? '응답 없음'})</Tag> },
            { label: '프로세스', children: e.pid ?? DASH },
            { label: '시작 시각', children: fmtTs(e.started_at, true) },
          ]} />
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Card size="small" title="운영 시간">
          <Descriptions size="small" column={1} items={[
            { label: '접속 시작', children: d.hours.connect_from },
            { label: '정규장', children: `${d.hours.open} ~ ${d.hours.close}` },
            { label: '접속 종료', children: d.hours.connect_to },
            { label: '출처', children: d.hours.source },
          ]} />
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Card size="small" title="분봉 기준선 갱신">
          <Descriptions size="small" column={1} items={[
            { label: '실행 중', children: d.minute_refresh.running ? <Tag color="processing">실행 중</Tag> : '아니오' },
            { label: '마지막 시작', children: fmtTs(d.minute_refresh.last_started) },
            { label: '마지막 끝', children: fmtTs(d.minute_refresh.last_finished) },
            { label: '결과', children: d.minute_refresh.last_result ?? DASH },
            { label: '다음 예정(워치독 규칙)', children: d.minute_refresh.next_due },
          ]} />
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Card size="small" title="기준 데이터">
          <Descriptions size="small" column={1} items={[
            { label: 'data 수정', children: fmtTs(d.baseline.data_updated) },
            { label: 'dist 수정', children: fmtTs(d.baseline.dist_updated) },
            { label: '동기', children: d.baseline.in_sync ? <Tag color="green">같음</Tag> : <Tag color="orange">dist 에 반영 안 됨</Tag> },
            { label: '적용', children: d.baseline.applies },
          ]} />
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Card size="small" title="소피증권 유니버스 일봉">
          <Descriptions size="small" column={1} items={[
            { label: '종목 수', children: fmtNum(d.universe_daily.n_codes) },
            { label: '밀린 수', children: <Typography.Text type={d.universe_daily.stale_count > 0 ? 'danger' : undefined}>{fmtNum(d.universe_daily.stale_count)}</Typography.Text> },
            { label: '거래중단 추정', children: fmtNum(d.universe_daily.stale_inactive_count) },
            { label: '상세', children: <a href="#/hub/quality">품질 탭에서 보기</a> },
          ]} />
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Card size="small" title="재기동 기록">
          <Descriptions size="small" column={1} items={[
            { label: '마지막 자정 재기동', children: r.last_midnight ? `${fmtTs(r.last_midnight)} (${r.days_since}일 전)` : DASH },
            { label: '마지막 재빌드', children: fmtTs(r.last_rebuild) },
          ]} />
        </Card>
      </Col>
      <Col span={24}>
        <Card size="small" title={`연계 계약 요약 (${d.contract.length})`}>
          <ol data-testid="contract" style={{ margin: 0, paddingLeft: 20 }}>{d.contract.map((c) => <li key={c}>{c}</li>)}</ol>
        </Card>
      </Col>
    </Row>
  )
}
