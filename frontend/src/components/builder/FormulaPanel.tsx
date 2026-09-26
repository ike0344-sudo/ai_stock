// 사용자 수식 편집기 (§5.4 "사용자 수식"): 입력칸(고정폭) · [검사](오류 위치 표시) · [저장](이름·설명) · 내 수식 목록(불러오기·삭제) · 예시 모음.
// 서버(execution-agent c5)가 아직 없으면 404 → "준비 중"으로 보인다. 컴파일된 조건은 [진입에 넣기]/[청산에 넣기] 로 조건 행에 박는다(수식 파일이 나중에 바뀌어도 옛 결과는 그대로).
import { App, Alert, Button, Card, Input, List, Popconfirm, Space, Typography } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError } from '@/api/client'
import { checkFormula, deleteFormula, FORMULA_EXAMPLES, formulaErrorAt, getFormula, putFormula, useFormulas, type FormulaCheck, type FormulaErrorAt } from '@/api/formulas'
import type { Condition, Group, Mode } from '@/types/studio'

interface Props {
  mode: Mode
  barMinutes: number
  /** 빌더 전략일 때만 조건 행에 넣을 수 있다(기존 전략·틱 조건 진입엔 조건식이 없다) */
  canInsert: boolean
  onInsert: (target: 'entry' | 'exit' | 'filter', node: Group | Condition) => void
  /** 틱 조건 진입이고 서버가 틱 필터(c8)를 알릴 때 — 수식을 "틱 분봉·일봉 조건"에 넣는 버튼을 보인다 */
  canInsertFilter?: boolean
}

/** 오류 줄과 위치 표시(^) — 고정폭으로 찍는다 */
export function ErrorCaret({ text, at }: { text: string; at: FormulaErrorAt }) {
  const line = text.split('\n')[at.line - 1] ?? ''
  return (
    <pre data-testid="formula-caret" style={{ margin: 0, padding: 8, background: 'rgba(245,34,45,0.06)', borderRadius: 6, fontFamily: 'Consolas, monospace', overflowX: 'auto' }}>
      {`${at.line}줄 ${at.col}칸\n${line}\n${' '.repeat(Math.max(0, at.col - 1))}^ ${at.expected ? `여기엔 ${at.expected} 이(가) 와야 한다` : at.message}`}
    </pre>
  )
}

/** enabled=false(서버에 수식 라우터가 없음)면 요청을 아예 보내지 않고 준비 중 안내만 — 콘솔에 404 가 쌓이지 않게 */
export function FormulaPanel({ enabled, ...rest }: Props & { enabled: boolean }) {
  if (!enabled) {
    return <Alert type="info" showIcon data-testid="formula-pending" message="사용자 수식 편집기는 서버 준비 중이다(studio-conditions c5, execution-agent 구현 대기)" description="서버에 수식 저장소·검사 경로가 생기면 이 자리에 입력칸이 나타난다. 지금은 조건 행으로 조립하거나 레시피를 불러 쓰세요." />
  }
  return <FormulaEditor {...rest} />
}

