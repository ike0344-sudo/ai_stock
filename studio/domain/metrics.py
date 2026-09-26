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
