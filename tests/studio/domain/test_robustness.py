"""robustness.py — 비용 민감도·몬테카를로·집중도."""
import numpy as np
import pandas as pd
import pytest

from studio.domain import robustness as rb
from studio.domain.costs import CostModel
from studio.domain.engine.fills import ExitRules, FillRules
from studio.domain.engine.portfolio import PortfolioRules, run_portfolio
from studio.domain.models import Panel


def _engine_trades(seed=3, n=200, m=6):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-02", periods=n)
    cols = {}
    for k in range(m):
        cl = 20_000 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, n)))
        op = np.r_[cl[0], cl[:-1]] * (1 + rng.normal(0, 0.004, n))
        cols[f"{k:06d}"] = (op, np.maximum(op, cl) * 1.005, np.minimum(op, cl) * 0.995, cl)
    f = lambda i: pd.DataFrame({c: v[i] for c, v in cols.items()}, index=idx)  # noqa: E731
    c = f(3)
    vol = pd.DataFrame(1e6, index=idx, columns=c.columns)
    panel = Panel(f(0), f(1), f(2), c, vol, c * vol, c.shift(1))
    ent = pd.DataFrame(rng.random((n, m)) < 0.08, index=idx, columns=c.columns)
    ext = pd.DataFrame(rng.random((n, m)) < 0.10, index=idx, columns=c.columns)
    res = run_portfolio(panel, ent, ext, CostModel(), ExitRules(stop_loss_pct=6), FillRules(),
                        PortfolioRules(initial_capital=10_000_000, max_positions=3))
    df = pd.DataFrame([{
        "code": t.code, "entry_ts": t.entry_ts, "exit_ts": t.exit_ts, "entry_price": t.entry_price, "qty": t.qty,
        "gross_pnl": t.gross_pnl, "commission": t.commission, "tax": t.tax, "slippage_cost": t.slippage_cost,
        "net_pnl": t.net_pnl, "net_pct": t.net_pct} for t in res.trades])
    return res, df


def test_cost_sensitivity_k1_equals_actual_and_k0_equals_frictionless_from_fills():
    res, df = _engine_trades()
    assert len(df) > 10
    cs = rb.cost_sensitivity(df, 10_000_000)
    rows = {r["mult"]: r for r in cs["rows"]}
    assert rows[1.0]["net_pnl"] == pytest.approx(df["net_pnl"].sum(), rel=1e-9)
    # 비용 전 손익을 체결 기준가(reference_price)로 독립 계산 — 슬리피지 전 가격
    buys = {}
    frictionless = 0.0
    for f in res.fills:
        if f.side == "buy":
            buys.setdefault(f.code, []).append(f)
        else:
            b = buys[f.code].pop(0)
            frictionless += (f.reference_price - b.reference_price) * f.qty
    assert rows[0.0]["net_pnl"] == pytest.approx(frictionless, rel=1e-9)
    # 배수에 선형, 손익분기 = 비용 전 ÷ 총비용
    assert rows[2.0]["net_pnl"] == pytest.approx(2 * rows[1.0]["net_pnl"] - rows[0.0]["net_pnl"], rel=1e-9)
    be = cs["breakeven_cost_mult"]
    assert be == pytest.approx(cs["gross_before_costs"] / cs["total_costs"])
    assert cs["gross_before_costs"] - be * cs["total_costs"] == pytest.approx(0.0, abs=1e-6)


def test_cost_breakeven_edge_cases():
    base = dict(code="A", entry_ts=pd.Timestamp("2024-01-02"), exit_ts=pd.Timestamp("2024-01-03"), entry_price=100.0, qty=10,
                net_pct=0.0, commission=1.0, tax=1.0, slippage_cost=1.0)
    loss = pd.DataFrame([{**base, "gross_pnl": -100.0, "net_pnl": -102.0}])
    assert rb.cost_sensitivity(loss, 1e6)["breakeven_cost_mult"] == 0.0  # 비용 0 이어도 손실
    free = pd.DataFrame([{**base, "gross_pnl": 50.0, "net_pnl": 50.0, "commission": 0.0, "tax": 0.0, "slippage_cost": 0.0}])
    assert rb.cost_sensitivity(free, 1e6)["breakeven_cost_mult"] is None


