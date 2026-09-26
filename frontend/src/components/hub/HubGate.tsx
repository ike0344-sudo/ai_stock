// 허브 패널 공통 껍데기 — 로딩 / "허브 API 준비 중" / 오류 / 데이터 네 가지 상태를 한 곳에서 처리한다.
import type { UseQueryResult } from '@tanstack/react-query'
import { Alert, Spin } from 'antd'
import type { ReactNode } from 'react'
import { isUnavailable } from '@/api/hub'
import { ApiError } from '@/api/client'

export function UnavailableNote({ path }: { path: string }) {
  return (
    <Alert
      type="info"
      showIcon
      data-testid="hub-unavailable"
      message="허브 API 준비 중"
      description={`GET ${path} — datahub/api.py 가 붙으면 채워집니다. 값을 지어내 보여주지 않습니다.`}
    />
  )
}

interface Props<T> {
  query: UseQueryResult<T, ApiError>
  path: string // 사용자에게 보여줄 경로(준비 중 안내용)
  children: (data: T) => ReactNode
}

export function HubGate<T>({ query, path, children }: Props<T>) {
  if (query.isPending) return <Spin data-testid="hub-loading" />
  if (query.isError) {
    if (isUnavailable(query.error)) return <UnavailableNote path={path} />
    const e = query.error
    return <Alert type="error" showIcon data-testid="hub-error" message={`${e.code}: ${e.message}`} description={`GET ${path}`} />
  }
  return <>{children(query.data)}</>
}
