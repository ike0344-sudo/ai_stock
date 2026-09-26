// 숫자 칸 — 그냥 숫자이거나 **변수**(최적화 때 값을 바꿔 가며 돌릴 이름표)다. 설계서 §5.4 "숫자 칸 '변수로'".
import { Button, InputNumber, Space, Tag, Tooltip } from 'antd'
import { isParam, type Num } from '@/types/studio'
import { useParamsApi } from './ParamsContext'

interface Props {
  value: Num | null | undefined
  onChange: (v: Num | null) => void
  hint: string // 변수 이름의 밑그림 (예: n, stop_loss)
  min?: number
  max?: number
  step?: number
  disabled?: boolean
  width?: number
  suffix?: string
  'data-testid'?: string
}

export function NumField({ value, onChange, hint, min, max, step, disabled, width = 96, suffix, ...rest }: Props) {
  const api = useParamsApi()
  if (isParam(value)) {
    const def = api?.params[value.param]?.default
    return (
      <Space size={4} data-testid={rest['data-testid'] ? `${rest['data-testid']}-param` : undefined}>
        <Tooltip title={def !== undefined ? `변수 — 기본값 ${def}` : '변수'}>
          <Tag color="purple" style={{ marginInlineEnd: 0 }}>[{value.param}]</Tag>
        </Tooltip>
        <Button size="small" type="link" disabled={disabled || !api} onClick={() => api && onChange(api.fixParam(value.param))}>고정값으로</Button>
      </Space>
    )
  }
  return (
    <Space size={2}>
      <InputNumber
        data-testid={rest['data-testid']}
        size="small" style={{ width }} min={min} max={max} step={step} disabled={disabled} suffix={suffix}
        value={value ?? null}
        onChange={(v) => onChange(v === null ? null : Number(v))}
      />
      {api && value !== null && value !== undefined && (
        <Button size="small" type="link" disabled={disabled} onClick={() => onChange(api.makeParam(Number(value), hint))}>변수로</Button>
      )}
    </Space>
  )
}
