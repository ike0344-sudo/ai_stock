import pandas as pd
import pytest

from backtesting.strategies.ma_crossover import MovingAverageCrossover
from backtesting.strategies.new_high_leg_exit import NewHighLegExit
from backtesting.strategies.new_high_swing import NewHighSwing
from backtesting.strategies.new_high_volume_divergence_exit import NewHighVolumeDivergenceExit
from backtesting.strategies.pullback_reentry import PullbackReentry
from backtesting.strategies.rsi_strategy import RsiStrategy
from backtesting.strategies.vcp_breakout import VcpBreakout
from backtesting.types import Signal

from ._lookahead import assert_signals_do_not_use_future_data


def _candles(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({"close": closes}, index=index)


def _ohlcv(high: list[float], low: list[float], close: list[float], volume: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(close), freq="B")
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume}, index=index)


def test_ma_crossover_buy_on_golden_cross():
    closes = [10, 10, 10, 10, 10, 10, 20, 20, 20, 20, 20, 20]
    candles = _candles(closes)

    signals = MovingAverageCrossover().evaluate(candles, {"short_window": 2, "long_window": 4})

    assert (signals == Signal.BUY).sum() >= 1
    assert (signals == Signal.SELL).sum() == 0


def test_ma_crossover_sell_on_dead_cross():
    closes = [20, 20, 20, 20, 20, 20, 10, 10, 10, 10, 10, 10]
    candles = _candles(closes)

    signals = MovingAverageCrossover().evaluate(candles, {"short_window": 2, "long_window": 4})

    assert (signals == Signal.SELL).sum() >= 1
    assert (signals == Signal.BUY).sum() == 0


def test_ma_crossover_rejects_invalid_window_order():
    candles = _candles([10] * 10)

    with pytest.raises(ValueError):
        MovingAverageCrossover().evaluate(candles, {"short_window": 20, "long_window": 5})


def test_rsi_buy_signal_on_sustained_decline():
    closes = [100 - i for i in range(20)]
    candles = _candles(closes)

    signals = RsiStrategy().evaluate(candles, {"period": 14, "buy_below": 30, "sell_above": 70})

    assert (signals == Signal.BUY).sum() >= 1
    assert (signals == Signal.SELL).sum() == 0


def test_rsi_sell_signal_on_sustained_rally():
    closes = [100 + i for i in range(20)]
    candles = _candles(closes)

    signals = RsiStrategy().evaluate(candles, {"period": 14, "buy_below": 30, "sell_above": 70})

    assert (signals == Signal.SELL).sum() >= 1
    assert (signals == Signal.BUY).sum() == 0


def test_new_high_swing_buy_on_channel_breakout_with_volume():
    # 21봉 평평한 구간(고가10/거래량100) 뒤 22번째 봉이 채널을 종가로 돌파 + 거래량 1.5배 이상
    candles = _ohlcv(
        high=[10] * 21 + [50], low=[9] * 21 + [40], close=[9.5] * 21 + [45], volume=[100] * 21 + [1000],
    )

    signals = NewHighSwing().evaluate(candles, {"n_day_high": 5, "exit_low_days": 3})

    assert signals.iloc[-1] == Signal.BUY
    # rolling(5) 워밍업 구간(자기 자신을 채널에 포함시키면 안 됨)은 항상 HOLD
    assert (signals.iloc[:5] == Signal.HOLD).all()


def test_new_high_swing_no_buy_without_volume_confirmation():
    # 가격은 똑같이 채널을 돌파하지만 거래량이 평소와 같다 -> 진입 보류
    candles = _ohlcv(
        high=[10] * 21 + [50], low=[9] * 21 + [40], close=[9.5] * 21 + [45], volume=[100] * 22,
    )

    signals = NewHighSwing().evaluate(candles, {"n_day_high": 5, "exit_low_days": 3})

    assert signals.iloc[-1] == Signal.HOLD


def test_new_high_swing_sell_on_channel_breakdown():
    # 21봉 평평한 구간(저가19) 뒤 22번째 봉이 3일 저가채널(19) 아래로 종가 이탈
    candles = _ohlcv(
        high=[20] * 21 + [9], low=[19] * 21 + [8], close=[19.5] * 21 + [8.5], volume=[100] * 22,
    )

    signals = NewHighSwing().evaluate(candles, {"n_day_high": 5, "exit_low_days": 3})

    assert signals.iloc[-1] == Signal.SELL


