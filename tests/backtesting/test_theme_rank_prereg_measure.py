import numpy as np
import pandas as pd
import pytest

from backtesting.theme_rank_prereg_measure import (
    DailyPriceLookup,
    entry_price,
    forward_return,
    one_sample_ttest,
    theme_ranks,
    theme_row,
    two_sample_ttest,
)


def _make_daily_csv(path, dates, closes):
    pd.DataFrame({"date": dates, "open": closes, "high": closes, "low": closes,
                  "close": closes, "volume": [1] * len(dates)}).to_csv(path, index=False)


def test_daily_price_lookup_prev_close_finds_last_trading_day_before_date(tmp_path):
    _make_daily_csv(tmp_path / "000001.csv",
                     ["2026-07-01", "2026-07-02", "2026-07-06"], [100, 101, 102])
    lookup = DailyPriceLookup(str(tmp_path))

    # 07-03,07-04,07-05는 인덱스에 없음(주말/휴장) - 그 이전 마지막 거래일(07-02)을 찾아야 함
    assert lookup.prev_close("000001", "2026-07-03") == 101
    assert lookup.prev_close("000001", "2026-07-06") == 101  # 07-06 자신이 아니라 그 이전
    assert lookup.prev_close("000001", "2026-07-01") is None  # 이전 거래일 없음
    assert lookup.close("000001", "2026-07-06") == 102


def test_theme_ranks_sorts_by_score_descending():
    frame = {"t": "09:01", "rows": [
        {"theme": "A", "score": 50.0}, {"theme": "B", "score": 80.0}, {"theme": "C", "score": 60.0},
    ]}

    ranks = theme_ranks(frame)

    assert ranks == {"B": 1, "C": 2, "A": 3}


def test_theme_row_finds_matching_theme():
    frame = {"rows": [{"theme": "A", "leader": "X"}, {"theme": "B", "leader": "Y"}]}

    assert theme_row(frame, "B")["leader"] == "Y"
    assert theme_row(frame, "Z") is None


def test_entry_price_reconstructs_from_prev_close_and_pct(tmp_path):
    _make_daily_csv(tmp_path / "000002.csv", ["2026-07-01"], [1000])
    lookup = DailyPriceLookup(str(tmp_path))
    name_to_code = {"테스트종목": "000002"}

    code, price = entry_price(lookup, name_to_code, "테스트종목", 5.0, "2026-07-02")

    assert code == "000002"
    assert price == pytest.approx(1000 * 1.05)


def test_entry_price_returns_none_price_when_name_unmapped(tmp_path):
    lookup = DailyPriceLookup(str(tmp_path))

    code, price = entry_price(lookup, {}, "없는종목", 5.0, "2026-07-02")

    assert code is None
    assert price is None


def test_forward_return_uses_close_over_entry(tmp_path):
    _make_daily_csv(tmp_path / "000003.csv", ["2026-07-02"], [110])
    lookup = DailyPriceLookup(str(tmp_path))

    ret = forward_return(lookup, "000003", "2026-07-02", entry=100.0)

    assert ret == pytest.approx(0.10)


def test_one_sample_ttest_matches_known_values():
    x = np.array([0.01, 0.02, 0.03, -0.01, 0.015])

    mean, t, n = one_sample_ttest(x)

    assert n == 5
    assert mean == pytest.approx(x.mean())
    assert t == pytest.approx(mean / (x.std(ddof=1) / np.sqrt(5)))


def test_two_sample_ttest_positive_diff_when_a_greater_than_b():
    a = np.array([0.02, 0.03, 0.025, 0.028, 0.022])
    b = np.array([0.0, 0.001, -0.002, 0.0005, 0.001])

    diff, t, na, nb = two_sample_ttest(a, b)

    assert diff > 0
    assert t > 0
    assert na == 5 and nb == 5
