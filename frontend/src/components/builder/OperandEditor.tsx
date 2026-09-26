// 조건의 한쪽(피연산자) 편집 — 가격 값 / 지표 / 시장 지수 / 숫자. 지표는 카탈로그(§3.7)가 메뉴·파라미터·모드를 정한다.
import { Select, Space, Switch, Typography } from 'antd'
import { indOperand, operandKindDefault } from '@/lib/spec'
import type { IndicatorCatalog, IndOperand, Mode, Operand, ParamValue } from '@/types/studio'
import { isParam } from '@/types/studio'
import { NumField } from './NumField'

export const FIELD_KO: Record<string, string> = { open: '시가', high: '고가', low: '저가', close: '종가', volume: '거래량', value: '거래대금' }
const KIND_KO: Record<Operand['kind'], string> = { field: '가격·거래량', ind: '지표', market: '시장 지수', const: '숫자' }
const INDEX_KO = { kospi: '코스피', kosdaq: '코스닥' }
const MARKET_NAME_KO = { close: '종가', sma: '이동평균', change_pct: '등락률(%)' }

interface Props {
  op: Operand
  onChange: (op: Operand) => void
  cat: IndicatorCatalog
  mode: Mode
  allowMarket: boolean
  side: 'left' | 'right'
}

/** 분봉·틱 모드는 지표를 분봉 기준으로 쓴다 — 카탈로그 modes 와 대조할 실제 모드 */
const effectiveMode = (m: Mode): Mode => (m === 'tick' ? 'intraday' : m)

export function OperandEditor({ op, onChange, cat, mode, allowMarket, side }: Props) {
  const kinds = (['field', 'ind', 'const', ...(allowMarket ? ['market'] : [])] as Operand['kind'][])
  const inds = cat.indicators.filter((d) => d.modes.includes(effectiveMode(mode)) && d.compute)
  const tid = `operand-${side}`

  return (
    <Space size={4} wrap data-testid={tid}>
      <Select<Operand['kind']> size="small" style={{ width: 104 }} value={op.kind} data-testid={`${tid}-kind`}
        options={kinds.map((k) => ({ value: k, label: KIND_KO[k] }))}
        onChange={(k) => onChange(operandKindDefault(k, cat))} />

      {op.kind === 'field' && (
        <Select size="small" style={{ width: 90 }} value={op.name} options={cat.fields.map((f) => ({ value: f, label: FIELD_KO[f] }))}
          onChange={(name) => onChange({ ...op, name })} data-testid={`${tid}-field`} />
      )}

      {op.kind === 'ind' && <IndFields op={op} onChange={onChange} cat={cat} inds={inds} tid={tid} />}

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

      {op.kind === 'const' && (
        <NumField hint={side === 'right' ? 'threshold' : 'value'} value={op.value} onChange={(v) => onChange({ ...op, value: v ?? 0 })} width={110} data-testid={`${tid}-const`} />
      )}

      {(op.kind === 'field' || op.kind === 'ind') && (
        <>
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

function IndFields({ op, onChange, cat, inds, tid }: { op: IndOperand; onChange: (o: Operand) => void; cat: IndicatorCatalog; inds: IndicatorCatalog['indicators']; tid: string }) {
  const def = cat.indicators.find((d) => d.name === op.name)
  const setParam = (name: string, v: ParamValue) => onChange({ ...op, params: { ...op.params, [name]: v } })
  return (
    <>
      <Select size="small" style={{ width: 140 }} showSearch optionFilterProp="label" value={op.name} data-testid={`${tid}-ind`}
        options={inds.map((d) => ({ value: d.name, label: d.label }))}
        onChange={(name) => onChange(indOperand(cat, name, op))} />
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
