// 일봉 최신화 패널 (§5.4): 모드 3개(밀린 종목만 / 전체 겹쳐받기 / 종목 지정+검색 다중 선택), 대상 수, 정책 버튼,
// "16시 전에는 어제까지가 최신" 안내.
import { Alert, Card, Radio, Space } from 'antd'
import { useState } from 'react'
import { collectDaily, useHub } from '@/api/hub'
import type { StaleData } from '@/types/data'
import { CodesSelect } from './CodesSelect'
import { PolicyButton } from './PolicyButton'

type Mode = 'stale' | 'all' | 'codes'

export function CollectDailyPanel() {
  const [mode, setMode] = useState<Mode>('stale')
  const [codes, setCodes] = useState<string[]>([])
  const stale = useHub<StaleData>('/api/data/stale?dataset=daily', { enabled: mode === 'codes' })
  const needCodes = mode === 'codes' && codes.length === 0

  return (
    <Card size="small" title="일봉 최신화" data-testid="collect-daily">
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Alert type="info" showIcon message="16시 전에는 어제까지가 최신입니다 — 오늘 일봉은 장 마감(15:30) 뒤, 야간 갱신(16:00~)에 생깁니다." />
        <Radio.Group value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
          <Radio.Button value="stale">밀린 종목만</Radio.Button>
          <Radio.Button value="all">전체 겹쳐받기</Radio.Button>
          <Radio.Button value="codes">종목 지정</Radio.Button>
        </Radio.Group>
        {mode === 'codes' && (
          <CodesSelect value={codes} onChange={setCodes} options={stale.data?.rows.map((r) => ({ code: r.code, name: r.name }))} />
        )}
        <PolicyButton
          kind="collect_daily"
          mode={mode}
          codes={mode === 'codes' ? codes : undefined}
          disabled={needCodes}
          disabledReason="종목을 1개 이상 고르세요"
          labelNow="일봉 받기"
          submit={(w) => collectDaily({ mode, ...(mode === 'codes' ? { codes } : {}), ...w })}
        />
      </Space>
    </Card>
  )
}
