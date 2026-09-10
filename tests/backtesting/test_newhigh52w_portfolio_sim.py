import pandas as pd
import pytest

import backtesting.portfolio_sim as ps
from backtesting.newhigh52w_portfolio_sim import compute_mdd, simulate_window_portfolio, to_candidates


def _trades(rows: list[tuple]) -> pd.DataFrame:
    """rows: (code, entry_date, exit_date, net_pct)."""
    return pd.DataFrame([{"code": c, "entry_date": e, "exit_date": x, "net_pct": p} for c, e, x, p in rows])


def test_to_candidates_breaks_same_day_ties_by_code_ascending():
    trades = _trades([
        ("003", "2025-09-01", "2025-09-10", 0.01),
        ("001", "2025-09-01", "2025-09-10", 0.02),
        ("002", "2025-09-01", "2025-09-10", -0.01),
    ])

    out = to_candidates(trades)

    assert list(out["code"]) == ["001", "002", "003"]  # 코드 오름차순
    # entry_time이 마이크로초 단위로 서로 달라 동률이 없어짐(결정론)
    assert out["entry_time"].nunique() == 3
    assert out["entry_time"].is_monotonic_increasing


def test_to_candidates_empty_returns_empty_with_expected_columns():
    out = to_candidates(pd.DataFrame(columns=["code", "entry_date", "exit_date", "net_pct"]))

    assert out.empty
    assert list(out.columns) == ["code", "entry_time", "exit_time", "pct"]


def test_simulate_window_portfolio_skips_when_slots_full_and_reuses_freed_slot():
    # 1슬롯: A(9/1~9/10) 보유 중 B(9/5 진입 시도)는 스킵, C(9/11 진입, A 청산 후)는 채택
    trades = _trades([
        ("A", "2025-09-01", "2025-09-10", 0.10),
        ("B", "2025-09-05", "2025-09-15", 0.05),
        ("C", "2025-09-11", "2025-09-20", -0.02),
    ])

    sim = simulate_window_portfolio(trades, capital=1_000_000, max_slots=1)

    assert sim["taken"] == 2
    assert sim["skipped"] == 1
    assert sim["portfolio_ret"] == pytest.approx(0.10 + (-0.02))  # 슬롯1개, 복리없음(전액재투입 고정크기)


def test_simulate_window_portfolio_empty_trades_gives_zero_return_zero_mdd():
    sim = simulate_window_portfolio(pd.DataFrame(columns=["code", "entry_date", "exit_date", "net_pct"]))

    assert sim["portfolio_ret"] == 0.0
    assert sim["taken"] == 0 and sim["skipped"] == 0
    assert sim["mdd"] == 0.0


def test_compute_mdd_tracks_peak_to_trough_across_sequential_exits():
    candidates = pd.DataFrame([
        {"code": "A", "entry_time": pd.Timestamp("2025-09-01"), "exit_time": pd.Timestamp("2025-09-05"), "pct": 0.20},
        {"code": "B", "entry_time": pd.Timestamp("2025-09-02"), "exit_time": pd.Timestamp("2025-09-10"), "pct": -0.30},
        {"code": "C", "entry_time": pd.Timestamp("2025-09-11"), "exit_time": pd.Timestamp("2025-09-20"), "pct": 0.05},
    ])
    result = ps.simulate_slot_portfolio(candidates, initial_capital=1_000_000, max_concurrent_positions=2)

    mdd = compute_mdd(result)

    # 2슬롯 -> 슬롯크기=500,000. 자본: 1,000,000 -> (A청산,9/5)+100,000=1,100,000(peak)
    # -> (B청산,9/10)-150,000=950,000 -> (C청산,9/20)+25,000=975,000(peak 아직 1,100,000)
    # 낙폭 = (1,100,000-950,000)/1,100,000
    assert mdd == pytest.approx((1_100_000 - 950_000) / 1_100_000)


def test_compute_mdd_zero_when_no_trades_taken():
    result = ps.simulate_slot_portfolio(pd.DataFrame(columns=["code", "entry_time", "exit_time", "pct"]))

    assert compute_mdd(result) == 0.0
