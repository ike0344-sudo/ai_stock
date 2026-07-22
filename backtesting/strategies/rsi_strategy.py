"""RSI 과매도/과매수 전략.

파라미터: period, buy_below, sell_above (예: {"period": 14, "buy_below": 30, "sell_above": 70})
"""
import pandas as pd

from ..indicators import compute_rsi
from ..types import Signal


class RsiStrategy:
    name = "rsi"

    def evaluate(self, candles: pd.DataFrame, params: dict) -> pd.Series:
        rsi = compute_rsi(candles["close"], params["period"])
        buy_below = params["buy_below"]
        sell_above = params["sell_above"]

        signals = pd.Series(Signal.HOLD, index=candles.index)
        signals[rsi < buy_below] = Signal.BUY
        signals[rsi > sell_above] = Signal.SELL
        return signals
