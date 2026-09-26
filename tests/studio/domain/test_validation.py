"""validation.py — 분할·폴드·그리드·선택·판정."""
import datetime as dt
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from studio.domain import validation as v
from studio.domain.metrics import standard_metrics
from studio.domain.models import BacktestResult, Trade


def days(n=100, holidays=()):
    out, d = [], dt.date(2024, 1, 1)
    while len(out) < n:
        if d.weekday() < 5 and d not in holidays:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def PR(default, mn=None, mx=None, step=None):
    return SimpleNamespace(default=default, min=mn, max=mx, step=step)


# ------------------------------------------------------------------ 분할
def test_split_days_counts_trading_days_not_calendar_days():
    hol = {dt.date(2024, 2, 12), dt.date(2024, 3, 1)}
    d = days(100, hol)
    assert not set(d) & hol
    s = v.split_days(d, holdout_pct=20, train_pct=70)
    assert len(s.holdout_days) == 20 and len(s.opt_days) == 80
    assert len(s.is_days) == 56 and len(s.oos_days) == 24  # floor(80×0.7)
    # 연속·겹침 없음·순서, 홀드아웃은 맨 뒤
    assert s.is_days + s.oos_days + s.holdout_days == d
    assert s.is_days[-1] < s.oos_days[0] and s.oos_days[-1] < s.holdout_days[0]


def test_split_floor_boundaries_and_split_date():
    d = days(33)
    s = v.split_days(d, holdout_pct=20, train_pct=50)
    assert len(s.holdout_days) == 6 and len(s.opt_days) == 27 and len(s.is_days) == 13  # floor(6.6), floor(13.5)
    s2 = v.split_days(d, holdout_pct=0, split_date=d[9])
    assert s2.holdout_days == [] and s2.is_days == d[:10] and s2.oos_days == d[10:]
    with pytest.raises(v.ValidationConfigError):
        v.split_days(d, holdout_pct=0, split_date=d[-1])  # OOS 가 비었다
    with pytest.raises(v.ValidationConfigError):
        v.split_days(d[:1], holdout_pct=0)
    with pytest.raises(v.ValidationConfigError):
        v.split_days([d[1], d[0]])


def test_walkforward_folds_rolling_and_anchored():
    r = v.walkforward_folds(100, 40, 20, mode="rolling")
    assert [(f.train, f.test) for f in r] == [((0, 39), (40, 59)), ((20, 59), (60, 79)), ((40, 79), (80, 99))]
    a = v.walkforward_folds(100, 40, 20, mode="anchored")
    assert [f.train for f in a] == [(0, 39), (0, 59), (0, 79)] and [f.test for f in a] == [f.test for f in r]
    g = v.walkforward_folds(100, 30, 10, step_days=20)
    assert [f.test for f in g] == [(30, 39), (50, 59), (70, 79), (90, 99)]  # 사이가 비면 그 구간은 건너뜀
    with pytest.raises(v.ValidationConfigError, match="폴드가 하나도"):
        v.walkforward_folds(50, 40, 20)
    with pytest.raises(v.ValidationConfigError):
        v.walkforward_folds(100, 40, 20, step_days=10)  # 검증 구간 겹침
    # 검증 구간끼리 겹치지 않고 학습은 항상 검증 앞
    for f in r + a:
        assert f.train[1] + 1 == f.test[0]
    assert all(x.test[1] < y.test[0] for x, y in zip(r, r[1:]))


