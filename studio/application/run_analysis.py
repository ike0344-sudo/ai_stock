"""실행 결과(거래 표·평가금 곡선)에서 화면용 분해를 계산한다 — 결과 화면 §5.4 ResultPage.

저장하지 않고 **읽을 때 계산**한다(원본은 trades·equity parquet 하나). 순수 pandas/numpy.
- monthly/yearly: 평가금 곡선의 월말·연말 수익률(첫 구간은 초기자금 기준)
- exit_reasons: 청산 사유별 건수·비율·평균 수익률
- by_sector / by_theme_group: 청산된 거래 기준 (거래 수·승률·순손익 합·평균 순수익률)
- histogram: 거래 순수익률(%) 분포
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

HIST_BINS = 20


def _period_returns(equity: pd.DataFrame, initial_capital: float, freq: str) -> list[dict[str, Any]]:
    if equity.empty:
        return []
    s = pd.Series(equity["equity"].to_numpy(dtype=float), index=pd.to_datetime(equity["ts"]))
    last = s.groupby(s.index.to_period(freq)).last()
    prev = last.shift(1).fillna(initial_capital)
    ret = (last / prev - 1) * 100
    return [{"period": str(p), "return_pct": float(r)} for p, r in ret.items()]


def _group_perf(closed: pd.DataFrame, key: pd.Series) -> list[dict[str, Any]]:
    rows = []
    for k, g in closed.groupby(key.fillna("(미분류)")):
        pnl = g["net_pnl"].astype(float)
        rows.append({
            "key": str(k), "n": int(len(g)), "win_rate_pct": float((pnl > 0).mean() * 100),
            "net_pnl": float(pnl.sum()), "avg_net_pct": float(g["net_pct"].astype(float).mean() * 100),
        })
    return sorted(rows, key=lambda r: -r["net_pnl"])


def histogram(values_pct: np.ndarray, bins: int = HIST_BINS) -> dict[str, Any]:
    v = values_pct[np.isfinite(values_pct)]
    if len(v) == 0:
        return {"edges": [], "counts": []}
    lo, hi = float(v.min()), float(v.max())
    if lo == hi:
        lo, hi = lo - 0.5, hi + 0.5
    counts, edges = np.histogram(v, bins=bins, range=(lo, hi))
    return {"edges": [float(e) for e in edges], "counts": [int(c) for c in counts]}


def analyze(trades: pd.DataFrame, equity: pd.DataFrame, initial_capital: float,
            theme_groups: Mapping[str, str] | None = None) -> dict[str, Any]:
    closed = trades[trades["net_pnl"].notna()] if len(trades) else trades
    out: dict[str, Any] = {
        "monthly": _period_returns(equity, initial_capital, "M"),
        "yearly": _period_returns(equity, initial_capital, "Y"),
        "exit_reasons": [], "by_sector": [], "by_theme_group": None,
        "histogram": histogram(closed["net_pct"].to_numpy(dtype=float) * 100) if len(closed) else histogram(np.array([])),
    }
    if not len(closed):
        return out
    reasons = closed.groupby(closed["exit_reason"].fillna("(없음)"))
    out["exit_reasons"] = sorted(
        ({"reason": str(r), "n": int(len(g)), "share_pct": float(len(g) / len(closed) * 100),
          "avg_net_pct": float(g["net_pct"].astype(float).mean() * 100)} for r, g in reasons),
        key=lambda x: -x["n"])
    if "sector" in closed.columns:
        out["by_sector"] = _group_perf(closed, closed["sector"])
    if theme_groups:  # 매핑 자료가 없으면 None — 화면이 "없음"으로 보여준다(값을 지어내지 않는다)
        out["by_theme_group"] = _group_perf(closed, closed["code"].map(theme_groups))
    return out


def downsample(df: pd.DataFrame, max_points: int = 800) -> pd.DataFrame:
    """곡선 점 수를 줄인다(마지막 점은 항상 유지) — 비교 화면 응답 크기용."""
    if len(df) <= max_points:
        return df
    idx = np.unique(np.linspace(0, len(df) - 1, max_points).round().astype(int))
    return df.iloc[idx]
