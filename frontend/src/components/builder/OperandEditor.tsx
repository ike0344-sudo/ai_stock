// 조건의 한쪽(피연산자) 편집 — 가격 값 / 지표 / 시장 지수 / 숫자 / 포지션. 지표는 카탈로그(§3.7)가 메뉴·파라미터·모드를 정한다.
// 지표는 분류 나무 + 검색으로 고르고(지원 안 되는 모드면 숨기지 않고 비활성+이유), 분봉 실행에선 시간 단위를 고른다(서버가 알릴 때만).
import { InfoCircleOutlined } from '@ant-design/icons'
import { Popover, Select, Space, Switch, Tag, Tooltip, Typography } from 'antd'
import { indicatorTree, matchesQuery, POS_LABEL, tfLabel, timeframeOptions } from '@/lib/conditionMeta'
import { indOperand, operandKindDefault } from '@/lib/spec'
import type { IndicatorCatalog, IndicatorDef, IndOperand, Mode, Operand, ParamValue } from '@/types/studio'
import { isParam } from '@/types/studio'
import { useConditionCtx } from './ConditionContext'
import { NumField } from './NumField'

export const FIELD_KO: Record<string, string> = { open: '시가', high: '고가', low: '저가', close: '종가', volume: '거래량', value: '거래대금' }
const KIND_KO: Record<Operand['kind'], string> = { field: '가격·거래량', ind: '지표', market: '시장 지수', const: '숫자', pos: '포지션' }
const INDEX_KO = { kospi: '코스피', kosdaq: '코스닥' }
const MARKET_NAME_KO = { close: '종가', sma: '이동평균', change_pct: '등락률(%)' }
const MODE_KO = { daily_single: '일봉', daily_portfolio: '일봉', intraday: '분봉', tick: '틱' } as const

interface Props {
  op: Operand
  onChange: (op: Operand) => void
  cat: IndicatorCatalog
  mode: Mode
  allowMarket: boolean
  /** 청산 조건 편집기에서만 true — 포지션 값은 보유 중에만 있다 */
  allowPos?: boolean
  /** 숫자 칸 단위 표시 — 억 원 지표와 비교하는 상수에 "억" */
  constSuffix?: string
  side: 'left' | 'right'
}

export function OperandEditor({ op, onChange, cat, mode, allowMarket, allowPos = false, constSuffix, side }: Props) {
  const posOk = allowPos && mode !== 'tick' && !!cat.capabilities?.operand_kinds.includes('pos') // 틱 모드는 포지션 조건 청산을 아직 지원하지 않는다(서버가 거부)
  const kinds = (['field', 'ind', 'const', ...(allowMarket ? ['market'] : []), ...(posOk ? ['pos'] : [])] as Operand['kind'][])
  const tid = `operand-${side}`
  const ctx = useConditionCtx()
  const def = op.kind === 'ind' ? cat.indicators.find((d) => d.name === op.name) : undefined
  const tfs = op.kind === 'ind' || op.kind === 'field' ? timeframeOptions(cat.capabilities, def, mode, ctx.barMinutes, ctx.source) : []
  const setTf = (tf: string) => {
    if (op.kind !== 'ind' && op.kind !== 'field') return
    const { tf: _drop, ...rest } = op
    void _drop
    onChange((tf === 'bar' ? rest : { ...rest, tf }) as Operand)
  }

  return (
    <Space size={4} wrap data-testid={tid}>
      <Select<Operand['kind']> size="small" style={{ width: 104 }} value={op.kind} data-testid={`${tid}-kind`}
        options={kinds.map((k) => ({ value: k, label: KIND_KO[k] }))}
        onChange={(k) => onChange(operandKindDefault(k, cat))} />

      {op.kind === 'field' && (
        <Select size="small" style={{ width: 90 }} value={op.name} options={cat.fields.map((f) => ({ value: f, label: FIELD_KO[f] }))}
          onChange={(name) => onChange({ ...op, name })} data-testid={`${tid}-field`} />
      )}

      {op.kind === 'ind' && <IndFields op={op} onChange={onChange} cat={cat} mode={mode} tid={tid} />}

      {op.kind === 'market' && (
        <>
          <Select size="small" style={{ width: 84 }} value={op.index} options={cat.market.indexes.map((i) => ({ value: i, label: INDEX_KO[i] }))} onChange={(index) => onChange({ ...op, index })} />
          <Select size="small" style={{ width: 104 }} value={op.name} options={cat.market.names.map((n) => ({ value: n, label: MARKET_NAME_KO[n] }))}
            onChange={(name) => onChange({ ...op, name, params: name === 'close' ? {} : { n: 20 } })} />
          {op.name !== 'close' && (
            <NumField hint="mkt_n" min={cat.n_range[0]} max={cat.n_range[1]} value={(op.params?.n as number) ?? 20}
              onChange={(v) => onChange({ ...op, params: { ...op.params, n: v as ParamValue } })} suffix="일" />
          )}
        </>
      )}

      {op.kind === 'pos' && (
        <Select size="small" style={{ width: 200 }} value={op.name} data-testid={`${tid}-pos`}
          options={(cat.capabilities?.pos_names?.length ? cat.capabilities.pos_names : Object.keys(POS_LABEL)).map((value) => ({ value, label: POS_LABEL[value] ?? value }))} onChange={(name) => onChange({ ...op, name })} />
      )}

      {op.kind === 'const' && (
        <NumField hint={side === 'right' ? 'threshold' : 'value'} value={op.value} onChange={(v) => onChange({ ...op, value: v ?? 0 })} width={110} suffix={constSuffix} data-testid={`${tid}-const`} />
      )}

      {(op.kind === 'field' || op.kind === 'ind') && (
        <>
          {tfs.length > 0 && (
            <Space size={2}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>시간 단위</Typography.Text>
              <Select size="small" style={{ width: 150 }} value={op.tf ?? 'bar'} data-testid={`${tid}-tf`} onChange={setTf}
                options={tfs.map((t) => ({ value: t.value, label: t.label, disabled: t.disabled, reason: t.reason }))}
                optionRender={(o) => (o.data.reason ? <Tooltip title={o.data.reason} placement="right"><span style={{ opacity: 0.5 }}>{o.label} — {o.data.reason}</span></Tooltip> : <span>{o.label}</span>)} />
            </Space>
          )}
          {op.tf && tfs.length === 0 && <Tag data-testid={`${tid}-tf-tag`}>{tfLabel(op.tf)}</Tag>}
          <Space size={2}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>며칠 전</Typography.Text>
            <NumField hint="offset" min={0} max={cat.n_range[1]} width={64} value={op.offset ?? 0} onChange={(v) => onChange({ ...op, offset: typeof v === 'number' ? v : 0 })} />
          </Space>
          <Space size={2}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>배수 ×</Typography.Text>
            <NumField hint="mult" step={0.1} width={72} value={op.mul ?? 1} onChange={(v) => onChange({ ...op, mul: v ?? 1 })} />
          </Space>
        </>
      )}
    </Space>
  )
}

