"""폴드 경계를 걸치는 미청산 포지션이 이중진입으로 잡히지 않는지 회귀 테스트.

배경: daily_walk_forward.py 첫 구현은 폴드마다 독립적으로 simulator.run을 불렀다.
폴드 N의 포지션이 폴드 N+1의 test 구간까지 안 닫힌 채 넘어가면, 폴드 N+1은 그 사실을
모르고(각 simulator.run 호출이 자기 폴드만 봄) 자기 구간 안의 새 BUY 신호를 또
진입으로 잡아버렸다 — 실측(133.6s -> 10.3s 속도 최적화 과정에서 발견)으로 확인된
버그. 지금은 종목당 한 번만(simulate_and_bucket_by_fold) 이어서 시뮬레이션하고
거래를 entry_date로 폴드에 사후 배정해 고쳤다. "폴드별로 쪼개 처리"가 자연스러운
구현이라 다음에 성능 최적화 등으로 되돌아오기 쉬우므로, 이 테스트 하나로 막는다.
"""
import pandas as pd

from backtesting.daily_walk_forward import simulate_and_bucket_by_fold
from backtesting.ml.walk_forward import split as wf_split
from backtesting.types import Signal


class _FixedSignalStrategy:
    """가격과 무관하게, 준비된 날짜에만 BUY/SELL을 낸다 — 폴드 경계 시나리오를
    정확히 구성하기 위한 테스트 전용 더미(strategy 인터페이스만 흉내)."""

    name = "fixed_signal_for_test"

    def __init__(self, buy_dates, sell_dates):
        self.buy_dates = set(buy_dates)
        self.sell_dates = set(sell_dates)

    def evaluate(self, candles: pd.DataFrame, params: dict) -> pd.Series:
        def sig(ts):
            d = ts.date()
            if d in self.buy_dates:
                return Signal.BUY
            if d in self.sell_dates:
                return Signal.SELL
            return Signal.HOLD

        return pd.Series([sig(ts) for ts in candles.index], index=candles.index)


def _make_candles() -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=45)
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000_000},
        index=idx,
    )


def test_position_spanning_fold_boundary_is_not_double_entered():
    candles = _make_candles()

    # test_days=step_days=10 -> 폴드가 빈틈/겹침 없이 붙는다.
    splits = wf_split(candles.index[0].date(), candles.index[-1].date(), train_days=1, test_days=10, step_days=10)
    assert len(splits) >= 2
    fold1, fold2 = splits[0], splits[1]

    trading_days = [d.date() for d in candles.index]
    # simulator.run은 신호가 뜬 봉이 아니라 "다음 봉의 시가"로 체결한다 — 그래서 실제
    # 체결일(entry_date)은 신호일 + 1거래일이다. fold1의 마지막 거래일에 체결되도록
    # 신호는 그 하루 전에 심는다.
    fold1_last_idx = max(i for i, d in enumerate(trading_days) if d <= fold1.test_end)
    fold2_first_idx = min(i for i, d in enumerate(trading_days) if d >= fold2.test_start)

    buy_signal_date = trading_days[fold1_last_idx - 1]   # 체결은 fold1_last_idx(폴드1 안)에서.
    entry_date = trading_days[fold1_last_idx]
    exit_date = trading_days[fold2_first_idx + 3]

    # 폴드2 test 구간에도 "새 진입처럼 보이는" BUY 신호를 하나 더 심는다 — 버그가 있던
    # 구현이면 폴드1의 미청산 포지션을 모르고 이걸 또 진입으로 잡는다.
    phantom_buy_date = trading_days[fold2_first_idx]

    strategy = _FixedSignalStrategy(buy_dates=[buy_signal_date, phantom_buy_date], sell_dates=[exit_date])
    horizon_end = candles.index[-1].date()

    fold_trades, _ = simulate_and_bucket_by_fold(
        {"TEST": candles}, strategy, splits, horizon_end, params={}
    )

    all_closed = [t for fold in fold_trades for t in fold if t.pnl is not None]
    assert len(all_closed) == 1, (
        f"폴드 경계를 걸친 포지션이 이중진입으로 잡혔다({len(all_closed)}건) — "
        "폴드별 독립 시뮬레이션으로 되돌아갔는지 확인할 것"
    )
    assert all_closed[0].entry_date == entry_date
    assert len(fold_trades[0]) == 1   # 진입은 폴드1 것으로 배정
    assert len(fold_trades[1]) == 0   # 폴드2엔 팬텀 진입이 없어야 한다
