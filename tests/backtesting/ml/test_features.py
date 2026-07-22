import pandas as pd

from backtesting.ml.features import build_features


def _candles(prices: list[float], volumes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01 09:00", periods=len(prices), freq="1min")
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p * 1.001 for p in prices],
            "low": [p * 0.999 for p in prices],
            "close": prices,
            "volume": volumes,
        },
        index=index,
    )


def test_features_do_not_use_future_data():
    base_prices = [100 + i * 0.1 for i in range(40)]
    base_volumes = [1000 + i for i in range(40)]

    candles_a = _candles(base_prices, base_volumes)
    modified_prices = list(base_prices)
    modified_prices[35] = 500  # 미래 시점(인덱스 35) 가격을 크게 바꿈
    candles_b = _candles(modified_prices, base_volumes)

    features_a = build_features(candles_a)
    features_b = build_features(candles_b)

    # 미래 변경 지점(35)보다 훨씬 이전인 시점 20의 특징은 영향받지 않아야 함
    pd.testing.assert_series_equal(features_a.iloc[20], features_b.iloc[20], check_names=False)


def test_features_have_expected_columns():
    candles = _candles([100 + i * 0.1 for i in range(30)], [1000] * 30)

    features = build_features(candles)

    expected = {
        "return_1", "return_5", "momentum_10", "volatility_10",
        "volume_ratio_20", "rsi_14", "high_low_range",
    }
    assert expected.issubset(set(features.columns))
