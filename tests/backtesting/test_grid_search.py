from datetime import date

import numpy as np
import pandas as pd
import pytest

from backtesting import grid_search
from backtesting.strategies.ma_crossover import MovingAverageCrossover


def _daily_candles(n: int = 40) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=n, freq="B")
    closes = [10.0] * (n // 2) + [20.0] * (n - n // 2)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * n},
        index=index,
    )


def _minute_candles(days: int = 10, per_day: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    frames = []
    for d in range(days):
        day = pd.Timestamp("2026-01-01") + pd.Timedelta(days=d)
        index = pd.date_range(day + pd.Timedelta(hours=9), periods=per_day, freq="1min")
        prices = 100 + np.cumsum(rng.normal(0, 0.15, size=per_day))
        frames.append(
            pd.DataFrame(
                {
                    "open": prices,
                    "high": prices + 0.05,
                    "low": prices - 0.05,
                    "close": prices,
                    "volume": rng.integers(900, 1100, size=per_day),
                },
                index=index,
            )
        )
    return pd.concat(frames)


def test_param_combinations_produces_cartesian_product():
    combos = grid_search._param_combinations({"a": [1, 2], "b": [10]})

    assert combos == [{"a": 1, "b": 10}, {"a": 2, "b": 10}]


def test_run_rule_based_produces_result_per_stock_and_param(monkeypatch):
    candles = _daily_candles()
    monkeypatch.setattr(grid_search, "load_history", lambda *a, **k: candles)

    results = grid_search.run_rule_based(
        client=object(),
        stock_codes=["005930"],
        strategy=MovingAverageCrossover(),
        param_grid={"short_window": [2], "long_window": [5]},
        start=date(2026, 1, 1),
        end=date(2026, 3, 1),
    )

    assert len(results) == 1
    assert results[0].stock_code == "005930"
    assert results[0].params == {"short_window": 2, "long_window": 5}


def test_run_rule_based_computes_benchmark_buy_and_hold_return(monkeypatch):
    """벤치마크(매수 후 보유) 수익률이 OOS 구간 가격으로 정확히 계산되는지 확인.

    실제로 MA 크로스오버 OOS +160%가 벤치마크(매수 후 보유) +285%에 못 미쳐 사실은
    시장을 못 따라간 것으로 드러난 사례를 계기로 추가된 필드."""
    index = pd.date_range("2026-01-01", periods=10, freq="B")
    closes = [10.0] * 7 + [12.0, 14.0, 20.0]  # in_sample_ratio=0.7 -> split_idx=7, OOS=[12,14,20]
    candles = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * 10},
        index=index,
    )
    monkeypatch.setattr(grid_search, "load_history", lambda *a, **k: candles)

    results = grid_search.run_rule_based(
        client=object(), stock_codes=["005930"], strategy=MovingAverageCrossover(),
        param_grid={"short_window": [2], "long_window": [3]},
        start=date(2026, 1, 1), end=date(2026, 1, 20),
    )

    assert len(results) == 1
    expected_benchmark = (20.0 / 12.0 - 1) * 100
    assert results[0].benchmark_oos_return_pct == pytest.approx(expected_benchmark)


def test_run_rule_based_skips_invalid_param_combo(monkeypatch):
    candles = _daily_candles()
    monkeypatch.setattr(grid_search, "load_history", lambda *a, **k: candles)

    results = grid_search.run_rule_based(
        client=object(),
        stock_codes=["005930"],
        strategy=MovingAverageCrossover(),
        param_grid={"short_window": [10], "long_window": [5]},
        start=date(2026, 1, 1),
        end=date(2026, 3, 1),
    )

    assert results == []


def test_run_ml_walk_forward_produces_valid_result_structure(monkeypatch):
    candles = _minute_candles()
    monkeypatch.setattr(grid_search, "load_history", lambda *a, **k: candles)

    results = grid_search.run_ml_walk_forward(
        client=object(),
        stock_codes=["005930"],
        param_grid={"buy_threshold": [0.5]},
        start=date(2026, 1, 1),
        end=date(2026, 1, 10),
        train_days=5,
        test_days=2,
        step_days=2,
        label_horizon_minutes=5,
        label_return_threshold=0.0005,
    )

    for result in results:
        assert result.strategy_name == "ml_day_trading"
        assert result.out_of_sample.num_trades >= 0
        assert result.in_sample.num_trades >= 0
