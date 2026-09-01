import pandas as pd
import pytest

from backtesting.swap_signal_validation import date_concentration, pairwise_table, standalone_net_table


def _sw():
    return pd.DataFrame({
        "date": ["2026-07-01", "2026-07-01", "2026-07-02"],
        "new_ret_1m": [0.02, 0.02, 0.01],
        "old_ret_1m": [0.00, 0.00, 0.00],
        "new_ret_3m": [0.02, 0.02, 0.01],
        "old_ret_3m": [0.00, 0.00, 0.00],
        "new_ret_5m": [0.02, 0.02, 0.01],
        "old_ret_5m": [0.00, 0.00, 0.00],
        "new_ret_10m": [0.02, 0.02, 0.01],
        "old_ret_10m": [0.00, 0.00, 0.00],
    })


def test_date_concentration_flags_the_dominant_day():
    out = date_concentration(_sw(), "1m")

    # 07-01 이 diff 합의 (0.02+0.02)/(0.02+0.02+0.01) = 0.8 = 80% - 압도적.
    assert out.iloc[0]["date"] == "2026-07-01"
    assert out.iloc[0]["share_of_total"] == pytest.approx(0.8)


def test_standalone_net_table_subtracts_cost_and_keeps_two_constants_separate():
    out = standalone_net_table(_sw(), "IS")

    row_46 = out[(out["cost"] == "0.46%(기존전략)") & (out["horizon"] == "1m")].iloc[0]
    row_52 = out[(out["cost"] == "0.52%(틱연구)") & (out["horizon"] == "1m")].iloc[0]
    # 평균 new_ret_1m = (0.02+0.02+0.01)/3 = 0.01667 -> 비용만큼만 차이나야 한다
    assert row_46["net_mean_pct"] - row_52["net_mean_pct"] == pytest.approx(0.52 - 0.46, abs=1e-6)


def test_pairwise_table_n_zero_when_all_nan():
    sw = _sw()
    sw["new_ret_3m"] = None
    sw["old_ret_3m"] = None

    out = pairwise_table(sw, "IS")

    assert int(out[out["horizon"] == "3m"].iloc[0]["n"]) == 0
