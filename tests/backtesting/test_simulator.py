import pandas as pd

from backtesting import simulator
from backtesting.types import Signal


def _candles_and_signals(closes: list[float], signal_map: dict[int, Signal]) -> tuple[pd.DataFrame, pd.Series]:
    index = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    candles = pd.DataFrame({"close": closes}, index=index)
    signals = pd.Series(Signal.HOLD, index=index)
    for i, signal in signal_map.items():
        signals.iloc[i] = signal
    return candles, signals


def test_buy_then_sell_applies_commission_and_slippage():
    candles, signals = _candles_and_signals(
        [100, 100, 110, 110], {1: Signal.BUY, 3: Signal.SELL}
    )

    trades = simulator.run(
        candles, signals, commission_rate=0.01, slippage_rate=0.01, initial_capital=10_000
    )

    assert len(trades) == 1
    trade = trades[0]
    expected_entry_price = 100 * 1.01
    expected_exit_price = 110 * 0.99
    assert trade.entry_price == expected_entry_price
    assert trade.exit_price == expected_exit_price
    assert trade.quantity == int(10_000 // expected_entry_price)
    assert trade.pnl is not None
    expected_gross = (expected_exit_price - expected_entry_price) * trade.quantity
    expected_cost = trade.commission
    assert trade.pnl == expected_gross - expected_cost


def test_force_eod_close_liquidates_open_position_at_day_end():
    index = pd.to_datetime(
        ["2026-01-01 09:00", "2026-01-01 09:05", "2026-01-01 15:20", "2026-01-02 09:00"]
    )
    candles = pd.DataFrame({"close": [100, 105, 108, 120]}, index=index)
    signals = pd.Series(
        [Signal.BUY, Signal.HOLD, Signal.HOLD, Signal.HOLD], index=index
    )

    trades = simulator.run(
        candles,
        signals,
        commission_rate=0.0,
        slippage_rate=0.0,
        initial_capital=10_000,
        force_eod_close=True,
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_price == 108
    assert trade.pnl is not None


def test_unclosed_position_included_without_pnl():
    candles, signals = _candles_and_signals([100, 105], {0: Signal.BUY})

    trades = simulator.run(
        candles, signals, commission_rate=0.0, slippage_rate=0.0, initial_capital=10_000
    )

    assert len(trades) == 1
    assert trades[0].pnl is None
    assert trades[0].exit_price is None
