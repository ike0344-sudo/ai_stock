import pandas as pd
import pytest

from backtesting.strategies.envelope import EnvelopeStrategy
from backtesting.types import Signal


def _candles(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({"close": closes}, index=index)


def test_buy_signal_when_price_drops_below_lower_band():
    # ma_window=3, envelope_pct=0.05. index3: ma=mean(100,100,90)=96.67, lower≈91.83
    # close[3]=90 <= 91.83 → BUY
    candles = _candles([100, 100, 100, 90, 100, 100])

    signals = EnvelopeStrategy().evaluate(candles, {"ma_window": 3, "envelope_pct": 0.05})

    assert signals.iloc[3] == Signal.BUY


def test_sell_signal_ma_touch_mode_when_price_reverts_to_average():
    # index3: BUY (as above). index4: ma=mean(100,90,100)=96.67, close=100 >= 96.67 → SELL
    candles = _candles([100, 100, 100, 90, 100, 100])

    signals = EnvelopeStrategy().evaluate(
        candles, {"ma_window": 3, "envelope_pct": 0.05, "exit_mode": "ma_touch"}
    )

    assert signals.iloc[4] == Signal.SELL


def test_sell_signal_opposite_band_mode_requires_upper_band_touch():
    # index3: ma=mean(100,100,112)=104, upper=104*1.05=109.2, close=112 >= 109.2 → SELL
    candles = _candles([100, 100, 100, 112])

    signals = EnvelopeStrategy().evaluate(
        candles, {"ma_window": 3, "envelope_pct": 0.05, "exit_mode": "opposite_band"}
    )

    assert signals.iloc[3] == Signal.SELL


def test_opposite_band_mode_does_not_sell_on_mere_ma_touch():
    # ma_touch였다면 매도였을 상황(index4, close=100>=ma 96.67)이 opposite_band에서는
    # 상단 밴드(109.2 근방)에 못 미쳐 HOLD여야 함
    candles = _candles([100, 100, 100, 90, 100, 100])

    signals = EnvelopeStrategy().evaluate(
        candles, {"ma_window": 3, "envelope_pct": 0.05, "exit_mode": "opposite_band"}
    )

    assert signals.iloc[4] == Signal.HOLD


def test_defaults_to_ma_touch_exit_mode_when_unspecified():
    candles = _candles([100, 100, 100, 90, 100, 100])

    signals = EnvelopeStrategy().evaluate(candles, {"ma_window": 3, "envelope_pct": 0.05})

    assert signals.iloc[4] == Signal.SELL


def test_rejects_unknown_exit_mode():
    candles = _candles([100] * 10)

    with pytest.raises(ValueError):
        EnvelopeStrategy().evaluate(
            candles, {"ma_window": 3, "envelope_pct": 0.05, "exit_mode": "not_a_real_mode"}
        )
