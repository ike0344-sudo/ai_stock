"""studio-conditions c8 실데이터 실측 — 틱 모드 B + 분봉·일봉 필터(통합 AL). 필터 없음 / 분봉 필터 / 분봉+일봉 정배열 + 사전 필터 의 시간·신호 수.
SC-C8 조합: 체결강도 >= 150 그리고 5분봉 20선 위 그리고 일봉 정배열(전일).  수동 실행: python tests/studio/perf_conditions_c8.py"""
import sys
import time

sys.path.insert(0, ".")
from studio.application.backtest_service import run_backtest
from studio.domain.spec import Spec
from studio.infrastructure.market_data import LocalMarketData

F = lambda n="close", **k: {"kind": "field", "name": n, **k}  # noqa: E731
I = lambda n, p=None, **k: {"kind": "ind", "name": n, "params": p or {}, **k}  # noqa: E731
cond = lambda l, op, r: {"left": l, "op": op, "right": r}  # noqa: E731
ABOVE = cond(F(tf="m5"), "gt", I("sma", {"src": "close", "n": 20}, tf="m5"))
ALIGNED = [cond(I("sma", {"src": "close", "n": 5}, tf="daily_prev"), "gt", I("sma", {"src": "close", "n": 20}, tf="daily_prev")),
           cond(I("sma", {"src": "close", "n": 20}, tf="daily_prev"), "gt", I("sma", {"src": "close", "n": 60}, tf="daily_prev"))]


def spec(start, end, filt=None, pre=None):
    t = {"entry_source": "catalog", "catalog": {"breakout_min": None, "trade_strength": {"w": 60, "min": 150}, "time_from": "09:05", "time_to": "15:00"},
         "cooldown_sec": 300, "exclude_gap_open_pct": 5, "time_stop_sec": 600, "eod_time": "15:19:59"}
    if filt:
        t["filter"] = {"logic": "all", "items": filt}
    if pre:
        t["prefilter"] = {"logic": "all", "items": pre}
    return Spec.model_validate({"version": 1, "name": "c8 실측", "mode": "tick", "period": {"start": start, "end": end}, "universe": {"type": "all"},
                                "tick": t, "portfolio": {"max_positions": 5}, "exits": {"stop_loss_pct": 1.5, "take_profit_pct": 3.0}})


if __name__ == "__main__":
    md = LocalMarketData()
    rng = md.data_ranges()["tick_al"]
    start, end = str(rng[0]), str(rng[1])
    print("틱 범위:", start, "~", end, "| 분봉 출처 al(통합)")
    runs = {"① 틱만(체결강도>=150)": spec(start, end),
            "② + 5분봉 20선 위": spec(start, end, [ABOVE]),
            "③ + 일봉 정배열(전일)": spec(start, end, [ABOVE, *ALIGNED]),
            "④ ③ + 사전 필터(전일 종가>SMA20)": spec(start, end, [ABOVE, *ALIGNED], [cond(F(), "gt", I("sma", {"src": "close", "n": 20}))])}
    for k, sp in runs.items():
        t0 = time.perf_counter()
        rec = run_backtest(sp, md)
        dt_ = time.perf_counter() - t0
        c = rec.summary["tick"]
        m = rec.summary["metrics"]
        print(f"{k}: {dt_:6.1f}s 신호 {c['signals']} 거래 {len(rec.trades)}  (쌍 {c['used_pairs']}/{c['expected_pairs']}, 분봉없음 {c.get('filter_pairs_without_minutes', '-')}, "
              f"사전필터 제외 {c.get('prefilter_pairs_skipped', '-')})  승률 {m['win_rate_pct']:.1f}% 기대값 {m['expectancy_pct']:+.3f}%")
