"""전략 2번 — SK하이닉스 과대낙폭 분할매수 (SK하이닉스_매매전략_통합본.pdf 전략3).

15분봉 60기간 단순이동평균(60선) 대비 괴리율이 -9%/-12%/-15% 밴드에 닿을 때마다
1/3씩 분할매수(최대 3단, 반등 확인 없이 즉시)하고, 고가가 60선에 닿으면 전량
청산한다. 하드스톱(평단 대비 -20%)과 시간청산(15거래일 내 60선 미복귀)이 보조
청산 규칙.

PDF 원문은 "지정가 3분할을 미리 깔아두고 60선이 움직이면 수시 갱신"이라 하지만,
이 코드베이스엔 주문 체결 확인/미체결 재지정 로직이 전혀 없어(모든 기존 실주문
경로가 시장가 즉시체결을 가정) 문자 그대로 구현하려면 그 인프라를 통째로 새로
만들어야 한다. 대신 "밴드를 저가/현재가가 건드리는 순간 그 즉시 시장가로 매수"
방식을 쓴다 — 경제적 효과는 거의 동일하고(유동성 높은 대형주라 체결가가 밴드가와
크게 벌어지지 않음), 기존 trading_loop.py의 주문 패턴과도 일치한다.

성과(PDF 기준, 2025/07~2026/07 SK하이닉스 15분봉 백테스트): 연 12회, 평균 +4.20%,
승률 92%(11승1패), 최악 -3.82%, 누적 +50.4%, 평균 보유 1.6일. SK하이닉스가 약
7배 상승한 초강세장에 최적화된 결과이므로 추세 붕괴 국면에서는 하드스톱이
현실화될 수 있다는 PDF의 경고를 그대로 옮겨 둔다.

거래소 기준: 60선(60기간 이평선)은 KRX 단독 기준 15분봉으로 계산한다(백테스트가
NXT 출범 전 KRX 단독 이력 기준이라, 실전에서도 oversold_trading_loop.py가
load_history 호출 시 exchange="1"을 명시해 맞춘다) — 통합(KRX+NXT) 분봉을 쓰면 같은
분봉의 거래량/종가가 달라져 60선 자체가 백테스트와 어긋난다. 반면 밴드 터치 판단에
쓰는 실시간 현재가/청산 호가는 실제 주문이 체결될 거래소 기준(실전은 통합/SOR)을
따른다 — 이건 "추세 판단"이 아니라 "지금 얼마에 체결되는가"의 문제라 KRX로 고정할
이유가 없다.
"""
from datetime import date

import pandas as pd

STOCK_CODE = "000660"  # SK하이닉스
MA_WINDOW = 60
BAR_INTERVAL_MINUTES = 15

# 60선 대비 -9%/-12%/-15% 밴드에서 각 1/3씩 분할매수 (PDF 전략3 표)
TIER_BAND_PCTS = (0.09, 0.12, 0.15)
TIER_FRACTION = 1.0 / len(TIER_BAND_PCTS)

HARD_STOP_PCT = 0.20  # 평단 대비 -20%
TIME_EXIT_TRADING_DAYS = 15  # 최초 진입 후 15거래일 내 60선 미복귀 시 청산

# 계좌 배정 비중 권장치(PDF) — 별도 플래그 없이 run-trading --strategy strategy_2
# 실행 시 --total-capital을 이 비율만큼만 넣는 방식으로 적용한다.
RECOMMENDED_ALLOCATION_PCT_RANGE = (0.20, 0.30)


