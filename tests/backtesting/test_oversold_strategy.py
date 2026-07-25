from datetime import date

import pandas as pd
import pytest

from backtesting.oversold_strategy import (
    HARD_STOP_PCT,
    MA_WINDOW,
    TIME_EXIT_TRADING_DAYS,
    compute_ma,
    compute_tier_prices,
    count_trading_days,
    describe_strategy_2,
    generate_signals,
    next_entry_tier,
    should_exit_by_hard_stop,
    should_exit_by_time,
    should_exit_by_touch,
)


# ---- describe_strategy_2 ----

def test_describe_strategy_2_has_entry_exit_operation_keys():
    description = describe_strategy_2()

    assert set(description.keys()) == {"entry", "exit", "operation", "exchange_basis"}
    assert all(isinstance(v, list) and len(v) > 0 for v in description.values())
    assert all("000660" in item or "60선" in item or "%" in item or "PDF" in item for item in description["entry"])


# ---- compute_ma ----

def test_compute_ma_rolling_average_of_close():
    candles = pd.DataFrame({"close": [100.0, 200.0, 300.0]})

    ma = compute_ma(candles, window=3)

    assert ma.iloc[-1] == pytest.approx(200.0)
    assert pd.isna(ma.iloc[0])  # 윈도우 미충족 구간은 NaN


# ---- compute_tier_prices ----

def test_compute_tier_prices_matches_pdf_multipliers():
    # PDF: 1차 60선×0.91, 2차 60선×0.88, 3차 60선×0.85
    prices = compute_tier_prices(100.0)

    assert prices == pytest.approx([91.0, 88.0, 85.0])


# ---- next_entry_tier ----

def test_next_entry_tier_returns_1_when_price_touches_first_band():
    assert next_entry_tier(filled_tier_count=0, low_or_current_price=90.0, ma_value=100.0) == 1


def test_next_entry_tier_returns_none_when_price_above_first_band():
    assert next_entry_tier(filled_tier_count=0, low_or_current_price=95.0, ma_value=100.0) is None


def test_next_entry_tier_returns_2_when_price_touches_second_band_and_first_already_filled():
    assert next_entry_tier(filled_tier_count=1, low_or_current_price=87.0, ma_value=100.0) == 2


def test_next_entry_tier_returns_none_when_second_band_not_reached_yet():
    # 1차는 이미 체결됐고 가격이 91보다 낮지만 2차 밴드(88)엔 아직 안 닿음
    assert next_entry_tier(filled_tier_count=1, low_or_current_price=89.0, ma_value=100.0) is None


def test_next_entry_tier_returns_none_after_all_three_tiers_filled():
    # 3단 초과 매수 금지 — 가격이 훨씬 더 떨어져도 None
    assert next_entry_tier(filled_tier_count=3, low_or_current_price=50.0, ma_value=100.0) is None


# ---- should_exit_by_touch ----

def test_should_exit_by_touch_true_when_price_reaches_ma():
    assert should_exit_by_touch(high_or_current_price=100.0, ma_value=100.0) is True
    assert should_exit_by_touch(high_or_current_price=101.0, ma_value=100.0) is True


def test_should_exit_by_touch_false_when_price_below_ma():
    assert should_exit_by_touch(high_or_current_price=99.0, ma_value=100.0) is False


# ---- should_exit_by_hard_stop ----

def test_should_exit_by_hard_stop_true_at_exactly_threshold():
    avg_price = 100.0
    trigger_price = avg_price * (1 - HARD_STOP_PCT)

    assert should_exit_by_hard_stop(trigger_price, avg_price) is True


def test_should_exit_by_hard_stop_false_above_threshold():
    assert should_exit_by_hard_stop(current_price=85.0, avg_entry_price=100.0) is False  # -15%, 아직 -20% 아님


# ---- count_trading_days / should_exit_by_time ----

def test_count_trading_days_counts_inclusive_weekdays_only():
    # 2026-07-20(월)~2026-07-24(금) = 5거래일
    assert count_trading_days(date(2026, 7, 20), date(2026, 7, 24)) == 5


def test_count_trading_days_zero_when_end_before_start():
    assert count_trading_days(date(2026, 7, 24), date(2026, 7, 20)) == 0


def test_should_exit_by_time_false_within_window():
    entry = date(2026, 7, 20)
    today = date(2026, 7, 20)  # 1거래일째

    assert should_exit_by_time(entry, today, trading_days=TIME_EXIT_TRADING_DAYS) is False


# ---- generate_signals (Strategy 프로토콜 어댑터) ----

def test_generate_signals_maps_tier_touch_to_entry_and_ma_touch_to_exit():
    closes = [100.0] * MA_WINDOW + [90.0, 100.0]  # 60선 형성 후 1차 밴드 터치 -> 복귀 시 60선 터치
    df = pd.DataFrame({"close": closes})

    out = generate_signals(df)

    assert out["signal"].iloc[MA_WINDOW] == 1  # 90 <= 60선*0.91 => 1차 밴드 터치(진입)
    assert out["signal"].iloc[MA_WINDOW + 1] == -1  # 가격 복귀로 60선 터치(청산)
    assert (out["signal"].iloc[: MA_WINDOW - 1] == 0).all()  # 60선 미형성 구간(rolling 미충족)은 홀드


def test_generate_signals_exposes_name_and_params():
    assert generate_signals.name == "strategy_2"
    assert generate_signals.params["ma_window"] == MA_WINDOW


def test_should_exit_by_time_true_once_past_window():
    entry = date(2026, 6, 1)
    today = date(2026, 6, 1)
    # entry로부터 정확히 TIME_EXIT_TRADING_DAYS 거래일 뒤 하루를 더 넘긴 날짜를 계산
    business_days = pd.bdate_range(entry, periods=TIME_EXIT_TRADING_DAYS + 2)
    past_deadline = business_days[-1].date()

    assert should_exit_by_time(entry, past_deadline, trading_days=TIME_EXIT_TRADING_DAYS) is True
