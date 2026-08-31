"""+8% 진입 후 분할 매도 검증. 목표 밴드와 손절폭을 바꿔가며 비교.

진입: 전일比 +8% 최초 터치(갭으로 넘겼으면 시가).
매도: 지정한 두 목표(전일比)에서 절반씩. 남은 물량은 15:20 종가 청산.
손절: 진입가 대비 -stop%. 같은 봉에서 손절가와 목표가가 같이 닿으면 손절 우선.

비교군으로 +20% 일괄 익절과 고점 대비 트레일링도 같이 돌린다.
"""
import os
import sys
from itertools import product

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import load

CAPITAL = 60_000_000
COST_PCT = 0.25
ENTRY_LV = 8.0
EXIT_MIN = 920
STOPS = [3.0, 4.0, 5.0]
BANDS = [(12.0, 13.0), (13.0, 14.0), (14.0, 15.0), (13.0, 16.0), (20.0, 20.0)]
TRAIL = 5.0                       # 비교용: 당일 고점 대비 트레일링


def run(bars, pc, stop_pct, band=None, trail=None):
    mins = bars.index.hour * 60 + bars.index.minute
    seg = bars[mins <= EXIT_MIN]
    if len(seg) < 5:
        return None
    h = seg["high"].to_numpy(); lo = seg["low"].to_numpy()
    o = seg["open"].to_numpy(); c = seg["close"].to_numpy()

    trig = pc * (1 + ENTRY_LV / 100)
    hit = np.flatnonzero(h >= trig)
    if hit.size == 0:
        return None
    i0 = int(hit[0])
    entry = max(trig, o[i0])
    stop = entry * (1 - stop_pct / 100)
    t1 = pc * (1 + band[0] / 100) if band else None
    t2 = pc * (1 + band[1] / 100) if band else None

    qty = 1.0; realized = 0.0
    peak = h[i0]
    sold1 = False
    for i in range(i0, len(seg)):
        peak = max(peak, h[i])
        if lo[i] <= stop:                                   # 손절 우선
            px = min(stop, o[i]) if i > i0 else stop
            return {"ret": realized + qty * ((px / entry - 1) * 100 - COST_PCT),
                    "how": "손절", "t": seg.index[i0].strftime("%H:%M"), "min": i - i0}
        if band:
            if not sold1 and h[i] >= t1:                    # 1차 목표 절반
                px = max(t1, o[i]) if i > i0 else t1
                realized += 0.5 * ((px / entry - 1) * 100 - COST_PCT)
                qty -= 0.5; sold1 = True
            if sold1 and qty > 0 and h[i] >= t2:            # 2차 목표 나머지
                px = max(t2, o[i]) if i > i0 else t2
                realized += qty * ((px / entry - 1) * 100 - COST_PCT)
                return {"ret": realized, "how": "익절완료",
                        "t": seg.index[i0].strftime("%H:%M"), "min": i - i0}
        if trail is not None and lo[i] <= peak * (1 - trail / 100) and i > i0:
            px = min(peak * (1 - trail / 100), o[i])
            return {"ret": realized + qty * ((px / entry - 1) * 100 - COST_PCT),
                    "how": "트레일", "t": seg.index[i0].strftime("%H:%M"), "min": i - i0}
    how = "1차만" if (band and sold1) else "종가"
    return {"ret": realized + qty * ((c[-1] / entry - 1) * 100 - COST_PCT),
            "how": how, "t": seg.index[i0].strftime("%H:%M"), "min": len(seg) - 1 - i0}


