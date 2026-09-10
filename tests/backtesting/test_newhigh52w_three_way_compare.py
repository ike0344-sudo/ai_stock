import pandas as pd
import pytest

from backtesting.newhigh52w_three_way_compare import add_winner_columns, win_summary


def _row(def_name="5_20", variant="a", portfolio_ret=0.0, universe_ret=0.0):
    return {"def": def_name, "variant": variant, "portfolio_ret": portfolio_ret, "ctrl_universe_ret": universe_ret}


def test_strategy_beats_both_requires_positive_and_above_universe():
    df = pd.DataFrame([
        _row(portfolio_ret=0.10, universe_ret=0.05),   # 전략 1등(현금·유니버스 둘 다 이김)
        _row(portfolio_ret=-0.02, universe_ret=-0.05),  # 유니버스는 이겨도 현금(0%)엔 짐 -> 1등 아님
        _row(portfolio_ret=0.03, universe_ret=0.08),    # 현금은 이겨도 유니버스에 짐 -> 1등 아님
    ])

    out = add_winner_columns(df)

    assert list(out["strategy_beats_both"]) == [True, False, False]
    assert list(out["winner"]) == ["portfolio", "cash", "universe"]


def test_win_summary_counts_per_def_variant_combo():
    df = pd.DataFrame([
        _row("5_20", "a", 0.10, 0.05),
        _row("5_20", "a", -0.01, -0.05),
        _row("5_20", "b", 0.20, 0.05),
    ])

    out = add_winner_columns(df)
    summary = win_summary(out).set_index(["def", "variant"])

    assert summary.loc[("5_20", "a"), "n_windows"] == 2
    assert summary.loc[("5_20", "a"), "n_wins"] == 1
    assert summary.loc[("5_20", "a"), "win_rate"] == pytest.approx(0.5)
    assert summary.loc[("5_20", "b"), "n_wins"] == 1
