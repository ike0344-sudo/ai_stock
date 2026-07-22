import numpy as np
import pandas as pd

from backtesting.ml import model as ml_model
from backtesting.ml.features import build_features
from backtesting.ml.labeling import make_labels
from backtesting.strategies.ml_strategy import MLStrategy
from backtesting.types import Signal


def _candles(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    prices = 100 + np.cumsum(rng.normal(0, 0.2, size=n))
    index = pd.date_range("2026-01-01 09:00", periods=n, freq="1min")
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices + 0.1,
            "low": prices - 0.1,
            "close": prices,
            "volume": rng.integers(900, 1100, size=n),
        },
        index=index,
    )


def test_ml_strategy_emits_only_buy_and_hold():
    candles = _candles()
    features = build_features(candles)
    labels = make_labels(candles, horizon_minutes=5, return_threshold=0.001)

    trained = ml_model.train(features, labels, model_type="random_forest", n_estimators=10)

    signals = MLStrategy().evaluate(candles, {"model": trained, "buy_threshold": 0.5})

    assert set(signals.unique()).issubset({Signal.BUY, Signal.HOLD})
