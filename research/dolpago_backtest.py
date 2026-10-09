"""돌파고(2021 실매매) 역추적 규칙을 통합(AL) 1분봉으로 백테스트 (사용자 2026-10-08).

    python research/dolpago_backtest.py           # 격자 전체 → results/dolpago/grid.csv + 요약 출력

역추적 규칙(memory dolpago-reverse-engineering):
  진입 = 그날(09:00~) 고가를 k호가 넘는 순간 매수, 조건: 전일종가 +2% 이상 · 09시부터 누적 대금 30억 이상
  청산 = 진입가 -S호가 손절 / 보유 중 최고가 -X호가 트레일 / (선택) +B호가 찍으면 본전 손절 / 15:19 강제
  일봉 필터(선택) = 60일 수익>0 · 전일종가 20일선 +5% 이상 · 전일 대금 ≥ 20일 평균 0.5배

1분봉 한계 — 봉 안의 순서를 모르므로 보수적으로 친다:
  진입봉은 종가로만 손절·트레일 판정, 이후 봉은 시가가 손절선 아래면 시가, 저가가 닿으면 손절선에서 체결.
  진입·손절 체결은 1호가 불리하게(슬리피지), 비용 = 수수료 0.015%×2 + 거래세 0.20%(2026).
기간은 거래대금 상위 100 의 90% 이상이 보관소에 있는 날만 쓴다(2026-08-26~).
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

OUT = "results/dolpago"
START = "2026-08-26"
COST = 0.00015 * 2 + 0.002
GAP_MIN, TV_MIN = 0.02, 30e8
NONE = 10**6  # B(본전) 안 씀


def load_daily() -> pd.DataFrame:
    rows = []
    for p in glob.glob("data/stocks/daily_al/*.csv"):
        x = pd.read_csv(p, dtype={"date": str})
        x = x[x.date >= "20260301"]
        if len(x) < 70:
            continue
        x["code"] = os.path.basename(p)[:6]
        c = x.close
        x["pc"] = c.shift()
        x["r60"] = c.shift() / c.shift(61) - 1
        x["dma20"] = c.shift() / c.shift().rolling(20).mean() - 1
        x["pvr"] = x.value_mw.shift() / x.value_mw.shift(2).rolling(20).mean()
        rows.append(x)
    d = pd.concat(rows)
    d["date"] = pd.to_datetime(d.date).dt.strftime("%Y-%m-%d")
    d["filt"] = (d.r60 > 0) & (d.dma20 > 0.05) & (d.pvr >= 0.5)
    return d.set_index(["code", "date"])


def load_days(daily: pd.DataFrame) -> list[tuple]:
    """(code, date, pc, filt, o,h,l,c, cumtv, minute) — 09:00~15:19 정규장 봉만."""
    out = []
    for p in glob.glob("data/stocks/minute_al_archive/*.parquet"):
        code = os.path.basename(p)[:6]
        m = pd.read_parquet(p)
        m = m[m.index >= START]
        mins = m.index.hour * 60 + m.index.minute
        m = m[(mins >= 540) & (mins <= 919)]
        for day, g in m.groupby(m.index.strftime("%Y-%m-%d")):
            key = (code, day)
            if key not in daily.index or len(g) < 30:
                continue
            r = daily.loc[key]
            if not (r.pc > 0) or g.high.max() < r.pc * (1 + GAP_MIN):
                continue  # 하루 종일 +2% 를 못 넘은 종목은 진입 자체가 없다
            f = lambda s: s.to_numpy(np.float64)
            out.append((code, day, float(r.pc), bool(r.filt), f(g.open), f(g.high), f(g.low), f(g.close),
                        np.cumsum(f(g.close) * f(g.volume)),
                        (g.index.hour * 60 + g.index.minute).to_numpy(np.int64)))
    return out


@numba.njit(cache=True)
def tick(p):
    if p < 2000: return 1.0
    if p < 5000: return 5.0
    if p < 20000: return 10.0
    if p < 50000: return 50.0
    if p < 200000: return 100.0
    if p < 500000: return 500.0
    return 1000.0


@numba.njit(cache=True)
def sim(o, h, l, c, cumtv, mins, pc, k, S, X, B, gap_min, tv_min, slip=1.0):
    """한 종목·하루. 반환 (진입봉, 청산봉, 진입가, 청산가, 진입봉 최고가) 배열."""
    n = len(o)
    res = np.empty((n, 5))
    m = 0
    run_high = h[0]
    pos = False
    entry = 0.0; peak = 0.0; ei = 0
    for i in range(1, n):
        if not pos:
            trig = run_high + k * tick(run_high)
            if (h[i] >= trig and mins[i] < 900 and c[i - 1] >= pc * (1 + gap_min) and cumtv[i - 1] >= tv_min):
                px = max(o[i], trig)
                entry = px + slip * tick(px)  # slip 호가 불리하게
                peak = h[i]; ei = i; pos = True
                t = tick(entry)
                stop = max(entry - S * t, peak - X * t)
                if peak >= entry + B * t:
                    stop = max(stop, entry)
                if c[i] <= stop or i == n - 1:  # 진입봉은 종가로만 판정
                    res[m, 0] = ei; res[m, 1] = i; res[m, 2] = entry; res[m, 3] = c[i]; res[m, 4] = h[i]
                    m += 1; pos = False
        else:
            t = tick(entry)
            stop = max(entry - S * t, peak - X * t)
            if peak >= entry + B * t:
                stop = max(stop, entry)
            ex = -1.0
            if o[i] <= stop:
                ex = o[i] - slip * tick(o[i])
            elif l[i] <= stop:
                ex = stop - slip * tick(stop)
            else:
                peak = max(peak, h[i])
                stop2 = max(entry - S * t, peak - X * t)
                if peak >= entry + B * t:
                    stop2 = max(stop2, entry)
                if c[i] <= stop2:
                    ex = c[i]
                elif i == n - 1:
                    ex = c[i]
            if ex > 0:
                res[m, 0] = ei; res[m, 1] = i; res[m, 2] = entry; res[m, 3] = ex; res[m, 4] = peak
                m += 1; pos = False
        run_high = max(run_high, h[i])
    return res[:m]


def run(days, k, S, X, B, use_filt) -> pd.DataFrame:
    recs = []
    for code, day, pc, filt, o, h, l, c, tv, mins in days:
        if use_filt and not filt:
            continue
        r = sim(o, h, l, c, tv, mins, pc, k, S, X, B, GAP_MIN, TV_MIN)
        for ei, xi, en, ex, pk in r:
            ei, xi = int(ei), int(xi)
            recs.append((code, day, mins[ei], xi - ei, en, ex, en / pc - 1, en / o[0] - 1))
    t = pd.DataFrame(recs, columns=["code", "date", "min", "hold", "entry", "exit", "vs_pc", "vs_open"])
    t["gross"] = t.exit / t.entry - 1
    t["net"] = t.gross - COST
    return t


def summarize(t: pd.DataFrame) -> dict:
    if t.empty:
        return dict(n=0)
    w, lo = t[t.net > 0], t[t.net <= 0]
    daily = t.groupby("date").net.sum()
    return dict(n=len(t), per_day=len(t) / t.date.nunique(), win=(t.net > 0).mean(),
                gross=t.gross.mean() * 100, net=t.net.mean() * 100,
                avg_w=w.net.mean() * 100, avg_l=lo.net.mean() * 100,
                pf=w.net.sum() / -lo.net.sum() if len(lo) else np.inf,
                pos_days=(daily > 0).mean(), sum_net_1000=t.net.sum() * 1000)  # 1,000만 원씩 넣었을 때 손익(만원)


def main():
    os.makedirs(OUT, exist_ok=True)
    daily = load_daily()
    days = load_days(daily)
    dates = sorted({d[1] for d in days})
    half = dates[len(dates) // 2]
    print(f"종목일 {len(days)} · 거래일 {len(dates)} ({dates[0]}~{dates[-1]}) · 앞/뒤 나눔 {half}")
    rows = []
    for k, S, X, B, f in itertools.product((1, 2, 3), (3, 4, 6), (2, 3, 4, 6, 10), (NONE, 2), (False, True)):
        t = run(days, k, S, X, B, f)
        a, b = t[t.date < half], t[t.date >= half]
        rows.append(dict(k=k, S=S, X=X, B="-" if B == NONE else B, filt=f,
                         **summarize(t), net_front=summarize(a).get("net"), net_back=summarize(b).get("net")))
    g = pd.DataFrame(rows)
    g.to_csv(f"{OUT}/grid.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    cols = ["k", "S", "X", "B", "filt", "n", "per_day", "win", "gross", "net", "avg_w", "avg_l", "pf", "pos_days", "sum_net_1000", "net_front", "net_back"]
    print("\n[세후 평균 상위 15]"); print(g.sort_values("net", ascending=False)[cols].head(15).round(3).to_string(index=False))
    print("\n[앞 절반 1등 → 뒤 절반 성적]")
    best = g.sort_values("net_front", ascending=False).iloc[0]; print(best[cols].to_string())
    print("\n[돌파고 원형 k=2 S=4 X=4 B=2 필터 없음/있음]")
    print(g[(g.k == 2) & (g.S == 4) & (g.X == 4) & (g.B == 2)][cols].round(3).to_string(index=False))
    t = run(days, 2, 4, 4, 2, False)
    t.to_csv(f"{OUT}/trades_k2S4X4B2.csv", index=False, encoding="utf-8-sig")
    print("\n[원형 지문] 보유(분) 분위", t.hold.quantile([.25, .5, .75, .9]).to_dict(),
          "· 진입가/전일종가 중앙 %.1f%% · 진입가/시가 중앙 %.1f%%" % (t.vs_pc.median() * 100, t.vs_open.median() * 100))
    t["seg"] = pd.cut(t["min"], [539, 544, 569, 599, 659, 900], labels=["09:00-04", "09:05-29", "09:30-59", "10시", "11시~"])
    print(t.groupby("seg", observed=True).agg(n=("net", "size"), win=("net", lambda x: (x > 0).mean()),
                                               gross=("gross", lambda x: x.mean() * 100), net=("net", lambda x: x.mean() * 100)).round(3).to_string())


if __name__ == "__main__":
    main()
