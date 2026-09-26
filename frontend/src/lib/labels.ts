// 화면 문구 사전 — 서버 값(영문 코드)을 쉬운 말로
import type { Mode } from '@/types/studio'

export const MODE_LABEL: Record<Mode, string> = { daily_single: '일봉 · 단일 종목', daily_portfolio: '일봉 · 포트폴리오', intraday: '분봉 단타', tick: '체결(틱)' }
export const EXIT_REASON_LABEL: Record<string, string> = {
  signal: '조건 청산', stop: '손절', target: '익절', trailing: '트레일링 스톱', time: '보유 기간 초과', eod: '장 마감 청산', end_of_data: '데이터 끝에서 청산',
}
export const exitReason = (r: string | null | undefined): string => (r ? EXIT_REASON_LABEL[r] ?? r : '—')
export const KIND_LABEL_RUN: Record<string, string> = { backtest: '백테스트', optimize: '최적화', walkforward: '워크포워드', holdout_check: '홀드아웃' }

export const KIND_LABEL: Record<string, string> = { optimize: '최적화', walkforward: '워크포워드', holdout_check: '홀드아웃 열람' }