# ------------------------------------------------------------------ 그리드
def test_axis_values_and_count():
    assert v.axis_values(PR(5, 3, 9, 2)) == [3, 5, 7, 9] and all(isinstance(x, int) for x in v.axis_values(PR(5, 3, 9, 2)))
    assert v.axis_values(PR(0.02, 0.01, 0.05, 0.01)) == [0.01, 0.02, 0.03, 0.04, 0.05]  # 부동소수 잡음 제거
    assert v.axis_values(PR(7)) == [7] and v.axis_values(PR(7, 1, 9, None)) == [7]
    params = {"a": PR(5, 3, 9, 2), "b": PR(20, 10, 40, 10), "c": PR(1)}
    assert v.count_combinations(params) == 4 * 4
    assert v.count_combinations(params, vary=["a"]) == 4
    with pytest.raises(v.ValidationConfigError):
        v.grid_axes(params, vary=["zzz"])
    combos, idx = v.combinations(v.grid_axes(params))
    assert combos[0] == {"a": 3, "b": 10, "c": 1} and combos[-1] == {"a": 9, "b": 40, "c": 1}
    assert len(combos) == len(set(map(tuple, idx))) == 16


def test_grid_too_large():
    params = {"a": PR(1, 1, 100, 1), "b": PR(1, 1, 60, 1)}  # 6,000
    assert v.count_combinations(params) == 6000
    with pytest.raises(v.GridTooLargeError) as e:
        v.combinations(v.grid_axes(params))
    assert e.value.n == 6000 and e.value.limit == 5000
    v.combinations(v.grid_axes({"a": PR(1, 1, 100, 1), "b": PR(1, 1, 50, 1)}))  # 5,000 은 통과


# ------------------------------------------------------------------ 구간 점수
def _rand_case(seed=0, n=300, m=40):
    rng = np.random.default_rng(seed)
    e = 1e7 * np.cumprod(1 + rng.normal(0.0006, 0.01, n))
    exit_idx = np.sort(rng.integers(5, n, m))
    pct = rng.normal(0.004, 0.05, m)
    pnl = pct * 2e6
    return e, TradeArraysCase(exit_idx, pnl, pct)


def TradeArraysCase(exit_idx, pnl, pct):
    return v.TradeArrays(exit_idx=exit_idx, net_pnl=pnl, net_pct=pct)


def test_window_metrics_equals_standard_metrics_over_full_range():
    e, tr = _rand_case()
    ts = pd.bdate_range("2024-01-01", periods=len(e))
    trades = [Trade("A", ts[max(0, i - 3)], 100.0, ts[i], 100.0, 1, None, 0, 0, 0, float(p), float(q), None, 1, None, None)
              for i, p, q in zip(tr.exit_idx, tr.net_pnl, tr.net_pct)]
    eq = pd.DataFrame({"ts": ts, "cash": e, "positions_value": 0.0, "equity": e, "n_positions": 0})
    std = standard_metrics(BacktestResult(trades, eq, [], {}), 1e7)
    w = v.window_metrics(e, 0, len(e) - 1, 1e7, tr)
    for k, val in w.items():
        assert val == pytest.approx(std[k], rel=1e-12, abs=1e-12), k


def test_window_metrics_slice_uses_previous_equity_as_base_and_exit_dates():
    e, tr = _rand_case(1)
    w = v.window_metrics(e, 100, 199, 1e7, tr)
    assert w["total_return_pct"] == pytest.approx((e[199] / e[99] - 1) * 100)
    n_in = int(((tr.exit_idx >= 100) & (tr.exit_idx <= 199)).sum())
    assert w["num_trades"] == n_in > 0


def test_objective_min_trades_and_select_best_uses_only_is_values():
    m = {"num_trades": 29, "sharpe": 3.0}
    assert v.objective_value(m, "sharpe", 30) is None
    assert v.objective_value({**m, "num_trades": 30}, "sharpe", 30) == 3.0
    assert v.objective_value({"num_trades": 40, "cagr_pct": float("nan")}, "cagr", 30) is None
    assert v.select_best([None, 1.0, 3.0, 3.0, None]) == 2  # 동점은 앞
    assert v.select_best([None, None]) is None


