"""P1·P2·P3 — 호환 모드 vs 기존 simulator.run / metrics.compute / simulate_slot_portfolio.

실데이터(data/cache/daily_all.parquet, 고정 구간 2023-01-02~2026-08-31, 코드 정렬 앞 20종목)는
@pytest.mark.parity — 없으면 skip. 합성 모서리는 항상 돈다.
"""
import os

import numpy as np
import pandas as pd
import pytest

from backtesting import metrics as legacy_metrics_mod
from backtesting import simulator
from backtesting.portfolio_sim import simulate_slot_portfolio
from backtesting.strategies.ma_crossover import MovingAverageCrossover
from backtesting.strategies.new_high_swing import NewHighSwing
from backtesting.strategies.rsi_strategy import RsiStrategy
from backtesting.types import Signal
from studio.domain.engine.compat import legacy_slots, run_compat
from studio.domain.metrics import legacy_metrics

PARQUET = os.path.join("data", "cache", "daily_all.parquet")
COMM, SLIP, CAP = 0.00015, 0.001, 10_000_000
STRATEGIES = {
    "ma_5_20": (MovingAverageCrossover(), {"short_window": 5, "long_window": 20}),
    "rsi_14_30_70": (RsiStrategy(), {"period": 14, "buy_below": 30, "sell_above": 70}),
    "new_high_20": (NewHighSwing(), {"n_day_high": 20}),
}
TOL = 1e-9


def _assert_same_trades(old, new):
    assert len(old) == len(new)
    for o, n in zip(old, new):
        assert o.entry_date == n.entry_ts.date()
        assert (o.exit_date is None) == (n.exit_ts is None)
        if o.exit_date is not None:
            assert o.exit_date == n.exit_ts.date()
            assert o.exit_price == pytest.approx(n.exit_price, abs=TOL, rel=TOL)
            assert o.pnl == pytest.approx(n.net_pnl, abs=TOL, rel=TOL)
            assert o.pnl_pct == pytest.approx(n.net_pct, abs=TOL, rel=TOL)
        assert o.entry_price == pytest.approx(n.entry_price, abs=TOL, rel=TOL)
        assert o.quantity == n.qty
        assert o.commission == pytest.approx(n.commission, abs=TOL, rel=TOL)
        assert o.slippage == pytest.approx(n.slippage_cost, abs=TOL, rel=TOL)


def _both(candles, signals, code="X", force_eod_close=False):
    old = simulator.run(candles, signals, COMM, SLIP, CAP, code, force_eod_close=force_eod_close)
    new = run_compat(candles, signals, COMM, SLIP, CAP, code, force_eod_close=force_eod_close)
    return old, new


def _p2(old, new, candles):
    m_old = legacy_metrics_mod.compute(old, candles, CAP)
    m_new = legacy_metrics(new, candles.index.normalize().nunique(), CAP)
    for k, v in m_new.items():
        assert getattr(m_old, k) == pytest.approx(v, abs=TOL, rel=TOL), k


# ------------------------------------------------------------------ 실데이터

@pytest.fixture(scope="module")
def real20():
    if not os.path.exists(PARQUET):
        pytest.skip("daily_all.parquet 없음")
    d = pd.read_parquet(PARQUET)
    d = d[(d["date"] >= "2023-01-02") & (d["date"] <= "2026-08-31")]
    out = {}
    for code, g in d.groupby("code"):
        if len(g) < 500:
            continue
        out[code] = g.assign(date=pd.to_datetime(g["date"])).set_index("date")[
            ["open", "high", "low", "close", "volume"]].astype(float)
        if len(out) == 20:
            break
    assert len(out) == 20
    return out


@pytest.mark.parity
@pytest.mark.parametrize("name", STRATEGIES)
def test_p1_p2_real_20_stocks(real20, name):
    strat, params = STRATEGIES[name]
    total = 0
    for code, candles in real20.items():
        sig = strat.evaluate(candles, params)
        old, new = _both(candles, sig, code)
        _assert_same_trades(old, new)
        _p2(old, new, candles)
        total += len(old)
    assert total > 20  # 거래가 실제로 나오는 비교여야 의미가 있다


