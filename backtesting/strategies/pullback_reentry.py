"""[폐기됨 - strategies/__init__.py 활성 로테이션에서 제외, 2026-08-29]

가설 반증: 워크포워드에서 초과수익-코스피 상관 0.34, 상승장 5폴드 중 4개 플러스,
하락장 9폴드 중 6개 마이너스 - 뚜렷한 국면의존. backtest-agent 진단: 이 신호는
"n_day_high 돌파가 최근에 있었어야" 성립하는데, 그 선행조건 자체가 상승장에서
훨씬 잦게 발생한다(개별종목 우연이 아니라 구조적 편향). 즉 실제 작동한 메커니즘은
"셰이크아웃 후 재돌파"가 아니라 그냥 "상승장 지속"이었다 - new_high_swing이 국면
무관(상관 0.05)하게 같은 자리를 더 깨끗하게 커버하므로 이 전략은 존재 이유가 없다.
국면조건부로 가설을 다시 쓰는 것(사실상 "상승장엔 사면 오른다"의 재진술)과, 신호를
개별종목 상대강도 조건으로 바꾸는 것(지수 데이터가 필요해 현재 단일종목 evaluate()
인터페이스로는 계산 불가 - 완전히 새 가설이 됨) 둘 다 검토 후 기각했다. 코드/테스트는
기록으로 남긴다("정보를 접지 않는다") - 되살릴 거면 새 가설로 처음부터 다시 시작할 것.
---
일봉 눌림목 재돌파 (신고가추세매매 후보2) — 돌파 이후 얕은 되돌림을 거쳐 재상승할 때 진입.

패턴: 1) n_day_high 채널을 상향 돌파(신고가) 발생 → 2) 이후 최대 pullback_window_days
거래일 안에서 exit_low_days 저가채널을 한 번도 이탈하지 않은 얕은 되돌림 → 3) 그 구간
안에서 다시 reentry_days 신고가를 경신(재돌파)하면 진입. 청산은 new_high_swing.py와
동일한 저가채널 이탈 — 신고가추세매매 전략군 전체가 같은 청산 규칙을 써야 진입 규칙만
바꿔가며 서로 비교할 수 있다(EXIT_LOW_RATIO 등 상수를 상속으로 그대로 재사용).

근사 하나: "눌림 구간에서 그 특정 돌파일 이후로 한 번도 이탈 안 했는지"를 정확히 추적
하려면 전략이 자기 포지션 상태(마지막 돌파일이 언제였는지)를 들고 있어야 하는데,
그건 simulator.run()이 상태를 안 돌려주는 계약과 부딪힌다(new_high_swing.py의 하드
플로어를 생략한 이유와 동일). 대신 "최근 pullback_window_days 거래일 롤링 창 안에
돌파와 무이탈이 동시에 있었는지"로 근사한다 — 창 경계에서 실제 돌파일과 며칠 어긋날
수 있지만 방향성은 같다. 상태 추적이 꼭 필요해지면(예: 어긋남이 실제로 신호 품질을
떨어뜨리는 게 확인되면) simulator.run()에 전략별 상태를 넘겨주는 훅을 추가하는 걸
백테스트 에이전트에 요청할 것 — 엔진 변경은 이 에이전트 권한 밖.

파라미터: n_day_high(1차 돌파 채널, new_high_swing.py와 동일 후보 20/60/120 공유),
pullback_window_days=10(근거: 눌림은 보통 2주 이내에 재랠리로 마무리되는 게 전형적 -
너무 길면 "돌파 직후"라는 전제가 희석됨), reentry_days=3(근거: 재돌파 확인은 짧게 -
1이면 전일 대비 상승과 구분이 안 되고, 길면 이미 많이 오른 뒤 후행 확인이 됨).
"""
import pandas as pd

from ..types import Signal
from .new_high_swing import NewHighSwing


class PullbackReentry(NewHighSwing):
    name = "pullback_reentry"

    PULLBACK_WINDOW_DAYS = 10
    REENTRY_DAYS = 3

    def evaluate(self, candles: pd.DataFrame, params: dict) -> pd.Series:
        n = params["n_day_high"]
        m = params.get("exit_low_days") or max(2, round(n * self.EXIT_LOW_RATIO))
        p = params.get("pullback_window_days", self.PULLBACK_WINDOW_DAYS)
        k = params.get("reentry_days", self.REENTRY_DAYS)

        entry_channel = candles["high"].shift(1).rolling(n).max()
        exit_channel = candles["low"].shift(1).rolling(m).min()
        reentry_channel = candles["close"].shift(1).rolling(k).max()
        avg_volume = candles["volume"].shift(1).rolling(self.VOLUME_LOOKBACK_DAYS).mean()

        broke_out = candles["close"] > entry_channel
        channel_breached = candles["close"] < exit_channel

        recent_breakout = broke_out.astype(int).shift(1).rolling(p).max() > 0
        no_breach_since = channel_breached.astype(int).shift(1).rolling(p).max() == 0
        reentry_trigger = candles["close"] > reentry_channel
        volume_ok = candles["volume"] >= avg_volume * self.VOLUME_MULT

        buy_condition = recent_breakout & no_breach_since & reentry_trigger & volume_ok

        signals = pd.Series(Signal.HOLD, index=candles.index)
        signals[buy_condition] = Signal.BUY
        signals[channel_breached] = Signal.SELL
        return signals
