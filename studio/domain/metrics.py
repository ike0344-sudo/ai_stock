"""성과 지표 (설계서 §3.8).

두 벌이다 — 섞지 마라:
  · `legacy_metrics`   : 기존 CLI 기준 6개(P2). `backtesting.metrics.compute` 와 정의가 같다
                         (실현 손익 기준 MDD, 거래 단위 샤프, trading_days/252 CAGR).
  · `standard_metrics` : 일별 평가(equity) 기준 표준 지표 — 스튜디오 화면·검증용.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .models import BacktestResult, Trade

# ---------------------------------------------------------------- 기존 CLI 기준 (P2)


def legacy_metrics(trades: list[Trade], trading_days: int, initial_capital: float) -> dict:
    """완결(net_pnl 있는) 거래만 집계. trading_days = candles.index.normalize().nunique()."""
    closed = sorted((t for t in trades if t.net_pnl is not None), key=lambda t: t.exit_ts.normalize())
    total_pnl = sum(t.net_pnl for t in closed)
    total_return = (total_pnl / initial_capital * 100) if initial_capital else 0.0
    wins = [t for t in closed if t.net_pnl > 0]
    return {
        "total_return_pct": total_return,
        "cagr_pct": _cagr_pct(total_pnl, initial_capital, trading_days),
        "win_rate_pct": (len(wins) / len(closed) * 100) if closed else 0.0,
        "max_drawdown_pct": _realized_mdd_pct(closed, initial_capital),
        "sharpe_ratio": _trade_sharpe(closed),
        "num_trades": len(closed),
    }


def _cagr_pct(total_pnl: float, initial_capital: float, trading_days: int) -> float:
    years = trading_days / 252
    if years <= 0 or initial_capital <= 0:
        return 0.0
    final = initial_capital + total_pnl
    if final <= 0:
        return -100.0
    return ((final / initial_capital) ** (1 / years) - 1) * 100


def _realized_mdd_pct(closed: list[Trade], initial_capital: float) -> float:
    equity = peak = initial_capital
    mdd = 0.0
    for t in closed:
        equity += t.net_pnl
        peak = max(peak, equity)
        if peak > 0:
            mdd = max(mdd, (peak - equity) / peak)
    return mdd * 100


def _trade_sharpe(closed: list[Trade]) -> float:
    r = [t.net_pct for t in closed if t.net_pct is not None]
    if len(r) < 2:
        return 0.0
    mean = sum(r) / len(r)
    std = math.sqrt(sum((x - mean) ** 2 for x in r) / (len(r) - 1))
    if std == 0:
        return 0.0
    return mean / std * math.sqrt(len(r))


# ---------------------------------------------------------------- 진입 기준 집계 (분할 청산 조각 → 진입 한 건)


def entry_level(closed: list[Trade]) -> list[tuple[float, float, "pd.Timestamp", int]]:
    """청산된 거래(조각 포함) → 진입 한 건씩 (순손익, 순수익률(소수), 마지막 청산 시각, 보유 봉) — 청산 시각 순.
    같은 `entry_id` 조각은 합산한다(순수익률 = 합계 순손익 ÷ 매수 금액 합). 조각을 따로 세면 승률이 부풀려진다(분할 익절의 첫 조각은 거의 이익).
    `entry_id < 0`(조각 없음 — 호환·틱 엔진 등)은 각자 한 진입."""
    groups: dict = {}
    for k, t in enumerate(closed):
        key = t.entry_id if t.entry_id >= 0 else ("solo", k)
        g = groups.get(key)
        amt = t.entry_price * t.qty
        if g is None:
            groups[key] = [t.net_pnl, amt, t.exit_ts, t.bars_held]
        else:
            g[0] += t.net_pnl
            g[1] += amt
            if t.exit_ts >= g[2]:
                g[2], g[3] = t.exit_ts, max(g[3], t.bars_held)
    rows = [(g[0], g[0] / g[1], g[2], g[3]) for g in groups.values()]
    rows.sort(key=lambda r: r[2])  # 안정 정렬 — 같은 시각이면 진입 순
    return rows


def collapse_entries(trades: pd.DataFrame) -> pd.DataFrame:
    """거래표(조각 행 포함) → 진입 한 건당 한 행. `entry_id` 칸이 없거나 조각이 없으면 그대로 돌려준다.
    합산: qty·gross_pnl·commission·tax·slippage_cost·net_pnl. net_pct = 합계 순손익 ÷ (진입가×수량 합). exit_ts=마지막 조각, exit_price=수량 가중,
    exit_reason=마지막 조각, bars_held·mfe_pct·mae_pct = 마지막 조각(누적 값이라 마지막이 진입 전체의 값)."""
    if "entry_id" not in trades.columns or "slice" not in trades.columns or trades.empty or not (trades["slice"] > 1).any():
        return trades
    t = trades.copy()
    solo = t["entry_id"] < 0
    t["_key"] = np.where(solo, -1 - np.arange(len(t)), t["entry_id"])  # 조각 없는 행은 각자 한 진입
    t["_amt"] = t["entry_price"] * t["qty"]
    t["_xq"] = t["exit_price"] * t["qty"]
    agg = {c: "sum" for c in ("qty", "gross_pnl", "commission", "tax", "slippage_cost", "net_pnl", "_amt", "_xq") if c in t.columns}
    last_cols = [c for c in t.columns if c not in agg and c not in ("_key",)]
    t = t.sort_values(["_key", "slice"], kind="stable")
    g = t.groupby("_key", sort=False)
    out = g.agg({**agg, **{c: "last" for c in last_cols}})
    out["net_pct"] = out["net_pnl"] / out["_amt"]
    out["exit_price"] = out["_xq"] / out["qty"]
    out["slice"] = 1
    out = out.drop(columns=["_amt", "_xq"]).reset_index(drop=True)
    return out.sort_values("exit_ts", kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------- 표준 지표 (일별 평가)


def standard_metrics(result: BacktestResult, initial_capital: float, periods_per_year: int = 252,
                     benchmark: pd.Series | None = None) -> dict:
    """equity(일별 평가) + trades 로 계산. benchmark = 같은 index 의 지수 종가(선택)."""
    eq = result.equity
    out: dict = {}
    if eq.empty:
        return out
    e = eq["equity"].to_numpy(dtype=float)
    n = len(e)
    ret = np.diff(np.concatenate([[initial_capital], e])) / np.concatenate([[initial_capital], e])[:-1]
    out.update(equity_stats(e, initial_capital, periods_per_year))

    closed = sorted((t for t in result.trades if t.net_pnl is not None), key=lambda t: t.exit_ts)
    if any(t.slice > 1 for t in closed):  # 분할 청산 — 승률·기대값·손익비는 **진입 한 건 기준**(조각 합산)
        ent = entry_level(closed)
        out.update(trade_stats(np.array([r[0] for r in ent]), np.array([r[1] for r in ent])))
        out["num_slices"] = len(closed)
        out["avg_holding_bars"] = float(np.mean([r[3] for r in ent]))
    else:
        out.update(trade_stats(np.array([t.net_pnl for t in closed]), np.array([t.net_pct for t in closed])))
        out["avg_holding_bars"] = float(np.mean([t.bars_held for t in closed])) if closed else 0.0
    out["exposure_pct"] = float((eq["n_positions"] > 0).mean() * 100)

    traded = sum(f.price * f.qty for f in result.fills)
    out["turnover"] = traded / (2 * float(np.mean(e))) if np.mean(e) > 0 else 0.0  # 편도 합 ÷ 2 ÷ 평균 평가금
    out["commission_total"] = sum(f.commission for f in result.fills)
    out["tax_total"] = sum(f.tax for f in result.fills)
    out["slippage_total"] = sum(f.slippage_cost for f in result.fills)
    out["skipped"] = dict(result.skipped)

    if benchmark is not None and len(benchmark) == n:
        b = benchmark.to_numpy(dtype=float)
        bret = np.diff(b) / b[:-1]
        out["benchmark_return_pct"] = (b[-1] / b[0] - 1) * 100
        out["excess_return_pct"] = out["total_return_pct"] - out["benchmark_return_pct"]
        r1 = ret[1:]
        bv = bret.var(ddof=1) if len(bret) > 1 else 0.0  # 관측 2개 이하면 분산 정의 불가 -> 베타 0
        out["beta"] = float(np.cov(r1, bret, ddof=1)[0, 1] / bv) if bv > 0 else 0.0
    return out


def equity_stats(e: np.ndarray, base: float, periods_per_year: int = 252) -> dict:
    """평가금 배열 e(구간 안 봉마다) 와 구간 직전 평가금 base 로 계산하는 지표 — 표준 지표와 검증 구간
    지표(validation.py)가 **같은 정의**를 쓰도록 한 곳에 둔다."""
    n = len(e)
    out: dict = {"total_return_pct": (e[-1] / base - 1) * 100}
    years = n / periods_per_year
    out["cagr_pct"] = ((e[-1] / base) ** (1 / years) - 1) * 100 if years > 0 and e[-1] > 0 else (
        -100.0 if e[-1] <= 0 else 0.0)
    path = np.concatenate([[base], e])
    peak = np.maximum.accumulate(path)
    dd = path / peak - 1
    out["max_drawdown_pct"] = -dd.min() * 100
    out["mdd_duration_bars"] = _longest_underwater(dd)
    ret = np.diff(path) / path[:-1]
    vol = ret.std(ddof=1) if n > 1 else 0.0
    out["volatility_pct"] = vol * math.sqrt(periods_per_year) * 100
    mean = ret.mean()
    out["sharpe"] = mean / vol * math.sqrt(periods_per_year) if vol > 0 else 0.0
    down = ret[ret < 0]
    dvol = math.sqrt((down ** 2).sum() / n) if n else 0.0  # 목표수익 0 기준 하방편차
    out["sortino"] = mean / dvol * math.sqrt(periods_per_year) if dvol > 0 else 0.0
    out["calmar"] = out["cagr_pct"] / out["max_drawdown_pct"] if out["max_drawdown_pct"] > 0 else 0.0
    return out


def trade_stats(net_pnl: np.ndarray, net_pct: np.ndarray) -> dict:
    """청산 순서로 정렬된 거래의 순손익(원)·순수익률(소수) 배열 → 승률·손익비·기대값·최대 연속 손실."""
    n = len(net_pnl)
    win = net_pnl > 0
    gp, gl = float(net_pnl[win].sum()), float(-net_pnl[~win].sum())
    best = cur = 0
    for w in win:
        cur = 0 if w else cur + 1
        best = max(best, cur)
    return {
        "num_trades": n,
        "win_rate_pct": float(win.mean() * 100) if n else 0.0,
        "profit_factor": gp / gl if gl > 0 else (math.inf if gp > 0 else 0.0),
        "avg_win_pct": float(net_pct[win].mean() * 100) if win.any() else 0.0,
        "avg_loss_pct": float(net_pct[~win].mean() * 100) if (~win).any() else 0.0,
        "expectancy_pct": float(net_pct.mean() * 100) if n else 0.0,
        "max_consec_losses": best,
    }


def _longest_underwater(dd: np.ndarray) -> int:
    best = cur = 0
    for x in dd:
        cur = cur + 1 if x < 0 else 0
        best = max(best, cur)
    return best
