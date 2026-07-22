import pandas as pd
import pytest

from backtesting.breakout_reversal import (
    detect_entries,
    simulate_all_entries,
    simulate_all_partial_exits,
    simulate_all_tiered_exits,
    simulate_partial_exit_trade,
    simulate_tiered_exit_trade,
    simulate_trade_path,
)


def _candles(day: str, closes: list[float], volumes: list[float]) -> pd.DataFrame:
    index = pd.date_range(f"{day} 09:00", periods=len(closes), freq="1min")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": volumes}, index=index
    )


def test_detect_entries_fires_when_both_conditions_met():
    # 3분간 100->101.6 (+1.6%>1.5%), 거래대금 3구간 합 = 각 bar 100*2e7=2e9 -> 합 6e9 >= 4e9
    closes = [100, 100, 101.6]
    volumes = [20_000_000, 20_000_000, 20_000_000]
    candles = _candles("2026-01-01", closes, volumes)

    entries = detect_entries(candles, window_minutes=3, min_trade_value=4_000_000_000, min_return_pct=0.015)

    assert entries.iloc[2] == True  # noqa: E712


def test_detect_entries_false_when_return_insufficient():
    closes = [100, 100, 100.5]  # +0.5% < 1.5%
    volumes = [2_000_000, 2_000_000, 2_000_000]
    candles = _candles("2026-01-01", closes, volumes)

    entries = detect_entries(candles, window_minutes=3, min_trade_value=4_000_000_000, min_return_pct=0.015)

    assert entries.iloc[2] == False  # noqa: E712


def test_detect_entries_false_when_trade_value_insufficient():
    closes = [100, 100, 102]
    volumes = [10, 10, 10]  # 거래대금 매우 작음
    candles = _candles("2026-01-01", closes, volumes)

    entries = detect_entries(candles, window_minutes=3, min_trade_value=4_000_000_000, min_return_pct=0.015)

    assert entries.iloc[2] == False  # noqa: E712


def test_detect_entries_does_not_leak_across_day_boundary():
    day1 = _candles("2026-01-01", [100, 100], [2_000_000, 2_000_000])
    day2 = _candles("2026-01-02", [102], [2_000_000])
    combined = pd.concat([day1, day2])

    entries = detect_entries(combined, window_minutes=3, min_trade_value=4_000_000_000, min_return_pct=0.015)

    # day2의 단일 캔들은 day1 데이터와 합쳐져 3분 윈도우를 채우면 안 됨 (rolling(3)에 NaN만 있어야 함)
    assert entries.iloc[-1] == False  # noqa: E712


def test_simulate_trade_path_exits_on_take_profit():
    candles = _candles("2026-01-01", [100, 101, 104], [1000, 1000, 1000])

    result = simulate_trade_path(candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02)

    assert result.exit_reason == "take_profit"
    assert result.net_pnl_pct >= 0.03


def test_simulate_trade_path_exits_on_stop_loss():
    candles = _candles("2026-01-01", [100, 99, 97], [1000, 1000, 1000])

    result = simulate_trade_path(candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02)

    assert result.exit_reason == "stop_loss"
    assert result.net_pnl_pct <= -0.02


def test_simulate_trade_path_force_closes_at_eod():
    candles = _candles("2026-01-01", [100, 100.5, 100.8], [1000, 1000, 1000])

    result = simulate_trade_path(candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02)

    assert result.exit_reason == "eod"
    assert result.exit_idx == 2


def test_simulate_trade_path_does_not_carry_over_to_next_day():
    day1 = _candles("2026-01-01", [100, 100.5], [1000, 1000])
    day2 = _candles("2026-01-02", [150], [1000])  # 익일 급등 -> 반영되면 안 됨
    combined = pd.concat([day1, day2])

    result = simulate_trade_path(combined, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02)

    assert result.exit_reason == "eod"
    assert result.exit_time == combined.index[1]  # day1의 마지막 캔들에서 청산


def test_simulate_trade_path_tracks_peak_pnl():
    candles = _candles("2026-01-01", [100, 102, 100.5], [1000, 1000, 1000])

    result = simulate_trade_path(candles, entry_idx=0, take_profit_pct=0.10, stop_loss_pct=0.10)

    assert result.peak_pnl_pct == pytest.approx(result.path[1][2])
    assert result.peak_pnl_pct > result.net_pnl_pct  # 마지막엔 peak보다 낮아짐


