import os

import numpy as np
import pandas as pd

from backtesting import final_strategy
from backtesting.final_strategy import (
    RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    RECOMMENDED_PROBA_THRESHOLD,
    TOP_N,
    build_training_dataset,
    describe_strategy_1,
    detect_final_entries,
    evaluate_tiered_exit_from_path,
    evaluate_tiered_exit_from_path_with_exit_idx,
    train_and_save_final_model,
)
from backtesting.ml_entry_filter import FEATURE_COLUMNS, load_model, predict_quality_proba


def _daily(dates: list[str], closes: list[float]) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * len(closes)}, index=index
    )


def _rising_minute(day: str, closes: list[float]) -> pd.DataFrame:
    index = pd.date_range(f"{day} 09:00", periods=len(closes), freq="1min")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [20_000_000] * len(closes)},
        index=index,
    )


def test_describe_strategy_1_returns_entry_exit_operation_sections():
    description = describe_strategy_1()

    assert set(description.keys()) == {"entry", "exit", "operation", "exchange_basis"}
    assert all(isinstance(items, list) and len(items) > 0 for items in description.values())
    assert any(str(TOP_N) in line for line in description["entry"])
    assert any(str(RECOMMENDED_PROBA_THRESHOLD) in line for line in description["operation"])
    assert any(str(RECOMMENDED_MAX_CONCURRENT_POSITIONS) in line for line in description["operation"])


def test_detect_final_entries_true_once_all_conditions_align():
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])  # 전일종가 100
    # 단조 증가하는 상승 -> 3분수익률/거래대금/당일신고가/무하락 조건이 자연스럽게 맞음
    minute = _rising_minute("2026-01-02", [100.5, 102, 105, 108, 111, 115, 120])
    daily_top35 = {pd.Timestamp("2026-01-02"): {"000001"}}
    regime_by_day = {pd.Timestamp("2026-01-02"): True}

    entries = detect_final_entries(minute, daily, "000001", daily_top35, regime_by_day)

    # idx0~2는 당일상승률(7%) 미달(각 0.5/2/5%), idx3~6(8/11/15/20%)은 모든 조건 충족
    assert list(entries) == [False, False, False, True, True, True, True]


def test_detect_final_entries_false_when_not_in_top35():
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])
    minute = _rising_minute("2026-01-02", [100.5, 102, 105, 108, 111, 115, 120])
    daily_top35 = {pd.Timestamp("2026-01-02"): {"다른종목"}}  # 000001은 top35에 없음
    regime_by_day = {pd.Timestamp("2026-01-02"): True}

    entries = detect_final_entries(minute, daily, "000001", daily_top35, regime_by_day)

    assert not entries.any()


def test_detect_final_entries_false_when_regime_is_down():
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])
    minute = _rising_minute("2026-01-02", [100.5, 102, 105, 108, 111, 115, 120])
    daily_top35 = {pd.Timestamp("2026-01-02"): {"000001"}}
    regime_by_day = {pd.Timestamp("2026-01-02"): False}  # 코스피 지수 60이평선 아래

    entries = detect_final_entries(minute, daily, "000001", daily_top35, regime_by_day)

    assert not entries.any()


def test_evaluate_tiered_exit_from_path_all_tiers_hit_gives_positive_pnl():
    # 4단계 익절 목표(2.5/4/5.5/7%)를 모두 넘는 순수익률 경로
    path = [(0, 0.03, 0.03), (1, 0.045, 0.045), (2, 0.06, 0.06), (3, 0.08, 0.08)]

    pct = evaluate_tiered_exit_from_path(path)

    assert pct > 0


def test_evaluate_tiered_exit_from_path_with_exit_idx_matches_pct_and_returns_last_leg_idx():
    path = [(0, 0.03, 0.03), (1, 0.045, 0.045), (2, 0.06, 0.06), (3, 0.08, 0.08)]

    pct, exit_idx = evaluate_tiered_exit_from_path_with_exit_idx(path)

    assert pct == evaluate_tiered_exit_from_path(path)
    assert exit_idx == 3  # 마지막 tier가 idx=3에서 발동, 전량 소진되므로 그 지점이 종료 시점


def test_evaluate_tiered_exit_from_path_with_exit_idx_stop_loss_case():
    path = [(0, -0.03, 0.0)]  # 무장 전 즉시 손절

    pct, exit_idx = evaluate_tiered_exit_from_path_with_exit_idx(path)

    assert exit_idx == 0
    assert pct < 0


def test_build_training_dataset_produces_one_row_per_qualifying_entry(tmp_path, monkeypatch):
    daily_dir = tmp_path / "stocks" / "daily"
    minute_dir = tmp_path / "stocks" / "minute"
    daily_dir.mkdir(parents=True)
    minute_dir.mkdir(parents=True)

    _daily(["2026-01-01", "2026-01-02"], [100, 999]).to_csv(daily_dir / "000001.csv")
    _rising_minute("2026-01-02", [100.5, 102, 105, 108, 111, 115, 120]).to_csv(minute_dir / "000001.csv")
    # 코스피 지수 로컬 데이터가 tmp_path에 없으므로, 레짐 판단은 고정값으로 대체
    monkeypatch.setattr(
        final_strategy, "load_kospi_regime_by_day", lambda data_dir: {pd.Timestamp("2026-01-02"): True}
    )

    features_df, labels_s = build_training_dataset(str(tmp_path))

    assert list(features_df.columns) == FEATURE_COLUMNS
    assert len(features_df) == 4  # detect_final_entries 테스트와 동일한 4건(idx3~6)
    assert len(labels_s) == 4
    assert labels_s.isin([0, 1]).all()


def test_train_and_save_final_model_persists_loadable_model(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    synthetic_features = pd.DataFrame({c: rng.normal(size=100) for c in FEATURE_COLUMNS})
    synthetic_labels = pd.Series((synthetic_features["return_pct"] > 0).astype(int))
    monkeypatch.setattr(
        final_strategy, "build_training_dataset", lambda data_dir: (synthetic_features, synthetic_labels)
    )
    model_path = str(tmp_path / "nested" / "entry_filter_model.joblib")

    trained, features_df, labels_s = train_and_save_final_model(
        data_dir="unused", model_path=model_path, n_estimators=10
    )

    assert os.path.exists(model_path)
    loaded = load_model(model_path)
    proba = predict_quality_proba(loaded, features_df)
    assert len(proba) == len(labels_s)
    assert proba.between(0, 1).all()
