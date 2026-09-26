// 조건 편집기가 위에서 물려받는 실행 맥락 — 시간 단위 선택지(실행 봉 길이·분봉 출처)를 만드는 데 쓴다.
import { createContext, useContext } from 'react'
import type { MinuteSource } from '@/types/studio'

export interface ConditionCtx { barMinutes: number; source: MinuteSource }
export const ConditionContext = createContext<ConditionCtx>({ barMinutes: 5, source: 'al' })
export const useConditionCtx = () => useContext(ConditionContext)
