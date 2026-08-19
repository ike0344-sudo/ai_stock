import pandas as pd
import pytest

from backtesting.breakout_reversal import (
    DEFAULT_COMMISSION_RATE,
    DEFAULT_SLIPPAGE_RATE,
    DEFAULT_TAX_RATE,
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


def test_detect_entries_uses_value_column_instead_of_close_times_volume_when_present():
    # close*volume 근사로는 거래대금이 거의 0이지만, 실제 체결대금 누적합인 value
    # 컬럼은 6e9로 충족 — realtime_feed.CandleAggregator가 넘기는 분봉 형태를 재현.
    closes = [100, 100, 101.6]
    volumes = [1, 1, 1]
    values = [2_000_000_000, 2_000_000_000, 2_000_000_000]
    index = pd.date_range("2026-01-01 09:00", periods=3, freq="1min")
    candles = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": volumes, "value": values},
        index=index,
    )

    entries = detect_entries(candles, window_minutes=3, min_trade_value=4_000_000_000, min_return_pct=0.015)

    assert entries.iloc[2] == True  # noqa: E712


def test_detect_entries_does_not_leak_across_day_boundary():
    day1 = _candles("2026-01-01", [100, 100], [2_000_000, 2_000_000])
    day2 = _candles("2026-01-02", [102], [2_000_000])
    combined = pd.concat([day1, day2])

    entries = detect_entries(combined, window_minutes=3, min_trade_value=4_000_000_000, min_return_pct=0.015)

    # day2의 단일 캔들은 day1 데이터와 합쳐져 3분 윈도우를 채우면 안 됨 (rolling(3)에 NaN만 있어야 함)
    assert entries.iloc[-1] == False  # noqa: E712


def test_simulate_trade_path_fills_entry_and_exit_at_next_bar_open():
    # 체결시점 보수화: entry_idx=0에서 신호가 확인돼도 실제 진입은 idx1의 시가에서
    # 체결되고, idx3에서 감지된 익절 신호도 idx4의 시가에서 체결된다(신호봉 종가로
    # 곧바로 체결하는 낙관적 가정을 제거).
    candles = _candles("2026-01-01", [100, 101, 104, 106, 106], [1000] * 5)

    result = simulate_trade_path(candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02)

    assert result.entry_price == pytest.approx(101 * (1 + DEFAULT_SLIPPAGE_RATE))
    assert result.exit_reason == "take_profit"
    assert result.exit_idx == 4  # 익절 감지(idx3) 다음 봉에서 체결
    assert result.net_pnl_pct >= 0.03


def test_simulate_trade_path_falls_back_to_signal_bar_close_when_no_next_bar_in_day():
    # 신호봉이 당일 마지막 봉이면 다음 봉 시가로 체결할 수 없어 신호봉 자체 종가로
    # 체결한다(장마감 동시호가 체결에 준하는 폴백).
    candles = _candles("2026-01-01", [100, 104], [1000, 1000])

    result = simulate_trade_path(candles, entry_idx=1, take_profit_pct=0.03, stop_loss_pct=0.02)

    assert result.entry_price == pytest.approx(104 * (1 + DEFAULT_SLIPPAGE_RATE))
    assert result.exit_idx == 1


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


def test_simulate_trade_path_applies_sell_tax_by_default():
    candles = _candles("2026-01-01", [100, 101, 104, 106, 106], [1000] * 5)

    with_tax = simulate_trade_path(candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02)
    no_tax = simulate_trade_path(
        candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02, tax_rate=0.0
    )

    assert with_tax.net_pnl_pct == pytest.approx(no_tax.net_pnl_pct - DEFAULT_TAX_RATE)


