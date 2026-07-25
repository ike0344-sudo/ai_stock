import numpy as np
import pandas as pd
import pytest

from backtesting import ml_reversal
from backtesting.breakout_reversal import simulate_trade_path
from backtesting.ml_reversal import (
    FEATURE_COLUMNS,
    TrainedReversalModel,
    build_training_examples,
    extract_armed_features,
    predict_success_probability,
    simulate_trade_path_with_ml_exit,
    train_reversal_model,
)


def _candles(day: str, closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    index = pd.date_range(f"{day} 09:00", periods=len(closes), freq="1min")
    volumes = volumes or [1000] * len(closes)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": volumes}, index=index
    )


def test_extract_armed_features_skips_points_below_arm_threshold():
    candles = _candles("2026-01-01", [100, 100.2, 100.3])  # peak net pct 작음, 무장 안 됨
    path = simulate_trade_path(candles, entry_idx=0, take_profit_pct=0.10, stop_loss_pct=0.10)

    features = extract_armed_features(candles, path, breakeven_arm_pct=0.01)

    assert features.empty


def test_extract_armed_features_includes_points_after_arming():
    # 체결시점 보수화로 진입은 idx1의 시가(101)에서 체결되고, idx2에서 +2.5% 근접 -> 무장
    candles = _candles("2026-01-01", [100, 101, 104, 102, 100.5])
    path = simulate_trade_path(candles, entry_idx=0, take_profit_pct=0.10, stop_loss_pct=0.10)

    features = extract_armed_features(candles, path, breakeven_arm_pct=0.01)

    assert not features.empty
    assert set(FEATURE_COLUMNS).issubset(features.columns)


def test_build_training_examples_labels_by_final_outcome():
    # 체결시점 보수화(다음 봉 시가 체결)를 감안해 익절/무장 후 손절 경로에 각각
    # 상승 지속 봉을 추가했다.
    winning = _candles("2026-01-01", [100, 101, 104, 108, 108])  # take_profit
    losing = _candles("2026-01-02", [100, 101, 104, 100, 96])  # 무장 후 stop_loss

    win_path = simulate_trade_path(winning, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02)
    lose_path = simulate_trade_path(losing, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02)

    features_win, labels_win = build_training_examples(winning, [win_path], breakeven_arm_pct=0.01)
    features_lose, labels_lose = build_training_examples(losing, [lose_path], breakeven_arm_pct=0.01)

    if not labels_win.empty:
        assert (labels_win == 1).all()
    if not labels_lose.empty:
        assert (labels_lose == 0).all()


def test_train_reversal_model_raises_on_insufficient_samples():
    features = pd.DataFrame([{c: 0.0 for c in FEATURE_COLUMNS}] * 5)
    labels = pd.Series([0, 1, 0, 1, 0])

    with pytest.raises(ml_reversal.InsufficientTrainingDataError):
        train_reversal_model(features, labels)


def test_train_reversal_model_raises_on_single_class():
    features = pd.DataFrame([{c: 0.0 for c in FEATURE_COLUMNS}] * 60)
    labels = pd.Series([1] * 60)

    with pytest.raises(ml_reversal.InsufficientTrainingDataError):
        train_reversal_model(features, labels)


def test_train_and_predict_round_trip():
    rng = np.random.default_rng(0)
    features = pd.DataFrame({c: rng.normal(size=100) for c in FEATURE_COLUMNS})
    labels = pd.Series((features["current_net_pct"] > 0).astype(int))

    trained = train_reversal_model(features, labels, model_type="random_forest", n_estimators=10)
    proba = predict_success_probability(trained, features)

    assert len(proba) == 100
    assert proba.between(0, 1).all()


class _StubModel:
    """predict_proba가 인덱스 순서대로 미리 정해둔 확률을 반환하는 스텁."""

    def __init__(self, probabilities: list[float]):
        self._probabilities = iter(probabilities)

    def predict_proba(self, X):
        p = next(self._probabilities)
        return np.array([[1 - p, p]])


def test_simulate_trade_path_with_ml_exit_fires_early_on_low_success_probability():
    # 무장 후에도 계속 completes 하지만 손절/익절에 닿지 않는 경로 -> ML이 조기 개입해야 확인 가능
    candles = _candles("2026-01-01", [100, 101.5, 101, 100.8, 100.6, 100.5])
    trained = TrainedReversalModel(model=_StubModel([0.9, 0.2]))  # 2번째 armed 시점에 반전 예측

    result = simulate_trade_path_with_ml_exit(
        candles, entry_idx=0, trained=trained,
        take_profit_pct=0.10, stop_loss_pct=0.10, breakeven_arm_pct=0.005,
    )

    assert result.exit_reason == "ml_breakeven"


def test_simulate_trade_path_with_ml_exit_respects_take_profit_before_ml_check():
    candles = _candles("2026-01-01", [100, 104])  # 즉시 익절
    trained = TrainedReversalModel(model=_StubModel([0.0] * 5))  # 항상 반전 예측이어도

    result = simulate_trade_path_with_ml_exit(
        candles, entry_idx=0, trained=trained,
        take_profit_pct=0.03, stop_loss_pct=0.02, breakeven_arm_pct=0.01,
    )

    assert result.exit_reason == "take_profit"


def test_simulate_trade_path_with_ml_exit_does_not_fire_before_armed():
    candles = _candles("2026-01-01", [100, 100.2, 100.3, 100.4])  # 무장 임계값 미도달
    trained = TrainedReversalModel(model=_StubModel([]))  # 호출되면 StopIteration으로 실패해야 정상

    result = simulate_trade_path_with_ml_exit(
        candles, entry_idx=0, trained=trained,
        take_profit_pct=0.10, stop_loss_pct=0.10, breakeven_arm_pct=0.05,
    )

    assert result.exit_reason == "eod"