def test_simulate_all_entries_runs_one_path_per_entry():
    candles = _candles("2026-01-01", [100, 100, 101.6, 100, 100], [20_000_000] * 5)
    entries = detect_entries(candles, window_minutes=3, min_trade_value=4_000_000_000, min_return_pct=0.015)

    paths = simulate_all_entries(candles, entries, take_profit_pct=0.10, stop_loss_pct=0.10)

    assert entries.sum() >= 1
    assert len(paths) == entries.sum()


def test_partial_exit_not_triggered_when_stop_loss_hit_first():
    candles = _candles("2026-01-01", [100, 99, 97], [1000, 1000, 1000])

    result = simulate_partial_exit_trade(candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02)

    assert result.triggered is False
    assert result.first_leg_exit_reason == "stop_loss"
    assert result.overall_net_pnl_pct <= -0.02


def test_partial_exit_triggers_at_take_profit_then_trails_remainder_up():
    # 진입 100 -> 3분 뒤 104(+4%, 익절 트리거) -> 계속 상승 106까지 갔다가 소폭 하락
    candles = _candles("2026-01-01", [100, 101, 102, 104, 106, 105.5], [1000] * 6)

    result = simulate_partial_exit_trade(
        candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02,
        split_ratio=0.5, trailing_stop_pct=0.01,
    )

    assert result.triggered is True
    assert result.first_leg_exit_reason == "take_profit_partial"
    # 나머지 절반이 106 근처까지 추가 상승분을 더 챙겼으므로, split_ratio=0.5 기준
    # 순수익은 단순 +3% 익절(전량)보다 커야 함
    assert result.overall_net_pnl_pct > 0.03


def test_partial_exit_remainder_stops_on_trailing_drawdown():
    # 트리거(104) 이후 108까지 올랐다가 -1% 이상 빠지면 그 시점에 잔량 청산
    candles = _candles("2026-01-01", [100, 101, 102, 104, 108, 106.5, 106.4], [1000] * 7)

    result = simulate_partial_exit_trade(
        candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02,
        split_ratio=0.5, trailing_stop_pct=0.01,
    )

    assert result.triggered is True
    assert result.remainder_exit_reason == "trailing_stop"
    assert result.remainder_exit_idx < len(candles) - 1  # EOD까지 안 가고 조기 청산됨


def test_partial_exit_remainder_force_closes_at_eod_if_no_trailing_hit():
    candles = _candles("2026-01-01", [100, 101, 104, 104.5, 104.8], [1000] * 5)  # 계속 완만히 상승만

    result = simulate_partial_exit_trade(
        candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02,
        split_ratio=0.5, trailing_stop_pct=0.05,  # 넉넉한 트레일링 폭 -> 안 걸림
    )

    assert result.triggered is True
    assert result.remainder_exit_reason == "eod"
    assert result.remainder_exit_idx == len(candles) - 1


def test_partial_exit_does_not_carry_remainder_into_next_day():
    day1 = _candles("2026-01-01", [100, 101, 104, 104.2], [1000] * 4)
    day2 = _candles("2026-01-02", [150], [1000])
    combined = pd.concat([day1, day2])

    result = simulate_partial_exit_trade(
        combined, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02,
        split_ratio=0.5, trailing_stop_pct=0.05,
    )

    assert result.remainder_exit_idx == 3  # day1의 마지막 캔들
    assert result.remainder_exit_reason == "eod"


def test_split_ratio_of_one_behaves_like_full_take_profit_exit():
    """split_ratio=1.0이면 트리거 시점에 전량 매도 -> 나머지 트레일링 로직은 결과에 영향 없어야 함."""
    candles = _candles("2026-01-01", [100, 101, 102, 104, 110, 90], [1000] * 6)

    result = simulate_partial_exit_trade(
        candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02,
        split_ratio=1.0, trailing_stop_pct=0.01,
    )

    assert result.overall_net_pnl_pct == pytest.approx(result.overall_net_pnl_pct)  # leg1만 반영
    # leg2(나머지 0%)가 폭락해도 overall에는 영향 없어야 함
    baseline = simulate_trade_path(candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02)
    assert result.overall_net_pnl_pct == pytest.approx(baseline.net_pnl_pct)


