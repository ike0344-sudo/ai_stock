"""strategy-backtesting에서 공유하는 데이터 타입.

Design: docs/02-design/features/strategy-backtesting.design.md §3.1
"""
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

import pandas as pd

PRICE_LIMIT_PCT = 0.30  # 코스피/코스닥 상하한가 기준 (전일 종가 대비 ±30%)
PRICE_LIMIT_TOLERANCE_PCT = 0.005  # 호가단위 반올림 오차를 흡수하기 위한 여유폭


def prev_day_close_series(candles: pd.DataFrame) -> pd.Series:
    """일자(정규화)별 전일 종가 Series. candles 안에 그 이전 거래일 데이터가 없으면
    (예: 시뮬레이션 대상 구간의 첫날) 해당 일자는 NaN — 상하한가 판정 불가로
    체결 가능 취급한다(알 수 없는 값으로 거래를 막지 않는 쪽을 선택)."""
    daily_close = candles.groupby(candles.index.normalize())["close"].last()
    return daily_close.shift(1)


def is_price_limit_locked(price: float, prev_close: float) -> bool:
    """전일 종가 대비 ±PRICE_LIMIT_PCT 근처면 상하한가 고정으로 보고 체결 불가 처리."""
    if pd.isna(prev_close):
        return False
    upper = prev_close * (1 + PRICE_LIMIT_PCT)
    lower = prev_close * (1 - PRICE_LIMIT_PCT)
    return price >= upper * (1 - PRICE_LIMIT_TOLERANCE_PCT) or price <= lower * (1 + PRICE_LIMIT_TOLERANCE_PCT)


class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Trade:
    stock_code: str
    entry_date: date
    entry_price: float
    quantity: int
    commission: float
    slippage: float
    exit_date: date | None = None
    exit_price: float | None = None
    pnl: float | None = None
    pnl_pct: float | None = None


@dataclass
class PerformanceMetrics:
    total_return_pct: float
    cagr_pct: float
    win_rate_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    num_trades: int


@dataclass
class GridSearchResult:
    stock_code: str
    strategy_name: str
    params: dict
    in_sample: PerformanceMetrics
    out_of_sample: PerformanceMetrics
    trades: list[Trade] = field(default_factory=list)
    # 같은 구간을 그냥 매수 후 보유했을 때의 수익률. 전략 수익률만 보면 "시장이 올라서
    # 번 것"과 "전략이 잘해서 번 것"을 구분 못 하는 문제가 실제 백테스트에서 발견되어 추가.
    benchmark_is_return_pct: float = 0.0
    benchmark_oos_return_pct: float = 0.0
