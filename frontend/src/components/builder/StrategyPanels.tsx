// 전략 소스 (§5.4): 조건 조립기 / 기존 전략(8종 + 파라미터 폼) / 프리셋(불러오기·저장·삭제)
import { App, Button, Card, Input, InputNumber, Popconfirm, Radio, Select, Space, Tag, Typography } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { deletePreset, getPreset, putPreset, usePresets } from '@/api/studio'
import { ApiError } from '@/api/client'
import { defaultEntry, defaultExit } from '@/lib/spec'
import type { LegacyStrategyDef, SpecJson, StrategySpec } from '@/types/studio'

export function StrategySourceSwitch({ strategy, legacy, onChange, noLegacy }: { strategy: StrategySpec | null; legacy: LegacyStrategyDef[]; onChange: (s: StrategySpec) => void; noLegacy?: boolean }) {
  const source = strategy?.source ?? 'builder'
  return (
    <Radio.Group value={source} data-testid="strategy-source"
      onChange={(e) => {
        if (e.target.value === 'builder') onChange({ source: 'builder', entry: defaultEntry(), exit: defaultExit() })
        else {
          const first = legacy.find((l) => !l.deprecated) ?? legacy[0]
          onChange({ source: 'legacy', name: first?.name ?? 'ma_crossover', params: defaults(first) })
        }
      }}>
      <Radio.Button value="builder">조건 조립기</Radio.Button>
      <Radio.Button value="legacy" disabled={noLegacy} title={noLegacy ? '분봉·틱 모드는 조건 조립기만 쓴다(기존 전략 8종은 일봉 전용)' : undefined}>기존 전략</Radio.Button>
    </Radio.Group>
  )
}

const defaults = (d?: LegacyStrategyDef): Record<string, number | string | null> =>
  Object.fromEntries((d?.params ?? []).filter((p) => p.default !== null && p.default !== undefined).map((p) => [p.name, p.default as number | string]))

/** 기존 전략 선택 + 파라미터 폼. 폐기된 전략은 표시만 하고 경고한다. */
export function LegacyForm({ strategy, defs, onChange }: { strategy: Extract<StrategySpec, { source: 'legacy' }>; defs: LegacyStrategyDef[]; onChange: (s: StrategySpec) => void }) {
  const def = defs.find((d) => d.name === strategy.name)
  return (
    <Card size="small" title="기존 전략" data-testid="legacy-form">
      <Space direction="vertical" style={{ width: '100%' }}>
        <Select style={{ width: 360 }} value={strategy.name} data-testid="legacy-name"
          options={defs.map((d) => ({ value: d.name, label: `${d.label}${d.deprecated ? ' (폐기)' : ''}` }))}
          onChange={(name) => onChange({ source: 'legacy', name, params: defaults(defs.find((d) => d.name === name)) })} />
        {def?.deprecated && <Typography.Text type="warning">폐기된 전략 — {def.note}</Typography.Text>}
        {(def?.params ?? []).map((p) => {
          const v = strategy.params[p.name]
          const set = (x: unknown) => onChange({ ...strategy, params: { ...strategy.params, [p.name]: x as never } })
          return (
            <Space key={p.name} wrap>
              <span style={{ width: 300 }}>{p.label || p.name}</span>
              {p.kind === 'enum' ? (
                <Select style={{ width: 160 }} value={v as string} options={(p.choices ?? []).map((c) => ({ value: c, label: c }))} onChange={set} />
              ) : (
                <InputNumber min={p.lo ?? undefined} max={p.hi ?? undefined} step={p.kind === 'float' ? 0.01 : 1} value={(v as number | null) ?? null}
                  placeholder={p.optional ? '비우면 자동' : undefined} onChange={(x) => set(x === null ? (p.optional ? null : p.default) : Number(x))} data-testid={`legacy-param-${p.name}`} />
              )}
            </Space>
          )
        })}
      </Space>
    </Card>
  )
}

/** 프리셋 불러오기·저장·삭제. 저장 이름은 프리셋 키(파일 이름)다. */
export function PresetBar({ spec, onLoad }: { spec: SpecJson; onLoad: (s: SpecJson, name: string) => void }) {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const presets = usePresets()
  const [selected, setSelected] = useState<string | undefined>()
  const [saveName, setSaveName] = useState('')

  const load = async (name: string) => {
    try {
      const r = await getPreset(name)
      onLoad(r.spec, name)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }
  const save = async () => {
    try {
      await putPreset(saveName.trim(), spec)
      message.success(`프리셋 "${saveName.trim()}" 저장`)
      void qc.invalidateQueries({ queryKey: ['presets'] })
    } catch (e) {
      const fe = e instanceof ApiError ? Object.values(e.fieldErrors).join(', ') : ''
      message.error(e instanceof ApiError ? `${e.message}${fe ? ` — ${fe}` : ''}` : String(e))
    }
  }
  const remove = async () => {
    if (!selected) return
    try {
      await deletePreset(selected)
      message.success(`프리셋 "${selected}" 삭제`)
      setSelected(undefined)
      void qc.invalidateQueries({ queryKey: ['presets'] })
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }
  return (
    <Card size="small" title="프리셋" data-testid="preset-bar">
      <Space wrap>
        <Select style={{ width: 300 }} placeholder="프리셋 고르기" loading={presets.isPending} value={selected} onChange={setSelected} data-testid="preset-select"
          options={(presets.data ?? []).map((p) => ({ value: p.name, label: `${p.title ?? p.name}  ·  ${p.mode ?? ''}` }))} />
        <Button disabled={!selected} onClick={() => selected && load(selected)} data-testid="preset-load">불러오기</Button>
        <Popconfirm title="프리셋 삭제" description="기본 프리셋은 git 으로 되살릴 수 있습니다." okText="삭제" cancelText="취소" onConfirm={remove} disabled={!selected}>
          <Button danger disabled={!selected}>삭제</Button>
        </Popconfirm>
        <span style={{ width: 24 }} />
        <Input style={{ width: 180 }} placeholder="저장할 이름" value={saveName} onChange={(e) => setSaveName(e.target.value)} data-testid="preset-name" />
        <Button type="primary" ghost disabled={!saveName.trim()} onClick={save} data-testid="preset-save">지금 조건을 저장</Button>
        {presets.isError && <Tag color="red">프리셋 목록 오류</Tag>}
      </Space>
    </Card>
  )
}
