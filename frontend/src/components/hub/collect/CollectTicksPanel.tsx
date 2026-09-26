// 체결 수집 패널 (§5.4): 조회창 달력 · [빠진 것 지금 받기] · 기간 지정 수집 · 자동 수집 줄 · 수동 확인 필요 목록 · 정규장 자동 일시정지 안내
import { useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Card, DatePicker, InputNumber, Radio, Space, Table, Tag, Typography } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useState } from 'react'
import { collectTicks, retryTicks, useHub } from '@/api/hub'
import { fmtNum, fmtTs } from '@/lib/format'
import type { TickGivenUp, TickWindowData } from '@/types/data'
import { CodesSelect } from './CodesSelect'
import { HubGate } from '../HubGate'
import { PolicyButton } from './PolicyButton'
import { TickWindowCalendar } from './TickWindowCalendar'

export function CollectTicksPanel() {
  const q = useHub<TickWindowData>('/api/data/tick-window', { refetchMs: 30_000 })
  return (
    <Card size="small" title="체결 수집" data-testid="collect-ticks">
      <HubGate query={q} path="/api/data/tick-window">{(w) => <TicksBody w={w} />}</HubGate>
    </Card>
  )
}

function TicksBody({ w }: { w: TickWindowData }) {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [universe, setUniverse] = useState<'default' | 'codes'>('default')
  const [codes, setCodes] = useState<string[]>([])
  const [conc, setConc] = useState(4)
  const first = w.dates[0]?.date
  const last = w.dates[w.dates.length - 1]?.date
  const a = w.auto
  const n = a.last_night

  const retry = async (pairs: TickRetryPairs) => {
    try {
      const r = await retryTicks({ pairs })
      message.success(`${r.retried}쌍을 자동 재시도로 되돌렸습니다`)
      void qc.invalidateQueries({ queryKey: ['hub'] })
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Alert type={w.verdict === 'good' ? 'success' : w.verdict === 'warn' ? 'warning' : 'error'} showIcon message={w.reason} description={`${w.universe} · ${w.note}`} />
      <TickWindowCalendar dates={w.dates} />

      <Space wrap data-testid="tick-auto">
        <strong>자동 수집</strong>
        <Tag color={a.enabled ? 'green' : 'default'}>{a.enabled ? '켜짐' : '꺼짐'}</Tag>
        <span>다음 실행 {fmtTs(a.next_run)}</span>
        <span>|</span>
        {n ? (
          <span>
            지난밤({n.night}) 받은 {fmtNum(n.collected_pairs)}쌍 · 남은 {fmtNum(n.remaining_pairs)}쌍 · 미룬 {fmtNum(n.deferred)}쌍 · 시도 {fmtNum(n.attempts)}회
          </span>
        ) : (
          <Typography.Text type="secondary">지난밤 기록 없음</Typography.Text>
        )}
      </Space>

      <Space direction="vertical" size={4}>
        <strong>빠진 것 지금 받기</strong>
        <PolicyButton kind="collect_ticks" mode="catch_up" labelNow="빠진 것 받기" submit={(x) => collectTicks({ mode: 'catch_up', ...x })} />
      </Space>

      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <strong>기간 지정 수집</strong>
        <DatePicker.RangePicker
          value={range}
          onChange={(v) => setRange(v && v[0] && v[1] ? [v[0], v[1]] : null)}
          disabledDate={(d) => !first || !last || d.isBefore(dayjs(first), 'day') || d.isAfter(dayjs(last), 'day')}
        />
        <Space wrap>
          <Radio.Group value={universe} onChange={(e) => setUniverse(e.target.value as 'default' | 'codes')}>
            <Radio.Button value="default">상위 35 합집합(기본)</Radio.Button>
            <Radio.Button value="codes">종목 지정</Radio.Button>
          </Radio.Group>
          <span>동시성 <InputNumber min={1} max={6} value={conc} onChange={(v) => setConc(v ?? 4)} /></span>
        </Space>
        {universe === 'codes' && <CodesSelect value={codes} onChange={setCodes} />}
        <PolicyButton
          kind="collect_ticks"
          mode="range"
          codes={universe === 'codes' ? codes : undefined}
          disabled={!range || (universe === 'codes' && codes.length === 0)}
          disabledReason={!range ? '기간을 고르세요(조회창 안만 가능)' : '종목을 1개 이상 고르세요'}
          labelNow="기간 수집"
          submit={(x) =>
            collectTicks({
              mode: 'range', start: range![0].format('YYYY-MM-DD'), end: range![1].format('YYYY-MM-DD'),
              universe, ...(universe === 'codes' ? { codes } : {}), concurrency: conc, ...x,
            })
          }
        />
        <Typography.Text type="secondary">정규장(09:00~15:30)에는 진행 중이던 체결 수집이 자동으로 일시정지됩니다 — 소피증권 실시간이 REST 한도를 먼저 씁니다.</Typography.Text>
      </Space>

      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        <Space>
          <strong>수동 확인 필요 ({a.given_up.length})</strong>
          <Button size="small" disabled={!a.given_up.length} onClick={() => retry('all')}>전체 다시 시도</Button>
        </Space>
        <Table<TickGivenUp>
          data-testid="given-up"
          size="small"
          rowKey={(r) => `${r.code}|${r.date}`}
          pagination={false}
          dataSource={a.given_up}
          locale={{ emptyText: '자동 재시도를 포기한 쌍이 없습니다' }}
          columns={[
            { title: '종목', render: (_, r) => `${r.code} ${r.name ?? ''}` },
            { title: '날짜', dataIndex: 'date' },
            { title: '시도', dataIndex: 'attempts', render: (v: number) => `${v}회` },
            { title: '남은 거래일', dataIndex: 'days_left', render: (v: number | null) => (v === null ? '창 밖(되살릴 수 없음)' : `${v}일`) },
            { title: '', render: (_, r) => <Button size="small" onClick={() => retry([{ code: r.code, date: r.date }])}>다시 시도</Button> },
          ]}
        />
      </Space>
    </Space>
  )
}

type TickRetryPairs = 'all' | { code: string; date: string }[]
