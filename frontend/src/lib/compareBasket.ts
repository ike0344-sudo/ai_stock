// "비교에 추가" 바구니 — 브라우저에 기억한다(실행 기록·결과 화면에서 담고 비교 화면에서 쓴다). 서버 상태가 아니다.
const KEY = 'studio.compare'
export const MAX_COMPARE = 5

export function getBasket(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string').slice(0, MAX_COMPARE) : []
  } catch {
    return []
  }
}
export function setBasket(ids: string[]): void {
  localStorage.setItem(KEY, JSON.stringify([...new Set(ids)].slice(0, MAX_COMPARE)))
}
/** 담는다. 가득 차면 false(담지 않음). 이미 있으면 true. */
export function addToBasket(id: string): boolean {
  const cur = getBasket()
  if (cur.includes(id)) return true
  if (cur.length >= MAX_COMPARE) return false
  setBasket([...cur, id])
  return true
}
export const removeFromBasket = (id: string): void => setBasket(getBasket().filter((x) => x !== id))
