import numpy as np
import pandas as pd
import pytest

from backtesting.newhigh52w_rolling_windows import correlation_table, loss_stats_table, rolling_windows


def test_rolling_windows_steps_by_3_months_and_spans_12_months_each():
    windows = rolling_windows("2020-05-01", "2020-11-01", step_months=3)

    assert windows == [
        ("2020-05-01", "2021-04-30"),
        ("2020-08-01", "2021-07-31"),
        ("2020-11-01", "2021-10-31"),
    ]


def test_rolling_windows_last_window_matches_prior_round_exactly():
    windows = rolling_windows("2025-09-01", "2025-09-01", step_months=3)

    assert windows == [("2025-09-01", "2026-08-31")]  # 2차 라운드의 "재사용 구간"과 동일


def test_correlation_table_negative_when_excess_rises_as_universe_falls():
    # x=유니버스, y=초과분: 유니버스가 낮을수록(하락장) 초과분이 커지는 관계 -> corr<0
    df = pd.DataFrame({
        "def": ["5_20"] * 4, "variant": ["a"] * 4,
        "ctrl_universe_ret": [-0.10, -0.02, 0.05, 0.20],
        "excess_vs_universe": [0.15, 0.05, -0.03, -0.18],
    })

    table = correlation_table(df)

    assert len(table) == 1
    assert table.loc[0, "corr"] < 0
    assert table.loc[0, "sign"] == "음(-)"


def test_correlation_table_nan_when_fewer_than_two_points():
    df = pd.DataFrame({"def": ["5_20"], "variant": ["a"], "ctrl_universe_ret": [0.1],
                        "excess_vs_universe": [0.05]})

    table = correlation_table(df)

    assert np.isnan(table.loc[0, "corr"])
    assert table.loc[0, "sign"] == "N/A"


def test_loss_stats_table_finds_worst_trade_and_counts_beyond_stop():
    pooled = {
        "a_stop8_target24": pd.DataFrame({"net_pct": [0.1, -0.09, -0.30, 0.02]}),
        "c_no_exit": pd.DataFrame({"net_pct": [0.5, -0.60, -0.01]}),
    }

    table = loss_stats_table(pooled).set_index("variant")

    assert table.loc["a_stop8_target24", "worst_single_trade_pct"] == pytest.approx(-0.30)
    assert table.loc["a_stop8_target24", "n_losses_beyond_stop8pct"] == 2  # -0.09, -0.30 둘 다 -8% 초과
    assert table.loc["c_no_exit", "worst_single_trade_pct"] == pytest.approx(-0.60)


def test_loss_stats_table_empty_variant_reports_zero_not_dropped():
    pooled = {"b_stop8_notarget": pd.DataFrame(columns=["net_pct"])}

    table = loss_stats_table(pooled)

    assert len(table) == 1
    assert table.loc[0, "n_pooled_trades"] == 0
    assert np.isnan(table.loc[0, "worst_single_trade_pct"])
