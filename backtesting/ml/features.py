"""분봉 캔들 → 데이트레이딩용 특징(feature) 생성.

Design: docs/02-design/features/strategy-backtesting.design.md §4.1
각 시점의 특징은 그 시점까지의 데이터만 사용한다 (rolling/shift 계산은 과거만 참조).
"""
import pandas as pd

from ..indicators import compute_rsi


def build_features(candles: pd.DataFrame) -> pd.DataFrame:
    close = candles["close"]
    volume = candles["volume"]

    features = pd.DataFrame(index=candles.index)
    features["return_1"] = close.pct_change(1)
    features["return_5"] = close.pct_change(5)
    features["momentum_10"] = close / close.shift(10) - 1
    features["volatility_10"] = close.pct_change().rolling(10).std()
    features["volume_ratio_20"] = volume / volume.rolling(20).mean()
    features["rsi_14"] = compute_rsi(close, 14)
    features["high_low_range"] = (candles["high"] - candles["low"]) / close

    return features
