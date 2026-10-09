"""돌파고 규칙을 통합(AL) 체결 틱으로 다시 백테스트 — 1분봉판(dolpago_backtest.py)의 봉 내부 순서 한계를 없앤다.

    python research/dolpago_tick_backtest.py     # → results/dolpago/tick_grid.csv + 요약

체결 하나하나를 시간순으로 본다: W초 전까지의 그날(09:00~) 최고 체결가 + k호가 이상 체결이 나오면 그 체결가(+slip호가)에 매수,
보유 중 체결가가 손절선(진입-S호가 / 최고가-X호가 / +B호가 찍은 뒤 본전) 이하로 나오면 그 체결가(-slip호가)에 매도.
진입 조건·일봉 필터·비용은 1분봉판과 같다. 대상은 tick_al 보관소에 있는 종목(하루 110~174개)뿐이다.
"""
from __future__ import annotations

import glob
import itertools
import os
import sys

import numba
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))
from dolpago_backtest import COST, GAP_MIN, NONE, OUT, TV_MIN, load_daily, summarize, tick


def load_days(daily: pd.DataFrame) -> list[tuple]:
    out = []
    for p in glob.glob("data/stocks/tick_al/*/*.parquet"):
        code, day = os.path.basename(os.path.dirname(p)), os.path.basename(p)[:10]
        if (code, day) not in daily.index:
            continue
        r = daily.loc[(code, day)]
        x = pd.read_parquet(p, columns=["time", "cur_prc", "trde_qty"]).iloc[::-1]  # 파일은 최신순
        sec = x.time.str[:2].astype(int) * 3600 + x.time.str[2:4].astype(int) * 60 + x.time.str[4:6].astype(int)
        keep = (sec >= 9 * 3600) & (sec <= 15 * 3600 + 20 * 60)
        px = x.cur_prc.abs().to_numpy(np.float64)[keep.to_numpy()]
        if len(px) < 100 or not (r.pc > 0) or px.max() < r.pc * (1 + GAP_MIN):
            continue
        qty = x.trde_qty.abs().to_numpy(np.float64)[keep.to_numpy()]
        out.append((code, day, float(r.pc), bool(r.filt), px, np.cumsum(px * qty), sec.to_numpy(np.int64)[keep.to_numpy()]))
    return out


@numba.njit(cache=True)
def sim(px, cumtv, sec, pc, k, S, X, B, gap_min, tv_min, slip, W):
    """기준 고가 = W초 전까지의 그날 최고 체결가(체결은 한 호가씩 오르므로 직전 체결까지 넣으면 k>=2 돌파가 안 생긴다).
    청산 뒤 60초는 재진입 안 함. 반환 (진입 idx, 청산 idx, 진입가, 청산가, 보유 중 최고가)."""
    n = len(px)
    res = np.empty((n // 2 + 1, 5))
    m = 0
    ref = -1.0; j = 0
    pos = False
    entry = 0.0; peak = 0.0; ei = 0; cool = -1
    last_ok = 15 * 3600
    for i in range(1, n):
        while j < i and sec[j] <= sec[i] - W:
            ref = max(ref, px[j]); j += 1
        p = px[i]
        if not pos:
            if (ref > 0 and p >= ref + k * tick(ref) and sec[i] < last_ok and sec[i] >= cool
                    and p >= pc * (1 + gap_min) and cumtv[i - 1] >= tv_min):
                entry = p + slip * tick(p); peak = p; ei = i; pos = True
        else:
            peak = max(peak, p)
            t = tick(entry)
            stop = max(entry - S * t, peak - X * t)
            if peak >= entry + B * t:
                stop = max(stop, entry)
            if p <= stop or i == n - 1:
                res[m, 0] = ei; res[m, 1] = i; res[m, 2] = entry; res[m, 3] = p - slip * tick(p); res[m, 4] = peak
                m += 1; pos = False; cool = sec[i] + 60
    return res[:m]


def run(days, k, S, X, B, use_filt, slip, W) -> pd.DataFrame:
    recs = []
    for code, day, pc, filt, px, tv, sec in days:
        if use_filt and not filt:
            continue
        for ei, xi, en, ex, pk in sim(px, tv, sec, pc, k, S, X, B, GAP_MIN, TV_MIN, slip, W):
            ei, xi = int(ei), int(xi)
            recs.append((code, day, sec[ei], sec[xi] - sec[ei], en, ex, pk / en - 1, en / pc - 1))
    t = pd.DataFrame(recs, columns=["code", "date", "sec", "hold_s", "entry", "exit", "mfe", "vs_pc"])
    t["gross"] = t.exit / t.entry - 1
    t["net"] = t.gross - COST
    return t


def main():
    os.makedirs(OUT, exist_ok=True)
    days = load_days(load_daily())
    dates = sorted({d[1] for d in days})
    half = dates[len(dates) // 2]
    print(f"종목일 {len(days)} · 종목 {len({d[0] for d in days})} · 거래일 {len(dates)} ({dates[0]}~{dates[-1]}) · 앞/뒤 {half}")
    rows = []
    for k, S, X, B, f, slip, W in itertools.product((1, 2, 3), (4, 6), (3, 4, 6, 10), (NONE, 2), (False, True), (0, 1), (30, 120)):
        t = run(days, k, S, X, B, f, slip, W)
        rows.append(dict(k=k, S=S, X=X, B="-" if B == NONE else B, filt=f, slip=slip, W=W, **summarize(t),
                         net_front=summarize(t[t.date < half]).get("net"), net_back=summarize(t[t.date >= half]).get("net")))
    g = pd.DataFrame(rows)
    g.to_csv(f"{OUT}/tick_grid.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    cols = ["k", "S", "X", "B", "filt", "slip", "W", "n", "per_day", "win", "gross", "net", "avg_w", "avg_l", "pf", "pos_days", "sum_net_1000", "net_front", "net_back"]
    for slip in (0, 1):
        print(f"\n[slip={slip} 세후 상위 10]")
        print(g[g.slip == slip].sort_values("net", ascending=False)[cols].head(10).round(3).to_string(index=False))
    print("\n[세전 플러스 조합 수]", (g.gross > 0).sum(), "/", len(g), " [세후 플러스]", (g.net > 0).sum())
    t = run(days, 2, 4, 4, 2, False, 0, 60)
    t.to_csv(f"{OUT}/tick_trades_k2S4X4B2.csv", index=False, encoding="utf-8-sig")
    print("\n[원형 k2 S4 X4 B2 slip0 지문] 보유(초) 분위", t.hold_s.quantile([.25, .5, .75, .9]).to_dict(),
          "· 승률(세전) %.2f · 세전 %.3f%% · 진입가/전일종가 중앙 %.1f%%" % ((t.gross > 0).mean(), t.gross.mean() * 100, t.vs_pc.median() * 100))
    t["seg"] = pd.cut(t.sec, [32399, 32699, 34199, 35999, 39599, 54000], labels=["09:00-04", "09:05-29", "09:30-59", "10시", "11시~"])
    print(t.groupby("seg", observed=True).agg(n=("net", "size"), win=("gross", lambda x: (x > 0).mean()),
                                               gross=("gross", lambda x: x.mean() * 100), net=("net", lambda x: x.mean() * 100)).round(3).to_string())


if __name__ == "__main__":
    main()
