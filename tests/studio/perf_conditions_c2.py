"""studio-conditions c2 실데이터 실측 — 분봉 62일 x 상위30 에서 청산 확장의 비용(측정 -> 비교). 통합(AL) 분봉 기준.
같은 진입으로 ① 기본 청산 ② 분할 익절+본전+트레일링 발동+분 단위 보유 ③ pos 조건 청산 을 돌려 시간·거래 수를 잰다.
수동 실행: python tests/studio/perf_conditions_c2.py"""
import sys
import time

sys.path.insert(0, ".")
from studio.application.backtest_service import run_backtest
from studio.domain.spec import Spec
from studio.infrastructure.market_data import LocalMarketData

F = lambda n="close", **k: {"kind": "field", "name": n, **k}  # noqa: E731
I = lambda n, p=None, **k: {"kind": "ind", "name": n, "params": p or {}, **k}  # noqa: E731
C = lambda v: {"kind": "const", "value": v}  # noqa: E731
POS = lambda n: {"kind": "pos", "name": n}  # noqa: E731


def spec(exit_, exits, start="2026-06-26", end="2026-09-23"):
    entry = {"logic": "all", "items": [{"left": F(), "op": "gt", "right": I("highest", {"src": "high", "n": 20}, tf="daily_prev")}]}
    return Spec.model_validate({
        "version": 1, "name": "c2 실측", "mode": "intraday", "period": {"start": start, "end": end}, "universe": {"type": "all"},
        "strategy": {"source": "builder", "entry": entry, "exit": exit_},
        "intraday": {"bar_minutes": 5, "prefilter_top_value": 30, "eod_time": "15:20"}, "exits": exits, "portfolio": {"max_positions": 5}})


if __name__ == "__main__":
    md = LocalMarketData()
    md.data_ranges()
    base_exit = {"logic": "any", "items": [{"left": F(), "op": "lt", "right": I("vwap")}]}
    pos_exit = {"logic": "any", "items": [{"left": POS("return_pct"), "op": "gte", "right": C(3)},
                                          {"left": POS("drawdown_pct"), "op": "gte", "right": C(1.5)},
                                          {"left": POS("minutes_held"), "op": "gte", "right": C(60)},
                                          {"logic": "all", "items": [{"left": POS("return_pct"), "op": "lt", "right": C(0)},
                                                                     {"left": F(), "op": "lt", "right": I("vwap")}]}]}
    runs = {
        "① 기본 청산(손절2·익절4)": spec(base_exit, {"stop_loss_pct": 2.0, "take_profit_pct": 4.0}),
        "② 분할익절+본전+발동+분보유": spec(base_exit, {"stop_loss_pct": 2.0, "take_profit_levels": [{"pct": 2, "fraction": 0.5}, {"pct": 4, "fraction": 1}],
                                                 "breakeven_after_pct": 1.0, "trailing_stop_pct": 1.5, "trail_activate_pct": 2.0,
                                                 "max_holding_minutes": 90}),
        "③ pos 조건 청산": spec(pos_exit, {"stop_loss_pct": 2.0}),
    }
    for k, sp in runs.items():
        t0 = time.perf_counter()
        rec = run_backtest(sp, md)
        dt_ = time.perf_counter() - t0
        m = rec.summary["metrics"]
        print(f"{k}: {dt_:5.1f}s  진입 {rec.summary['n_entries']}건 / 조각 {rec.summary['n_trades']}행  승률 {m['win_rate_pct']:.1f}%  "
              f"기대값 {m['expectancy_pct']:+.3f}%  MDD {m['max_drawdown_pct']:.1f}%  총수익 {m['total_return_pct']:+.2f}%")
        print("   기간:", rec.summary.get("intraday", {}).get("period_used") or rec.meta.get("period_used"),
              "| 종목", rec.summary.get("n_codes"), "| 분봉 출처", rec.meta.get("minute_source", "al"))
