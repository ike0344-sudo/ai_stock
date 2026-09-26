// 진입·청산 조건 그룹 편집기 (§5.4): AND/OR · 행 추가·삭제·복제 · 하위 그룹 1단계. 서버 오류 경로가 가리키는 행은 빨갛게 강조한다(§8.4 #8).
import { CopyOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Card, Radio, Select, Space, Tooltip, Typography } from 'antd'
import { addItem, duplicateItem, errorsUnder, groupDepth, MAX_DEPTH, newCondition, newGroup, removeItem, replaceItem } from '@/lib/spec'
import type { Condition, Group, IndicatorCatalog, Mode, Op, ValidationIssue } from '@/types/studio'
import { isGroup } from '@/types/studio'
import { OperandEditor } from './OperandEditor'

export const OP_KO: Record<Op, string> = {
  gt: '초과 (>)', gte: '이상 (≥)', lt: '미만 (<)', lte: '이하 (≤)', cross_above: '위로 돌파 (↗)', cross_below: '아래로 돌파 (↘)',
}

interface Props {
  group: Group
  onChange: (g: Group) => void
  cat: IndicatorCatalog
  mode: Mode
  /** 서버 오류 경로의 접두사 — 예: strategy.entry */
  path: string
  errors: ValidationIssue[]
  allowMarket?: boolean
  title: string
  /** 최상위 그룹이 비면 안 되는지(진입) — 비었을 때 안내 */
  required?: boolean
  nested?: boolean
}

export function ConditionGroupEditor({ group, onChange, cat, mode, path, errors, allowMarket = false, title, required = false, nested = false }: Props) {
  const canNest = groupDepth(group) < MAX_DEPTH && !nested
  const tid = `group-${path}`
  return (
    <div data-testid={tid} style={nested ? { border: '1px dashed #d9d9d9', borderRadius: 6, padding: 8 } : undefined}>
      <Space wrap style={{ marginBottom: 8 }}>
        <Typography.Text strong>{title}</Typography.Text>
        <Radio.Group size="small" value={group.logic} onChange={(e) => onChange({ ...group, logic: e.target.value as Group['logic'] })} data-testid={`${tid}-logic`}>
          <Radio.Button value="all">모두 만족(AND)</Radio.Button>
          <Radio.Button value="any">하나라도 만족(OR)</Radio.Button>
        </Radio.Group>
        <Button size="small" icon={<PlusOutlined />} onClick={() => onChange(addItem(group, newCondition()))} data-testid={`${tid}-add`}>조건 추가</Button>
        {canNest && <Button size="small" icon={<PlusOutlined />} onClick={() => onChange(addItem(group, newGroup()))} data-testid={`${tid}-add-group`}>하위 그룹</Button>}
      </Space>
      {group.items.length === 0 && (
        <Typography.Text type={required ? 'danger' : 'secondary'} data-testid={`${tid}-empty`}>
          {required ? '조건이 하나도 없습니다 — 최소 1개가 필요해요' : '조건 없음'}
        </Typography.Text>
      )}
      <Space direction="vertical" size={6} style={{ width: '100%' }}>
        {group.items.map((item, i) => {
          const errs = errorsUnder(errors, path, i)
          const rowPath = `${path}.items.${i}`
          const actions = (
            <Space size={2}>
              <Tooltip title="복제"><Button size="small" type="text" icon={<CopyOutlined />} onClick={() => onChange(duplicateItem(group, i))} aria-label="조건 복제" /></Tooltip>
              <Tooltip title="삭제"><Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => onChange(removeItem(group, i))} aria-label="조건 삭제" /></Tooltip>
            </Space>
          )
          return (
            <Card key={i} size="small" data-testid={`row-${rowPath}`} data-error={errs.length > 0}
              style={{ borderColor: errs.length ? '#f5222d' : undefined, boxShadow: errs.length ? '0 0 0 1px #f5222d33' : undefined }}
              styles={{ body: { padding: 8 } }}>
              {isGroup(item) ? (
                <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
                  <div style={{ flex: 1 }}>
                    <ConditionGroupEditor group={item} nested title="하위 그룹" path={rowPath} errors={errors} cat={cat} mode={mode} allowMarket={allowMarket}
                      onChange={(g) => onChange(replaceItem(group, i, g))} />
                  </div>
                  {actions}
                </Space>
              ) : (
                <ConditionRow cond={item} cat={cat} mode={mode} allowMarket={allowMarket} actions={actions} onChange={(c) => onChange(replaceItem(group, i, c))} />
              )}
              {errs.map((m) => <div key={m}><Typography.Text type="danger" style={{ fontSize: 12 }}>⚠ {m}</Typography.Text></div>)}
            </Card>
          )
        })}
      </Space>
    </div>
  )
}

function ConditionRow({ cond, onChange, cat, mode, allowMarket, actions }: {
  cond: Condition; onChange: (c: Condition) => void; cat: IndicatorCatalog; mode: Mode; allowMarket: boolean; actions: React.ReactNode
}) {
  return (
    <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
      <Space wrap size={6}>
        <OperandEditor op={cond.left} side="left" cat={cat} mode={mode} allowMarket={allowMarket} onChange={(left) => onChange({ ...cond, left })} />
        <Select<Op> size="small" style={{ width: 128 }} value={cond.op} data-testid="op-select"
          options={cat.ops.map((o) => ({ value: o, label: OP_KO[o] }))} onChange={(op) => onChange({ ...cond, op })} />
        <OperandEditor op={cond.right} side="right" cat={cat} mode={mode} allowMarket={allowMarket} onChange={(right) => onChange({ ...cond, right })} />
      </Space>
      {actions}
    </Space>
  )
}
