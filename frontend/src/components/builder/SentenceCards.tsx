// 조건을 "문장 빈칸 채우기" 카드로 만든다 (설계서 §5.5). 카드 = 쉬운 문장 + 빈칸(입력칸·시간 단위·선택), [+ 조건 추가] = 분류·검색 템플릿 목록.
// 문장·설명·오류는 전부 서버(templates API)가 준 쉬운 말을 그대로 보인다. 명세에는 조건 AST 만 저장한다(템플릿 id 는 매번 /match 로 되읽는다).
// 문장에 안 맞는 조건은 카드 대신 직접 조립 행 그대로(풀이 + 그 자리에서 편집), "직접 조립(고급)" 탭으로 전체를 옛 조립기로 볼 수 있다.
import { CopyOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Button, Card, Input, InputNumber, Modal, Radio, Segmented, Select, Skeleton, Space, Tooltip, Typography } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '@/api/client'
import { buildTemplate, matchTemplates } from '@/api/studio'
import { addItem, duplicateItem, errorsUnder, removeItem, replaceItem } from '@/lib/spec'
import type { CondTemplate, CondTemplates, Condition, Group, IndicatorCatalog, Mode, TplMatch, TplSlot, TplValues, ValidationIssue } from '@/types/studio'
import { isGroup } from '@/types/studio'
import { ConditionGroupEditor, ConditionRow } from './ConditionGroupEditor'

interface Props {
  group: Group
  onChange: (g: Group) => void
  cat: IndicatorCatalog
  mode: Mode
  path: string
  errors: ValidationIssue[]
  /** 진입 조건이면 "산다", 청산이면 "판다" */
  role: 'entry' | 'exit'
  required?: boolean
  barMinutes: number
  source: string
  tpl: CondTemplates
}

const BUILD_DEBOUNCE_MS = 350

export function SentenceGroupEditor({ group, onChange, cat, mode, path, errors, role, required = false, barMinutes, source, tpl }: Props) {
  const [advanced, setAdvanced] = useState(false)
  const [picker, setPicker] = useState(false)
  const tid = `cards-${path}`
  const verb = role === 'entry' ? '산다' : '판다'
  // 하위 그룹·수식·뒤집기가 든 그룹은 카드로 못 그린다 — 직접 조립으로 보인다
  const plain = group.items.every((i) => !isGroup(i)) && !group.negate && !group.formula
  const showAdvanced = advanced || !plain
  const conds = group.items.filter((i): i is Condition => !isGroup(i))
  const byId = useMemo(() => new Map(tpl.templates.map((t) => [t.id, t])), [tpl])

  const match = useQuery({
    queryKey: ['tpl-match', mode, barMinutes, JSON.stringify(conds)],
    queryFn: () => matchTemplates(conds, mode, barMinutes),
    enabled: !showAdvanced && conds.length > 0, retry: false, staleTime: 60_000, placeholderData: keepPreviousData,
  })

  const view = (
    <Segmented size="small" value={showAdvanced ? 'adv' : 'cards'} data-testid={`${tid}-view`} disabled={!plain}
      options={[{ label: '문장으로 만들기', value: 'cards' }, { label: '직접 조립(고급)', value: 'adv' }]} onChange={(v) => setAdvanced(v === 'adv')} />
  )

  if (showAdvanced) {
    return (
      <div data-testid={tid}>
        <Space wrap style={{ marginBottom: 6 }}>
          {view}
          {!plain && <Typography.Text type="secondary" style={{ fontSize: 12 }} data-testid={`${tid}-adv-note`}>하위 그룹·수식이 들어 있어 직접 조립 화면으로 보여 줍니다</Typography.Text>}
        </Space>
        <ConditionGroupEditor title={role === 'entry' ? '진입 조건 (이 조건이 참이면 다음 봉 시가에 산다)' : '청산 조건 (이 조건이 참이면 다음 봉 시가에 판다)'} path={path} group={group} required={required}
          cat={cat} mode={mode} errors={errors} allowPos={role === 'exit'} onChange={onChange} />
      </div>
    )
  }

  const matches = match.data && match.data.length === conds.length ? match.data : null
  return (
    <div data-testid={tid}>
      <Space wrap style={{ marginBottom: 8 }}>
        <Typography.Text strong>아래를</Typography.Text>
        <Radio.Group size="small" value={group.logic} onChange={(e) => onChange({ ...group, logic: e.target.value as Group['logic'] })} data-testid={`${tid}-logic`}>
          <Radio.Button value="all">모두 만족하면 {verb}</Radio.Button>
          <Radio.Button value="any">하나라도 만족하면 {verb}</Radio.Button>
        </Radio.Group>
        <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setPicker(true)} data-testid={`${tid}-add`}>조건 추가</Button>
        {view}
      </Space>
      {conds.length === 0 && (
        <Typography.Paragraph type={required ? 'danger' : 'secondary'} data-testid={`${tid}-empty`} style={{ margin: 0 }}>
          {required ? '조건이 아직 없어요 — [조건 추가] 를 눌러 문장 목록에서 골라 보세요(최소 1개)' : '조건 없음'}
        </Typography.Paragraph>
      )}
      <Space direction="vertical" size={6} style={{ width: '100%' }}>
        {conds.map((c, i) => {
          const errs = errorsUnder(errors, path, i)
          const actions = (
            <Space size={2}>
              <Tooltip title="복제"><Button size="small" type="text" icon={<CopyOutlined />} onClick={() => onChange(duplicateItem(group, i))} aria-label="조건 복제" /></Tooltip>
              <Tooltip title="삭제"><Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => onChange(removeItem(group, i))} aria-label="조건 삭제" /></Tooltip>
            </Space>
          )
          const m = matches ? matches[i] : undefined
          return (
            <Card key={i} size="small" data-testid={`card-${path}.${i}`} data-error={errs.length > 0} styles={{ body: { padding: 10 } }}
              style={{ borderColor: errs.length ? '#f5222d' : undefined, boxShadow: errs.length ? '0 0 0 1px #f5222d33' : undefined }}>
              {m === undefined ? <Skeleton.Input active size="small" block />
                : m === null || !byId.get(m.id) ? (
                  <div data-testid={`card-${path}.${i}-plain`}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>문장 카드로 나타낼 수 없는 조건이에요 — 아래에서 그대로 고칠 수 있어요([직접 조립(고급)] 에서도 같은 모습)</Typography.Text>
                    <ConditionRow cond={c} cat={cat} mode={mode} allowMarket={false} allowPos={role === 'exit'} actions={actions} onChange={(nc) => onChange(replaceItem(group, i, nc))} />
                  </div>
                ) : (
                  <SentenceCard tpl={byId.get(m.id)!} match={m} mode={mode} barMinutes={barMinutes} source={source} actions={actions} onChange={(nc) => onChange(replaceItem(group, i, nc))} />
                )}
            </Card>
          )
        })}
      </Space>
      <TemplatePicker open={picker} onClose={() => setPicker(false)} tpl={tpl} role={role} mode={mode} barMinutes={barMinutes} source={source}
        onPick={(c) => { onChange(addItem(group, c)); setPicker(false) }} />
    </div>
  )
}

