"""일봉 신고가 스윙 — 청산가설 A(재오버행 형성 / 최근 구간 저점 이탈) 버전.

new_high_swing.py와 진입은 완전히 동일(같은 n_day_high 채널 + 거래량 조건). 청산만
바꾼다 — new_high_swing.py는 검증(국면무관, 부수효과 확인)이 이미 진행/완료된
파일이라 그대로 두고, 이 파일에서 진입 로직만 그대로 복제해 A/B 비교 대상으로 삼는다
(코드 몇 줄 중복이지만 검증 끝난 파일을 건드리지 않는 쪽이 더 싸다).

가설: 진입가설의 후반부("추격매수 자금이 가격을 밀어올린다")를 그대로 뒤집으면,
그 추격매수 자금이 이번 상승구간에서 사들인 가격(=이번 구간 저점)이 깨지는 순간
그들이 새로운 오버행(본전 오면 판다는 잠재매도)이 된다 — 진입 때 이용한 메커니즘이
이번엔 반대로 작동한다는 신호다. 그래서 청산채널을 고정폭(new_high_swing.py의
N x 1/3, 터틀 관행 - 진입가설과 무관)이 아니라 "가장 최근에 n_day_high를 새로
갱신한 시점(leg 시작) 이후의 최저가"로 정의한다. EXIT_LOW_RATIO라는 진입과 무관한
임의 상수가 통째로 사라진다(청산 쪽 자유파라미터 0개).

동작 특성(미리 밝혀둠 - 파라미터로 눌러 덮지 않는다): entry_channel(N일 채널)은
추세가 매끄럽게 이어지면 n 값과 거의 무관하게 거의 매일 갱신되는 경향이 있다
(상승 추세 안에서는 rolling max가 최근 값에 수렴하므로). 그러면 leg가 자주
리셋되며 앵커가 "어제 저가"에 가깝게 바짝 따라붙어, 완만하게 그라인딩하는
추세에서는 청산이 지금(new_high_swing.py)보다 더 타이트해질 수 있다. 이게 손익비를
개선하는지 오히려 승자를 더 일찍 자르는지는 가설 검증 대상이지 미리 정할 값이
아니라서, 리셋 민감도를 줄이는 별도 상수를 넣지 않았다.
"""
import pandas as pd

from ..types import Signal
from .new_high_swing import NewHighSwing


class NewHighLegExit(NewHighSwing):
    name = "new_high_leg_exit"

    def evaluate(self, candles: pd.DataFrame, params: dict) -> pd.Series:
        n = params["n_day_high"]

        entry_channel = candles["high"].shift(1).rolling(n).max()
        avg_volume = candles["volume"].shift(1).rolling(self.VOLUME_LOOKBACK_DAYS).mean()
        broke_out = candles["close"] > entry_channel
        buy_condition = broke_out & (candles["volume"] >= avg_volume * self.VOLUME_MULT)

        # "가장 최근 신고가 갱신(=새 leg 시작)" 이후 구간의 최저가를 누적 추적한다.
        # broke_out이 다시 뜰 때마다 leg_id가 올라가 앵커가 그 시점 저가로 리셋된다.
        leg_id = broke_out.cumsum()
        swing_low_since_breakout = candles["low"].groupby(leg_id).cummin()
        exit_channel = swing_low_since_breakout.shift(1)
        sell_condition = candles["close"] < exit_channel

        signals = pd.Series(Signal.HOLD, index=candles.index)
        signals[buy_condition] = Signal.BUY
        signals[sell_condition] = Signal.SELL
        return signals
