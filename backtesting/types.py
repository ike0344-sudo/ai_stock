"""strategy-backtesting에서 공유하는 데이터 타입.

Design: docs/02-design/features/strategy-backtesting.design.md §3.1
"""
from dataclasses import dataclass, field
from datetime import date
from enum import Enum


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
