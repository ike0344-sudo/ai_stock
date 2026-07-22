import pandas as pd
import pytest

from backtesting.portfolio_sim import monthly_profit_breakdown, simulate_slot_portfolio


def _candidates(rows: list[tuple]) -> pd.DataFrame:
    """rows: (code, entry_time, exit_time, pct) 튜플 목록."""
    return pd.DataFrame(
        [{"code": c, "entry_time": pd.Timestamp(e), "exit_time": pd.Timestamp(x), "pct": p} for c, e, x, p in rows]
    )


def test_simulate_slot_portfolio_reuses_freed_slot_for_later_trade():
    # 2슬롯: A(09:00-09:30)/B(09:10-09:40)는 겹쳐서 슬롯 2개 다 사용, C(09:35-10:00)는
    # A가 09:30에 끝난 뒤라 A의 슬롯을 재사용해 채택되어야 함
    candidates = _candidates(
        [
            ("A", "2026-07-20 09:00", "2026-07-20 09:30", 0.02),
            ("B", "2026-07-20 09:10", "2026-07-20 09:40", 0.03),
            ("C", "2026-07-20 09:35", "2026-07-20 10:00", -0.01),
        ]
    )

    result = simulate_slot_portfolio(candidates, initial_capital=10_000_000, max_concurrent_positions=2)

    assert result.skipped_count == 0
    assert len(result.taken_trades) == 3
    assert result.slot_size == 5_000_000
    expected_profit = 5_000_000 * 0.02 + 5_000_000 * 0.03 + 5_000_000 * (-0.01)
    assert result.final_capital == pytest.approx(10_000_000 + expected_profit)


def test_simulate_slot_portfolio_skips_signal_when_no_free_slot():
    # 1슬롯: B가 A와 겹쳐서(A 09:00-09:30 진행 중에 B 09:10 진입 시도) 스킵되어야 함
    candidates = _candidates(
        [
            ("A", "2026-07-20 09:00", "2026-07-20 09:30", 0.02),
            ("B", "2026-07-20 09:10", "2026-07-20 09:40", 0.05),
            ("C", "2026-07-20 09:35", "2026-07-20 10:00", -0.01),
        ]
    )

    result = simulate_slot_portfolio(candidates, initial_capital=10_000_000, max_concurrent_positions=1)

    assert result.skipped_count == 1
    taken_codes = [t.code for t in result.taken_trades]
    assert taken_codes == ["A", "C"]
    expected_profit = 10_000_000 * 0.02 + 10_000_000 * (-0.01)
    assert result.final_capital == pytest.approx(10_000_000 + expected_profit)


def test_simulate_slot_portfolio_empty_candidates_returns_unchanged_capital():
    result = simulate_slot_portfolio(pd.DataFrame(columns=["code", "entry_time", "exit_time", "pct"]))

    assert result.final_capital == result.initial_capital
    assert result.trades == []


def test_simulate_slot_portfolio_processes_out_of_order_input_by_entry_time():
    # 입력 순서가 시간순이 아니어도 entry_time 기준으로 정렬해 처리해야 함
    candidates = _candidates(
        [
            ("late", "2026-07-20 10:00", "2026-07-20 10:30", 0.01),
            ("early", "2026-07-20 09:00", "2026-07-20 09:30", 0.02),
        ]
    )

    result = simulate_slot_portfolio(candidates, initial_capital=10_000_000, max_concurrent_positions=1)

    assert [t.code for t in result.trades] == ["early", "late"]
    assert result.skipped_count == 0


def test_monthly_profit_breakdown_groups_by_entry_month():
    candidates = _candidates(
        [
            ("A", "2026-04-05 09:00", "2026-04-05 09:30", 0.02),
            ("B", "2026-04-20 09:00", "2026-04-20 09:30", -0.01),
            ("C", "2026-05-03 09:00", "2026-05-03 09:30", 0.03),
        ]
    )
    result = simulate_slot_portfolio(candidates, initial_capital=10_000_000, max_concurrent_positions=5)

    breakdown = monthly_profit_breakdown(result)

    assert list(breakdown["month"].astype(str)) == ["2026-04", "2026-05"]
    assert list(breakdown["n_trades"]) == [2, 1]
    april_profit = 2_000_000 * 0.02 + 2_000_000 * (-0.01)
    assert breakdown.iloc[0]["profit"] == pytest.approx(april_profit)


def test_monthly_profit_breakdown_empty_when_all_skipped():
    candidates = _candidates(
        [
            ("A", "2026-04-05 09:00", "2026-04-05 09:30", 0.02),
            ("B", "2026-04-05 09:10", "2026-04-05 09:40", 0.03),
        ]
    )
    result = simulate_slot_portfolio(candidates, initial_capital=10_000_000, max_concurrent_positions=1)

    breakdown = monthly_profit_breakdown(result)

    assert len(result.taken_trades) == 1
    assert len(breakdown) == 1
