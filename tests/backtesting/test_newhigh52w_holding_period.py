import pandas as pd
import pytest

from backtesting.newhigh52w_holding_period import (
    compute_calmar,
    rank_is,
    resolve_slots,
    turnover_cost_table,
)


def test_resolve_slots_unlimited_uses_n_trades_and_never_zero():
    assert resolve_slots("unlimited", n_trades=17) == 17
    assert resolve_slots("unlimited", n_trades=0) == 1  # 0건이어도 0으로 나누지 않게 최소 1


def test_resolve_slots_fixed_values_pass_through():
    assert resolve_slots(5, n_trades=100) == 5
    assert resolve_slots(20, n_trades=1) == 20


def test_compute_calmar_divides_by_mdd_when_nonzero():
    assert compute_calmar(0.10, 0.05) == pytest.approx(2.0)


def test_compute_calmar_returns_raw_return_when_mdd_zero():
    # 0으로 나누기 방지 - MDD0(무손실)이면 수익률 그대로가 점수
    assert compute_calmar(0.10, 0.0) == pytest.approx(0.10)
    assert compute_calmar(-0.05, 0.0) == pytest.approx(-0.05)


def test_rank_is_picks_highest_mean_calmar_combo():
    df = pd.DataFrame([
        {"def": "5_20", "N": 5, "slot_spec": "5", "calmar": 1.0, "start": "w1"},
        {"def": "5_20", "N": 5, "slot_spec": "5", "calmar": 3.0, "start": "w2"},  # 평균 2.0
        {"def": "20_60", "N": 10, "slot_spec": "5", "calmar": 5.0, "start": "w1"},
        {"def": "20_60", "N": 10, "slot_spec": "5", "calmar": 5.0, "start": "w2"},  # 평균 5.0 (1등)
    ])

    ranked = rank_is(df)

    assert ranked.iloc[0][["def", "N", "slot_spec"]].tolist() == ["20_60", 10, "5"]
    assert ranked.iloc[0]["calmar"] == pytest.approx(5.0)


def test_turnover_cost_table_only_uses_unlimited_slot_rows_and_sums_taken():
    df = pd.DataFrame([
        {"def": "5_20", "N": 5, "slot_spec": "5", "taken": 100},       # 무제한 아님 - 제외
        {"def": "5_20", "N": 5, "slot_spec": "unlimited", "taken": 10},
        {"def": "5_20", "N": 5, "slot_spec": "unlimited", "taken": 8},
        {"def": "5_20", "N": 120, "slot_spec": "unlimited", "taken": 2},
    ])

    out = turnover_cost_table(df).set_index("N")

    assert out.loc[5, "taken"] == 18  # 10+8, slot_spec="5" 행은 무시
    assert out.loc[120, "taken"] == 2
    assert out.loc[5, "total_cost_pct_points"] > out.loc[120, "total_cost_pct_points"]  # 회전 많을수록 비용 많음
