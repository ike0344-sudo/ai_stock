"""견고성 점검 — 비용 민감도 · 몬테카를로 · 집중도 (설계서 §3.8). 순수 계산.

입력은 거래 표(DataFrame — code, exit_ts, entry_price, qty, gross_pnl, commission, tax, slippage_cost, net_pnl,
net_pct) 하나다. 엔진을 다시 돌리지 않는 **사후 근사**라서, 비용이 달라졌을 때 사이징·체결 건너뜀이 달라지는 것은
반영하지 못한다(결과에 approximation 으로 표시).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MULTIPLIERS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)
MC_SIMS = 1_000
MC_SEED = 42
MC_MIN_TRADES = 5


def cost_sensitivity(trades: pd.DataFrame, initial_capital: float,
                     multipliers: tuple[float, ...] = MULTIPLIERS) -> dict:
    """비용(수수료·세금·슬리피지)을 k 배로 했을 때 순수익 = 비용 전 손익 − k × 총비용.

    gross_pnl 은 슬리피지가 이미 체결가에 들어간 값이라 비용 전 손익 = gross_pnl + slippage_cost 다.
    k=1 이면 실제 순수익과 정확히 같다. 손익분기 배수 = 비용 전 손익 ÷ 총비용(그 배수에서 순수익 0).
    """
    a = float((trades["gross_pnl"] + trades["slippage_cost"]).sum())
    c = float((trades["commission"] + trades["tax"] + trades["slippage_cost"]).sum())
    rows = [{"mult": k, "net_pnl": a - k * c, "net_return_pct": (a - k * c) / initial_capital * 100}
            for k in multipliers]
    if c <= 0:
        be = None
    elif a <= 0:
        be = 0.0  # 비용이 0 이어도 손실
    else:
        be = a / c
    return {"rows": rows, "breakeven_cost_mult": be, "gross_before_costs": a, "total_costs": c,
            "approximation": "같은 거래·같은 수량을 가정한 사후 계산(비용이 바뀌면 달라질 사이징·건너뜀은 미반영)"}


def monte_carlo(trades: pd.DataFrame, initial_capital: float, n_sims: int = MC_SIMS, seed: int = MC_SEED) -> dict | None:
    """거래 순수익률(net_pct)을 복원추출해 거래 순서를 섞은 1,000개 경로 → 최종 수익·MDD 의 5/50/95% 분위.

    한 거래에 자본의 w(평균 진입 금액 ÷ 초기자금) 를 건다고 보고 복리: 자산 *= 1 + w × net_pct.
    **겹친 보유는 무시**한다(거래를 한 줄로 세움) — 동시 보유가 많은 포트폴리오에선 낙폭 규모가 실제와 다르다.
    """
    pct = trades["net_pct"].to_numpy(dtype=float)
    n = len(pct)
    if n < MC_MIN_TRADES:
        return None
    w = float(min(1.0, (trades["entry_price"] * trades["qty"]).mean() / initial_capital))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_sims, n))
    cum = np.cumprod(1.0 + w * pct[idx], axis=1)
    path = np.concatenate([np.ones((n_sims, 1)), cum], axis=1)
    peak = np.maximum.accumulate(path, axis=1)
    mdd = ((peak - path) / peak).max(axis=1) * 100
    final = (cum[:, -1] - 1) * 100
    q = lambda a: {"p5": float(np.percentile(a, 5)), "p50": float(np.percentile(a, 50)),  # noqa: E731
                   "p95": float(np.percentile(a, 95))}
    return {"n_sims": n_sims, "seed": seed, "n_trades": n, "weight": w,
            "final_return_pct": q(final), "max_drawdown_pct": q(mdd),
            "prob_mdd_gt_30": float((mdd > 30).mean()),
            "approximation": "겹친 보유 무시 — 거래를 한 줄로 세워 복리"}


def concentration(trades: pd.DataFrame, top_ks: tuple[int, ...] = (1, 2, 3)) -> dict:
    """손익이 몇 종목·며칠에 몰렸나 — 기여 상위 k 개(종목별·청산일별 순손익 합이 큰 순)를 빼면 순손익이 얼마이고
    부호가 뒤집히나. 부호가 뒤집히면 '소수의 운 좋은 거래'로 번 결과다."""
    total = float(trades["net_pnl"].sum())
    out: dict[str, Any] = {"total_net_pnl": total}
    for label, key in (("by_code", trades["code"]), ("by_date", pd.to_datetime(trades["exit_ts"]).dt.normalize())):
        g = trades.groupby(key)["net_pnl"].sum().sort_values(ascending=False)
        rows = []
        for k in top_ks:
            if len(g) <= k:
                continue
            excl = total - float(g.iloc[:k].sum())
            rows.append({"k": k, "removed": [str(x) if label == "by_code" else str(x.date()) for x in g.index[:k]],
                         "removed_pnl": float(g.iloc[:k].sum()), "net_pnl_excluding": excl,
                         "sign_flipped": bool(total != 0 and np.sign(excl) != np.sign(total))})
        out[label] = rows
    return out


def robustness_report(trades: pd.DataFrame, initial_capital: float, *, is_compat: bool = False,
                      seed: int = MC_SEED) -> dict | None:
    """결과 화면용 묶음(summary.robustness). 종료된 거래가 없으면 None."""
    closed = trades[trades["net_pnl"].notna()]
    if closed.empty:
        return None
    out: dict[str, Any] = {"n_trades": len(closed)}
    if is_compat:
        # 호환 모드의 slippage_cost 는 기존 코드 정의(진입 쪽만)라 비용 전 손익을 복원할 수 없다.
        out.update(cost_sensitivity=None, breakeven_cost_mult=None,
                   cost_sensitivity_note="호환 모드는 기존 코드의 슬리피지 기록이 진입 쪽뿐이라 비용 민감도를 계산하지 않는다")
    else:
        cs = cost_sensitivity(closed, initial_capital)
        out.update(cost_sensitivity=cs["rows"], breakeven_cost_mult=cs["breakeven_cost_mult"],
                   cost_sensitivity_meta={k: cs[k] for k in ("gross_before_costs", "total_costs", "approximation")})
    out["monte_carlo"] = monte_carlo(closed, initial_capital, seed=seed)
    out["concentration"] = concentration(closed)
    return out
