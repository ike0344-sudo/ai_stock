"""'승률 60%'가 되는 조합이 있는지: 돌파 진입은 그대로 두고 청산만 익절 +g% / 손절 -s% 고정으로 바꿔 본다 (사용자 2026-10-11).

    python research/dolpago_target_backtest.py     # → results/dolpago/target_grid.csv + 요약

익절은 지정가(목표가에 체결됐다고 봄 — 낙관적), 손절은 그 체결가에서 slip호가 불리하게. 승률은 세후 기준.
"""
from __future__ import annotations

import itertools
import os

import numba
import numpy as np
import pandas as pd

from dolpago_backtest import COST, GAP_MIN, OUT, TV_MIN, load_daily, summarize, tick
from dolpago_flow_backtest import buy_cum
from dolpago_tick_backtest import load_days


@numba.njit(cache=True)
def sim(px, cumtv, cumbuy, sec, pc, k, g, s, gap_min, tv_min, slip, W, T, R, end):
    n = len(px)
    res = np.empty((n // 2 + 1, 3))
    m = 0
    ref = -1.0; j = 0; a = 0
    pos = False
    entry = 0.0; ei = 0; cool = -1
    for i in range(1, n):
        while j < i and sec[j] <= sec[i] - W:
            ref = max(ref, px[j]); j += 1
        while a < i and sec[a] < sec[i] - T:
            a += 1
        p = px[i]
        if not pos:
            if (ref > 0 and p >= ref + k * tick(ref) and sec[i] < end and sec[i] >= cool
                    and p >= pc * (1 + gap_min) and cumtv[i - 1] >= tv_min):
                tot = cumtv[i] - cumtv[a]
                if R <= 0 or (tot > 0 and (cumbuy[i] - cumbuy[a]) / tot >= R):
                    entry = p + slip * tick(p); ei = i; pos = True
        else:
            ex = -1.0
            if p >= entry * (1 + g): ex = entry * (1 + g)
            elif p <= entry * (1 - s) or i == n - 1: ex = p - slip * tick(p)
            if ex > 0:
                res[m, 0] = ei; res[m, 1] = entry; res[m, 2] = ex
                m += 1; pos = False; cool = sec[i] + 60
    return res[:m]


def run(days, k, g, s, use_filt, slip, R, end) -> pd.DataFrame:
    recs = []
    for code, day, pc, filt, px, tv, cb, sec in days:
        if use_filt and not filt:
            continue
        for ei, en, ex in sim(px, tv, cb, sec, pc, k, g, s, GAP_MIN, TV_MIN, slip, 30, 30, R, end):
            recs.append((code, day, en, ex))
    t = pd.DataFrame(recs, columns=["code", "date", "entry", "exit"])
    t["gross"] = t.exit / t.entry - 1
    t["net"] = t.gross - COST
    return t


def main():
    os.makedirs(OUT, exist_ok=True)
    days = [(c, d, pc, f, px, tv, buy_cum(px, tv), sec) for c, d, pc, f, px, tv, sec in load_days(load_daily())]
    half = sorted({d[1] for d in days})[len({d[1] for d in days}) // 2]
    ENDS = {"09:30": 9 * 3600 + 1800, "15:00": 15 * 3600}
    rows = []
    for k, g, s, f, slip, R, (en, end) in itertools.product(
            (1, 2), (.005, .01, .015, .02, .03), (.01, .02, .03, .05), (False, True), (0, 1), (0, .9), ENDS.items()):
        t = run(days, k, g, s, f, slip, R, end)
        rows.append(dict(k=k, 익절=g * 100, 손절=s * 100, filt=f, slip=slip, R=R, end=en, **summarize(t),
                         net_front=summarize(t[t.date < half]).get("net"), net_back=summarize(t[t.date >= half]).get("net")))
    r = pd.DataFrame(rows)
    r.to_csv(f"{OUT}/target_grid.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    cols = ["k", "익절", "손절", "filt", "slip", "R", "end", "n", "win", "gross", "net", "avg_w", "avg_l", "pf", "net_front", "net_back"]
    big = r[r.n >= 100]
    print("[승률 상위 10]"); print(big.sort_values("win", ascending=False)[cols].head(10).round(3).to_string(index=False))
    print("\n[세후 평균 상위 10]"); print(big.sort_values("net", ascending=False)[cols].head(10).round(3).to_string(index=False))
    print("\n승률 60%+", (big.win >= .6).sum(), "/", len(big), "· 그중 세후 플러스", ((big.win >= .6) & (big.net > 0)).sum(),
          "· 세후 플러스 전체", (big.net > 0).sum(), "· 앞뒤 모두 플러스", ((big.net_front > 0) & (big.net_back > 0)).sum())


if __name__ == "__main__":
    main()
