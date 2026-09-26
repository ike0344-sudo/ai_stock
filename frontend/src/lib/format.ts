// 표시용 변환 — 값이 없으면(null) 항상 "—". 0 과 없음을 섞지 않는다(계약 규칙).
import dayjs from 'dayjs'
import type { Decision, Verdict, Window } from '@/types/data'

export const DASH = '—'

/** ISO 시각 → "MM-DD HH:mm". ISO 가 아닌 문장("2026-10-03 (토) 09:00 이후" 같은)이 오면 지어내지 않고 그대로 보여준다. */
export const fmtTs = (ts: string | null | undefined, withSeconds = false): string => {
  if (!ts) return DASH
  const d = dayjs(ts)
  return d.isValid() ? d.format(withSeconds ? 'MM-DD HH:mm:ss' : 'MM-DD HH:mm') : ts
}

export const fmtDate = (d: string | null | undefined): string => (d ? dayjs(d).format('YYYY-MM-DD') : DASH)

export const fmtNum = (n: number | null | undefined): string => (n === null || n === undefined ? DASH : n.toLocaleString('ko-KR'))

export const fmtPct = (share: number | null | undefined, digits = 1): string =>
  share === null || share === undefined ? DASH : `${(share * 100).toFixed(digits)}%`

/** 초 → "1시간 26분" / "45분" / "30초" */
export function fmtDuration(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return DASH
  const s = Math.max(0, Math.round(sec))
  if (s < 60) return `${s}초`
  const m = Math.round(s / 60)
  if (m < 60) return `${m}분`
  const h = Math.floor(m / 60)
  return m % 60 ? `${h}시간 ${m % 60}분` : `${h}시간`
}

export const VERDICT_COLOR: Record<Verdict, string> = { good: '#52c41a', warn: '#fa8c16', bad: '#f5222d' }
export const VERDICT_LABEL: Record<Verdict, string> = { good: '좋음', warn: '주의', bad: '나쁨' }

export const WINDOW_LABEL: Record<Window, string> = {
  market: '정규장(소피증권 가동)',
  sophie_live: '소피증권 가동 시간',
  night: '야간',
  holiday: '휴장·주말',
}

/** 대량 수집 판정을 사람 말로 — 시간대 배너용 */
export function bulkText(decision: Decision, suggestAt: string | null, connectTo: string): string {
  if (decision === 'allow_now') return '대량 수집: 지금 가능'
  if (decision === 'needs_confirm') return '대량 수집: 확인 후 가능'
  return `대량 수집: ${suggestAt ? dayjs(suggestAt).format('HH:mm') : connectTo} 예약만`
}

/** 카탈로그 basis 값(KRX · AL · derived · reference) → 사람 말 */
export const BASIS_LABEL: Record<string, string> = { KRX: 'KRX', AL: '통합(AL)', derived: '파생', reference: '참조' }
export const basisLabel = (b: string): string => BASIS_LABEL[b] ?? b
export const DATASET_BASIS_COLOR: Record<string, string> = { KRX: 'blue', AL: 'purple', derived: 'default', reference: 'default' }

/** 카탈로그 retention(keep · forever · forever_unrecoverable · overwrite_20d · regenerable) → 배지 문구 */
export function retentionBadge(r: string): { text: string; color: string } {
  switch (r) {
    case 'forever_unrecoverable': return { text: '영구 보관 · 재수집 불가', color: 'green' }
    case 'forever': return { text: '영구 보관', color: 'green' }
    case 'overwrite_20d': return { text: '20거래일 창 · 갱신 때 덮어씀', color: 'orange' }
    case 'regenerable': return { text: '재생성 가능', color: 'default' }
    case 'keep': return { text: '보관', color: 'blue' }
    default: return { text: r, color: 'default' }
  }
}

export const KIND_LABEL: Record<string, string> = {
  collect_daily: '일봉 최신화',
  collect_ticks: '체결 수집',
  collect_minute_al: '통합 분봉 갱신',
  archive_minute_al: '보관 병합',
  tick_nightly: '체결 야간 수집',
  daily_catchup: '일봉 아침 따라잡기',
  backtest: '백테스트',
}

/** 종목 코드 6자리 검사 — 서버(^[0-9A-Z]{6}$)와 같은 규칙 */
export const CODE_RE = /^[0-9A-Z]{6}$/
