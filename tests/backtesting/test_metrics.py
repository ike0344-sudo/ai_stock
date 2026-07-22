from datetime import date

import pandas as pd
import pytest

from backtesting import metrics
from backtesting.types import Trade


def _closed_trade(entry_date, exit_date, entry_price, exit_price, quantity) -> Trade:
    pnl = (exit_price - entry_price) * quantity
    pnl_pct = pnl / (entry_price * quantity)
    return Trade(
        stock_code="TEST",
        entry_date=entry_date,
        entry_price=entry_price,
        quantity=quantity,
        commission=0.0,
        slippage=0.0,
        exit_date=exit_date,
        exit_price=exit_price,
        pnl=pnl,
        pnl_pct=pnl_pct,
    )


def _candles(num_days: int) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=num_days, freq="D")
    return pd.DataFrame({"close": [100.0] * num_days}, index=index)


def test_total_return_matches_sum_of_trade_pnl():
    trades = [
        _closed_trade(date(2026, 1, 1), date(2026, 1, 5), 100, 110, 100),  # +1000
        _closed_trade(date(2026, 1, 6), date(2026, 1, 10), 100, 95, 100),  # -500
    ]

    result = metrics.compute(trades, _candles(20), initial_capital=10_000)

    assert result.total_return_pct == pytest.approx(5.0)  # (1000 - 500) / 10000 * 100
    assert result.num_trades == 2
    assert result.win_rate_pct == pytest.approx(50.0)


def test_max_drawdown_reflects_largest_peak_to_trough_drop():
    trades = [
        _closed_trade(date(2026, 1, 1), date(2026, 1, 5), 100, 101, 100),  # +100 -> equity 10100 (peak)
        _closed_trade(date(2026, 1, 6), date(2026, 1, 10), 100, 99.5, 100),  # -50 -> equity 10050
        _closed_trade(date(2026, 1, 11), date(2026, 1, 15), 100, 100.3, 100),  # +30 -> equity 10080
    ]

    result = metrics.compute(trades, _candles(20), initial_capital=10_000)

    expected_max_drawdown = (10_100 - 10_050) / 10_100 * 100
    assert result.max_drawdown_pct == pytest.approx(expected_max_drawdown)


def test_open_trades_without_pnl_are_excluded():
    open_trade = Trade(
        stock_code="TEST",
        entry_date=date(2026, 1, 1),
        entry_price=100,
        quantity=10,
        commission=0.0,
        slippage=0.0,
    )
    closed = _closed_trade(date(2026, 1, 2), date(2026, 1, 3), 100, 110, 10)

    result = metrics.compute([open_trade, closed], _candles(10), initial_capital=10_000)

    assert result.num_trades == 1
