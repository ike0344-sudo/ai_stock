// 변수 칸 지원 — 숫자 칸의 "변수로" 버튼이 명세의 params 에 변수를 만들고 칸을 {"param": 이름} 으로 바꾼다.
// 컨텍스트가 없으면(결과 화면의 읽기 전용 표시 등) NumField 는 그냥 숫자 칸이다.
import { createContext, useContext } from 'react'
import type { Num, ParamRange } from '@/types/studio'

export interface ParamsApi {
  params: Record<string, ParamRange>
  /** 현재 값을 기본값으로 하는 새 변수를 만들고 참조를 돌려준다 */
  makeParam: (current: number, hint: string) => Num
  /** 변수 참조를 고정값(변수의 기본값)으로 되돌린다 */
  fixParam: (name: string) => number
}

export const ParamsContext = createContext<ParamsApi | null>(null)
export const useParamsApi = () => useContext(ParamsContext)
