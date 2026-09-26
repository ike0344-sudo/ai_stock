// 종목 표기는 항상 종목명 — 코드는 마우스를 올렸을 때 툴팁으로만. 이름은 서버(종목 마스터)가 결과 상세의 `names` 맵으로 준다(화면마다 따로 찾지 않는다).
// 이름을 정말 모르는 코드(상장폐지 등)만 코드로 보인다.
import { createContext, useContext } from 'react'

export type StockNames = Record<string, string>
export const StockNamesContext = createContext<StockNames>({})
export const useStockNames = (): StockNames => useContext(StockNamesContext)

/** 이름 → 맵의 이름 → 코드 순으로 */
export const stockLabel = (names: StockNames, code: string, name?: string | null): string => (name && name.trim()) || names[code] || code

export function StockName({ code, name }: { code: string; name?: string | null }) {
  const label = stockLabel(useStockNames(), code, name)
  return <span title={label === code ? undefined : code} data-testid="stock-name">{label}</span>
}