function FormulaEditor({ mode, barMinutes, canInsert, canInsertFilter = false, onInsert }: Props) {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const list = useFormulas()
  const [text, setText] = useState('')
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<FormulaCheck | null>(null)
  const [err, setErr] = useState<FormulaErrorAt | null>(null)
  const [other, setOther] = useState<string | null>(null)

  const notReady = list.isError && list.error.status === 404
  const reset = () => { setRes(null); setErr(null); setOther(null) }

  const check = async () => {
    setBusy(true); reset()
    try {
      setRes(await checkFormula(text, mode, mode === 'intraday' || mode === 'tick' ? barMinutes : undefined))
    } catch (e) {
      const at = formulaErrorAt(e)
      if (at) setErr(at)
      else setOther(e instanceof ApiError ? `${e.code} — ${e.message}` : String(e))
    } finally { setBusy(false) }
  }
  const save = async () => {
    try {
      await putFormula(name.trim(), { text, description: desc })
      message.success(`수식 "${name.trim()}" 저장`)
      void qc.invalidateQueries({ queryKey: ['formulas'] })
    } catch (e) { message.error(e instanceof ApiError ? `${e.message}${Object.values(e.fieldErrors).length ? ` — ${Object.values(e.fieldErrors).join(', ')}` : ''}` : String(e)) }
  }
  const load = async (n: string) => {
    try { const f = await getFormula(n); setText(f.text); setName(f.name); setDesc(f.description ?? ''); reset() } catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
  }
  const remove = async (n: string) => {
    try { await deleteFormula(n); message.success(`수식 "${n}" 삭제`); void qc.invalidateQueries({ queryKey: ['formulas'] }) } catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
  }

  if (notReady) {
    return <Alert type="info" showIcon data-testid="formula-pending" message="사용자 수식 편집기는 서버 준비 중이다(studio-conditions c5, execution-agent 구현 대기)" description="서버에 수식 저장소·검사 경로가 생기면 이 자리에 입력칸이 나타난다. 지금은 조건 행으로 조립해 주세요." />
  }
  return (
    <Card size="small" title="수식으로 조건 쓰기" data-testid="formula-panel">
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Input.TextArea value={text} onChange={(e) => { setText(e.target.value); reset() }} autoSize={{ minRows: 3, maxRows: 10 }} spellCheck={false} maxLength={2000} showCount
          placeholder="예) C > D.HIGHEST(H,20)   ·  M5.C > M5.MA(C,20) AND DL.C > DL.MA(C,20)" style={{ fontFamily: 'Consolas, monospace' }} data-testid="formula-text" />
        <Space wrap>
          <Button type="primary" onClick={check} loading={busy} disabled={!text.trim()} data-testid="formula-check">검사</Button>
          <Button disabled={!res?.ok || !canInsert} onClick={() => res?.ast && onInsert('entry', res.ast)} data-testid="formula-insert-entry">진입 조건에 넣기</Button>
          <Button disabled={!res?.ok || !canInsert} onClick={() => res?.ast && onInsert('exit', res.ast)} data-testid="formula-insert-exit">청산 조건에 넣기</Button>
          {canInsertFilter && <Button disabled={!res?.ok} onClick={() => res?.ast && onInsert('filter', res.ast)} data-testid="formula-insert-filter">틱 분봉·일봉 조건에 넣기</Button>}
          {!canInsert && !canInsertFilter && <Typography.Text type="secondary" style={{ fontSize: 12 }}>조건 조립기 전략(틱 조건 진입 제외)에서만 넣을 수 있다</Typography.Text>}
        </Space>
        {res?.ok && <Alert type="success" showIcon data-testid="formula-ok" message="수식이 맞습니다" description={res.narration ?? undefined} />}
        {err && <Alert type="error" showIcon data-testid="formula-error" message={`수식 오류 — ${err.message}`} description={<ErrorCaret text={text} at={err} />} />}
        {other && <Alert type="error" showIcon data-testid="formula-other-error" message={other} />}

        <Space wrap>
          <Input placeholder="저장할 이름(한글·영문·숫자)" style={{ width: 220 }} value={name} maxLength={40} onChange={(e) => setName(e.target.value)} data-testid="formula-name" />
          <Input placeholder="설명(선택)" style={{ width: 300 }} value={desc} onChange={(e) => setDesc(e.target.value)} />
          <Button onClick={save} disabled={!name.trim() || !text.trim()} data-testid="formula-save">저장</Button>
        </Space>

        <div>
          <Typography.Text strong>예시 모음</Typography.Text>
          <List size="small" dataSource={FORMULA_EXAMPLES} data-testid="formula-examples"
            renderItem={(ex) => <List.Item actions={[<Button key="use" size="small" type="link" onClick={() => { setText(ex.text); reset() }}>입력칸에 채우기</Button>]}><Space direction="vertical" size={0}><span>{ex.title}</span><Typography.Text code>{ex.text}</Typography.Text></Space></List.Item>} />
        </div>
        <div>
          <Typography.Text strong>내 수식</Typography.Text>
          {list.isPending && <div><Typography.Text type="secondary">불러오는 중…</Typography.Text></div>}
          {list.isError && !notReady && <Alert type="error" showIcon message={`수식 목록을 못 불러옴: ${list.error.message}`} />}
          {list.data && (
            <List size="small" data-testid="formula-list" locale={{ emptyText: '저장한 수식이 없다' }} dataSource={list.data}
              renderItem={(f) => (
                <List.Item actions={[
                  <Button key="load" size="small" type="link" onClick={() => load(f.name)} data-testid={`formula-load-${f.name}`}>불러오기</Button>,
                  <Popconfirm key="del" title={`수식 "${f.name}" 을 지울까요?`} okText="삭제" cancelText="취소" onConfirm={() => remove(f.name)}><Button size="small" type="link" danger>삭제</Button></Popconfirm>,
                ]}><Space direction="vertical" size={0}><Typography.Text strong>{f.name}</Typography.Text><Typography.Text type="secondary">{f.description ?? ''}</Typography.Text></Space></List.Item>
              )} />
          )}
        </div>
      </Space>
    </Card>
  )
}
