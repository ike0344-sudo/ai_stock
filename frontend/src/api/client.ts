// API 클라이언트 — 서버의 봉투(설계서 §6.2)를 해석한다.
//   성공  {"data": ...}                                   → data 를 돌려준다
//   실패  {"error": {"code", "message", "details"}}       → ApiError 를 던진다
// 화면은 code 로 분기하고(예: LOCKED → 잠금 배너), details.fieldErrors 로 칸을 강조한다.
import type { ErrorEnvelope } from '@/types'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** 400 VALIDATION_ERROR 의 칸별 메시지 — {"칸 경로": "메시지"} */
  get fieldErrors(): Record<string, string> {
    const fe = this.details.fieldErrors
    return fe && typeof fe === 'object' ? (fe as Record<string, string>) : {}
  }
}

function isErrorEnvelope(body: unknown): body is ErrorEnvelope {
  return typeof body === 'object' && body !== null && 'error' in body
}

/** 응답 본문을 봉투 규칙대로 풀어 data 를 돌려준다(테스트하기 쉽게 fetch 와 분리). */
export function unwrap<T>(status: number, body: unknown): T {
  if (status >= 200 && status < 300 && typeof body === 'object' && body !== null && 'data' in body) {
    return (body as { data: T }).data
  }
  if (isErrorEnvelope(body)) {
    const { code, message, details } = body.error
    throw new ApiError(status, code, message, details ?? {})
  }
  // 봉투가 아닌 응답(프록시 오류 페이지 등)
  throw new ApiError(status, 'BAD_RESPONSE', `예상하지 못한 응답 (HTTP ${status})`)
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'NETWORK', '서버에 연결할 수 없음 — 스튜디오 서버(python -m studio)가 떠 있는지 확인')
  }
  let parsed: unknown = null
  try {
    parsed = await res.json()
  } catch {
    /* 본문이 JSON 이 아님 — unwrap 이 BAD_RESPONSE 로 처리 */
  }
  return unwrap<T>(res.status, parsed)
}

export const apiGet = <T>(path: string) => request<T>('GET', path)
export const apiPost = <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {})
export const apiPut = <T>(path: string, body: unknown) => request<T>('PUT', path, body)
export const apiDelete = <T>(path: string) => request<T>('DELETE', path)
export const apiPatch = <T>(path: string, body: unknown) => request<T>('PATCH', path, body)