def test_pullback_reentry_buys_on_rebreakout_after_shallow_pullback():
    # 21봉 평평(idx0-20) -> 돌파(idx21, close20/vol1000) -> 얕은 눌림 2봉(idx22-23,
    # 저가채널 이탈 없음) -> 재돌파(idx24, close20.5가 직전 3일 종가고점 20을 돌파)
    candles = _ohlcv(
        high=[10] * 21 + [21, 19, 18.5, 21],
        low=[9] * 21 + [19, 17.5, 17, 18],
        close=[9.5] * 21 + [20, 18, 17.5, 20.5],
        volume=[100] * 21 + [1000, 100, 100, 1000],
    )

    signals = PullbackReentry().evaluate(candles, {"n_day_high": 5})

    assert signals.iloc[24] == Signal.BUY
    # 최초 돌파 당일(idx21)은 이 전략의 진입 조건이 아니다(그건 new_high_swing 담당) - 눌림도
    # 재돌파도 아직 없었으므로 HOLD.
    assert signals.iloc[21] == Signal.HOLD
    assert (signals.iloc[:5] == Signal.HOLD).all()


def test_vcp_breakout_suppresses_buy_without_range_contraction():
    # new_high_swing과 완전히 같은 채널돌파+거래량 조건을 만족하지만(같은 fixture로
    # test_new_high_swing_buy_on_channel_breakout_with_volume는 BUY였다), 돌파 전
    # 변동폭이 플랫 구간 내내 똑같아 "수축"이 없다 -> VCP 게이트가 BUY를 막아야 한다.
    candles = _ohlcv(
        high=[10] * 21 + [50], low=[9] * 21 + [40], close=[9.5] * 21 + [45], volume=[100] * 21 + [1000],
    )

    signals = VcpBreakout().evaluate(candles, {"n_day_high": 5, "exit_low_days": 3})

    assert signals.iloc[-1] == Signal.HOLD


def test_new_high_leg_exit_resets_anchor_on_fresh_breakout():
    # idx21 첫 돌파(그날 저가 8, 아주 깊게 눌렸다 종가만 돌파) -> idx23 재돌파로 leg가
    # 리셋되며 앵커가 8(leg1)에서 13.8(leg2)로 올라간다 -> idx24 종가 13.2는 옛 앵커(8)
    # 보다는 한참 위지만 새 앵커(13.8)보다는 아래라서, "리셋 없는" 구현이면 안 팔리고
    # "리셋 있는"(이 전략) 구현이면 팔려야 한다 - 이 차이가 가설 A의 핵심이다.
    candles = _ohlcv(
        high=[10] * 21 + [15, 13.5, 17, 14],
        low=[9] * 21 + [8, 12, 13.8, 13],
        close=[9.5] * 21 + [14, 13, 16.5, 13.2],
        volume=[100] * 21 + [1000, 100, 1000, 100],
    )

    signals = NewHighLegExit().evaluate(candles, {"n_day_high": 5})

    assert signals.iloc[21] == Signal.BUY   # 최초 돌파(진입은 new_high_swing과 동일 로직)
    assert signals.iloc[24] == Signal.SELL  # 새 leg의 저점(13.8) 이탈 - 옛 leg 저점(8)만 봤다면 안 팔림


def test_new_high_volume_divergence_exit_sells_on_lower_volume_local_high():
    # idx21 첫 국소고점(돌파, 거래량1000, 비교대상 없어 매도신호 없음) -> idx22 고점 아님
    # (HOLD) -> idx23 두번째 국소고점인데 거래량이 idx21보다 낮음(400<1000) -> SELL ->
    # idx24 세번째 국소고점, 거래량이 직전 국소고점(idx23의 400)보다 높음(500>400) -> HOLD
    candles = _ohlcv(
        high=[10] * 21 + [15, 14, 14.9, 14.95],
        low=[9] * 21 + [14, 13, 14.3, 14.5],
        close=[9.5] * 21 + [14.5, 13.5, 14.7, 14.9],
        volume=[100] * 21 + [1000, 100, 400, 500],
    )

    signals = NewHighVolumeDivergenceExit().evaluate(candles, {"n_day_high": 5})

    assert signals.iloc[21] == Signal.BUY
    assert signals.iloc[22] == Signal.HOLD  # 국소고점 자체가 아님
    assert signals.iloc[23] == Signal.SELL  # 국소고점 + 직전 국소고점보다 거래량 감소(다이버전스)
    assert signals.iloc[24] == Signal.HOLD  # 국소고점이지만 직전 국소고점보다 거래량 증가


