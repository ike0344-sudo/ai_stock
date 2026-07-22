"""학습된 모델을 Strategy 인터페이스로 래핑.

파라미터: model (ml.model.TrainedModel), buy_threshold (float)
매도/청산은 simulator의 force_eod_close가 담당한다 (데이트레이딩 — 당일 강제 청산).
"""
import pandas as pd

from ..ml.features import build_features
from ..ml.model import predict
from ..types import Signal


class MLStrategy:
    name = "ml_day_trading"

    def evaluate(self, candles: pd.DataFrame, params: dict) -> pd.Series:
        trained_model = params["model"]
        buy_threshold = params["buy_threshold"]

        features = build_features(candles)
        proba = predict(trained_model, features)

        signals = pd.Series(Signal.HOLD, index=candles.index)
        signals[proba >= buy_threshold] = Signal.BUY
        return signals
