"""일반 모드 엔진 vs 호환 모드(= 기존 simulator.run) 교차검증 — 엔진 경제성 독립 확인.

비용 0·손절/익절 없음·종목 1개일 때 일반 모드는 호환 모드와 **체결 시점·가격·수익률이 같아야** 한다
(진입/청산 신호 규칙·상하한가 이월·대기 신호 덮어쓰기 규칙이 같다). 수량은 비교하지 않는다 —
호환 모드는 현금 제약이 없고 일반 모드는 있다(손실 후 자금이 줄면 수량이 달라짐).
차이가 남는 알려진 경우(의도된 규칙 차이, 설계서 §3.5 vs §3.6):
  · 끝까지 보유 중인 마지막 거래(호환=미청산, 일반=end_of_data 청산)
  · **상한/하한가로 잠긴 봉의 매수** — 일반 모드는 그날 취소(`skipped.upper_limit`), 호환 모드는 대기 신호를
    유지했다가 다음 봉에 체결한다(기존 simulator.run 의 규칙 4).
  · **잠겨서 밀린 청산이 다음 봉의 새 BUY 신호에 덮어써짐** — 기존 simulator.run 의 규칙 5(매 봉 새 신호가 대기
    신호를 덮어씀)는 잠김으로 이월된 SELL 을 보유 중에 온 BUY 가 지워 버린다(청산이 사라진다). 일반 모드는 이월된
    청산을 유지한다. 시드 5·53 에서 실측.
  잠김을 건드린 시드는 건너뛰고(skip) 잠김 이월 자체의 동치는 아래 고정 시나리오로 따로 확인한다. 건너뛰지 않은
  시드가 충분히 많은지(>=40/60)도 마지막 테스트가 센다.
"""
import numpy as np
import pandas as pd
import pytest

from studio.domain.costs import CostModel
from studio.domain.engine.compat import run_compat
from studio.domain.engine.fills import ExitRules, FillRules
from studio.domain.engine.portfolio import PortfolioRules, run_portfolio
from studio.domain.models import ExitReason, Panel

ZERO = CostModel(0.0, 0.0, "rate", 0.0, 0.0)


def _data(seed, n=250):
    rng = np.random.default_rng(seed)
    close = 1000 * np.cumprod(1 + rng.normal(0, 0.04, n))
    op = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.01, n))
    shock = rng.random(n) < 0.008  # 상하한가 근처 시가 — 잠김 이월 경로를 탄다
    op = np.where(shock, np.r_[close[0], close[:-1]] * rng.choice([1.3, 0.7], n), op)
    idx = pd.bdate_range("2023-01-02", periods=n)
    c = pd.DataFrame({"A": close}, index=idx)
    o = pd.DataFrame({"A": op}, index=idx)
    hi = pd.DataFrame({"A": np.maximum(op, close) * 1.01}, index=idx)
    lo = pd.DataFrame({"A": np.minimum(op, close) * 0.99}, index=idx)
    v = pd.DataFrame({"A": np.full(n, 1e6)}, index=idx)
    return Panel(o, hi, lo, c, v, c * v, c.shift(1)), rng


@pytest.mark.parametrize("seed", range(60))
def test_general_equals_compat_when_costless(seed):
    panel, rng = _data(seed)
    n = len(panel.close)
    buy = rng.random(n) < 0.12
    sell = rng.random(n) < 0.12
    idx = panel.close.index
    ent = pd.DataFrame({"A": buy}, index=idx)
    ext = pd.DataFrame({"A": sell}, index=idx)
    sigs = pd.Series(np.where(sell, "sell", np.where(buy, "buy", "hold")), index=idx)
    candles = pd.DataFrame({k: getattr(panel, k)["A"] for k in ("open", "high", "low", "close", "volume")})

    old = [t for t in run_compat(candles, sigs, 0.0, 0.0, 1e12, "A", tax_rate=0.0) if t.net_pnl is not None]
    res = run_portfolio(panel, ent, ext, ZERO, ExitRules(), FillRules(),
                        PortfolioRules(initial_capital=1e12, max_positions=1, sizing="equal_slot_fixed"))
    new = [t for t in res.trades if t.exit_reason != ExitReason.END_OF_DATA]
    if res.skipped["upper_limit"] or res.diagnostics["carried_exits"]:
        pytest.skip("잠김을 건드린 시드 — 의도된 규칙 차이(모듈 docstring)")
    assert len(old) == len(new) > 0  # 표본이 비지 않아야 의미가 있다
    for o, n_ in zip(old, new):
        assert (o.entry_ts, o.exit_ts) == (n_.entry_ts, n_.exit_ts)
        assert o.entry_price == pytest.approx(n_.entry_price, rel=1e-12)
        assert o.exit_price == pytest.approx(n_.exit_price, rel=1e-12)
        assert o.net_pct == pytest.approx(n_.net_pct, abs=1e-12)


def test_enough_seeds_actually_compared():
    """건너뛴 시드가 너무 많으면 이 교차검증이 공허해진다."""
    compared = 0
    for seed in range(60):
        panel, rng = _data(seed)
        n = len(panel.close)
        buy, sell = rng.random(n) < 0.12, rng.random(n) < 0.12
        idx = panel.close.index
        res = run_portfolio(panel, pd.DataFrame({"A": buy}, index=idx), pd.DataFrame({"A": sell}, index=idx),
                            ZERO, ExitRules(), FillRules(), PortfolioRules(initial_capital=1e12, max_positions=1))
        compared += not (res.skipped["upper_limit"] or res.diagnostics["carried_exits"])
    assert compared >= 40


def test_locked_sell_carry_is_equivalent_without_overwrite():
    """하한가로 잠긴 봉의 청산 이월 — 사이에 새 신호가 없으면 두 모드가 같은 봉·같은 가격에 청산한다."""
    close = [100, 100, 100, 70, 70, 75, 75, 75]
    idx = pd.bdate_range("2024-01-02", periods=len(close))
    c = pd.DataFrame({"A": np.array(close, float)}, index=idx)
    panel = Panel(c, c * 1.01, c * 0.99, c, c * 0 + 1e6, c * 1e6, c.shift(1))
    buy = np.array([1, 0, 0, 0, 0, 0, 0, 0], bool)
    sell = np.array([0, 0, 1, 0, 0, 0, 0, 0], bool)
    sigs = pd.Series(np.where(sell, "sell", np.where(buy, "buy", "hold")), index=idx)
    candles = pd.DataFrame({k: getattr(panel, k)["A"] for k in ("open", "high", "low", "close", "volume")})
    (o,) = run_compat(candles, sigs, 0.0, 0.0, 1e12, "A", tax_rate=0.0)
    res = run_portfolio(panel, pd.DataFrame({"A": buy}, index=idx), pd.DataFrame({"A": sell}, index=idx), ZERO,
                        ExitRules(), FillRules(), PortfolioRules(initial_capital=1e12, max_positions=1))
    (n_,) = res.trades
    assert res.diagnostics["carried_exits"] == 1  # 잠김 경로를 실제로 탔다
    assert (o.exit_ts, o.exit_price) == (n_.exit_ts, n_.exit_price) == (idx[4], 70.0)
