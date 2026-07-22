"""이동평균 엔벨로프(밴드) 평균회귀 전략.

이동평균선 위아래로 일정 비율(envelope_pct)만큼 밴드를 그려, 가격이 하단 밴드
아래로 벗어나면 평균으로 되돌아올 것을 기대하고 매수한다.

파라미터:
- ma_window: 이동평균 기간 (예: 60)
- envelope_pct: 밴드 폭 비율 (예: 0.02 = 상하 2%)
- exit_mode: "ma_touch"(이동평균 복귀 시 매도, 기본값) 또는
  "opposite_band"(상단 밴드 터치 시 매도)

시뮬레이터(simulator.run)는 이미 포지션이 없을 때만 BUY를, 있을 때만 SELL을
반영하는 상태 머신이라 신호는 크로스 이벤트가 아니라 레벨(조건 충족 여부)로만
계산해도 동일하게 동작한다 (ma_crossover의 크로스 검출과 결과적으로 같음).
"""
import pandas as pd

from ..types import Signal

VALID_EXIT_MODES = ("ma_touch", "opposite_band")


class EnvelopeStrategy:
    name = "envelope"

    def evaluate(self, candles: pd.DataFrame, params: dict) -> pd.Series:
        ma_window = params["ma_window"]
        envelope_pct = params["envelope_pct"]
        exit_mode = params.get("exit_mode", "ma_touch")
        if exit_mode not in VALID_EXIT_MODES:
            raise ValueError(f"알 수 없는 exit_mode: {exit_mode} (허용값: {VALID_EXIT_MODES})")

        ma = candles["close"].rolling(ma_window).mean()
        lower_band = ma * (1 - envelope_pct)
        upper_band = ma * (1 + envelope_pct)

        buy_condition = candles["close"] <= lower_band
        if exit_mode == "opposite_band":
            sell_condition = candles["close"] >= upper_band
        else:
            sell_condition = candles["close"] >= ma

        signals = pd.Series(Signal.HOLD, index=candles.index)
        signals[buy_condition] = Signal.BUY
        signals[sell_condition] = Signal.SELL
        return signals
