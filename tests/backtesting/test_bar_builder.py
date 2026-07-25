import pandas as pd

from backtesting import bar_builder

TICKS = pd.DataFrame([
    {"price": 70000.0, "cum_volume": 1000, "time_hms": "090001", "bid": 69900.0},
    {"price": 70100.0, "cum_volume": 1500, "time_hms": "090030", "bid": 70000.0},
    {"price": 70050.0, "cum_volume": 1800, "time_hms": "090100", "bid": 69950.0},
    {"price": 70200.0, "cum_volume": 2200, "time_hms": "091500", "bid": 70100.0},
])


def test_build_bars_groups_into_minute_buckets_labeled_at_bucket_start():
    bars = bar_builder.build_bars(TICKS, "1min", "2026-07-25")

    assert list(bars.index) == [
        pd.Timestamp("2026-07-25 09:00:00"),
        pd.Timestamp("2026-07-25 09:01:00"),
        pd.Timestamp("2026-07-25 09:15:00"),
    ]
    first = bars.loc["2026-07-25 09:00:00"]
    assert (first["open"], first["high"], first["low"], first["close"]) == (70000.0, 70100.0, 70000.0, 70100.0)


def test_build_bars_first_tick_contributes_zero_volume():
    bars = bar_builder.build_bars(TICKS, "1min", "2026-07-25")

    # 09:00 버킷: 첫 틱(1000)은 diff 기준이 없어 0, 두번째 틱은 1500-1000=500
    assert bars.loc["2026-07-25 09:00:00", "volume"] == 500


def test_build_bars_no_gap_filling_for_empty_buckets():
    bars = bar_builder.build_bars(TICKS, "1min", "2026-07-25")

    # 09:02~09:14는 체결이 없으므로 봉 자체가 없어야 한다 (forward-fill 없음)
    assert pd.Timestamp("2026-07-25 09:02:00") not in bars.index


def test_build_bars_respects_15min_interval():
    bars = bar_builder.build_bars(TICKS, "15min", "2026-07-25")

    assert list(bars.index) == [
        pd.Timestamp("2026-07-25 09:00:00"),
        pd.Timestamp("2026-07-25 09:15:00"),
    ]
    assert bars.loc["2026-07-25 09:00:00", "volume"] == 500 + 300  # (1500-1000) + (1800-1500)


def test_build_bars_returns_empty_frame_for_empty_ticks():
    bars = bar_builder.build_bars(pd.DataFrame(columns=["price", "cum_volume", "time_hms", "bid"]), "1min", "2026-07-25")

    assert bars.empty
    assert list(bars.columns) == bar_builder.BAR_COLUMNS