# --- look-ahead 방어 (돌연변이 테스트) ---
# tests/backtesting/ml/test_features.py:test_features_do_not_use_future_data 와 동일한 방식을
# 실제 매매신호를 내는 전략 레이어로 확장 (state/agent_reports/
# strategy-agent_20260910-153500_tradingagents_salvage.md §2). 코드가 shift(1)로 맞게 짜여
# 있음은 이미 확인했지만, 리팩터 중 shift 하나가 빠져도 잡아줄 회귀가 지금까지 없었다.

_LOOKAHEAD_CLOSES = [100 + (i % 7) - 3 + i * 0.05 for i in range(30)]
_LOOKAHEAD_HIGH = [c + 1 for c in _LOOKAHEAD_CLOSES]
_LOOKAHEAD_LOW = [c - 1 for c in _LOOKAHEAD_CLOSES]
_LOOKAHEAD_VOLUME = [100 + (i % 5) * 30 for i in range(30)]


def test_ma_crossover_signals_do_not_use_future_data():
    candles = _candles(_LOOKAHEAD_CLOSES)
    assert_signals_do_not_use_future_data(
        MovingAverageCrossover(), {"short_window": 2, "long_window": 5}, candles, check_until=25,
    )


def test_rsi_signals_do_not_use_future_data():
    candles = _candles(_LOOKAHEAD_CLOSES)
    assert_signals_do_not_use_future_data(
        RsiStrategy(), {"period": 5, "buy_below": 40, "sell_above": 60}, candles, check_until=25,
    )


def test_new_high_swing_signals_do_not_use_future_data():
    candles = _ohlcv(_LOOKAHEAD_HIGH, _LOOKAHEAD_LOW, _LOOKAHEAD_CLOSES, _LOOKAHEAD_VOLUME)
    assert_signals_do_not_use_future_data(
        NewHighSwing(), {"n_day_high": 5, "exit_low_days": 3}, candles, check_until=25,
    )


def test_vcp_breakout_signals_do_not_use_future_data():
    candles = _ohlcv(_LOOKAHEAD_HIGH, _LOOKAHEAD_LOW, _LOOKAHEAD_CLOSES, _LOOKAHEAD_VOLUME)
    assert_signals_do_not_use_future_data(
        VcpBreakout(), {"n_day_high": 5, "exit_low_days": 3}, candles, check_until=25,
    )


def test_new_high_leg_exit_signals_do_not_use_future_data():
    candles = _ohlcv(_LOOKAHEAD_HIGH, _LOOKAHEAD_LOW, _LOOKAHEAD_CLOSES, _LOOKAHEAD_VOLUME)
    assert_signals_do_not_use_future_data(
        NewHighLegExit(), {"n_day_high": 5}, candles, check_until=25,
    )


def test_new_high_volume_divergence_exit_signals_do_not_use_future_data():
    candles = _ohlcv(_LOOKAHEAD_HIGH, _LOOKAHEAD_LOW, _LOOKAHEAD_CLOSES, _LOOKAHEAD_VOLUME)
    assert_signals_do_not_use_future_data(
        NewHighVolumeDivergenceExit(), {"n_day_high": 5}, candles, check_until=25,
    )


def test_pullback_reentry_signals_do_not_use_future_data():
    candles = _ohlcv(_LOOKAHEAD_HIGH, _LOOKAHEAD_LOW, _LOOKAHEAD_CLOSES, _LOOKAHEAD_VOLUME)
    assert_signals_do_not_use_future_data(
        PullbackReentry(), {"n_day_high": 5}, candles, check_until=25,
    )
