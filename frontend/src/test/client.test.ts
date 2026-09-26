import { describe, expect, it } from 'vitest'
import { ApiError, unwrap } from '@/api/client'
import { isUnavailable } from '@/api/hub'

describe('unwrap — 서버 봉투(§6.2) 해석', () => {
  it('성공은 data 만 돌려준다', () => {
    expect(unwrap<{ a: number }>(200, { data: { a: 1 } })).toEqual({ a: 1 })
    expect(unwrap<{ job_id: string }>(202, { data: { job_id: 'x' } })).toEqual({ job_id: 'x' })
  })

  it('실패는 code·message·details 를 가진 ApiError', () => {
    try {
      unwrap(400, { error: { code: 'VALIDATION_ERROR', message: '형식', details: { fieldErrors: { codes: '6자리' } } } })
      expect.unreachable()
    } catch (e) {
      const err = e as ApiError
      expect(err).toBeInstanceOf(ApiError)
      expect([err.status, err.code]).toEqual([400, 'VALIDATION_ERROR'])
      expect(err.fieldErrors).toEqual({ codes: '6자리' })
    }
  })

  it('봉투가 아닌 응답(프록시 오류 페이지 등)은 BAD_RESPONSE', () => {
    expect(() => unwrap(502, null)).toThrowError(/HTTP 502/)
    try {
      unwrap(200, { nope: 1 })
    } catch (e) {
      expect((e as ApiError).code).toBe('BAD_RESPONSE')
    }
  })

  it('fieldErrors 가 없으면 빈 객체', () => {
    expect(new ApiError(409, 'LOCKED', 'x').fieldErrors).toEqual({})
  })
})

describe('isUnavailable — "허브 API 준비 중" 판정', () => {
  it('404 NOT_FOUND 만 준비 중으로 본다', () => {
    expect(isUnavailable(new ApiError(404, 'NOT_FOUND', ''))).toBe(true)
    expect(isUnavailable(new ApiError(500, 'INTERNAL', ''))).toBe(false)
    expect(isUnavailable(new ApiError(0, 'NETWORK', ''))).toBe(false)
    expect(isUnavailable(new ApiError(404, 'SOMETHING', ''))).toBe(false)
    expect(isUnavailable(new Error('x'))).toBe(false)
  })
})