// ───────────── 문장 카드 한 장 ─────────────
function SentenceCard({ tpl, match, mode, barMinutes, source, actions, onChange }: {
  tpl: CondTemplate; match: TplMatch; mode: Mode; barMinutes: number; source: string; actions: React.ReactNode; onChange: (c: Condition) => void
}) {
  const [pending, setPending] = useState<TplValues>({})
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [sentence, setSentence] = useState<string | null>(null) // 서버가 채운 완성 문장(입력 중 갱신)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false; clearTimeout(timer.current) } }, [])
  // 서버가 되읽은 값이 오면(우리가 방금 만든 조건이 돌아옴) 입력 중 값은 비운다
  useEffect(() => { setPending({}); setFieldErrors({}); setSentence(null) }, [match.sentence, JSON.stringify(match.values)])

  const vals: TplValues = { ...match.values, ...pending }
  const edit = (name: string, v: number | string | null, immediate: boolean) => {
    if (v === null || v === '') return
    const next = { ...vals, [name]: v }
    setPending((p) => ({ ...p, [name]: v }))
    clearTimeout(timer.current)
    const go = async () => {
      try {
        const built = await buildTemplate(tpl.id, next, mode, barMinutes, source)
        if (!alive.current) return
        setFieldErrors({}); setSentence(built.sentence)
        onChange(built.condition)
      } catch (e) {
        if (alive.current) setFieldErrors(e instanceof ApiError ? e.fieldErrors : { _: String(e) })
      }
    }
    if (immediate) void go(); else timer.current = setTimeout(go, BUILD_DEBOUNCE_MS)
  }

  const tfVal = String(vals.tf ?? 'bar')
  const barWord = mode === 'intraday' && !tfVal.startsWith('daily') ? '봉' : '일' // 일봉 모드·일봉 시간 단위면 "일", 분봉이면 "봉"
  const slot = (name: string): TplSlot | undefined => tpl.slots.find((s) => s.name === name)
  const parts = tpl.sentence.split(/(\{[^}]+\})/).filter((p) => p !== '')
  const errText = Object.values(fieldErrors)

  return (
    <div data-testid={`card-${tpl.id}`}>
      <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
        <Space wrap size={4} align="center" data-testid="card-sentence">
          {parts.map((p, k) => {
            const m = /^\{([^}]+)\}$/.exec(p)
            if (!m) return <Typography.Text key={k}>{p}</Typography.Text>
            if (m[1] === '봉') return <Typography.Text key={k}>{barWord}</Typography.Text>
            const s = slot(m[1])
            if (!s) return <Typography.Text key={k}>{p}</Typography.Text>
            const bad = !!fieldErrors[s.name]
            if (s.kind === 'number') {
              return <InputNumber key={k} size="small" style={{ width: 84 }} status={bad ? 'error' : undefined} min={s.lo} max={s.hi} precision={s.integer ? 0 : undefined}
                value={vals[s.name] as number} data-testid={`card-slot-${s.name}`} aria-label={s.label} placeholder={s.label}
                onChange={(v) => edit(s.name, v as number | null, false)} />
            }
            return <Select key={k} size="small" style={{ minWidth: s.kind === 'tf' ? 170 : 100 }} status={bad ? 'error' : undefined} value={String(vals[s.name])} data-testid={`card-slot-${s.name}`} aria-label={s.label}
              popupMatchSelectWidth={false}
              options={s.choices.map((c) => ({ value: c.value, label: c.label, disabled: !c.enabled, title: c.reason ?? undefined }))}
              onChange={(v) => edit(s.name, v, true)} />
          })}
        </Space>
        {actions}
      </Space>
      <div><Typography.Text type="secondary" style={{ fontSize: 12 }} data-testid="card-hint">{tpl.hint}</Typography.Text></div>
      {tpl.warn && <div><Typography.Text type="warning" style={{ fontSize: 12 }} data-testid="card-warn">⚠ {tpl.warn}</Typography.Text></div>}
      {errText.length > 0 && <div><Typography.Text type="danger" style={{ fontSize: 12 }} data-testid="card-error">{errText.join(' · ')}</Typography.Text></div>}
      {sentence && !errText.length && <span hidden data-testid="card-built">{sentence}</span>}
    </div>
  )
}

