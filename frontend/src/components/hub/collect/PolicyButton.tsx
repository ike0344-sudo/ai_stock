// 정책 버튼 — `/api/data/policy` 판정에 따라 "지금 실행 / 확인 후 실행 / 20:10 예약" 으로 바뀐다 (설계서 §5.4 수집 탭).
//   allow_now      → [지금 실행]
//   needs_confirm  → [확인 후 실행](확인창에 이유·경고) + [예약]
//   schedule_only  → [HH:MM 예약]  ("지금" 버튼 자체가 없다 — 서버도 422 SOPHIE_MARKET_HOURS 로 막는다)
//   blocked        → 비활성 + 사유(POST 를 보내 보기 전에 안다)
//   API 없음       → 비활성 + "허브 API 준비 중"
import { useQueryClient } from '@tanstack/react-query'
import { App, Button, DatePicker, Popconfirm, Space, Typography } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useState } from 'react'
import { isUnavailable, qs, useHub } from '@/api/hub'
import { ApiError } from '@/api/client'
import { fmtDuration, fmtNum } from '@/lib/format'
import type { CollectKind, CollectWhen, PolicyData } from '@/types/data'

interface Props {
  kind: CollectKind
  mode?: string | null
  codes?: string[]
  /** 실제 제출 — when·scheduled_at·confirm 을 받아 POST. 성공하면 응답을 돌려준다 */
  submit: (w: CollectWhen) => Promise<unknown>
  labelNow?: string
  disabled?: boolean
  disabledReason?: string
}

export function PolicyButton({ kind, mode = null, codes, submit, labelNow = '지금 실행', disabled, disabledReason }: Props) {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const path = `/api/data/policy${qs({ kind, mode, codes: codes?.length ? codes.join(',') : null })}`
  const q = useHub<PolicyData>(path, { refetchMs: 30_000 })
  const [busy, setBusy] = useState(false)
  const [when, setWhen] = useState<Dayjs | null>(null)

  if (q.isPending) return <Button loading disabled>정책 확인 중</Button>
  if (q.isError) {
    return (
      <Space direction="vertical" size={2} data-testid="policy-unavailable">
        <Button disabled>{isUnavailable(q.error) ? '허브 API 준비 중' : '정책을 못 불러옴'}</Button>
        {!isUnavailable(q.error) && <Typography.Text type="danger">{q.error.message}</Typography.Text>}
      </Space>
    )
  }
  const p = q.data
  const suggested = p.suggest_at ? dayjs(p.suggest_at) : null
  const schedAt = when ?? suggested

  const run = async (w: CollectWhen) => {
    setBusy(true)
    try {
      const res = await submit(w)
      if (res && typeof res === 'object' && 'nothing_to_do' in res) message.info('받을 것이 없습니다')
      else message.success(w.when === 'now' ? '작업을 시작했습니다' : `${dayjs(w.scheduled_at).format('MM-DD HH:mm')} 에 예약했습니다`)
      void qc.invalidateQueries({ queryKey: ['jobs'] })
      void qc.invalidateQueries({ queryKey: ['hub'] })
    } catch (e) {
      if (e instanceof ApiError) {
        const at = typeof e.details.suggest_at === 'string' ? ` (제안 ${dayjs(e.details.suggest_at).format('HH:mm')})` : ''
        message.error(`${e.code}: ${e.message}${at}`)
      } else message.error(String(e))
    } finally {
      setBusy(false)
    }
  }
  const scheduled = () => run({ when: 'scheduled', scheduled_at: (schedAt ?? dayjs().add(1, 'hour')).format('YYYY-MM-DDTHH:mm:ss') })

  const off = disabled || !!p.blocked
  const scheduleControl = (primary: boolean) => (
    <Space.Compact>
      <DatePicker showTime={{ format: 'HH:mm' }} format="MM-DD HH:mm" value={schedAt} onChange={setWhen} allowClear={false} disabled={off} />
      <Button type={primary ? 'primary' : 'default'} loading={busy} disabled={off} onClick={scheduled}>
        {schedAt ? `${schedAt.format('HH:mm')} 예약` : '예약'}
      </Button>
    </Space.Compact>
  )

  return (
    <Space direction="vertical" size={4} data-testid="policy-button" data-decision={p.decision}>
      <Space wrap>
        {p.decision === 'allow_now' && (
          <Button type="primary" loading={busy} disabled={off} onClick={() => run({ when: 'now' })}>{labelNow}</Button>
        )}
        {p.decision === 'needs_confirm' && (
          <>
            <Popconfirm
              title="확인 후 실행"
              description={<div style={{ maxWidth: 360 }}>{[p.reason, ...p.warnings].map((t) => <div key={t}>· {t}</div>)}</div>}
              okText="그래도 실행"
              cancelText="취소"
              disabled={off}
              onConfirm={() => run({ when: 'now', confirm: true })}
            >
              <Button type="primary" danger loading={busy} disabled={off}>확인 후 실행</Button>
            </Popconfirm>
            {scheduleControl(false)}
          </>
        )}
        {p.decision === 'schedule_only' && scheduleControl(true)}
      </Space>
      {p.blocked && <Typography.Text type="danger">지금 시작할 수 없음 — {p.blocked.message}</Typography.Text>}
      {disabled && disabledReason && <Typography.Text type="secondary">먼저: {disabledReason}</Typography.Text>}
      <Typography.Text type="secondary">{p.reason}</Typography.Text>
      {(p.n_codes !== null || p.eta_sec !== null) && (
        <Typography.Text type="secondary">
          대상 {fmtNum(p.n_codes)}개{p.eta_sec !== null && <> · 예상 {fmtDuration(p.eta_sec)}(추정{p.estimate_basis ? `: ${p.estimate_basis}` : ''})</>}
        </Typography.Text>
      )}
      {p.warnings.map((w) => <Typography.Text key={w} type="warning">⚠ {w}</Typography.Text>)}
    </Space>
  )
}
