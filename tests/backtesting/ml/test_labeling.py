import pandas as pd

from backtesting.ml.labeling import make_labels


def _candles(prices: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01 09:00", periods=len(prices), freq="1min")
    return pd.DataFrame({"close": prices}, index=index)


def test_label_is_one_when_future_return_meets_threshold():
    prices = [100, 100, 103, 100, 100]
    candles = _candles(prices)

    labels = make_labels(candles, horizon_minutes=3, return_threshold=0.02)

    assert labels.iloc[0] == 1.0


def test_label_is_zero_when_threshold_not_met():
    prices = [100, 100, 100, 100, 100]
    candles = _candles(prices)

    labels = make_labels(candles, horizon_minutes=3, return_threshold=0.02)

    assert labels.iloc[0] == 0.0


def test_label_does_not_cross_into_next_day():
    index = pd.to_datetime(["2026-01-01 15:29", "2026-01-01 15:30", "2026-01-02 09:00"])
    candles = pd.DataFrame({"close": [100, 100, 200]}, index=index)

    labels = make_labels(candles, horizon_minutes=5, return_threshold=0.02)

    assert labels.iloc[0] == 0.0


def test_label_unaffected_by_past_data_changes():
    prices_a = [100, 100, 103, 100, 100]
    prices_b = list(prices_a)
    prices_b[0] = 999  # index 0의 값 변경이 index 2 라벨에 영향을 주면 안 됨

    labels_a = make_labels(_candles(prices_a), horizon_minutes=3, return_threshold=0.02)
    labels_b = make_labels(_candles(prices_b), horizon_minutes=3, return_threshold=0.02)

    assert labels_a.iloc[2] == labels_b.iloc[2]