// ───────────── [+ 조건 추가] 템플릿 고르기 ─────────────
function TemplatePicker({ open, onClose, tpl, role, mode, barMinutes, source, onPick }: {
  open: boolean; onClose: () => void; tpl: CondTemplates; role: 'entry' | 'exit'; mode: Mode; barMinutes: number; source: string; onPick: (c: Condition) => void
}) {
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('all')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (open) { setQ(''); setCat('all'); setErr(null) } }, [open])
  const list = useMemo(() => {
    const n = q.trim().toLowerCase()
    return tpl.templates.filter((t) => (role === 'exit' || t.role !== 'exit') && (cat === 'all' || t.category === cat)
      && (!n || `${t.sentence} ${t.example} ${t.hint} ${t.category_label} ${t.tags.join(' ')}`.toLowerCase().includes(n)))
  }, [tpl, role, cat, q])
  const cats = tpl.categories.filter((c) => c.key !== 'exit' || role === 'exit')

  const pick = async (t: CondTemplate) => {
    if (!t.available || busy) return
    setBusy(true); setErr(null)
    try { onPick((await buildTemplate(t.id, undefined, mode, barMinutes, source)).condition) } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) } finally { setBusy(false) }
  }

  return (
    <Modal open={open} onCancel={onClose} footer={null} width={720} title="어떤 조건을 넣을까요? — 문장을 고르면 빈칸만 채우면 돼요" destroyOnHidden data-testid="tpl-picker">
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        <Input.Search allowClear autoFocus placeholder="검색 — 예: 거래대금, 골든크로스, 신고가, 급등" value={q} onChange={(e) => setQ(e.target.value)} data-testid="tpl-search" />
        <Segmented size="small" value={cat} onChange={(v) => setCat(String(v))} data-testid="tpl-cats" options={[{ label: '전체', value: 'all' }, ...cats.map((c) => ({ label: c.label, value: c.key }))]} />
        {err && <Typography.Text type="danger">{err}</Typography.Text>}
        <div style={{ maxHeight: 440, overflowY: 'auto' }} data-testid="tpl-list">
          {list.length === 0 && <Typography.Text type="secondary">맞는 문장이 없어요 — 다른 말로 검색하거나 [직접 조립(고급)] 을 써 보세요</Typography.Text>}
          {list.map((t) => (
            <Tooltip key={t.id} title={t.available ? undefined : t.reason}>
              <div role="button" tabIndex={t.available ? 0 : -1} aria-disabled={!t.available} data-testid={`tpl-${t.id}`} onClick={() => void pick(t)} onKeyDown={(e) => { if (e.key === 'Enter') void pick(t) }}
                style={{ padding: '8px 10px', borderRadius: 6, cursor: t.available ? 'pointer' : 'not-allowed', opacity: t.available ? 1 : 0.45, borderBottom: '1px solid rgba(128,128,128,0.2)' }}>
                <div><Typography.Text strong>{t.example}</Typography.Text> <Typography.Text type="secondary" style={{ fontSize: 12 }}>· {t.category_label}</Typography.Text></div>
                <div><Typography.Text type="secondary" style={{ fontSize: 12 }}>{t.available ? t.hint : t.reason}</Typography.Text></div>
              </div>
            </Tooltip>
          ))}
        </div>
      </Space>
    </Modal>
  )
}