/** 지표 설명 — 무엇인지·정의 식·시점 규칙·예시·쓸 수 있는 모드. 서버가 안 준 칸은 그렇다고 말한다(지어내지 않음). */
export function IndicatorInfo({ def }: { def: IndicatorDef }) {
  return (
    <Space direction="vertical" size={4} style={{ maxWidth: 360 }} data-testid="ind-info">
      <Typography.Text strong>{def.label} <Typography.Text type="secondary" code>{def.name}</Typography.Text></Typography.Text>
      <Typography.Text>{def.desc}</Typography.Text>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>정의: {def.definition ?? '서버가 정의 식을 아직 안 줌'}</Typography.Text>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>시점: {def.timing}</Typography.Text>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>예시: {def.example ?? '없음'}</Typography.Text>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>쓸 수 있는 곳: {[...new Set(def.modes.map((m) => MODE_KO[m]))].join(' · ')}</Typography.Text>
    </Space>
  )
}

function IndFields({ op, onChange, cat, mode, tid }: { op: IndOperand; onChange: (o: Operand) => void; cat: IndicatorCatalog; mode: Mode; tid: string }) {
  const def = cat.indicators.find((d) => d.name === op.name)
  const setParam = (name: string, v: ParamValue) => onChange({ ...op, params: { ...op.params, [name]: v } })
  // 분류 나무: 모든 지표를 옵션으로 두고(비활성도 검색된다) 검색어는 filterOption 으로 거른다
  const options = indicatorTree(cat, mode).map((g) => ({
    label: g.category,
    options: g.options.map((o) => ({ value: o.value, label: o.label, disabled: o.disabled, reason: o.reason, def: o.def })),
  }))
  return (
    <>
      <Select size="small" style={{ width: 170 }} showSearch value={op.name} data-testid={`${tid}-ind`} options={options}
        // 분류(그룹) 자체는 false — true 를 주면 그룹의 지표가 검색어와 상관없이 전부 남는다(rc-select 는 그룹이 맞으면 자식을 거르지 않음)
        filterOption={(input, option) => !!option && 'def' in option && matchesQuery((option as { def: IndicatorDef }).def, input)}
        optionRender={(o) => {
          const d = o.data as { def?: IndicatorDef; reason?: string | null }
          if (!d.def) return o.label
          return (
            <Popover placement="right" mouseEnterDelay={0.4} content={<IndicatorInfo def={d.def} />}>
              <span style={{ opacity: d.reason ? 0.5 : 1 }}>{o.label}{d.reason ? <Typography.Text type="secondary" style={{ fontSize: 12 }}> — {d.reason}</Typography.Text> : null}</span>
            </Popover>
          )
        }}
        onChange={(name) => onChange(indOperand(cat, name, op))} />
      {def && <Popover content={<IndicatorInfo def={def} />} trigger="click"><InfoCircleOutlined style={{ cursor: 'pointer', color: '#8c8c8c' }} data-testid={`${tid}-info`} /></Popover>}
      {(def?.params ?? []).map((p) => {
        const v = op.params?.[p.name] ?? p.default
        if (p.kind === 'enum') {
          return <Select key={p.name} size="small" style={{ width: 84 }} value={v as string} options={(p.choices ?? []).map((c) => ({ value: c, label: FIELD_KO[c] ?? c }))} onChange={(x) => setParam(p.name, x)} />
        }
        if (p.kind === 'bool') {
          return <Space key={p.name} size={2}><Typography.Text type="secondary" style={{ fontSize: 12 }}>{p.label}</Typography.Text><Switch size="small" checked={!!v && !isParam(v)} onChange={(x) => setParam(p.name, x)} /></Space>
        }
        return (
          <Space key={p.name} size={2}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{p.label}</Typography.Text>
            <NumField hint={p.name === 'n' ? `${op.name}_n` : p.name} min={p.lo ?? undefined} max={p.hi ?? undefined} step={p.kind === 'float' ? 0.1 : 1} width={72}
              value={v as number} onChange={(x) => setParam(p.name, x as ParamValue)} data-testid={`${tid}-param-${p.name}`} />
          </Space>
        )
      })}
    </>
  )
}