@pytest.mark.parity
@pytest.mark.parametrize("name", STRATEGIES)
def test_p3_legacy_slots_real(real20, name):
    strat, params = STRATEGIES[name]
    alltr = []
    for code, candles in real20.items():
        alltr += run_compat(candles, strat.evaluate(candles, params), COMM, SLIP, CAP, code)
    for slots in (3, 5):
        got = legacy_slots(alltr, 10_000_000, slots)
        closed = [t for t in alltr if t.net_pct is not None]
        cand = pd.DataFrame({"entry_time": [t.entry_ts for t in closed], "exit_time": [t.exit_ts for t in closed],
                             "pct": [t.net_pct for t in closed], "code": [t.code for t in closed]})
        ref = simulate_slot_portfolio(cand, 10_000_000, slots)
        assert got["final_capital"] == pytest.approx(ref.final_capital, abs=TOL, rel=TOL)
        assert got["n_skipped"] == ref.skipped_count
        ref_taken = {(t.code, t.entry_time, t.exit_time) for t in ref.taken_trades}
        mine = {(t.code, t.entry_ts, t.exit_ts) for k, t in enumerate(alltr) if got["taken"][k]}
        assert mine == ref_taken


# ------------------------------------------------------------------ 합성 모서리

def _mk(closes, opens=None, idx=None):
    n = len(closes)
    idx = idx if idx is not None else pd.date_range("2024-01-02", periods=n, freq="B")
    o = np.asarray(opens if opens is not None else closes, dtype=float)
    cl = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": o, "high": np.maximum(o, cl) * 1.01, "low": np.minimum(o, cl) * 0.99,
                         "close": cl, "volume": 1000.0}, index=idx)


def _sig(c, at: dict):
    s = pd.Series(Signal.HOLD, index=c.index)
    for i, v in at.items():
        s.iloc[i] = v
    return s


def test_synthetic_upper_limit_lock_carries():
    closes = [100, 100, 130, 131, 130, 120, 110, 105, 100, 100]
    c = _mk(closes)
    s = _sig(c, {1: Signal.BUY, 4: Signal.SELL, 5: Signal.BUY, 6: Signal.SELL})
    old, new = _both(c, s)
    _assert_same_trades(old, new)
    _p2(old, new, c)
    # 봉2 시가(130)가 상한가 잠김 → 봉3(131) 에서 체결됐어야 한다 — 모서리가 실제로 발동했는지
    assert old[0].entry_date == c.index[3].date() and new[0].entry_ts == c.index[3]


def test_synthetic_lower_limit_locked_sell_carries():
    c = _mk([100, 100, 100, 70, 70, 80, 80, 80])
    s = _sig(c, {0: Signal.BUY, 2: Signal.SELL})
    old, new = _both(c, s)
    _assert_same_trades(old, new)
    assert old and old[0].exit_date is not None


def test_synthetic_never_closed():
    c = _mk([100, 101, 102, 103, 104, 105])
    s = _sig(c, {0: Signal.BUY})
    old, new = _both(c, s)
    _assert_same_trades(old, new)
    assert old[0].exit_date is None and new[0].exit_ts is None
    _p2(old, new, c)


def _intraday(days=3, per_day=6):
    idx = pd.DatetimeIndex([pd.Timestamp("2024-01-02") + pd.Timedelta(days=d, minutes=540 + 5 * k)
                            for d in range(days) for k in range(per_day)])
    rng = np.random.default_rng(3)
    close = 1000 * np.cumprod(1 + rng.normal(0, 0.01, len(idx)))
    return _mk(close, idx=idx)


@pytest.mark.parametrize("seed", range(6))
def test_synthetic_force_eod_close_random(seed):
    c = _intraday()
    rng = np.random.default_rng(seed)
    vals = [Signal.BUY, Signal.SELL, Signal.HOLD, Signal.HOLD]
    s = pd.Series([vals[i] for i in rng.integers(0, 4, len(c))], index=c.index)
    old, new = _both(c, s, force_eod_close=True)
    _assert_same_trades(old, new)
    _p2(old, new, c)


def test_synthetic_eod_locked_close_holds_over():
    idx = pd.DatetimeIndex(["2024-01-02 09:00", "2024-01-02 15:20", "2024-01-03 09:00",
                            "2024-01-03 15:20", "2024-01-04 09:00", "2024-01-04 15:20"])
    c = _mk([100, 100, 100, 70, 70, 75], idx=idx)
    s = pd.Series([Signal.BUY, Signal.HOLD, Signal.HOLD, Signal.BUY, Signal.HOLD, Signal.HOLD], index=idx)
    old, new = _both(c, s, force_eod_close=True)
    _assert_same_trades(old, new)


def test_random_signals_daily_fuzz():
    rng = np.random.default_rng(11)
    for _ in range(20):
        n = 120
        closes = 100 * np.cumprod(1 + rng.normal(0, 0.05, n))
        opens = np.r_[closes[0], closes[:-1]] * (1 + rng.normal(0, 0.02, n))
        c = _mk(closes, opens=opens)
        vals = [Signal.BUY, Signal.SELL, Signal.HOLD]
        s = pd.Series([vals[i] for i in rng.integers(0, 3, n)], index=c.index)
        old, new = _both(c, s)
        _assert_same_trades(old, new)
        _p2(old, new, c)
