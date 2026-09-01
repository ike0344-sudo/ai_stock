import numpy as np
import pandas as pd
import pytest

from backtesting.daily_bar_prereg_measure import (
    add_features,
    build_calendar,
    intraday_only_return,
    portfolio_return,
    quintile_groups,
    rebalance_grid,
)


def test_add_features_computes_ret_5d_and_clv():
    df = pd.DataFrame({
        "code": ["A"] * 7,
        "date": [f"2026-01-0{i}" for i in range(1, 8)],
        "open": [100] * 7, "high": [110, 110, 110, 110, 110, 110, 120],
        "low": [90] * 7, "close": [100, 101, 102, 103, 104, 105, 110],
    })

    out = add_features(df)

    # 6번째 행(인덱스5, close=105) ret_5d = close[5]/close[0]-1 = 105/100-1
    assert out.loc[5, "ret_5d"] == pytest.approx(0.05)
    assert out.loc[0, "clv"] == pytest.approx((100 - 90) / (110 - 90))


def test_add_features_clv_nan_when_high_equals_low():
    df = pd.DataFrame({"code": ["A"], "date": ["2026-01-01"], "open": [100],
                        "high": [100], "low": [100], "close": [100]})

    out = add_features(df)

    assert np.isnan(out.loc[0, "clv"])


def test_rebalance_grid_respects_lookback_and_lookahead_bounds():
    calendar = [f"d{i}" for i in range(20)]  # 20개 거래일, HORIZON=5 필요

    grid = rebalance_grid(calendar)

    # 첫 인덱스는 최소 5(ret_5d 여유), 마지막은 i+1+5 < 20 을 만족해야 함
    assert grid[0] == 5
    assert all(i + 1 + 5 < len(calendar) for i in grid)


def test_quintile_groups_splits_lowest_and_highest():
    cross = pd.DataFrame({"code": [f"c{i}" for i in range(10)], "ret_5d": list(range(10))})

    q1, q5 = quintile_groups(cross, "ret_5d")

    assert set(q1) == {"c0", "c1"}  # 최하위 20%
    assert set(q5) == {"c8", "c9"}  # 최상위 20%


def test_quintile_groups_returns_empty_when_all_values_tied():
    cross = pd.DataFrame({"code": ["a", "b", "c"], "ret_5d": [1.0, 1.0, 1.0]})

    q1, q5 = quintile_groups(cross, "ret_5d")

    assert q1 == [] and q5 == []


def test_portfolio_return_averages_equal_weighted_returns():
    pivot_open = pd.DataFrame({"a": [100.0], "b": [200.0]}, index=["2026-01-02"])
    pivot_close = pd.DataFrame({"a": [110.0], "b": [220.0]}, index=["2026-01-09"])

    mean_ret, n = portfolio_return(["a", "b"], "2026-01-02", "2026-01-09", pivot_open, pivot_close)

    assert mean_ret == pytest.approx(0.10)  # 둘 다 +10%
    assert n == 2


def test_intraday_only_return_compounds_daily_open_to_close_and_ignores_gaps():
    dates = ["d1", "d2"]
    # d1: 100->110(+10%), d2: 120->132(+10%, 갭업은 무시 - open이 120이라 전날종가110과 다름)
    pivot_open = pd.DataFrame({"a": [100.0, 120.0]}, index=dates)
    pivot_close = pd.DataFrame({"a": [110.0, 132.0]}, index=dates)

    mean_ret, n = intraday_only_return(["a"], dates, 0, pivot_open, pivot_close)

    assert mean_ret == pytest.approx(1.10 * 1.10 - 1)  # 갭 제외, 장중수익률만 복리
    assert n == 1
