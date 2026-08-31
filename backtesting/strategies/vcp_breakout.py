"""일봉 변동성수축 신고가 돌파 (신고가추세매매 후보1 변형) — 좁아진 변동성 위의 돌파만 진입.

new_high_swing.py의 진입/청산 채널 로직은 그대로 상속하고, "돌파 직전 일간 변동폭이
평소보다 충분히 좁았는지"(VCP: Volatility Contraction Pattern) 조건 하나만 덧씌운다.
좁은 베이스 위의 돌파가 넓게 출렁이던 구간에서 튀어나온 돌파보다 되돌림(휩쏘)에 덜
취약하다는 관찰(Minervini류 VCP)을 검증하기 위한 A/B 변형 — new_high_swing과 같은
n_day_high로 그리드서치해 이 게이트가 실제로 승률/손익비를 개선하는지 대조한다.

CONTRACTION_SHORT_DAYS 평균 일간레인지가 CONTRACTION_LONG_DAYS 평균 대비
CONTRACTION_RATIO 이하로 좁아져 있어야 진입을 허용한다. 파라미터로 노출하지 않고
고정한다 — n_day_high 스윙만으로도 그리드가 3배인데 여기서 또 늘리면 조합별 표본
수만 잘게 쪼개진다(파라미터 최소화).
"""
import pandas as pd

from ..types import Signal
from .new_high_swing import NewHighSwing


class VcpBreakout(NewHighSwing):
    name = "vcp_breakout"

    CONTRACTION_SHORT_DAYS = 5   # 근거: 돌파 직전 1주일 정도의 즉각적 변동성
    CONTRACTION_LONG_DAYS = 20   # 근거: VOLUME_LOOKBACK_DAYS와 동일 기준선(약 1개월) 재사용
    CONTRACTION_RATIO = 0.7      # 근거: Minervini VCP 관행 - 최근 변동폭이 평소 대비 30%+ 좁아야 유의미

    def evaluate(self, candles: pd.DataFrame, params: dict) -> pd.Series:
        signals = super().evaluate(candles, params).copy()

        daily_range_pct = (candles["high"] - candles["low"]) / candles["close"]
        short_avg_range = daily_range_pct.shift(1).rolling(self.CONTRACTION_SHORT_DAYS).mean()
        long_avg_range = daily_range_pct.shift(1).rolling(self.CONTRACTION_LONG_DAYS).mean()
        contracted = short_avg_range < long_avg_range * self.CONTRACTION_RATIO

        signals[(signals == Signal.BUY) & ~contracted] = Signal.HOLD
        return signals
