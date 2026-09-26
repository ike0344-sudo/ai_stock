// vitest 공통 준비 — jsdom 에 없는 브라우저 기능(antd·echarts 가 부름)을 채우고, 캔버스가 필요한 EChart 는 대역으로 바꾼다.
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false, media: query, onchange: null,
    addListener: () => undefined, removeListener: () => undefined,
    addEventListener: () => undefined, removeEventListener: () => undefined, dispatchEvent: () => false,
  }),
})

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO

// jsdom 은 canvas 가 없어 echarts 가 못 뜬다 — option 을 JSON 으로 노출하는 div 로 대체(옵션 내용은 옵션 함수 단위로 따로 검사)
vi.mock('@/components/charts/EChart', () => ({
  EChart: ({ option }: { option: unknown }) => <div data-testid="echart">{JSON.stringify(option)}</div>,
}))
