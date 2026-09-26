"""엔진 중간 곡선 오버헤드 실측(통합 AL) — 곡선 없음 / 콜백만 / 작업 처리기와 같은 progress.json 쓰기. 목표: 오버헤드 ≤ 5%.
수동 실행: python tests/studio/perf_live_curve.py"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, ".")
from jobrunner.store import JobStore
from studio.application import jobs
from studio.application.backtest_service import run_backtest
from studio.domain.spec import Spec
from studio.infrastructure.market_data import LocalMarketData

F = lambda n="close", **k: {"kind": "field", "name": n, **k}  # noqa: E731
I = lambda n, p=None, **k: {"kind": "ind", "name": n, "params": p or {}, **k}  # noqa: E731


def daily():
    return Spec.model_validate({"version": 1, "name": "곡선 일봉", "mode": "daily_portfolio", "period": {"start": "2023-01-02", "end": "2026-09-23"},
        "universe": {"type": "top_value", "n": 100}, "portfolio": {"max_positions": 10}, "exits": {"stop_loss_pct": 7, "take_profit_pct": 15},
        "strategy": {"source": "builder", "entry": {"logic": "all", "items": [{"left": F(), "op": "gt", "right": I("highest", {"src": "high", "n": 20})}]},
                     "exit": {"logic": "any", "items": [{"left": F(), "op": "lt", "right": I("lowest", {"src": "low", "n": 10})}]}}})


def intraday():
    return Spec.model_validate({"version": 1, "name": "곡선 분봉", "mode": "intraday", "period": {"start": "2026-06-26", "end": "2026-09-23"},
        "universe": {"type": "all"}, "intraday": {"bar_minutes": 5, "prefilter_top_value": 30, "eod_time": "15:20"},
        "exits": {"stop_loss_pct": 2, "take_profit_pct": 4}, "portfolio": {"max_positions": 5},
        "strategy": {"source": "builder", "entry": {"logic": "all", "items": [{"left": F(), "op": "gt", "right": I("highest", {"src": "high", "n": 20}, tf="daily_prev")}]},
                     "exit": {"logic": "any", "items": [{"left": F(), "op": "lt", "right": I("vwap")}]}}})


def timed(spec, md, mode, store, job_id):
    t = time.perf_counter()
    if mode == "off":
        rec = run_backtest(spec, md)
    elif mode == "callback":
        pts = []
        rec = run_backtest(spec, md, lambda s, f: None, curve=pts.append)
    else:  # 작업 처리기와 같은 경로: 점마다 progress.json 쓰기(실제 JobStore)
        live = jobs.LiveCurve()
        last = [0.0]

        def progress(stage, frac):  # 작업 처리기(jobs.run_backtest_job)와 같은 쓰기 간격 제한
            now = time.monotonic()
            if stage == "engine" and live.points and now - last[0] < jobs.LIVE_WRITE_INTERVAL:
                return
            last[0] = now
            store.write_progress(job_id, pct=frac * 100, stage=stage, **live.extra())
        rec = run_backtest(spec, md, progress, curve=live.add)
    return time.perf_counter() - t, rec


if __name__ == "__main__":
    md = LocalMarketData()
    md.data_ranges()
    root = Path(tempfile.mkdtemp())
    store = JobStore(root)
    job = store.create("x", "local", "studio.application.jobs:run_backtest_job", {})
    for name, sp in (("일봉 포트폴리오 3.7년 top100", daily()), ("분봉 62일×30", intraday())):
        timed(sp, md, "off", store, job["job_id"])  # 캐시 예열
        res = {m: [] for m in ("off", "callback", "job")}
        base = None
        for _ in range(5):
            for m in res:
                dt_, rec = timed(sp, md, m, store, job["job_id"])
                res[m].append(dt_)
                sig = (len(rec.trades), round(float(rec.equity["equity"].iloc[-1]), 4))
                base = base or sig
                assert sig == base, (m, sig, base)  # 결과 불변
        best = {m: sorted(v)[len(v) // 2] for m, v in res.items()}  # 중앙값(측정 잡음이 큰 PC)
        print(f"{name}: 거래 {base[0]} | " + " · ".join(f"{m} {best[m]:.2f}s" for m in best) +
              f" | 오버헤드 콜백 {100*(best['callback']/best['off']-1):+.1f}% · 작업(파일쓰기) {100*(best['job']/best['off']-1):+.1f}%")
    print("progress.json 크기:", len((root / "jobs" / job["job_id"] / "progress.json").read_bytes()) if (root / "jobs" / job["job_id"] / "progress.json").exists() else "?", "bytes")