def test_monte_carlo_seed_reproducible_and_shape():
    _, df = _engine_trades()
    a = rb.monte_carlo(df, 10_000_000)
    b = rb.monte_carlo(df, 10_000_000)
    assert a == b and a["seed"] == 42 and a["n_sims"] == 1000 and "겹친 보유 무시" in a["approximation"]
    assert rb.monte_carlo(df, 10_000_000, seed=7) != a
    fr, dd = a["final_return_pct"], a["max_drawdown_pct"]
    assert fr["p5"] <= fr["p50"] <= fr["p95"] and dd["p5"] <= dd["p50"] <= dd["p95"] and 0 <= a["prob_mdd_gt_30"] <= 1
    assert 0 < a["weight"] <= 1
    assert rb.monte_carlo(df.head(4), 10_000_000) is None  # 표본 5개 미만은 계산 안 함


def test_monte_carlo_known_answers():
    win = pd.DataFrame({"net_pct": [0.02] * 10, "entry_price": 100.0, "qty": 1000})  # w = 0.1
    r = rb.monte_carlo(win, 1_000_000)
    assert r["weight"] == pytest.approx(0.1)
    assert r["final_return_pct"]["p50"] == pytest.approx(((1 + 0.1 * 0.02) ** 10 - 1) * 100)  # 전부 같은 값 → 분포가 한 점
    assert r["max_drawdown_pct"]["p95"] == 0 and r["prob_mdd_gt_30"] == 0.0
    lose = pd.DataFrame({"net_pct": [-0.5] * 10, "entry_price": 100.0, "qty": 10_000})  # w = 1 → 매번 반토막
    assert rb.monte_carlo(lose, 1_000_000)["prob_mdd_gt_30"] == 1.0


def _trades(pnls, codes=None, dates=None):
    n = len(pnls)
    return pd.DataFrame({
        "code": codes or [f"C{i}" for i in range(n)],
        "exit_ts": pd.to_datetime(dates or pd.bdate_range("2024-01-02", periods=n)),
        "net_pnl": pnls})


def test_concentration_sign_flip():
    t = _trades([1000.0, -100, -100, -100, -100, -100, -100])  # 하나가 다 먹여 살림 → 총 400
    c = rb.concentration(t)
    assert c["total_net_pnl"] == pytest.approx(400)
    k1 = c["by_code"][0]
    assert k1["k"] == 1 and k1["removed"] == ["C0"] and k1["net_pnl_excluding"] == pytest.approx(-600) and k1["sign_flipped"]
    # 골고루 번 경우 상위 1개를 빼도 부호가 같다
    even = rb.concentration(_trades([100.0] * 10))
    assert not any(r["sign_flipped"] for r in even["by_code"]) and even["by_code"][2]["net_pnl_excluding"] == pytest.approx(700)
    # 날짜 기준: 같은 날 몰린 손익
    d = rb.concentration(_trades([500.0, 500.0, -100, -100, -100], dates=["2024-03-04", "2024-03-04", "2024-03-05", "2024-03-06", "2024-03-07"]))
    assert d["by_date"][0]["removed"] == ["2024-03-04"] and d["by_date"][0]["sign_flipped"]
    assert len(rb.concentration(_trades([1.0, 2.0]))["by_code"]) == 1  # 종목이 k 개 이하면 그 k 는 건너뜀


def test_report_and_compat_skips_cost_sensitivity():
    _, df = _engine_trades()
    r = rb.robustness_report(df, 10_000_000)
    assert r["breakeven_cost_mult"] is not None and len(r["cost_sensitivity"]) == 6 and r["monte_carlo"] and r["concentration"]
    rc = rb.robustness_report(df, 10_000_000, is_compat=True)
    assert rc["cost_sensitivity"] is None and "호환 모드" in rc["cost_sensitivity_note"] and rc["monte_carlo"]
    assert rb.robustness_report(df.iloc[0:0], 1e7) is None