def build() -> pd.DataFrame:
    pop = load()
    pop = pop[pop["open_gap_pct"] < 15]
    combos = [(f"{b[0]:g}/{b[1]:g} 분할" if b[0] != b[1] else f"+{b[0]:g} 일괄", b, None)
              for b in BANDS] + [("트레일 -5%", None, TRAIL)]
    rows = []
    for i, (code, g) in enumerate(pop.groupby("stock_code"), 1):
        print(f"\r[{i}/{pop['stock_code'].nunique()}] {code}", end="", file=sys.stderr)
        mp, dp = f"data/stocks/minute/{code}.csv", f"data/stocks/daily/{code}.csv"
        if not (os.path.exists(mp) and os.path.exists(dp)):
            continue
        pcs = pd.read_csv(dp, index_col=0, parse_dates=True).sort_index()["close"].shift(1)
        minute = pd.read_csv(mp, index_col=0, parse_dates=True).sort_index()
        want = set(g["date"])
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in want:
                continue
            pc = pcs.get(date, np.nan)
            if pd.isna(pc) or pc <= 0:
                continue
            for lab, band, tr in combos:
                for sp in STOPS:
                    r = run(bars, float(pc), sp, band, tr)
                    if r:
                        rows.append({"date": date, "code": code, "안": lab, "손절": sp, **r})
    print(file=sys.stderr)
    return pd.DataFrame(rows)


def table(df: pd.DataFrame, label: str) -> None:
    print("\n" + "=" * 100)
    print(f"[{label}]")
    print("=" * 100)
    print(f"{'매도안':>14}{'손절':>6}{'n':>6}{'승률':>8}{'평균익':>8}{'평균손':>8}"
          f"{'손익비':>8}{'기대값':>8}{'월평균':>10}{'MDD':>10}")
    n_month = df["date"].dt.to_period("M").nunique()
    for (lab, sp), g in df.groupby(["안", "손절"], sort=False):
        a = g["ret"].to_numpy(); w, l = a[a > 0], a[a <= 0]
        per_day = g.groupby("date")["ret"].mean()
        eq = np.cumsum(per_day.to_numpy())
        mdd = (np.maximum.accumulate(eq) - eq).max()
        m = per_day.groupby(per_day.index.to_period("M")).sum()
        pr = abs(w.mean() / l.mean()) if len(w) and len(l) else float("nan")
        print(f"{lab:>14}{sp:>5.0f}%{len(a):>6}{len(w)/len(a)*100:>7.1f}%"
              f"{w.mean():>7.2f}%{l.mean():>7.2f}%{pr:>8.2f}{a.mean():>7.2f}%"
              f"{m.mean()*CAPITAL/100/1e4:>8,.0f}만{mdd*CAPITAL/100/1e4:>8,.0f}만")


def main() -> None:
    df = build()
    df["after10"] = df["t"] >= "10:00"
    table(df, "전체 — 09시대 진입 포함 (10시 순위를 미리 안다는 가정)")
    table(df[df["after10"]], "10:00 이후 진입만 — 룩어헤드 없음")

    print("\n" + "-" * 100)
    print("13/14 분할의 청산 사유 분해 (손절 -4%, 전체 기준)")
    print("-" * 100)
    sub = df[(df["안"] == "13/14 분할") & (df["손절"] == 4.0)]
    for how, g in sub.groupby("how"):
        print(f"{how:>10}{len(g):>7}건 ({len(g)/len(sub)*100:>4.1f}%)  평균 {g['ret'].mean():>6.2f}%")
    df.to_csv("results/split_exit.csv", index=False, encoding="utf-8-sig")
    print("\n원본: results/split_exit.csv")


def demo() -> None:
    idx = pd.date_range("2026-01-02 09:00", periods=6, freq="1min")
    # 전일종가 100 → 108 진입 → 113, 114 순차 도달
    up = pd.DataFrame({"open": [104, 107, 110, 112, 113, 114], "high": [105, 109, 111, 113, 114, 115],
                       "low": [103, 106, 109, 111, 112, 113], "close": [104, 108, 110, 112, 113, 114]}, idx)
    r = run(up, 100.0, 4.0, (13.0, 14.0))
    assert r["how"] == "익절완료", r
    exp = 0.5 * ((113 / 108 - 1) * 100 - 0.25) + 0.5 * ((114 / 108 - 1) * 100 - 0.25)
    assert abs(r["ret"] - exp) < 1e-9, (r["ret"], exp)
    dn = pd.DataFrame({"open": [104, 107, 106, 104, 103, 102], "high": [105, 109, 107, 105, 104, 103],
                       "low": [103, 106, 103, 102, 101, 100], "close": [104, 108, 104, 103, 102, 101]}, idx)
    assert run(dn, 100.0, 4.0, (13.0, 14.0))["how"] == "손절"
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    main()
