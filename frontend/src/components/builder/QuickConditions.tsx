// 자주 쓰는 조건 바로 넣기 — 누르면 진입 조건 행 하나가 채워져 들어간다(값은 고쳐 쓴다). 조건 고르기가 낯선 첫 사용을 돕는다.
import { ThunderboltOutlined } from '@ant-design/icons'
import { Button, Space, Tooltip, Typography } from 'antd'
import { quickConditionsFor } from '@/lib/conditionFind'
import type { Condition, IndicatorCatalog, Mode } from '@/types/studio'

export function QuickConditions({ cat, mode, barMinutes, onAdd }: { cat: IndicatorCatalog; mode: Mode; barMinutes: number; onAdd: (c: Condition) => void }) {
  const list = quickConditionsFor(cat, mode)
  const hasTf = !!cat.capabilities?.timeframes && (mode === 'intraday' || mode === 'tick')
  if (!list.length) return null
  return (
    <Space wrap size={[6, 6]} data-testid="quick-conditions" style={{ marginBottom: 8 }}>
      <Typography.Text type="secondary"><ThunderboltOutlined /> 자주 쓰는 조건 넣기</Typography.Text>
      {list.map((q) => (
        <Tooltip key={q.key} title={q.hint}>
          <Button size="small" onClick={() => onAdd(q.build(barMinutes, hasTf))} data-testid={`quick-${q.key}`}>{q.label}</Button>
        </Tooltip>
      ))}
    </Space>
  )
}
