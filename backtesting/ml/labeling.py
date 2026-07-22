"""당일 종가 전 목표 시점까지 임계 수익률 도달 여부를 이진 라벨로 생성.

Design: docs/02-design/features/strategy-backtesting.design.md §4.1
시점 t의 라벨은 t 이후(같은 거래일 내)의 데이터만 사용하며, 익일로 넘어가지 않는다
(데이트레이딩 — 당일 청산 가정).
"""
import pandas as pd


def make_labels(candles: pd.DataFrame, horizon_minutes: int, return_threshold: float) -> pd.Series:
    close = candles["close"]
    dates = candles.index.normalize()
    labels = pd.Series(index=candles.index, dtype="float64")

    for i in range(len(candles)):
        day = dates[i]
        entry_price = close.iloc[i]
        window_end = min(i + horizon_minutes, len(candles) - 1)

        max_future_return = None
        j = i + 1
        while j <= window_end and dates[j] == day:
            future_return = (close.iloc[j] - entry_price) / entry_price
            if max_future_return is None or future_return > max_future_return:
                max_future_return = future_return
            j += 1

        if max_future_return is None:
            labels.iloc[i] = float("nan")
        else:
            labels.iloc[i] = 1.0 if max_future_return >= return_threshold else 0.0

    return labels
