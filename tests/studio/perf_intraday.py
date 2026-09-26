"""분봉·틱 성능·정합 실측(설계서 §8.9: 60거래일 x 상위 30 <= 60초) - 수동 실행: python tests/studio/perf_intraday.py"""
import sys
import time

sys.path.insert(0, ".")
from studio.application.backtest_service import run_backtest
from studio.domain.spec import Spec
from studio.infrastructure.market_data import LocalMarketData

CLOSE = {"kind": "field", "name": "close"}
hi = lambda n: {"kind": "ind", "name": "highest", "params": {"src": "high", "n": n}}  # noqa: E731
lo = lambda n: {"kind": "ind", "name": "lowest", "params": {"src": "low", "n": n}}  # noqa: E731


def spec(mode="intraday", start="2026-06-26", end="2026-09-23", **kw):
    d = {"version": 1, "name": "분봉 실측", "mode": mode, "period": {"start": start, "end": end},
         "universe": {"type": "all"},
         "strategy": {"source": "builder",
                      "entry": {"logic": "all", "items": [
                          {"left": CLOSE, "op": "gt", "right": hi(12)},
                          {"left": {"kind": "ind", "name": "vol_ratio", "params": {"n": 20}}, "op": "gte", "right": {"kind": "const", "value": 3}}]},
                      "exit": {"logic": "any", "items": [{"left": CLOSE, "op": "lt", "right": lo(6)}]}},
         "intraday": {"bar_minutes": 5, "prefilter_top_value": 30, "eod_time": "15:20"},
         "exits": {"stop_loss_pct": 2.0, "take_profit_pct": 4.0}, "portfolio": {"max_positions": 5}}
    d.update(kw)
    return Spec.model_validate(d)


if __name__ == "__main__":
    md = LocalMarketData()
    md.data_ranges()  # 분봉 커버리지 캐시(첫 호출 ~5초) — 측정에서 분리
    t = time.time()
    rec = run_backtest(spec(), md)
    el = time.time() - t
    cov = rec.summary["intraday"]
    print(f"INTRADAY {el:.1f}s trades={len(rec.trades)} pairs {cov['used_pairs']}/{cov['expected_pairs']} days {cov['days_with_bars']}/{cov['days_in_period']} codes {cov['codes_with_minutes']}/{cov['codes_requested']}")
    m = rec.summary["metrics"]
    print({k: round(m[k], 2) for k in ("total_return_pct", "max_drawdown_pct", "win_rate_pct", "profit_factor", "num_trades")}, rec.summary["skipped"])
    print(rec.trades["exit_reason"].value_counts().to_dict())
    for w in rec.warnings:
        print(" -", w)
    # 모드 A: 같은 신호를 틱으로 정밀화(체결 파일이 있는 구간 08-04~)
    t = time.time()
    a = run_backtest(spec("tick", start="2026-08-04", tick={"entry_source": "minute_refine", "catalog": {"breakout_min": 5}}), md)
    print(f"MODE A {time.time() - t:.1f}s trades={len(a.trades)} refine={ {k: v for k, v in a.summary['tick_refine'].items() if k != 'definition'} }")
    # 모드 B
    t = time.time()
    b = run_backtest(spec("tick", start="2026-09-14", strategy=None,
                          tick={"entry_source": "catalog", "catalog": {"breakout_min": 5, "time_from": "09:05", "time_to": "15:00"},
                                "cooldown_sec": 300, "exclude_gap_open_pct": 5, "time_stop_sec": 600, "eod_time": "15:19:59"},
                          universe={"type": "top_value", "n": 30}), md)
    m = b.summary["metrics"]
    print(f"MODE B {time.time() - t:.1f}s trades={len(b.trades)} cov={b.summary['tick']}")
    print({k: round(m[k], 2) for k in ("total_return_pct", "max_drawdown_pct", "win_rate_pct", "profit_factor", "num_trades")}, b.trades["exit_reason"].value_counts().to_dict())
