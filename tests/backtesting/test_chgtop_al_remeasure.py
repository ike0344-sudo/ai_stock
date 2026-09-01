import pandas as pd
import pytest

from backtesting.chgtop_al_remeasure import covered_dates, swap_pairwise_summary


def test_covered_dates_drops_out_of_safe_range_and_keeps_valid():
    out = covered_dates(["2026-07-01", "1999-01-01", "2026-07-02", "2026-09-15"])

    assert out == ["2026-07-01", "2026-07-02"]


def test_swap_pairwise_summary_computes_mean_diff_and_handles_empty():
    sw = pd.DataFrame({
        "date": ["2026-07-01", "2026-07-01", "2026-07-02"],
        "new_ret_1m": [0.01, 0.02, 0.03],
        "old_ret_1m": [0.00, 0.01, 0.01],
        "new_ret_3m": [None, None, None],
        "old_ret_3m": [None, None, None],
        "new_ret_5m": [0.01, 0.02, 0.03],
        "old_ret_5m": [0.00, 0.01, 0.01],
        "new_ret_10m": [0.01, 0.02, 0.03],
        "old_ret_10m": [0.00, 0.01, 0.01],
    })

    out = swap_pairwise_summary(sw, "IS")

    row_1m = out[out["horizon"] == "1m"].iloc[0]
    assert row_1m["n"] == 3
    # diffs = [0.01-0.00, 0.02-0.01, 0.03-0.01] = [0.01, 0.01, 0.02] -> 평균 0.01333 = 1.333%p
    assert row_1m["diff_mean_pct"] == pytest.approx(1.3333333, rel=1e-4)

    row_3m = out[out["horizon"] == "3m"].iloc[0]
    assert row_3m["n"] == 0  # 전부 NaN인 호라이즌은 0건으로 빠져야 한다
