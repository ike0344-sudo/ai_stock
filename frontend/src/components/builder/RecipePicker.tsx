// 조건검색 레시피 (§5.4 "레시피"): 분류별로 펼쳐 놓고, 불러오면 진입·청산 조건 행으로 풀린다.
// 서버가 아직 못 쓰는 재료(시간 단위·새 지표 등)가 든 레시피는 숨기지 않고 이유와 함께 비활성으로 보여 준다 — 서버가 지원하면 저절로 켜진다.
import { BookOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Input, Modal, Space, Spin, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { useRecipes } from '@/api/studio'
import { recipeFitsMode } from '@/lib/spec'
import { MODE_LABEL } from '@/lib/labels'
import type { Recipe, SpecJson } from '@/types/studio'

export function RecipePicker({ spec, onApply }: { spec: SpecJson; onApply: (r: Recipe) => void }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const recipes = useRecipes()
  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const m = new Map<string, Recipe[]>()
    for (const r of recipes.data ?? []) {
      if (needle && ![r.title, r.description, r.category].some((s) => s.toLowerCase().includes(needle))) continue
      m.set(r.category, [...(m.get(r.category) ?? []), r])
    }
    return [...m.entries()]
  }, [recipes.data, q])

  return (
    <>
      <Button icon={<BookOutlined />} onClick={() => setOpen(true)} data-testid="recipe-open">레시피 불러오기</Button>
      <Modal open={open} onCancel={() => setOpen(false)} footer={null} width={860} title="조건검색 레시피 — 골라서 불러오면 진입·청산 조건이 이 레시피로 바뀝니다" destroyOnHidden data-testid="recipe-modal">
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Input.Search allowClear placeholder="레시피·설명·분류 검색" onChange={(e) => setQ(e.target.value)} style={{ width: 320 }} data-testid="recipe-search" />
          {recipes.isPending && <Spin />}
          {recipes.isError && <Alert type="error" showIcon message={`레시피를 못 불러옴: ${recipes.error.message}`} />}
          {recipes.data && recipes.data.length === 0 && <Typography.Text type="secondary" data-testid="recipe-empty">레시피가 하나도 없습니다</Typography.Text>}
          {groups.map(([cat, list]) => (
            <div key={cat} data-testid={`recipe-cat-${cat}`}>
              <Typography.Title level={5} style={{ margin: '4px 0' }}>{cat}</Typography.Title>
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {list.map((r) => {
                  const fits = recipeFitsMode(r, spec)
                  return (
                    <Card key={r.id} size="small" data-testid={`recipe-${r.id}`} data-available={r.available} style={{ opacity: r.available ? 1 : 0.6 }}>
                      <Space style={{ width: '100%', justifyContent: 'space-between' }} align="start">
                        <Space direction="vertical" size={2}>
                          <Space wrap><Typography.Text strong>{r.title}</Typography.Text>{r.modes.map((m) => <Tag key={m}>{MODE_LABEL[m]}</Tag>)}</Space>
                          <Typography.Text type="secondary">{r.description}</Typography.Text>
                          {!r.available && <Typography.Text type="warning" data-testid={`recipe-${r.id}-reason`}>{r.unavailable_reason}</Typography.Text>}
                          {r.available && !fits && <Typography.Text type="secondary" style={{ fontSize: 12 }}>불러오면 {MODE_LABEL[r.modes[0]]} 모드로 바뀝니다(기간은 그 모드 데이터 끝에서 다시 잡음)</Typography.Text>}
                        </Space>
                        <Button type="primary" size="small" disabled={!r.available} data-testid={`recipe-${r.id}-apply`} onClick={() => { onApply(r); setOpen(false) }}>불러오기</Button>
                      </Space>
                    </Card>
                  )
                })}
              </Space>
            </div>
          ))}
        </Space>
      </Modal>
    </>
  )
}
