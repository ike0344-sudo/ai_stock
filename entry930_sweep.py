"""09:30 진입용으로 3배제 기준값을 다시 맞춘다.

    SCAN_CUTOFF=0930 python entry930_sweep.py

기존 3배제(눌림 5% / 첫5분 0.15 / 레인지 0.7)는 10:00 데이터로 고른 값이다. 09:30엔
30분치만 쌓여서 같은 숫자가 다른 뜻이 된다 - 눌림 5%는 훨씬 드물고, 첫 5분 비중은
분모가 작아 자동으로 커진다. 컷을 안 건 모집단에서 시뮬레이션을 한 번만 돌리고
임계값 조합을 마스크로 훑는다.
"""
import os
import sys
from itertools import product

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pullback_ladder_backtest as L

DDS = [3.0, 4.0, 5.0, 7.0, 99.0]        # 눌림 상한
F5S = [0.15, 0.25, 0.35, 1.0]           # 첫 5분 대금비중 상한
POSS = [0.5, 0.6, 0.7, 0.8]             # 레인지 위치 하한
TRAILS = [4.0, 5.0, 7.0, 10.0]
CACHE = "results/entry930_trades.csv"
MIN_N = 80                               # 이보다 적으면 조합을 신뢰하지 않는다


def trades() -> pd.DataFrame:
    """3배제를 안 건 모집단의 트레일별 수익률."""
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE, parse_dates=["date"], dtype={"code": str})

    b = L.load()
    live = b[(~b["already_20_by_10"]) & (b["open_gap_pct"] < 15)]
    plan = L.PLANS[L.ENTRY_PLAN]
    rows = []
    for code, g in live.groupby("stock_code"):
        path = os.path.join(L.MINUTE_DIR, f"{code}.csv")
        if not os.path.exists(path):
            continue
        minute = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        keep = g.set_index("date")
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in keep.index:
                continue
            r = {"date": date, "code": code}
            for t in TRAILS:
                out = L.simulate(bars, plan, t)
                r[f"t{t:g}"] = np.nan if out is None else out[0]
            row = keep.loc[date]
            for c in ["max_dd_to_10_pct", "first5_value_share", "pos_in_range_10",
                      "ret_at_10_pct"]:
                r[c] = float(row[c])
            rows.append(r)

    t = pd.DataFrame(rows).dropna()
    t.to_csv(CACHE, index=False, encoding="utf-8-sig")
    return t


def main() -> None:
    L.DAY_PEAK = True
    t = trades()
    print("=" * 84)
    print(f"09:30 진입 · 3배제 기준값 스윕  |  모집단 {len(t)}건 (컷 없음)")
    print("=" * 84)
    base = t["t5"].mean()
    print(f"컷 없이 전량 진입(트레일 -5%): 건당 {base:.2f}% · 누적 {t['t5'].sum():.0f}%\n")

    rows = []
    for dd, f5, pos, tr in product(DDS, F5S, POSS, TRAILS):
        g = t[(t["max_dd_to_10_pct"] <= dd) & (t["first5_value_share"] <= f5)
              & (t["pos_in_range_10"] >= pos)]
        if len(g) < MIN_N:
            continue
        r = g[f"t{tr:g}"]
        rows.append({"dd": dd, "f5": f5, "pos": pos, "tr": tr, "n": len(g),
                     "exp": r.mean(), "win": (r > 0).mean() * 100, "sum": r.sum()})
    df = pd.DataFrame(rows)

    for key, label in [("sum", "누적수익 상위"), ("exp", "건당 기대값 상위")]:
        print(f"{label} 10개")
        print(f"{'눌림':>6}{'첫5분':>7}{'레인지':>7}{'트레일':>7}{'건수':>7}{'건당':>8}{'승률':>7}{'누적':>8}")
        for _, r in df.sort_values(key, ascending=False).head(10).iterrows():
            print(f"{r['dd']:>6.0f}{r['f5']:>7.2f}{r['pos']:>7.1f}{r['tr']:>6.0f}%"
                  f"{int(r['n']):>7}{r['exp']:>7.2f}%{r['win']:>6.0f}%{r['sum']:>7.0f}%")
        print()

    print("-" * 84)
    print("기존 10:00용 값을 09:30에 그대로 쓴 경우 (눌림5 / 첫5분0.15 / 레인지0.7)")
    print("-" * 84)
    print(f"{'트레일':>7}{'건수':>7}{'건당':>8}{'승률':>7}{'누적':>8}")
    old = t[(t["max_dd_to_10_pct"] <= 5) & (t["first5_value_share"] <= 0.15)
            & (t["pos_in_range_10"] >= 0.7)]
    for tr in TRAILS:
        r = old[f"t{tr:g}"]
        print(f"{tr:>6.0f}%{len(r):>7}{r.mean():>7.2f}%{(r>0).mean()*100:>6.0f}%{r.sum():>7.0f}%")

    print("\n" + "-" * 84)
    print("축별 단독 효과 (다른 축은 해제, 트레일 -7%)")
    print("-" * 84)
    for col, name, vals, op in [("max_dd_to_10_pct", "눌림 <=", DDS, "le"),
                                ("first5_value_share", "첫5분 <=", F5S, "le"),
                                ("pos_in_range_10", "레인지 >=", POSS, "ge")]:
        print(f"\n{name}")
        for v in vals:
            g = t[t[col] <= v] if op == "le" else t[t[col] >= v]
            if len(g) < MIN_N:
                continue
            r = g["t7"]
            print(f"{v:>10.2f}{len(g):>7}{r.mean():>7.2f}%{(r>0).mean()*100:>6.0f}%{r.sum():>7.0f}%")


def demo() -> None:
    """마스크 방향 - 눌림/첫5분은 이하, 레인지는 이상."""
    t = pd.DataFrame({"max_dd_to_10_pct": [3.0, 9.0], "first5_value_share": [0.1, 0.9],
                      "pos_in_range_10": [0.9, 0.1]})
    m = (t["max_dd_to_10_pct"] <= 5) & (t["first5_value_share"] <= 0.15) & (t["pos_in_range_10"] >= 0.7)
    assert m.tolist() == [True, False], m.tolist()
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
