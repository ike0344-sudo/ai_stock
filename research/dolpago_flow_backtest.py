"""돌파고 틱 백테스트에 '매수 체결 쏠림'·'개장 직후만' 조건을 얹어 승률이 오르는지 본다 (사용자 2026-10-11).

    python research/dolpago_flow_backtest.py     # → results/dolpago/flow_grid.csv + 요약

틱 파일엔 매수/매도 구분이 없다(trde_qty 전부 양수, pred_pre_sig 는 전일대비 기호). 그래서 틱 규칙으로 추정한다:
직전 체결보다 비싸면 매수 체결, 싸면 매도 체결, 같으면 직전 방향 그대로. 추정이라 호가 기반보다 부정확하다.
진입 = dolpago_tick_backtest 의 돌파 조건 + 직전 T초 대금 중 매수 추정 비중 >= R + 진입 시각 < END.
"""
from __future__ import annotations

import itertools
import os

import numba
import numpy as np
import pandas as pd

from dolpago_backtest import COST, GAP_MIN, OUT, load_daily, summarize, tick
from dolpago_tick_backtest import load_days


@numba.njit(cache=True)
def buy_cum(px, cumtv):
    """틱 규칙으로 추정한 매수 체결 대금의 누적."""
    n = len(px)
    out = np.empty(n)
    side = 1.0; acc = 0.0
    for i in range(n):
        if i > 0:
            if px[i] > px[i - 1]: side = 1.0
            elif px[i] < px[i - 1]: side = 0.0
        acc += side * (cumtv[i] - (cumtv[i - 1] if i > 0 else 0.0))
        out[i] = acc
    return out


@numba.njit(cache=True)
def sim(px, cumtv, cumbuy, sec, pc, k, S, X, gap_min, tv_min, slip, W, T, R, end):
    n = len(px)
    res = np.empty((n // 2 + 1, 5))
    m = 0
    ref = -1.0; j = 0; a = 0
    pos = False
    entry = 0.0; peak = 0.0; ei = 0; cool = -1
    for i in range(1, n):
        while j < i and sec[j] <= sec[i] - W:
            ref = max(ref, px[j]); j += 1
        while a < i and sec[a] < sec[i] - T:
            a += 1
        p = px[i]
        if not pos:
            if (ref > 0 and p >= ref + k * tick(ref) and sec[i] < end and sec[i] >= cool
                    and p >= pc * (1 + gap_min) and cumtv[i - 1] >= tv_min):
                tot = cumtv[i] - cumtv[a]  # 직전 T초 대금(이번 체결 포함)
                if R <= 0 or (tot > 0 and (cumbuy[i] - cumbuy[a]) / tot >= R):
                    entry = p + slip * tick(p); peak = p; ei = i; pos = True
        else:
            peak = max(peak, p)
            t = tick(entry)
            stop = max(entry - S * t, peak - X * t)
            if p <= stop or i == n - 1:
                res[m, 0] = ei; res[m, 1] = i; res[m, 2] = entry; res[m, 3] = p - slip * tick(p); res[m, 4] = peak
                m += 1; pos = False; cool = sec[i] + 60
    return res[:m]


def run(days, k, X, use_filt, slip, W, T, R, end, tv_min, S=4) -> pd.DataFrame:
    recs = []
    for code, day, pc, filt, px, tv, cb, sec in days:
        if use_filt and not filt:
            continue
        for ei, xi, en, ex, pk in sim(px, tv, cb, sec, pc, k, S, X, GAP_MIN, tv_min, slip, W, T, R, end):
            recs.append((code, day, sec[int(ei)], en, ex))
    t = pd.DataFrame(recs, columns=["code", "date", "sec", "entry", "exit"])
    t["gross"] = t.exit / t.entry - 1
    t["net"] = t.gross - COST
    return t


def demo() -> None:
    px = np.array([100.0, 101, 101, 100, 100, 102]); cum = np.cumsum(px * 10)
    assert list(np.diff(buy_cum(px, cum), prepend=0) > 0) == [True, True, True, False, False, True]


def main():
    demo()
    os.makedirs(OUT, exist_ok=True)
    days = [(c, d, pc, f, px, tv, buy_cum(px, tv), sec) for c, d, pc, f, px, tv, sec in load_days(load_daily())]
    dates = sorted({d[1] for d in days})
    half = dates[len(dates) // 2]
    print(f"종목일 {len(days)} · 거래일 {len(dates)} ({dates[0]}~{dates[-1]}) · 앞/뒤 {half}")
    ENDS = {"09:05": 9 * 3600 + 300, "09:30": 9 * 3600 + 1800, "15:00": 15 * 3600}
    rows = []
    for k, X, f, slip, W, T, R, (en, end), tvm in itertools.product(
            (1, 2), (4, 10), (False, True), (0, 1), (10, 30), (10, 30), (0, .6, .75, .9), ENDS.items(), (30e8, 5e8)):
        if R == 0 and T != 10:
            continue  # R=0 이면 T 는 의미 없다
        t = run(days, k, X, f, slip, W, T, R, end, tvm)
        rows.append(dict(k=k, X=X, filt=f, slip=slip, W=W, T=T, R=R, end=en, tv억=int(tvm / 1e8), **summarize(t),
                         net_front=summarize(t[t.date < half]).get("net"), net_back=summarize(t[t.date >= half]).get("net")))
    g = pd.DataFrame(rows)
    g.to_csv(f"{OUT}/flow_grid.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    cols = ["k", "X", "filt", "slip", "W", "T", "R", "end", "tv억", "n", "per_day", "win", "gross", "net", "pf", "pos_days", "net_front", "net_back"]
    big = g[g.n >= 100]
    for slip in (0, 1):
        print(f"\n[slip={slip} · 100건 이상 · 세후 상위 10]")
        print(big[big.slip == slip].sort_values("net", ascending=False)[cols].head(10).round(3).to_string(index=False))
    print("\n[세후 플러스] 전체", (g.net > 0).sum(), "/", len(g), "· 100건 이상", (big.net > 0).sum(), "/", len(big),
          "· 그중 앞·뒤 절반 모두 플러스", ((big.net_front > 0) & (big.net_back > 0)).sum())
    b = g[(g.slip == 0) & (g.k == 2) & (g.X == 4) & (g.filt == False) & (g.W == 30) & (g.T == 10) & (g.tv억 == 30)]
    print("\n[조건별 승률 변화 · k2 X4 필터없음 slip0 W30 T10 대금30억]")
    print(b.pivot_table(index="R", columns="end", values="win").round(3).to_string())
    print(b.pivot_table(index="R", columns="end", values="gross").round(3).to_string())
    print(b.pivot_table(index="R", columns="end", values="n").to_string())


if __name__ == "__main__":
    main()
