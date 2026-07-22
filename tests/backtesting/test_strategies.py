import pandas as pd
import pytest

from backtesting.strategies.ma_crossover import MovingAverageCrossover
from backtesting.strategies.rsi_strategy import RsiStrategy
from backtesting.types import Signal


def _candles(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({"close": closes}, index=index)


def test_ma_crossover_buy_on_golden_cross():
    closes = [10, 10, 10, 10, 10, 10, 20, 20, 20, 20, 20, 20]
    candles = _candles(closes)

    signals = MovingAverageCrossover().evaluate(candles, {"short_window": 2, "long_window": 4})

    assert (signals == Signal.BUY).sum() >= 1
    assert (signals == Signal.SELL).sum() == 0


def test_ma_crossover_sell_on_dead_cross():
    closes = [20, 20, 20, 20, 20, 20, 10, 10, 10, 10, 10, 10]
    candles = _candles(closes)

    signals = MovingAverageCrossover().evaluate(candles, {"short_window": 2, "long_window": 4})

    assert (signals == Signal.SELL).sum() >= 1
    assert (signals == Signal.BUY).sum() == 0


def test_ma_crossover_rejects_invalid_window_order():
    candles = _candles([10] * 10)

    with pytest.raises(ValueError):
        MovingAverageCrossover().evaluate(candles, {"short_window": 20, "long_window": 5})


def test_rsi_buy_signal_on_sustained_decline():
    closes = [100 - i for i in range(20)]
    candles = _candles(closes)

    signals = RsiStrategy().evaluate(candles, {"period": 14, "buy_below": 30, "sell_above": 70})

    assert (signals == Signal.BUY).sum() >= 1
    assert (signals == Signal.SELL).sum() == 0


def test_rsi_sell_signal_on_sustained_rally():
    closes = [100 + i for i in range(20)]
    candles = _candles(closes)

    signals = RsiStrategy().evaluate(candles, {"period": 14, "buy_below": 30, "sell_above": 70})

    assert (signals == Signal.SELL).sum() >= 1
    assert (signals == Signal.BUY).sum() == 0