def test_neighbor_stability():
    idx = [(i,) for i in range(7)]
    smooth = [0.8, 0.9, 1.0, 1.1, 1.0, 0.9, 0.8]
    r = v.neighbor_stability(idx, smooth, 3)
    assert r["n_neighbors"] == 2 and r["ratio"] == pytest.approx(1.0 / 1.1) and not r["warn"]
    cliff = [0.0, 0.0, 0.1, 2.0, 0.1, 0.0, 0.0]
    r = v.neighbor_stability(idx, cliff, 3)
    assert r["ratio"] == pytest.approx(0.05) and r["warn"] and "성과 절벽" in r["reason"]
    r = v.neighbor_stability(idx, [None, None, None, 1.0, None, None, None], 3)
    assert r["warn"] and r["n_invalid"] == 2
    r = v.neighbor_stability(idx, [1, 1, 1, -0.5, 1, 1, 1], 3)
    assert r["warn"] and "0 이하" in r["reason"]
    # 2 변수: 가장자리 조합은 이웃이 적다, 대각선은 이웃이 아니다
    grid = [(i, j) for i in range(3) for j in range(3)]
    vals = [float(i + j) for i, j in grid]
    r = v.neighbor_stability(grid, vals, grid.index((2, 2)))
    assert r["n_neighbors"] == 2 and r["median"] == pytest.approx(3.0)
    assert v.neighbor_stability([(0,)], [1.0], 0)["reason"].startswith("이웃 조합이 없다")


def test_criteria_directions():
    m = {"sharpe": 1.2, "max_drawdown_pct": 25.0, "num_trades": 40}
    r = {c["metric"]: c for c in v.evaluate_criteria(
        {"sharpe": 1.0, "max_drawdown_pct": 20.0, "num_trades": 30, "nope": 1}, m)}
    assert r["sharpe"]["passed"] and r["sharpe"]["direction"] == "min"
    assert not r["max_drawdown_pct"]["passed"] and r["max_drawdown_pct"]["direction"] == "max"  # 낙폭은 이하
    assert r["num_trades"]["passed"] and not r["nope"]["passed"] and r["nope"]["note"] == "지표 없음"


def test_stitch_wfe_and_drift():
    e1 = np.array([100.0, 110, 121, 133.1])  # 매일 +10%
    e2 = np.array([200.0, 190, 180.5, 171.475])  # 매일 -5%
    s = v.stitch_equity([(e1, 1, 2), (e2, 2, 3)], 1000.0)
    assert list(s) == pytest.approx([1100, 1210, 1210 * 0.95, 1210 * 0.95 * 0.95])
    assert list(v.stitch_equity([(e1, 0, 1)], 100.0)) == pytest.approx([100.0, 110.0])  # i0=0 은 시작 자본(=조합의 초기 평가금) 기준
    assert v.walk_forward_efficiency([20.0, 10.0], 7.5) == pytest.approx(0.5)
    assert v.walk_forward_efficiency([-1.0, 1.0], 5.0) is None and v.walk_forward_efficiency([], 5.0) is None
    d = v.params_drift([{"a": 5, "b": 1}, {"a": 5, "b": 3}, {"a": 9, "b": 3}])
    assert d["a"]["n_distinct"] == 2 and d["b"]["max"] == 3


def test_optimize_config_from_validation_and_errors():
    val = SimpleNamespace(holdout_pct=25.0, objective="calmar", min_trades=10, criteria={"sharpe": 1.0})
    c = v.OptimizeConfig.from_validation(val, train_pct=60)
    assert (c.holdout_pct, c.objective, c.min_trades, c.train_pct, dict(c.criteria)) == (25.0, "calmar", 10, 60, {"sharpe": 1.0})
    assert v.OptimizeConfig.from_validation(None).holdout_pct == 20.0
    for bad in (dict(objective="x"), dict(holdout_pct=60), dict(train_pct=0), dict(min_trades=0)):
        with pytest.raises(v.ValidationConfigError):
            v.OptimizeConfig(**bad)
    with pytest.raises(v.ValidationConfigError):
        v.WalkForwardConfig(60, 20, step_days=10)
    assert v.WalkForwardConfig(60, 20).step == 20
