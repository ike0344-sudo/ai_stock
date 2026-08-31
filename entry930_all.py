"""09:30 기준 전수 탐색 - 진입 방식 / 필터 / 모집단을 한 판에 훑는다.

    SCAN_CUTOFF=0930 python entry930_all.py

앞선 스윕에서 3배제 재조정(눌림<=5 / 첫5분<=0.35 / 레인지>=0.7)이 최선으로 나왔다.
그 위에서 네 갈래를 본다.
  [A] 진입 방식 - 전량 09:30 / 전량 10:00 / 반반 분할 / 눌림 2분할 / 돌파
  [B] 추가 필터 한 개씩 - 무엇이 더 얹을 값어치가 있나
  [C] 모집단 - 09:30 대금 top10 vs top20
  [D] 10:00 확인 - 09:30에 사고 10:00 기준까지 통과한 것만 남기면
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pullback_ladder_backtest as L

BASE = {"dd": 5.0, "f5": 0.35, "pos": 0.7}     # 재조정 3배제
TRAILS = [4.0, 5.0, 7.0]
CACHE = "results/entry930_all.csv"
FEAT_1000 = "results/reach20_features.csv"     # 10:00 확인용

PLANS = {
    "전량 09:30": {"market": 1.0, "dips": [], "breakout": 0.0},
    "반반 09:30+10:00": {"market": 0.5, "dips": [], "breakout": 0.0, "market2": (0.5, 600)},
    "전량 10:00": {"market": 0.0, "dips": [], "breakout": 0.0, "market2": (1.0, 600)},
    "눌림 2분할 -2/돌파": {"market": 0.0, "dips": [(0.5, 2.0)], "breakout": 0.5},
    "눌림 3분할 -2/-4/돌파": {"market": 0.0, "dips": [(1/3, 2.0), (1/3, 4.0)], "breakout": 1/3},
    "돌파 1회만": {"market": 0.0, "dips": [], "breakout": 1.0},
}
KEEP = ["max_dd_to_10_pct", "first5_value_share", "pos_in_range_10", "ret_at_10_pct",
        "value_vs_20d_avg", "high_vs_20d_high_pct", "open_gap_pct", "cum_value_eok", "rank_10am"]


def build(top_n: int = 10) -> pd.DataFrame:
    """09:30 모집단의 (진입방식 x 트레일) 수익률 + 09:30 피처 + 10:00 피처."""
    cache = CACHE if top_n == 10 else CACHE.replace(".csv", f"_top{top_n}.csv")
    if os.path.exists(cache):
        return pd.read_csv(cache, parse_dates=["date"], dtype={"code": str})

    b = L.load() if top_n == 10 else _load_topn(top_n)
    live = b[(~b["already_20_by_10"]) & (b["open_gap_pct"] < 15)]
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
            for name, plan in PLANS.items():
                for t in TRAILS:
                    out = L.simulate(bars, plan, t)
                    r[f"{name}|{t:g}"] = np.nan if out is None else out[0]
            row = keep.loc[date]
            for c in KEEP:
                r[c] = float(row[c])
            rows.append(r)

    t = pd.DataFrame(rows).dropna(subset=[f"전량 09:30|5"])
    f10 = pd.read_csv(FEAT_1000, parse_dates=["date"], dtype={"stock_code": str})
    f10 = f10[f10["rank_10am"] <= 10][["date", "stock_code", "ret_at_10_pct",
                                       "pos_in_range_10", "max_dd_to_10_pct"]]
    f10.columns = ["date", "code", "ret10", "pos10", "dd10"]
    t = t.merge(f10, on=["date", "code"], how="left")
    t.to_csv(cache, index=False, encoding="utf-8-sig")
    return t


def _load_topn(top_n: int) -> pd.DataFrame:
    """clean20_conditions.load()의 top10 고정을 우회해 top20 모집단을 쓴다."""
    import clean20_conditions as C
    old, C.TOP_N = C.TOP_N, top_n
    try:
        return C.load()
    finally:
        C.TOP_N = old


def base_mask(t: pd.DataFrame) -> pd.Series:
    return ((t["max_dd_to_10_pct"] <= BASE["dd"]) & (t["first5_value_share"] <= BASE["f5"])
            & (t["pos_in_range_10"] >= BASE["pos"]))


def line(label: str, r: pd.Series) -> None:
    if len(r) == 0:
        print(f"{label:>24}{0:>7}")
        return
    print(f"{label:>24}{len(r):>7}{r.mean():>8.2f}%{(r > 0).mean()*100:>7.0f}%{r.sum():>8.0f}%")


def main() -> None:
    L.DAY_PEAK = True
    t = build()
    g = t[base_mask(t)]
    day_max = L.load().groupby("date")["ret_at_10_pct"].max()
    g = g.assign(max_ret=g["date"].map(day_max))

    print("=" * 72)
    print(f"09:30 전수 탐색  |  모집단 {len(t)}건 · 재조정 3배제 통과 {len(g)}건")
    print("=" * 72)

    print("\n[A] 진입 방식 (재조정 3배제만)")
    print(f"{'':>24}{'건수':>7}{'건당':>9}{'승률':>8}{'누적':>9}")
    best = None
    for name in PLANS:
        for tr in TRAILS:
            col = f"{name}|{tr:g}"
            line(f"{name} -{tr:g}%", g[col])
            s = g[col].sum()
            if best is None or s > best[0]:
                best = (s, col)
        print()
    print(f"최고: {best[1]}  누적 {best[0]:.0f}%")

    col = best[1]
    print(f"\n[B] 추가 필터 한 개씩 ({col})")
    print(f"{'':>24}{'건수':>7}{'건당':>9}{'승률':>8}{'누적':>9}")
    line("없음", g[col])
    filters = {
        "일컷 >=15%": g["max_ret"] >= 15,
        "일컷 >=20%": g["max_ret"] >= 20,
        "09:30 등락 >=5%": g["ret_at_10_pct"] >= 5,
        "09:30 등락 >=7%": g["ret_at_10_pct"] >= 7,
        "레인지 >=0.8": g["pos_in_range_10"] >= 0.8,
        "대금 >=20일평균 1.5배": g["value_vs_20d_avg"] >= 1.5,
        "대금 1.3~3배": g["value_vs_20d_avg"].between(1.3, 3.0),
        "20일 신고가": g["high_vs_20d_high_pct"] >= 0,
        "시가갭 <5%": g["open_gap_pct"] < 5,
        "시가갭 >=0%": g["open_gap_pct"] >= 0,
        "대금순위 <=5": g["rank_10am"] <= 5,
    }
    for label, m in filters.items():
        line(label, g.loc[m, col])

    print(f"\n[D] 10:00 확인 - 09:30에 사되 10:00 기준도 통과한 것만")
    print(f"{'':>24}{'건수':>7}{'건당':>9}{'승률':>8}{'누적':>9}")
    line("확인 없음", g[col])
    ok = g["ret10"].notna()
    line("10:00 top10 유지", g.loc[ok, col])
    line("+ 10시 레인지 >=0.7", g.loc[ok & (g["pos10"] >= 0.7), col])
    line("+ 10시 눌림 <=5%", g.loc[ok & (g["dd10"] <= 5), col])
    line("+ 10시 등락 >=7%", g.loc[ok & (g["ret10"] >= 7), col])
    line("셋 다", g.loc[ok & (g["pos10"] >= 0.7) & (g["dd10"] <= 5) & (g["ret10"] >= 7), col])


def demo() -> None:
    """market2 레그가 지정 시각에 들어가는지 - 안 들어가면 분할이 전량과 같아진다."""
    idx = pd.date_range("2026-01-02 09:30", periods=40, freq="1min")
    bars = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0,
                         "volume": 1.0}, index=idx)
    half = {"market": 0.5, "dips": [], "breakout": 0.0, "market2": (0.5, 600)}
    L.ENTRY_MIN = 570
    r, legs = L.simulate(bars, half, 20.0)
    assert legs == 2, legs                      # 09:30 + 10:00 두 번
    assert abs(r - (-L.COST_PCT)) < 1e-9, r     # 가격 불변이면 비용만 남는다
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
