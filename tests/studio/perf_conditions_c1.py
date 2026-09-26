"""studio-conditions c1 실데이터 실측 - SC-C1(손계산 대조)·SC-C2(돈다)·성능(분봉 62일 x 상위30, 조건 5개 · 일봉 피연산자 포함 <= 60초).
수동 실행: python tests/studio/perf_conditions_c1.py"""
import datetime as dt
import sys
import time

sys.path.insert(0, ".")
import numpy as np
import pandas as pd

from studio.application.backtest_service import run_backtest
from studio.domain.conditions.ast import Group
from studio.domain.conditions.evaluator import evaluate_group
from studio.domain.spec import Spec
from studio.infrastructure.market_data import LocalMarketData

F = lambda n="close", **k: {"kind": "field", "name": n, **k}  # noqa: E731
I = lambda n, p=None, **k: {"kind": "ind", "name": n, "params": p or {}, **k}  # noqa: E731
C = lambda v: {"kind": "const", "value": v}  # noqa: E731


def cond(l, op, r=None, **k):
    d = {"left": l, "op": op, **k}
    if r is not None:
        d["right"] = r
    return d


def spec(entry, start="2026-06-26", end="2026-09-23", exit_=None):
    return Spec.model_validate({
        "version": 1, "name": "c1 실측", "mode": "intraday", "period": {"start": start, "end": end}, "universe": {"type": "all"},
        "strategy": {"source": "builder", "entry": entry, "exit": exit_ or {"logic": "any", "items": [cond(F(), "lt", I("vwap"))]}},
        "intraday": {"bar_minutes": 5, "prefilter_top_value": 30, "eod_time": "15:20"}, "exits": {"stop_loss_pct": 2.0, "take_profit_pct": 4.0},
        "portfolio": {"max_positions": 5}})


if __name__ == "__main__":
    md = LocalMarketData()
    md.data_ranges()
    # ---- SC-C1: 분봉에서 "현재가 > 전일까지 20일 최고가"(daily_prev + include_current) 신호 = 원시 일봉으로 손계산
    start, end = dt.date(2026, 9, 14), dt.date(2026, 9, 23)
    codes = md.stock_info().index[:0].tolist() or ["000660", "042700", "028260", "036540", "072950", "204320", "022100"]
    daily = md.load_panel(start, end, 600, None)
    have = [c for c in codes if c in daily.close.columns]
    mp = md.minute_panel(have, start, end, 5, "al")
    g = Group.model_validate({"logic": "all", "items": [cond(F(), "gt", I("highest", {"src": "high", "n": 20, "include_current": True}, tf="daily_prev"))]})
    t = time.time()
    got = evaluate_group(g, mp, daily=daily, bar_minutes=5)
    print("SC-C1 evaluate %.2fs" % (time.time() - t), "codes", list(mp.close.columns), "bars", len(mp.close))
    raw = pd.read_parquet("data/cache/daily_all.parquet")
    raw["date"] = pd.to_datetime(raw["date"])
    mism = 0
    n_true = 0
    for code in mp.close.columns:
        h = raw[raw.code == code].set_index("date").sort_index()["high"]
        for ts in mp.close.index[:: 3]:
            d = ts.normalize()
            prior = h[h.index < d].iloc[-20:]  # D−20..D−1
            exp = bool(mp.close.loc[ts, code] > prior.max()) if len(prior) == 20 and not np.isnan(mp.close.loc[ts, code]) else False
            mism += exp != bool(got.loc[ts, code])
            n_true += exp
    print("SC-C1 hand-calc mismatches:", mism, "(signal bars in sample:", n_true, ")")
    # ---- SC-C2 + 성능: 조건 5개(분봉 20선·일봉 20선 장중·일봉 전일 RSI·5분→15분 이평·거래대금 순위) 전 기간 실행
    entry = {"logic": "all", "items": [
        cond(F(), "gt", I("sma", {"src": "close", "n": 20})),
        cond(F(), "gt", I("sma", {"src": "close", "n": 20}, tf="daily_live")),
        cond(I("rsi", {"n": 14}, tf="daily_prev"), "gte", C(50)),
        cond(I("sma", {"src": "close", "n": 3}, tf="m15"), "gt", I("sma", {"src": "close", "n": 8}, tf="m15")),
        cond(I("vol_ratio", {"n": 20}, tf="daily_prev"), "gte", C(1)),
    ]}
    t = time.time()
    rec = run_backtest(spec(entry), md)
    el = time.time() - t
    cov = rec.summary["intraday"]
    print(f"SC-C2/성능 분봉 5조건 {el:.1f}s (목표 60s) trades={len(rec.trades)} pairs {cov['used_pairs']}/{cov['expected_pairs']} days {cov['days_with_bars']}")
    rec2 = run_backtest(spec({"logic": "all", "items": [cond(F(), "gt", I("highest", {"src": "high", "n": 20, "include_current": True}, tf="daily_prev"))]}), md)
    print("SC-C1 recipe backtest trades", len(rec2.trades), rec2.summary["metrics"]["num_trades"])
