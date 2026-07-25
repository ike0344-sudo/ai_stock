import pandas as pd
import pytest

from backtesting.portfolio_sim import simulate_slot_portfolio
from backtesting.validate_strategy1 import compute_portfolio_metrics, run_walk_forward


def _candidates(rows: list[tuple]) -> pd.DataFrame:
    """rows: (code, entry_time, exit_time, pct) 튜플 목록."""
    return pd.DataFrame(
        [{"code": c, "entry_time": pd.Timestamp(e), "exit_time": pd.Timestamp(x), "pct": p} for c, e, x, p in rows]
    )


def test_compute_portfolio_metrics_matches_hand_calculation():
    candidates = _candidates(
        [
            ("A", "2026-07-20 09:00", "2026-07-20 09:30", 0.04),   # win
            ("B", "2026-07-20 09:10", "2026-07-20 09:40", -0.025), # loss (stop loss)
            ("C", "2026-07-20 09:35", "2026-07-20 10:00", 0.02),   # win
        ]
    )
    result = simulate_slot_portfolio(candidates, initial_capital=10_000_000, max_concurrent_positions=3)

    metrics = compute_portfolio_metrics(result)

    slot = 10_000_000 / 3
    gross_profit = slot * 0.04 + slot * 0.02
    gross_loss = slot * 0.025
    assert metrics["n_trades"] == 3
    assert metrics["win_rate_pct"] == pytest.approx(2 / 3 * 100)
    assert metrics["profit_factor"] == pytest.approx(gross_profit / gross_loss)
    assert metrics["total_return_pct"] == pytest.approx((gross_profit - gross_loss) / 10_000_000 * 100)
    # MDD: B가 손실 후 청산되며 잔고가 peak 대비 얼마나 빠졌는지
    assert metrics["mdd_pct"] > 0


def test_compute_portfolio_metrics_empty_result_is_all_zero():
    result = simulate_slot_portfolio(pd.DataFrame(columns=["code", "entry_time", "exit_time", "pct"]))
    metrics = compute_portfolio_metrics(result)
    assert metrics == {
        "n_trades": 0, "skipped_count": 0, "win_rate_pct": 0.0,
        "profit_factor": 0.0, "avg_r_multiple": 0.0, "total_return_pct": 0.0, "mdd_pct": 0.0,
    }


def test_run_walk_forward_skips_fold_with_insufficient_is_samples():
    # IS 표본이 50개 미만이라 학습이 불가능한 상황 -> 폴드가 에러 없이 skip 처리되어야 함
    rows = [("A", "2026-01-05 09:00", "2026-01-05 09:30", 0.01)]
    rows += [("B", "2026-04-05 09:00", "2026-04-05 09:30", 0.01)]
    trades_df = _candidates(rows)
    for col in ["trade_value_ratio", "return_pct", "momentum_5min", "momentum_10min",
                "volatility_10min", "volume_ratio", "rsi_14", "minutes_since_open", "n_day_high_distance"]:
        trades_df[col] = 0.0

    result = run_walk_forward(trades_df, train_days=60, test_days=30, step_days=30)

    assert len(result["folds"]) >= 1
    assert all(f["status"].startswith("skipped") for f in result["folds"])
    assert result["metrics"]["n_trades"] == 0


def test_run_walk_forward_never_lets_test_start_before_train_end():
    rows = [("A", f"2026-0{m}-05 09:00", f"2026-0{m}-05 09:30", 0.01) for m in range(1, 7)]
    trades_df = _candidates(rows)
    for col in ["trade_value_ratio", "return_pct", "momentum_5min", "momentum_10min",
                "volatility_10min", "volume_ratio", "rsi_14", "minutes_since_open", "n_day_high_distance"]:
        trades_df[col] = 0.0

    result = run_walk_forward(trades_df, train_days=60, test_days=30, step_days=30)

    for f in result["folds"]:
        assert f["train_end"] < f["test_start"]