def test_simulate_all_partial_exits_runs_one_per_entry():
    candles = _candles("2026-01-01", [100, 100, 101.6, 100, 100], [20_000_000] * 5)
    entries = detect_entries(candles, window_minutes=3, min_trade_value=4_000_000_000, min_return_pct=0.015)

    results = simulate_all_partial_exits(candles, entries, take_profit_pct=0.10, stop_loss_pct=0.10)

    assert len(results) == entries.sum()


def test_tiered_exit_fires_all_tiers_when_price_keeps_rising():
    # 각 분마다 순수익률이 정확히 다음 tier(2/3/4/5%)를 막 넘도록 설계된 가격
    candles = _candles("2026-01-01", [100, 102.3, 103.3, 104.3, 105.3], [1000] * 5)

    result = simulate_tiered_exit_trade(candles, entry_idx=0, tiers=(0.02, 0.03, 0.04, 0.05), stop_loss_pct=0.02)

    assert len(result.legs) == 4
    assert all(reason == "take_profit_tier" for _, reason, _, _ in result.legs)
    assert sum(fraction for _, _, fraction, _ in result.legs) == pytest.approx(1.0)
    assert result.net_pnl_pct == pytest.approx(0.0356, abs=0.001)


def test_tiered_exit_stops_full_position_when_no_tier_triggered_yet():
    candles = _candles("2026-01-01", [100, 97], [1000, 1000])

    result = simulate_tiered_exit_trade(candles, entry_idx=0, tiers=(0.02, 0.03, 0.04, 0.05), stop_loss_pct=0.02)

    assert len(result.legs) == 1
    assert result.legs[0][1] == "stop_loss"
    assert result.legs[0][2] == pytest.approx(1.0)
    assert result.net_pnl_pct <= -0.02


def test_tiered_exit_sells_remainder_at_breakeven_after_arming():
    # tier1(2%)만 닿고 그 뒤 진입가 근처로 되돌아오면, 남은 75%는 손절이 아니라 본전청산
    candles = _candles("2026-01-01", [100, 102.3, 99.9], [1000] * 3)

    result = simulate_tiered_exit_trade(candles, entry_idx=0, tiers=(0.02, 0.03, 0.04, 0.05), stop_loss_pct=0.02)

    assert len(result.legs) == 2
    assert result.legs[0][1] == "take_profit_tier"
    assert result.legs[0][2] == pytest.approx(0.25)
    assert result.legs[1][1] == "breakeven"
    assert result.legs[1][2] == pytest.approx(0.75)
    assert result.net_pnl_pct > 0  # 일부는 익절, 나머지는 본전이므로 전체는 소폭 플러스


def test_tiered_exit_force_closes_full_position_at_eod_when_nothing_triggered():
    candles = _candles("2026-01-01", [100, 100.5, 100.8], [1000] * 3)

    result = simulate_tiered_exit_trade(candles, entry_idx=0, tiers=(0.02, 0.03, 0.04, 0.05), stop_loss_pct=0.02)

    assert len(result.legs) == 1
    assert result.legs[0][1] == "eod"
    assert result.legs[0][2] == pytest.approx(1.0)
    assert result.exit_idx == len(candles) - 1


def test_tiered_exit_does_not_carry_over_to_next_day():
    day1 = _candles("2026-01-01", [100, 100.5], [1000, 1000])
    day2 = _candles("2026-01-02", [150], [1000])  # 익일 급등 -> 반영되면 안 됨
    combined = pd.concat([day1, day2])

    result = simulate_tiered_exit_trade(combined, entry_idx=0, tiers=(0.02, 0.03, 0.04, 0.05), stop_loss_pct=0.02)

    assert result.legs[0][1] == "eod"
    assert result.exit_time == combined.index[1]  # day1의 마지막 캔들에서 청산


def test_simulate_all_tiered_exits_runs_one_per_entry():
    candles = _candles("2026-01-01", [100, 100, 101.6, 100, 100], [20_000_000] * 5)
    entries = detect_entries(candles, window_minutes=3, min_trade_value=4_000_000_000, min_return_pct=0.015)

    results = simulate_all_tiered_exits(candles, entries, tiers=(0.02, 0.03, 0.04, 0.05), stop_loss_pct=0.02)

    assert len(results) == entries.sum()