def test_simulate_trade_path_skips_price_locked_bar_for_entry_fill():
    # 전일 종가 100 -> 다음날 첫 봉이 상한가(130, +30%)로 고정. 진입 신호(idx0)의
    # 체결 예정 봉(idx1)이 고정돼 있어 건너뛰고, 고정이 풀린 idx2의 시가로 체결돼야 한다.
    day1 = _candles("2026-01-01", [100], [1000])
    day2 = _candles("2026-01-02", [100, 130, 120], [1000, 1000, 1000])
    combined = pd.concat([day1, day2])

    result = simulate_trade_path(combined, entry_idx=1, take_profit_pct=0.5, stop_loss_pct=0.5)

    assert result.entry_price == pytest.approx(120 * (1 + DEFAULT_SLIPPAGE_RATE))


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
    """split_ratio=1.0이면 트리거 시점에 전량 매도 -> 나머지 트레일링 로직은 결과에
    영향 없이 leg1(트리거 체결가) 값만 그대로 overall에 반영돼야 한다."""
    candles = _candles("2026-01-01", [100, 101, 102, 104, 110, 90], [1000] * 6)

    result = simulate_partial_exit_trade(
        candles, entry_idx=0, take_profit_pct=0.03, stop_loss_pct=0.02,
        split_ratio=1.0, trailing_stop_pct=0.01,
    )

    assert result.triggered is True
    # leg2(나머지 0%)가 폭락(110->90)해도 overall에는 전혀 영향이 없어야 함
    two_way_commission = 2 * DEFAULT_COMMISSION_RATE
    entry_price = 100 * (1 + DEFAULT_SLIPPAGE_RATE)
    trigger_price = candles["close"].iloc[result.first_leg_exit_idx] * (1 - DEFAULT_SLIPPAGE_RATE)
    expected_leg1_pct = (trigger_price - entry_price) / entry_price - two_way_commission - DEFAULT_TAX_RATE
    assert result.overall_net_pnl_pct == pytest.approx(expected_leg1_pct)


def test_simulate_all_partial_exits_runs_one_per_entry():
    candles = _candles("2026-01-01", [100, 100, 101.6, 100, 100], [20_000_000] * 5)
    entries = detect_entries(candles, window_minutes=3, min_trade_value=4_000_000_000, min_return_pct=0.015)

    results = simulate_all_partial_exits(candles, entries, take_profit_pct=0.10, stop_loss_pct=0.10)

    assert len(results) == entries.sum()


def test_tiered_exit_fires_all_tiers_when_price_keeps_rising():
    # 각 분마다 순수익률이 정확히 다음 tier(2/3/4/5%)를 막 넘도록 설계된 가격
    # (세율 검증은 별도 테스트 담당이라 tax_rate=0으로 tier 경계값 설계를 그대로 유지)
    candles = _candles("2026-01-01", [100, 102.3, 103.3, 104.3, 105.3], [1000] * 5)

    result = simulate_tiered_exit_trade(
        candles, entry_idx=0, tiers=(0.02, 0.03, 0.04, 0.05), stop_loss_pct=0.02, tax_rate=0.0
    )

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
    # (세율 검증은 별도 테스트 담당이라 tax_rate=0으로 tier 경계값 설계를 그대로 유지)
    candles = _candles("2026-01-01", [100, 102.3, 99.9], [1000] * 3)

    result = simulate_tiered_exit_trade(
        candles, entry_idx=0, tiers=(0.02, 0.03, 0.04, 0.05), stop_loss_pct=0.02, tax_rate=0.0
    )

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


def test_detect_entries_false_when_trade_value_above_ceiling():
    # 거래대금 3구간 합 6e9 — 하한 4e9는 넘지만 상한 5e9를 초과하므로 제외.
    closes = [100, 100, 101.6]
    volumes = [20_000_000, 20_000_000, 20_000_000]
    candles = _candles("2026-01-01", closes, volumes)

    entries = detect_entries(
        candles, window_minutes=3, min_trade_value=4_000_000_000, min_return_pct=0.015,
        max_trade_value=5_000_000_000,
    )

    assert entries.iloc[2] == False  # noqa: E712
