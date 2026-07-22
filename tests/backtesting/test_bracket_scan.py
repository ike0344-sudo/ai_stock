import pandas as pd

from backtesting.bracket_scan import scan_bracket_zones, summarize_zones


def _candles(rows: list[tuple[str, float, float, float]]) -> pd.DataFrame:
    """rows: (timestamp, close, low, high)"""
    index = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame(
        {
            "close": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "high": [r[3] for r in rows],
        },
        index=index,
    )


def test_win_when_take_profit_hit_before_stop_loss():
    candles = _candles(
        [
            ("2026-01-01 09:00", 100, 100, 100),
            ("2026-01-01 09:01", 101, 100, 101),
            ("2026-01-01 09:02", 103, 102, 103),  # +3% 도달
        ]
    )

    result = scan_bracket_zones(candles, stop_loss_pct=0.02, take_profit_pct=0.03)

    first_row = result.iloc[0]
    assert first_row["outcome"] == "win"
    assert first_row["exit_price"] == 103.0


def test_loss_when_stop_loss_hit_before_take_profit():
    candles = _candles(
        [
            ("2026-01-01 09:00", 100, 100, 100),
            ("2026-01-01 09:01", 99, 98, 99),  # -2% 도달 (entry=100 -> stop=98)
            ("2026-01-01 09:02", 103, 102, 103),
        ]
    )

    result = scan_bracket_zones(candles, stop_loss_pct=0.02, take_profit_pct=0.03)

    first_row = result.iloc[0]
    assert first_row["outcome"] == "loss"
    assert first_row["exit_price"] == 98.0


def test_loss_takes_precedence_when_both_hit_in_same_candle():
    # 보수적 가정: 같은 봉에서 저가가 손절, 고가가 익절을 동시에 건드리면 손절 우선
    candles = _candles(
        [
            ("2026-01-01 09:00", 100, 100, 100),
            ("2026-01-01 09:01", 100, 97, 104),  # low<=98(stop) and high>=103(target)
        ]
    )

    result = scan_bracket_zones(candles, stop_loss_pct=0.02, take_profit_pct=0.03)

    assert result.iloc[0]["outcome"] == "loss"


def test_none_outcome_when_neither_hit_by_day_end():
    candles = _candles(
        [
            ("2026-01-01 09:00", 100, 100, 100),
            ("2026-01-01 09:01", 100.5, 100, 100.5),
            ("2026-01-01 15:30", 100.2, 100, 100.5),
        ]
    )

    result = scan_bracket_zones(candles, stop_loss_pct=0.02, take_profit_pct=0.03)

    assert result.iloc[0]["outcome"] == "none"


def test_does_not_carry_over_to_next_trading_day():
    candles = _candles(
        [
            ("2026-01-01 15:29", 100, 100, 100),
            ("2026-01-01 15:30", 100, 100, 100),  # 당일 마지막 봉, 아직 -2%/+3% 미도달
            ("2026-01-02 09:00", 200, 200, 200),  # 익일 급등 — 반영되면 안 됨
        ]
    )

    result = scan_bracket_zones(candles, stop_loss_pct=0.02, take_profit_pct=0.03)

    first_row = result.iloc[0]
    assert first_row["outcome"] == "none"
    assert first_row["exit_time"] == candles.index[1]  # 당일 마지막 봉에서 마감


def test_summarize_zones_buckets_by_time_and_computes_win_rate():
    outcomes = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(
                ["2026-01-01 09:05", "2026-01-01 09:20", "2026-01-01 10:05"]
            ),
            "outcome": ["win", "loss", "win"],
            "realized_pct": [3.0, -2.0, 3.0],
        }
    )

    summary = summarize_zones(outcomes, bucket_minutes=30)

    bucket_09 = summary[summary["time_bucket"] == "09:00"].iloc[0]
    assert bucket_09["n"] == 2
    assert bucket_09["win_rate_pct"] == 50.0

    bucket_10 = summary[summary["time_bucket"] == "10:00"].iloc[0]
    assert bucket_10["n"] == 1
    assert bucket_10["win_rate_pct"] == 100.0


def test_summarize_zones_handles_empty_input():
    empty = pd.DataFrame(columns=["entry_time", "outcome", "realized_pct"])

    summary = summarize_zones(empty)

    assert summary.empty
