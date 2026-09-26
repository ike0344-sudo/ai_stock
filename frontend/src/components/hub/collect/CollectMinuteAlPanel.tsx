// 통합 분봉 패널 (§5.4): 모드 4개 · 모드별 대상 수·예상 소요(추정)·"소피증권 기준선: 갱신됨(다음 재기동부터) / 안 바뀜" ·
// 기준선 갱신 실행 중이면 비활성+사유(policy.blocked) · 20:00 전 "오늘치 잘림" 안내(policy.warnings) · 정책 버튼
import { Card, InputNumber, Radio, Space, Tag, Typography } from 'antd'
import { useState } from 'react'
import { collectMinuteAl, useHub, qs } from '@/api/hub'
import type { PolicyData } from '@/types/data'
import { CodesSelect } from './CodesSelect'
import { PolicyButton } from './PolicyButton'

type Mode = 'sophie_baseline' | 'all_cached' | 'codes' | 'deep_archive'

const MODES: { value: Mode; label: string }[] = [
  { value: 'sophie_baseline', label: '소피증권 기준선 갱신(권장)' },
  { value: 'all_cached', label: '보유 전체' },
  { value: 'codes', label: '종목 지정' },
  { value: 'deep_archive', label: '과거 깊게(보관소만)' },
]
const MAX_CODES: Partial<Record<Mode, number>> = { codes: 500, deep_archive: 300 }

export function CollectMinuteAlPanel() {
  const [mode, setMode] = useState<Mode>('sophie_baseline')
  const [codes, setCodes] = useState<string[]>([])
  const [days, setDays] = useState(60)
  const needCodes = (mode === 'codes' || mode === 'deep_archive') && codes.length === 0
  const codesArg = mode === 'codes' || mode === 'deep_archive' ? codes : undefined
  // 모드별 "소피증권 기준선" 표시는 정책 응답의 baseline_effect — 같은 쿼리(캐시 공유)를 읽는다
  const pol = useHub<PolicyData>(`/api/data/policy${qs({ kind: 'collect_minute_al', mode, codes: codesArg?.join(',') })}`, { refetchMs: 30_000 })

  return (
    <Card size="small" title="통합 분봉 갱신" data-testid="collect-minute-al">
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Radio.Group value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
          {MODES.map((m) => <Radio.Button key={m.value} value={m.value}>{m.label}</Radio.Button>)}
        </Radio.Group>
        {pol.data && (
          <Space data-testid="baseline-effect">
            소피증권 기준선:
            {pol.data.baseline_effect === 'updated' && <Tag color="orange">갱신됨(다음 재기동부터 적용)</Tag>}
            {pol.data.baseline_effect === 'unchanged' && <Tag>안 바뀜</Tag>}
            {pol.data.baseline_effect === null && <Typography.Text type="secondary">—</Typography.Text>}
          </Space>
        )}
        {(mode === 'codes' || mode === 'deep_archive') && <CodesSelect value={codes} onChange={setCodes} max={MAX_CODES[mode]} />}
        {mode === 'deep_archive' && <span>과거 일수 <InputNumber min={20} max={250} value={days} onChange={(v) => setDays(v ?? 60)} /> (20~250) · 캐시는 건드리지 않고 보관소에만 병합</span>}
        <PolicyButton
          kind="collect_minute_al"
          mode={mode}
          codes={codesArg}
          disabled={needCodes}
          disabledReason="종목을 1개 이상 고르세요"
          labelNow="분봉 갱신"
          submit={(w) => collectMinuteAl({ mode, ...(codesArg ? { codes: codesArg } : {}), ...(mode === 'deep_archive' ? { days } : {}), ...w })}
        />
      </Space>
    </Card>
  )
}
