// 결과 헤더 (§5.4 ResultPage): 이름(편집)·모드·기간·데이터 기준·엔진 버전·git 해시·소요 시간 · [재실행] [조건 복제해서 수정] [비교에 추가] [CSV]
import { CopyOutlined, DownloadOutlined, PlusOutlined, ReloadOutlined, StarFilled, StarOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { App, Button, Input, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { patchRun, tradesCsvUrl } from '@/api/studio'
import { RunModal } from '@/components/builder/RunModal'
import { fmtDate } from '@/lib/format'
import { addToBasket } from '@/lib/compareBasket'
import { KIND_LABEL, MODE_LABEL } from '@/lib/labels'
import type { RunDetail, SpecJson } from '@/types/studio'

export function ResultHeader({ d }: { d: RunDetail }) {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const shownName = d.meta.name ?? d.spec.name
  const kind = d.meta.kind ?? 'backtest'
  const isBacktest = kind === 'backtest'
  const [name, setName] = useState(shownName)
  const [memo, setMemo] = useState(d.meta.memo ?? '')
  const [rerun, setRerun] = useState<SpecJson | null>(null)
  useEffect(() => { setName(shownName); setMemo(d.meta.memo ?? '') }, [shownName, d.meta.memo])

  const save = async (body: { name?: string; memo?: string | null; starred?: boolean }) => {
    try {
      await patchRun(d.run_id, body)
      void qc.invalidateQueries({ queryKey: ['run', d.run_id] })
      void qc.invalidateQueries({ queryKey: ['runs'] })
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }
  const git = d.meta.git?.commit ? `${d.meta.git.commit.slice(0, 7)}${d.meta.git.dirty ? ' (미커밋 변경 있음)' : ''}` : null
  const dataDate = d.meta.data?.daily?.[1]

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }} data-testid="result-header">
      <Space wrap>
        <Button type="text" size="large" data-testid="star-btn" aria-label={d.meta.starred ? '별표 해제' : '별표'}
          icon={d.meta.starred ? <StarFilled style={{ color: '#fadb14' }} /> : <StarOutlined />} onClick={() => save({ starred: !d.meta.starred })} />
        <Input style={{ width: 420, fontSize: 18, fontWeight: 600 }} value={name} maxLength={100} data-testid="run-name"
          onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && name !== shownName && save({ name })} onPressEnter={(e) => e.currentTarget.blur()} />
        <Tag color="blue">{MODE_LABEL[d.spec.mode]}</Tag>
        {!isBacktest && <Tag color="purple" data-testid="kind-tag">{KIND_LABEL[kind] ?? kind}</Tag>}
        {d.meta.compat && <Tag color="purple">호환 모드</Tag>}
        <Tag>{fmtDate(d.spec.period.start)} ~ {fmtDate(d.spec.period.end)}</Tag>
      </Space>
      <Space wrap size={[12, 4]}>
        <Typography.Text type="secondary" data-testid="data-basis">데이터 기준: 일봉 {dataDate ? fmtDate(dataDate) : '—'}(허브 기준일)</Typography.Text>
        <Typography.Text type="secondary">엔진 {d.meta.engine_version}</Typography.Text>
        {git && <Typography.Text type="secondary">git {git}</Typography.Text>}
        <Typography.Text type="secondary">소요 {d.meta.elapsed_sec}초</Typography.Text>
        <Typography.Text type="secondary" copyable={{ text: d.run_id }}>{d.run_id}</Typography.Text>
      </Space>
      <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} placeholder="메모 (이 결과에서 눈여겨볼 점)" value={memo} maxLength={2000} data-testid="run-memo"
        onChange={(e) => setMemo(e.target.value)} onBlur={() => memo !== (d.meta.memo ?? '') && save({ memo: memo || null })} />
      <Space wrap>
        {isBacktest && <Button icon={<ReloadOutlined />} onClick={() => setRerun(structuredClone(d.spec))} data-testid="rerun-btn">재실행</Button>}
        <Button icon={<CopyOutlined />} onClick={() => navigate(`${isBacktest ? '/backtest' : '/optimize'}?from=${d.run_id}`)} data-testid="clone-btn">{isBacktest ? '조건 복제해서 수정' : '조건 복제해서 다시 최적화'}</Button>
        <Button icon={<PlusOutlined />} data-testid="basket-btn"
          onClick={() => (addToBasket(d.run_id) ? message.success('비교에 담았습니다 — 실행 기록·비교 화면에서 확인') : message.warning('비교는 최대 5개까지 담을 수 있습니다'))}>비교에 추가</Button>
        <Button icon={<DownloadOutlined />} href={tradesCsvUrl(d.run_id)} data-testid="csv-btn">거래 CSV</Button>
      </Space>
      <RunModal spec={rerun} onClose={() => setRerun(null)} />
    </Space>
  )
}
