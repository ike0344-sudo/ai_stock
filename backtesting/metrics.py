"""거래 목록으로부터 성과 지표를 계산.

Design: docs/02-design/features/strategy-backtesting.design.md §4.1
"""
import math

import pandas as pd

from .types import PerformanceMetrics, Trade


def compute(trades: list[Trade], candles: pd.DataFrame, initial_capital: float) -> PerformanceMetrics:
    """완결된(pnl이 있는) 거래만 집계 대상으로 한다."""
    closed = sorted((t for t in trades if t.pnl is not None), key=lambda t: t.exit_date)

    total_pnl = sum(t.pnl for t in closed)
    total_return_pct = (total_pnl / initial_capital * 100) if initial_capital else 0.0

    trading_days = candles.index.normalize().nunique()
    cagr_pct = _cagr_pct(total_pnl, initial_capital, trading_days)

    wins = [t for t in closed if t.pnl > 0]
    win_rate_pct = (len(wins) / len(closed) * 100) if closed else 0.0

    return PerformanceMetrics(
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        win_rate_pct=win_rate_pct,
        max_drawdown_pct=_max_drawdown_pct(closed, initial_capital),
        sharpe_ratio=_sharpe_ratio(closed),
        num_trades=len(closed),
    )


def buy_and_hold_return_pct(candles: pd.DataFrame) -> float:
    """같은 구간을 그냥 매수 후 보유했을 때의 수익률 (전략 성과 비교용 벤치마크).

    실제 백테스트에서 전략의 raw 수익률만 보고 "좋다"고 판단했다가, 벤치마크와
    비교하니 시장 상승분도 못 따라간 경우가 있어 추가됨.
    """
    if candles.empty:
        return 0.0
    return (candles["close"].iloc[-1] / candles["close"].iloc[0] - 1) * 100


def _cagr_pct(total_pnl: float, initial_capital: float, trading_days: int) -> float:
    years = trading_days / 252
    if years <= 0 or initial_capital <= 0:
        return 0.0
    final_capital = initial_capital + total_pnl
    if final_capital <= 0:
        return -100.0
    return ((final_capital / initial_capital) ** (1 / years) - 1) * 100


def _max_drawdown_pct(closed_trades: list[Trade], initial_capital: float) -> float:
    equity = initial_capital
    peak = equity
    max_drawdown = 0.0
    for trade in closed_trades:
        equity += trade.pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown * 100


def _sharpe_ratio(closed_trades: list[Trade], risk_free_rate: float = 0.0) -> float:
    # 거래 단위 수익률의 Sharpe 근사치. 일별 수익률 기준 표준 공식과 다르며,
    # 거래 횟수가 적으면(<2) 통계적으로 무의미해 0을 반환한다.
    returns = [t.pnl_pct for t in closed_trades if t.pnl_pct is not None]
    if len(returns) < 2:
        return 0.0

    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance)
    if std_dev == 0:
        return 0.0

    return (mean_return - risk_free_rate) / std_dev * math.sqrt(len(returns))
