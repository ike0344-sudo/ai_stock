"""일봉 N일 신고가 스윙 (신고가추세매매 후보1) — Donchian 채널 시스템.

진입: 종가가 직전 n_day_high 거래일 고가 채널을 상향 돌파 + 당일 거래량이 직전
      VOLUME_LOOKBACK_DAYS일 평균의 VOLUME_MULT배 이상(최소 참여도 확인).
청산: 종가가 직전 exit_low_days 거래일 저가 채널을 하향 이탈.

전략1(final_strategy.py) 재측정에서 인트라데이 8필터가 전부 "이미 급등한 종목을
그 순간에 더 사는" 방향으로 수렴해 구조적 역선택(ML게이트 제외 시 -70.2%/MDD73.5%)을
만든다는 게 확인됐다 — 그 대안인 회의 후보1. entry_filters.py의 n_day_high_filter와
같은 shift(1).rolling(n).max() 로직을 분봉이 아니라 일봉 자체에 적용한다(분봉은
종목별 표본 중앙값이 3개월뿐이라 워크포워드가 안 선다는 게 확정됐기 때문).

n_day_high 후보: 20(짧은 구조, 신호 많음) / 60(REGIME_MA_PERIOD과 동일 주기) /
120(build_high120.py가 이미 운영 중인 신고가 기준) — grid_search.py로 셋 다 비교 후
하나만 채택할 것, 지금은 후보를 좁히지 않는다.

오버나이트 갭 대응: 별도 규칙 불필요 — simulator.run()이 이미 SELL 신호를 "다음 봉
시가"로 체결하므로(상하한가 고정 시엔 그다음으로 이월) 갭다운으로 채널을 관통해도
실제 체결 가능 가격(그날 시가)으로 청산된다. 여기서 스톱가 체결을 가정하는 코드를
추가하면 오히려 simulator.py의 체결 로직과 중복/불일치를 만든다.

ponytail: 진입가 대비 하드플로어(-8~10%)와 보유일 기반 시간손절은 넣지 않았다.
simulator.run()은 candles+signals만 받는 상태없는 계약이라(entry_price/보유일수를
전략에 되돌려주지 않음) 그 두 규칙을 여기서 구현하려면 전략이 포지션 상태를 별도로
추적해야 하는데, 그건 trading_loop.evaluate_exit가 겪던 것과 같은 "엔진 상태를
전략이 중복 추적"하는 문제를 새로 만드는 것이다. 저가채널 청산이 최대 역행폭을
사실상 제한하므로 1차는 이것으로 충분한지 먼저 보고, MDD가 갭리스크로 못 견디면
그때 simulator.run()에 stop_loss_pct/max_holding_days 같은 범용 파라미터를 추가하는
걸 백테스트 에이전트에 요청할 것(엔진 변경은 이 에이전트 권한 밖).
"""
import pandas as pd

from ..types import Signal


class NewHighSwing:
    name = "new_high_swing"

    VOLUME_MULT = 1.5          # 근거: final_strategy.py 3분 거래대금 조건의 일봉 버전(최소 참여도 확인)
    VOLUME_LOOKBACK_DAYS = 20  # 근거: 진입 채널 폭(n)과 분리된 고정 유동성 기준선(약 1개월)
    EXIT_LOW_RATIO = 1 / 3     # 근거: 터틀 시스템 관행 - 진입 채널 폭의 1/3을 청산 채널로

    def evaluate(self, candles: pd.DataFrame, params: dict) -> pd.Series:
        n = params["n_day_high"]
        m = params.get("exit_low_days") or max(2, round(n * self.EXIT_LOW_RATIO))

        entry_channel = candles["high"].shift(1).rolling(n).max()
        exit_channel = candles["low"].shift(1).rolling(m).min()
        avg_volume = candles["volume"].shift(1).rolling(self.VOLUME_LOOKBACK_DAYS).mean()

        buy_condition = (candles["close"] > entry_channel) & (candles["volume"] >= avg_volume * self.VOLUME_MULT)
        sell_condition = candles["close"] < exit_channel

        signals = pd.Series(Signal.HOLD, index=candles.index)
        signals[buy_condition] = Signal.BUY
        signals[sell_condition] = Signal.SELL
        return signals
