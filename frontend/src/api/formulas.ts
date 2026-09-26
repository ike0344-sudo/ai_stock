// 사용자 수식 API 어댑터 (studio-conditions c5, execution-agent 구현). 서버 경로·모양이 다르면 **이 파일만** 고친다.
// 가정(execution-agent 에 확인 편지 보냄, 2026-09-26 10:21): 저장소 GET/PUT/DELETE /api/formulas[/{name}], 검사 POST /api/formulas/check,
// 문법 오류는 422 FORMULA_INVALID + details {line, col, expected}. 404 는 "서버 준비 중"으로 다룬다(허브 API 와 같은 규칙).
import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import type { Condition, Group, Mode } from '@/types/studio'
import { ApiError, apiDelete, apiGet, apiPost, apiPut } from './client'

export interface FormulaRow { name: string; description: string | null; created_at: string | null }
export interface FormulaFull extends FormulaRow { text: string }
export interface FormulaCheck { ok: boolean; ast: Group | Condition | null; narration: string | null }
/** 수식 문법 오류의 위치 — 줄·칸은 1부터, expected 는 "여기엔 이런 것이 와야 한다" */
export interface FormulaErrorAt { line: number; col: number; expected: string; message: string }

export const useFormulas = (): UseQueryResult<FormulaRow[], ApiError> => useQuery({ queryKey: ['formulas'], queryFn: () => apiGet<FormulaRow[]>('/api/formulas'), retry: false })
export const getFormula = (name: string) => apiGet<FormulaFull>(`/api/formulas/${encodeURIComponent(name)}`)
export const putFormula = (name: string, body: { text: string; description: string }) => apiPut<FormulaRow>(`/api/formulas/${encodeURIComponent(name)}`, body)
export const deleteFormula = (name: string) => apiDelete<{ deleted: boolean }>(`/api/formulas/${encodeURIComponent(name)}`)
export const checkFormula = (text: string, mode: Mode, barMinutes?: number) =>
  apiPost<FormulaCheck>('/api/formulas/check', { text, mode, ...(barMinutes ? { bar_minutes: barMinutes } : {}) })

/** FORMULA_INVALID 오류에서 위치를 꺼낸다(다른 오류면 null) */
export function formulaErrorAt(e: unknown): FormulaErrorAt | null {
  if (!(e instanceof ApiError) || e.code !== 'FORMULA_INVALID') return null
  const d = e.details as { line?: number; col?: number; expected?: string }
  return { line: Number(d.line ?? 1), col: Number(d.col ?? 1), expected: String(d.expected ?? ''), message: e.message }
}

/** 설계서 §3.5 예시 모음 — 화면에서 눌러 입력칸에 채운다 */
export const FORMULA_EXAMPLES: { title: string; text: string }[] = [
  { title: '분봉에서 전일까지 20일 신고가 돌파', text: 'C > D.HIGHEST(H,20)' },
  { title: '5분봉 20선 위 + 일봉(장중) 20선 위', text: 'M5.C > M5.MA(C,20) AND DL.C > DL.MA(C,20)' },
  { title: '매수가 대비 +5% 이고 RSI 과열 (청산용)', text: 'POS.RETURN_PCT >= 5 AND RSI(14) >= 70' },
  { title: '골든크로스', text: 'CROSSUP(MA(C,5), MA(C,20))' },
  { title: '5분봉 20선 위에 연속 3봉 머물면', text: 'HOLD(M5.C > M5.MA(C,20), 3)' },
  { title: '거래량 3배 + 양봉', text: 'V > 3 * V(1) AND C > O' },
]
