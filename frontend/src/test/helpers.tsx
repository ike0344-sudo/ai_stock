// 테스트 공용 — 가짜 서버(fetch)와 렌더 래퍼.
// 가짜 서버는 실제 서버(studio/api)와 같은 규칙을 따른다: 성공은 {"data"}, 없는 경로는 404 NOT_FOUND 봉투 —
// 그래서 "허브 API 준비 중" 경로가 실제와 같은 조건으로 검사된다.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { ThemeProvider } from '@/lib/theme'

export interface Call {
  method: string
  path: string
  body: unknown
}

type Reply = { status?: number; data?: unknown; error?: { code: string; message: string; details?: Record<string, unknown> } }
type Route = Reply | ((call: Call) => Reply)

/** routes: "GET /api/data/overview" → 응답. 쿼리스트링은 무시하고 경로로 맞춘다(가장 긴 접두사 우선). 없으면 404 NOT_FOUND. */
export function mockApi(routes: Record<string, Route>) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://127.0.0.1:8780')
    const method = (init?.method ?? 'GET').toUpperCase()
    const call: Call = { method, path: url.pathname + url.search, body: init?.body ? JSON.parse(String(init.body)) : undefined }
    calls.push(call)
    const key = Object.keys(routes)
      .filter((k) => k.startsWith(`${method} `) && url.pathname === k.slice(method.length + 1))
      .sort((a, b) => b.length - a.length)[0]
    const raw = key ? routes[key] : undefined
    const reply: Reply = raw === undefined ? { status: 404, error: { code: 'NOT_FOUND', message: '찾을 수 없음' } } : typeof raw === 'function' ? raw(call) : raw
    const status = reply.status ?? (reply.error ? 400 : 200)
    const body = reply.error ? { error: { details: {}, ...reply.error } } : { data: reply.data }
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export function renderApp(ui: ReactElement, route = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}
