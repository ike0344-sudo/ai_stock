// 종목 지정 — 검색해서 여러 개 고르거나(밀린 종목 목록에서) 6자리 코드를 직접 붙여 넣는다.
// 코드 형식은 서버(^[0-9A-Z]{6}$)와 같은 규칙으로 화면에서도 먼저 거른다. 형식이 틀린 태그는 넣지 않고 알린다.
import { Select, Typography } from 'antd'
import { useState } from 'react'
import { CODE_RE } from '@/lib/format'

export interface CodeOption {
  code: string
  name: string | null
}

interface Props {
  value: string[]
  onChange: (codes: string[]) => void
  options?: CodeOption[]
  max?: number
  placeholder?: string
}

export function CodesSelect({ value, onChange, options = [], max, placeholder = '종목명·코드 검색 또는 6자리 코드 붙여넣기' }: Props) {
  const [bad, setBad] = useState<string[]>([])
  return (
    <>
      <Select
        mode="tags"
        data-testid="codes-select"
        style={{ width: '100%' }}
        value={value}
        placeholder={placeholder}
        tokenSeparators={[',', ' ', '\n']}
        options={options.map((o) => ({ value: o.code, label: `${o.code} ${o.name ?? ''}`.trim() }))}
        filterOption={(input, opt) => (opt?.label as string | undefined)?.toLowerCase().includes(input.toLowerCase()) ?? false}
        onChange={(vals: string[]) => {
          const upper = vals.map((v) => v.trim().toUpperCase())
          const ok = [...new Set(upper.filter((v) => CODE_RE.test(v)))]
          const wrong = upper.filter((v) => v && !CODE_RE.test(v))
          // 경고는 다음 입력에도 남긴다(붙여넣은 목록에서 뭐가 빠졌는지 볼 시간) — 새 오류가 오거나 목록을 비우면 갱신
          if (wrong.length) setBad(wrong)
          else if (ok.length === 0) setBad([])
          onChange(max ? ok.slice(0, max) : ok)
        }}
      />
      {bad.length > 0 && <Typography.Text type="danger" data-testid="codes-bad">형식이 틀려 뺐습니다(6자리 영숫자): {bad.join(', ')}</Typography.Text>}
      {max && value.length >= max && <Typography.Text type="warning"> 최대 {max}개까지</Typography.Text>}
    </>
  )
}
