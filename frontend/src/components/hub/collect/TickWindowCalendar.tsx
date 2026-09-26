// 조회창 달력 (§5.4): 수집됨 초록 · 일부 주황 · 미수집 빨강 · (오늘 = 회색) · 소실 임박(빠진 게 있고 남은 거래일 ≤3) 굵은 테두리
import { Space, Tag, Tooltip, Typography } from 'antd'
import { useDark } from '@/lib/theme'
import type { TickDate, TickDateStatus } from '@/types/data'

export const TICK_COLOR: Record<TickDateStatus, string> = { collected: '#52c41a', partial: '#fa8c16', missing: '#f5222d', pending: '#bfbfbf' }
const LABEL: Record<TickDateStatus, string> = { collected: '수집됨', partial: '일부', missing: '미수집', pending: '오늘(장 마감 전)' }
export const IMMINENT_DAYS = 3

export const isImminent = (d: TickDate): boolean => d.missing_count > 0 && d.status !== 'pending' && d.days_left <= IMMINENT_DAYS

export function TickWindowCalendar({ dates }: { dates: TickDate[] }) {
  const { dark } = useDark()
  const edge = dark ? '#fff' : '#000' // 소실 임박 테두리 — 배경과 반대색
  return (
    <Space direction="vertical" size={4} data-testid="tick-calendar">
      <Space wrap size={6}>
        {dates.map((d) => (
          <Tooltip key={d.date} title={`${d.date} · ${LABEL[d.status]} · ${d.collected_codes}/${d.expected_codes}종목${d.missing_count ? ` · 빠진 ${d.missing_count}` : ''} · 조회창에서 ${d.days_left}거래일 뒤 사라짐`}>
            <div
              data-testid={`tick-${d.date}`}
              data-status={d.status}
              data-imminent={isImminent(d)}
              style={{
                width: 58, padding: '4px 0', textAlign: 'center', fontSize: 12, color: '#fff', borderRadius: 4, background: TICK_COLOR[d.status],
                border: isImminent(d) ? `3px solid ${edge}` : '3px solid transparent', boxSizing: 'border-box',
              }}
            >
              {d.date.slice(5)}
              <br />
              {d.collected_codes}/{d.expected_codes}
            </div>
          </Tooltip>
        ))}
      </Space>
      <Space wrap>
        {(Object.keys(LABEL) as TickDateStatus[]).map((s) => <Tag key={s} color={TICK_COLOR[s]}>{LABEL[s]}</Tag>)}
        <Tag style={{ border: `3px solid ${edge}`, background: 'transparent', color: 'inherit' }}>소실 임박(≤{IMMINENT_DAYS}거래일)</Tag>
        <Typography.Text type="secondary">오래된 날짜부터 — 왼쪽이 먼저 조회창 밖으로 밀려납니다</Typography.Text>
      </Space>
    </Space>
  )
}
