"""이동평균 크로스오버 전략.

파라미터: short_window, long_window (예: {"short_window": 5, "long_window": 20})
"""
import pandas as pd

from ..types import Signal


class MovingAverageCrossover:
    name = "ma_crossover"

    def evaluate(self, candles: pd.DataFrame, params: dict) -> pd.Series:
        short_window = params["short_window"]
        long_window = params["long_window"]
        if short_window >= long_window:
            raise ValueError("short_window는 long_window보다 작아야 합니다")

        short_ma = candles["close"].rolling(short_window).mean()
        long_ma = candles["close"].rolling(long_window).mean()

        cross_up = (short_ma > long_ma) & (short_ma.shift(1) <= long_ma.shift(1))
        cross_down = (short_ma < long_ma) & (short_ma.shift(1) >= long_ma.shift(1))

        signals = pd.Series(Signal.HOLD, index=candles.index)
        signals[cross_up] = Signal.BUY
        signals[cross_down] = Signal.SELL
        return signals
