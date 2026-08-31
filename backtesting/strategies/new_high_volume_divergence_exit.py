"""일봉 신고가 스윙 — 청산가설 B(추격매수 소진 / 거래량 다이버전스) 버전.

new_high_swing.py와 진입은 완전히 동일(같은 채널+거래량 조건, new_high_leg_exit.py와
같은 이유로 검증 끝난 파일은 안 건드리고 복제). 청산만 다르다.

가설(수요쪽 얼굴, 청산가설A-공급쪽의 거울상 — state/agent_reports의 청산가설 문서
참고): 진입가설 후반부("추세추종 매수세가 가격을 밀어올린다")가 맞다면, 그 매수세가
마르기 시작하는 순간이 온다. 가격은 계속 신고가를 갱신해도 그 신고가를 만드는 거래량이
이전 신고가 때보다 줄어드는 건 "새로 붙는 매수자 수 자체가 줄고 있다"는 선행신호다 —
가격구조(청산가설A)가 아직 안 깨졌어도 엔진은 식고 있다는 신호이므로, A보다 먼저
발동할 것으로 예상한다(이 선후관계 자체가 A/B가 같은 메커니즘의 양면이라는 주장의
검증 대상 — 그 비교는 백테스트 에이전트가 두 전략의 신호 타임스탬프를 대조해서 할 것).

동작: 현재 진입 leg(new_high_leg_exit.py와 동일한 leg 정의 — 가장 최근 채널돌파
이후 구간) 안에서 "이 종가가 leg 내 지금까지의 최고치를 경신"할 때마다 그 순간의
거래량을 "국소 고점 거래량"으로 기록한다. 새 국소고점의 거래량이 바로 직전 국소고점의
거래량보다 낮으면(다이버전스) 그 자리에서 청산 신호를 낸다. leg의 첫 국소고점(=돌파
그 자체)은 비교 대상이 없어 청산 신호를 내지 않는다.

파라미터: 새로 추가한 자유 파라미터 0개 — "줄었으면 판다"를 그대로 부등호로 옮겼다
(몇 % 이상 줄어야 하는지 같은 문턱값을 넣지 않았다, 노이즈로 너무 잦으면 그때 추가할
것 — 지금은 가설을 있는 그대로 시험한다).

청산가설A(new_high_leg_exit.py)와는 별개 전략으로 둔다 — 같이 합치면 어느 쪽이
청산을 발동시켰는지 구분이 안 돼 "B가 A를 선행하는가"라는 검증 자체가 불가능해진다.
"""
import pandas as pd

from ..types import Signal
from .new_high_swing import NewHighSwing


class NewHighVolumeDivergenceExit(NewHighSwing):
    name = "new_high_volume_divergence_exit"

    def evaluate(self, candles: pd.DataFrame, params: dict) -> pd.Series:
        n = params["n_day_high"]

        entry_channel = candles["high"].shift(1).rolling(n).max()
        avg_volume = candles["volume"].shift(1).rolling(self.VOLUME_LOOKBACK_DAYS).mean()
        broke_out = candles["close"] > entry_channel
        buy_condition = broke_out & (candles["volume"] >= avg_volume * self.VOLUME_MULT)

        leg_id = broke_out.cumsum()
        close_cummax_in_leg = candles["close"].groupby(leg_id).cummax()
        is_new_local_high = candles["close"] >= close_cummax_in_leg

        # 국소고점이 아닌 봉은 NaN, 국소고점인 봉만 그날 거래량 — leg 안에서 앞으로
        # ffill하면 "지금까지의 가장 최근 국소고점 거래량"이 되고, 한 칸 shift하면
        # "바로 직전 국소고점 거래량"이 된다(leg 경계를 넘어 새지 않도록 둘 다 leg별로).
        peak_volume_held = candles["volume"].where(is_new_local_high).groupby(leg_id).ffill()
        prev_peak_volume = peak_volume_held.groupby(leg_id).shift(1)
        sell_condition = is_new_local_high & (candles["volume"] < prev_peak_volume)

        signals = pd.Series(Signal.HOLD, index=candles.index)
        signals[buy_condition] = Signal.BUY
        signals[sell_condition] = Signal.SELL
        return signals
