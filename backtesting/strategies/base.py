"""전략 인터페이스.

stock-auto-trading의 실시간 전략도 동일 시그니처(evaluate)를 구현해야 함.
Design: docs/02-design/features/strategy-backtesting.design.md §4.2
"""
from typing import Protocol

import pandas as pd


class Strategy(Protocol):
    name: str

    def evaluate(self, candles: pd.DataFrame, params: dict) -> pd.Series:
        """candles(OHLCV, date index)를 받아 각 행에 대한 Signal을 반환."""
        ...
