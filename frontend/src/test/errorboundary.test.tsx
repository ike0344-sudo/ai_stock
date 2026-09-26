import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ErrorBoundary } from '@/components/layout/ErrorBoundary'
import { renderApp } from './helpers'

const Boom = () => { throw new Error('터졌다') }

describe('ErrorBoundary', () => {
  it('자식이 그리다 죽으면 하얀 화면 대신 오류 문구', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    renderApp(<ErrorBoundary><Boom /></ErrorBoundary>)
    expect(screen.getByTestId('screen-crash')).toHaveTextContent('터졌다')
  })

  it('정상 자식은 그대로', () => {
    renderApp(<ErrorBoundary><p>정상</p></ErrorBoundary>)
    expect(screen.getByText('정상')).toBeInTheDocument()
    expect(screen.queryByTestId('screen-crash')).not.toBeInTheDocument()
  })
})