def describe_strategy_2() -> dict:
    """대시보드 조회용 — 전략 2번(과대낙폭 분할매수)의 진입/청산/운용 규칙."""
    band_pcts_text = "/".join(f"-{p:.0%}" for p in TIER_BAND_PCTS)
    return {
        "entry": [
            f"SK하이닉스(000660) 단일 종목, {BAR_INTERVAL_MINUTES}분봉 {MA_WINDOW}기간 이동평균(60선) 기준",
            f"60선 대비 {band_pcts_text} 밴드를 저가/현재가가 닿을 때마다 각 {TIER_FRACTION:.0%}씩 분할매수(최대 3단)",
            "반등 확인 없이 밴드 터치 즉시 매수 — 확인 대기 시 수익이 소멸하는 패닉성 급락 특성(PDF 실측)",
        ],
        "exit": [
            "고가가 60선에 닿으면 전량 청산(익절)",
            f"평단 대비 -{HARD_STOP_PCT:.0%} 하드스톱",
            f"최초 진입 후 {TIME_EXIT_TRADING_DAYS}거래일 내 60선 미복귀 시 청산(시간청산)",
        ],
        "operation": [
            "3단 초과 추가매수 금지(분할이지 물타기 아님)",
            f"계좌 배정 비중 {RECOMMENDED_ALLOCATION_PCT_RANGE[0]:.0%}~{RECOMMENDED_ALLOCATION_PCT_RANGE[1]:.0%} 이내 권장(--total-capital로 조절)",
            "성과(PDF 백테스트, 2025/07~2026/07): 연 12회 · 평균 +4.20% · 승률 92% · 누적 +50.4% · 평균 보유 1.6일",
        ],
        "exchange_basis": [
            f"{MA_WINDOW}기간 이동평균(추세 판단용 분봉): KRX 단독",
            "실시간 체결가/청산 호가 조회 폴백: 실전 계좌 기준 통합(SOR) — 실제 주문이 체결될 거래소와 일치",
        ],
    }


def compute_ma(candles: pd.DataFrame, window: int = MA_WINDOW) -> pd.Series:
    """종가 기준 단순이동평균. candles는 close 컬럼을 가진 시간순 DataFrame."""
    return candles["close"].rolling(window).mean()


def compute_tier_prices(ma_value: float) -> list[float]:
    """60선 값 기준 1차/2차/3차 밴드 가격을 순서대로 반환 (60선 × 0.91/0.88/0.85)."""
    return [ma_value * (1 - pct) for pct in TIER_BAND_PCTS]


def next_entry_tier(filled_tier_count: int, low_or_current_price: float, ma_value: float) -> int | None:
    """다음 미체결 티어(1-indexed)를 지금 가격이 건드렸으면 그 번호를 반환, 아니면
    None. 이미 3단 전부 체결됐으면 가격과 무관하게 항상 None(3단 초과 매수 금지)."""
    if filled_tier_count >= len(TIER_BAND_PCTS):
        return None
    tier_prices = compute_tier_prices(ma_value)
    next_tier_index = filled_tier_count  # 0-indexed
    if low_or_current_price <= tier_prices[next_tier_index]:
        return next_tier_index + 1
    return None


def should_exit_by_touch(high_or_current_price: float, ma_value: float) -> bool:
    """고가(또는 현재가)가 60선에 닿거나 넘으면 전량 청산 대상."""
    return high_or_current_price >= ma_value


def should_exit_by_hard_stop(current_price: float, avg_entry_price: float) -> bool:
    """평단 대비 -20% 이하로 떨어지면 하드스톱 청산 대상."""
    return (current_price - avg_entry_price) / avg_entry_price <= -HARD_STOP_PCT


def count_trading_days(start: date, end: date) -> int:
    """start(포함) ~ end(포함) 사이의 평일(주말 제외) 수 — orderbook_collector.
    is_market_open과 동일하게 공휴일 캘린더는 미반영."""
    if end < start:
        return 0
    return len(pd.bdate_range(start, end))


def should_exit_by_time(entry_date: date, today: date, trading_days: int = TIME_EXIT_TRADING_DAYS) -> bool:
    """최초 진입일(entry_date, 1일째로 산입) 기준 trading_days 거래일이 지나도록
    아직 60선 터치 청산이 안 됐으면 시간청산 대상."""
    return count_trading_days(entry_date, today) > trading_days
