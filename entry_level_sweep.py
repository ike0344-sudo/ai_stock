"""진입 수준(전일比 +6~12%)별 손절 발생률 비교. 손절은 진입가 대비 -3% 고정.

질문: 어느 구간에서 사면 가장 안 털리나.
같은 봉에서 손절가와 목표가가 모두 닿으면 손절로 본다(보수적).

주의: 모집단이 "10:00 대금순위 top10"이라 09시대 진입은 미래 정보가 섞인다.
그래서 전체와 "10:00 이후 진입"을 나눠 낸다. 구간 간 비교는 같은 편향을 공유하므로
상대 순위는 유효하다.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import load

CAPITAL = 60_000_000
COST_PCT = 0.25
LEVELS = [6.0, 7.0, 8.0, 9.0, 10.0, 12.0]
STOPS = [3.0]
TARGET_LV = 20.0
EXIT_MIN = 920


def run(bars: pd.DataFrame, pc: float, lv: float, stop_pct: float) -> dict | None:
    mins = bars.index.hour * 60 + bars.index.minute
    seg = bars[mins <= EXIT_MIN]
    if len(seg) < 5:
        return None
    h = seg["high"].to_numpy(); lo = seg["low"].to_numpy()
    o = seg["open"].to_numpy(); c = seg["close"].to_numpy()

    trig = pc * (1 + lv / 100)
    hit = np.flatnonzero(h >= trig)
    if hit.size == 0:
        return None
    i0 = int(hit[0])
    entry = max(trig, o[i0])
    stop = entry * (1 - stop_pct / 100)
    target = pc * (1 + TARGET_LV / 100)

    for i in range(i0, len(seg)):
        if lo[i] <= stop:
            px = min(stop, o[i]) if i > i0 else stop
            return {"how": "손절", "ret": (px / entry - 1) * 100 - COST_PCT,
                    "t": seg.index[i0].strftime("%H:%M"), "min": i - i0}
        if h[i] >= target:
            px = max(target, o[i]) if i > i0 else target
            return {"how": "익절", "ret": (px / entry - 1) * 100 - COST_PCT,
                    "t": seg.index[i0].strftime("%H:%M"), "min": i - i0}
    return {"how": "종가", "ret": (c[-1] / entry - 1) * 100 - COST_PCT,
            "t": seg.index[i0].strftime("%H:%M"), "min": len(seg) - 1 - i0}


def build() -> pd.DataFrame:
    pop = load()
    pop = pop[pop["open_gap_pct"] < 15]
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
            for lv in LEVELS:
                for sp in STOPS:
                    r = run(bars, float(pc), lv, sp)
                    if r:
                        rows.append({"date": date, "code": code, "lv": lv, "stop": sp, **r})
    print(file=sys.stderr)
    return pd.DataFrame(rows)


def table(df: pd.DataFrame, n_pop: int, label: str) -> None:
    print("\n" + "=" * 96)
    print(f"[{label}]")
    print("=" * 96)
    print(f"{'진입':>6}{'진입건수':>9}{'터치율':>8}{'손절률':>9}{'익절률':>9}{'종가률':>9}"
          f"{'평균익':>8}{'평균손':>8}{'손익비':>8}{'기대값':>8}")
    for lv, g in df.groupby("lv"):
        a = g["ret"].to_numpy(); w, l = a[a > 0], a[a <= 0]
        sl = (g["how"] == "손절").mean() * 100
        tp = (g["how"] == "익절").mean() * 100
        cl = (g["how"] == "종가").mean() * 100
        pr = abs(w.mean() / l.mean()) if len(w) and len(l) else float("nan")
        print(f"{lv:>5.0f}%{len(g):>9}{len(g)/n_pop*100:>7.0f}%{sl:>8.1f}%{tp:>8.1f}%{cl:>8.1f}%"
              f"{w.mean():>7.2f}%{l.mean():>7.2f}%{pr:>8.2f}{a.mean():>7.2f}%")


def main() -> None:
    df = build()
    pop = load()
    n_pop = len(pop[pop["open_gap_pct"] < 15])
    df["after10"] = df["t"] >= "10:00"

    table(df, n_pop, "전체 — 09시대 진입 포함 (10시 순위를 미리 안다는 가정, 실전 불가)")
    sub = df[df["after10"]]
    table(sub, n_pop, "10:00 이후 진입만 — 룩어헤드 없음")

    print("\n" + "-" * 96)
    print("손절까지 걸린 시간 / 진입 후 최대 상승 여력")
    print("-" * 96)
    print(f"{'진입':>6}{'손절중앙(분)':>13}{'익절중앙(분)':>13}{'09시대 진입비율':>16}")
    for lv, g in df.groupby("lv"):
        s = g[g["how"] == "손절"]["min"]; t = g[g["how"] == "익절"]["min"]
        print(f"{lv:>5.0f}%{s.median():>13.0f}{t.median():>13.0f}"
              f"{(~g['after10']).mean()*100:>15.0f}%")

    df.to_csv("results/entry_level_sweep.csv", index=False, encoding="utf-8-sig")
    print("\n원본: results/entry_level_sweep.csv")


def demo() -> None:
    idx = pd.date_range("2026-01-02 09:00", periods=5, freq="1min")
    up = pd.DataFrame({"open": [104, 109, 112, 116, 119], "high": [105, 111, 115, 118, 121],
                       "low": [103, 108, 111, 115, 118], "close": [104, 110, 114, 117, 120]}, idx)
    assert run(up, 100.0, 10.0, 3.0)["how"] == "익절"
    dn = pd.DataFrame({"open": [104, 109, 108, 106, 105], "high": [105, 111, 109, 107, 106],
                       "low": [103, 108, 106, 105.5, 104], "close": [104, 110, 107, 106, 105]}, idx)
    r = run(dn, 100.0, 10.0, 3.0)
    assert r["how"] == "손절" and abs(r["ret"] + 3.25) < 1e-9, r
    assert run(up, 1000.0, 10.0, 3.0) is None
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    main()
