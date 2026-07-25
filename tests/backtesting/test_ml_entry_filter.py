import numpy as np
import pandas as pd
import pytest

from backtesting import ml_entry_filter
from backtesting.breakout_reversal import simulate_trade_path
from backtesting.ml_entry_filter import (
    FEATURE_COLUMNS,
    TrainedEntryFilterModel,
    build_training_examples,
    extract_entry_features,
    load_model,
    predict_live_quality,
    predict_quality_proba,
    save_model,
    train_entry_filter_model,
)


def _candles(day: str, closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    index = pd.date_range(f"{day} 09:00", periods=len(closes), freq="1min")
    volumes = volumes or [1000] * len(closes)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": volumes}, index=index
    )


def _daily(dates: list[str], highs: list[float]) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    return pd.DataFrame({"open": highs, "high": highs, "low": highs, "close": highs, "volume": [1000] * len(highs)}, index=index)


def test_extract_entry_features_returns_all_columns_without_nan():
    candles = _candles("2026-01-01", [100, 100.5, 101, 101.8, 102.5])

    features = extract_entry_features(candles, entry_idx=4, window_minutes=3, min_trade_value=1_000_000)

    assert set(features.keys()) == set(FEATURE_COLUMNS)
    assert not any(pd.isna(v) for v in features.values())


def test_extract_entry_features_n_day_high_distance_excludes_current_day():
    # 당일(01-02)의 고가 999는 shift(1) 덕분에 참조에서 제외되어야 한다 (미래 데이터 누수 방지)
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])
    minute = _candles("2026-01-02", [150])

    features = extract_entry_features(minute, entry_idx=0, daily_candles=daily, n_day_high=1)

    # 참조값은 01-01의 100이어야 하므로 (150-100)/100 = 0.5
    assert features["n_day_high_distance"] == pytest.approx(0.5)


def test_build_training_examples_labels_by_final_outcome():
    # 체결시점 보수화(진입/청산 모두 다음 봉 시가 체결)로 인해 익절까지 한 봉 더
    # 여유가 필요해져, winning 경로에 상승 지속 봉을 추가했다.
    winning = _candles("2026-01-01", [100, 101, 104, 108, 108])  # take_profit
    losing = _candles("2026-01-02", [100, 101.5, 98])  # stop_loss

    win_path = simulate_trade_path(winning, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02)
    lose_path = simulate_trade_path(losing, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02)

    features_win, labels_win = build_training_examples(winning, [win_path])
    features_lose, labels_lose = build_training_examples(losing, [lose_path])

    assert list(labels_win) == [1]
    assert list(labels_lose) == [0]
    assert list(features_win.columns) == FEATURE_COLUMNS


def test_train_entry_filter_model_raises_on_insufficient_samples():
    features = pd.DataFrame([{c: 0.0 for c in FEATURE_COLUMNS}] * 5)
    labels = pd.Series([0, 1, 0, 1, 0])

    with pytest.raises(ml_entry_filter.InsufficientTrainingDataError):
        train_entry_filter_model(features, labels)


def test_train_entry_filter_model_raises_on_single_class():
    features = pd.DataFrame([{c: 0.0 for c in FEATURE_COLUMNS}] * 60)
    labels = pd.Series([1] * 60)

    with pytest.raises(ml_entry_filter.InsufficientTrainingDataError):
        train_entry_filter_model(features, labels)


def test_train_and_predict_round_trip():
    rng = np.random.default_rng(0)
    features = pd.DataFrame({c: rng.normal(size=100) for c in FEATURE_COLUMNS})
    labels = pd.Series((features["return_pct"] > 0).astype(int))

    trained = train_entry_filter_model(features, labels, model_type="random_forest", n_estimators=10)
    proba = predict_quality_proba(trained, features)

    assert len(proba) == 100
    assert proba.between(0, 1).all()


def test_train_and_predict_round_trip_with_hist_gradient_boosting():
    # LightGBM 대체용 — Windows 보안정책(WinError 4551)이 lightgbm 네이티브 DLL 로딩을
    # 막아서 같은 계열(히스토그램 기반 gradient boosting)의 sklearn 내장 구현을 씀
    rng = np.random.default_rng(0)
    features = pd.DataFrame({c: rng.normal(size=100) for c in FEATURE_COLUMNS})
    labels = pd.Series((features["return_pct"] > 0).astype(int))

    trained = train_entry_filter_model(features, labels, model_type="hist_gradient_boosting", max_iter=10)
    proba = predict_quality_proba(trained, features)

    assert len(proba) == 100
    assert proba.between(0, 1).all()


def test_predict_quality_proba_empty_features_returns_empty_series():
    trained = TrainedEntryFilterModel(model=None)

    result = predict_quality_proba(trained, pd.DataFrame(columns=FEATURE_COLUMNS))

    assert result.empty


def _trained_model():
    rng = np.random.default_rng(0)
    features = pd.DataFrame({c: rng.normal(size=100) for c in FEATURE_COLUMNS})
    labels = pd.Series((features["return_pct"] > 0).astype(int))
    return train_entry_filter_model(features, labels, model_type="random_forest", n_estimators=10)


def test_save_and_load_model_round_trip_produces_same_predictions(tmp_path):
    trained = _trained_model()
    path = str(tmp_path / "model.joblib")

    save_model(trained, path)
    loaded = load_model(path)

    sample = pd.DataFrame([{c: 0.0 for c in FEATURE_COLUMNS}])
    original_proba = predict_quality_proba(trained, sample)
    loaded_proba = predict_quality_proba(loaded, sample)
    assert loaded_proba.iloc[0] == pytest.approx(original_proba.iloc[0])


def test_predict_live_quality_matches_manual_extract_and_predict():
    trained = _trained_model()
    candles = _candles("2026-01-01", [100, 100.5, 101, 101.8, 102.5])

    live_proba = predict_live_quality(trained, candles, entry_idx=4, window_minutes=3, min_trade_value=1_000_000)

    features = extract_entry_features(candles, entry_idx=4, window_minutes=3, min_trade_value=1_000_000)
    features_df = pd.DataFrame([features])[FEATURE_COLUMNS]
    expected = predict_quality_proba(trained, features_df).iloc[0]

    assert live_proba == pytest.approx(expected)
    assert 0.0 <= live_proba <= 1.0
