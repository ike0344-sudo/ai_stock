""""오늘은 공치는 날"을 10:00에 미리 알 수 있나.

케이스가 하루도 안 나오는 날(=대금 top10 중 클린20이 0건)을 10:00 시점 정보만으로
걸러낼 수 있는지 본다. 지수(코스피/코스닥)와 그날 top10의 브레드스를 후보로 놓고
조건별 적중일 비율을 뽑는다.

    python clean20_day_filter.py

지수 15분봉 60선은 10:00 이전에 닫힌 봉(09:45봉)까지만 써서 룩어헤드를 막는다.
"""
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_concentration import residents
from clean20_conditions import load, wilson

MAX_GAP = 15.0
INDEX = {"코스피": "data/index/minute/001.csv", "코스닥": "data/index/minute/101.csv"}
import os
_CUT = os.environ.get("SCAN_CUTOFF", "1000")
TEN = pd.Timestamp(f"{_CUT[:2]}:{_CUT[2:]}").time()   # 판단 시각 - SCAN_CUTOFF와 맞춘다


def index_day(path: str) -> pd.DataFrame:
    """지수 1분봉 -> 일별 (10시 등락률, 10시 직전 15분봉의 60선 위 여부, 전일 등락률)."""
    close = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()["close"]
    k15 = close.resample("15min").last().dropna()
    ma = k15.rolling(60).mean()
    above = (k15 > ma).where(ma.notna())
    # 10:00 라벨 봉은 10:00~10:15을 담아서 못 쓴다 - 09:45봉(09:59에 확정)이 마지막
    above = above[above.index.time < TEN]

    day = pd.DataFrame({"close": close.groupby(close.index.normalize()).last()})
    day["prev_close"] = day["close"].shift(1)
    at10 = close[close.index.time <= TEN].groupby(close[close.index.time <= TEN].index.normalize()).last()
    day["ret10"] = (at10 / day["prev_close"] - 1) * 100
    day["above60"] = above.groupby(above.index.normalize()).last()
    day["prev_ret"] = ((day["close"] / day["prev_close"] - 1) * 100).shift(1)
    return day


def day_table() -> pd.DataFrame:
    """하루 한 줄: 그날 클린20이 나왔는지 + 10:00에 보이는 것들."""
    df = load()
    df["case"] = df["clean"] & (df["open_gap_pct"] < MAX_GAP)
    d = df.groupby("date").agg(
        hit=("case", "any"),
        n_case=("case", "sum"),
        max_ret10=("ret_at_10_pct", "max"),
        n_ret7=("ret_at_10_pct", lambda s: (s >= 7).sum()),
        n_high20=("high_vs_20d_high_pct", lambda s: (s >= 0).sum()),
        max_val=("value_vs_20d_avg", "max"),
    )
    d["n_rule4"] = df.assign(r=(df["ret_at_10_pct"] >= 7) & (df["pos_in_range_10"] >= 0.8)
                             & (df["value_vs_20d_avg"] >= 1.5) & (df["high_vs_20d_high_pct"] >= 0)
                             ).groupby("date")["r"].sum()
    # 상주 대형주가 그날 top10 대금에서 먹은 비중 - 높을수록 나머지가 마른다
    res = df["stock_code"].isin(residents(df))
    d["res_share"] = (df[res].groupby("date")["cum_value_eok"].sum()
                      / df.groupby("date")["cum_value_eok"].sum()).reindex(d.index).fillna(0)
    for label, path in INDEX.items():
        idx = index_day(path)
        d[f"{label}_ret10"] = d.index.map(idx["ret10"])
        d[f"{label}_60"] = d.index.map(idx["above60"])
        d[f"{label}_전일"] = d.index.map(idx["prev_ret"])
    return d


def rate(d: pd.DataFrame, mask: pd.Series, label: str, base: float) -> None:
    n = int(mask.sum())
    if n == 0:
        print(f"{label:>28}{0:>7}")
        return
    k = int(d.loc[mask, "hit"].sum())
    lo, hi = wilson(k, n)
    print(f"{label:>28}{n:>7}{k:>7}{k / n * 100:>7.0f}%{k / n / base:>7.2f}x{f'[{lo:.0f}-{hi:.0f}]':>13}")


def report() -> None:
    d = day_table()
    base = d["hit"].mean()
    print("=" * 78)
    print(f"공치는 날 예측  |  {d.index.min().date()} ~ {d.index.max().date()}  {len(d)}거래일")
    print("=" * 78)
    print(f"케이스 나온 날 {int(d['hit'].sum())}일 ({base*100:.0f}%) · 공친 날 {int((~d['hit']).sum())}일"
          f" · 케이스 총 {int(d['n_case'].sum())}건")
    print(f"\n{'조건(10:00 시점)':>28}{'일수':>7}{'적중':>7}{'비율':>8}{'배수':>8}{'95% CI':>13}")

    for name in ("코스피", "코스닥"):
        for lo, hi in [(-99, -1), (-1, 0), (0, 1), (1, 99)]:
            m = (d[f"{name}_ret10"] >= lo) & (d[f"{name}_ret10"] < hi)
            rate(d, m, f"{name} 10시 {lo:g}~{hi:g}%", base)
        rate(d, d[f"{name}_60"] == True, f"{name} 15분 60선 위", base)
        rate(d, d[f"{name}_60"] == False, f"{name} 15분 60선 아래", base)
        print()

    for col, name, cuts in [("max_ret10", "top10 최고 등락률", [0, 5, 7, 10, 15]),
                            ("n_ret7", "10시 +7% 종목 수", [0, 1, 2, 3]),
                            ("n_high20", "20일신고가 종목 수", [0, 1, 3, 5]),
                            ("n_rule4", "4조건 통과 종목 수", [0, 1, 2, 3])]:
        for i, lo in enumerate(cuts):
            hi = cuts[i + 1] if i + 1 < len(cuts) else 999
            m = (d[col] >= lo) & (d[col] < hi)
            rate(d, m, f"{name} {lo:g}{'+' if hi == 999 else f'~{hi:g}'}", base)
        print()

    print("-" * 78)
    print("공친 날을 가장 많이 걸러내는 단일 컷 (재현율/오탈락 확인)")
    print("-" * 78)
    print(f"{'컷':>28}{'통과일':>8}{'적중':>7}{'비율':>8}{'놓친 케이스':>12}")
    total = d["n_case"].sum()
    for label, m in {
        "top10 최고등락 >= 7%": d["max_ret10"] >= 7,
        "top10 최고등락 >= 10%": d["max_ret10"] >= 10,
        "top10 최고등락 >= 15%": d["max_ret10"] >= 15,
        "+7% 종목 >= 2": d["n_ret7"] >= 2,
        "+7% 종목 >= 3": d["n_ret7"] >= 3,
        "최고등락>=15% & +7%>=2": (d["max_ret10"] >= 15) & (d["n_ret7"] >= 2),
        "4조건 통과 >= 1": d["n_rule4"] >= 1,
        "4조건 통과 >= 2": d["n_rule4"] >= 2,
        "20일신고가 >= 3": d["n_high20"] >= 3,
        "코스피 60선 위": d["코스피_60"] == True,
        "코스닥 60선 위": d["코스닥_60"] == True,
        "코스피60위 & 4조건>=1": (d["코스피_60"] == True) & (d["n_rule4"] >= 1),
    }.items():
        n, k = int(m.sum()), int(d.loc[m, "hit"].sum())
        miss = total - d.loc[m, "n_case"].sum()
        print(f"{label:>28}{n:>8}{k:>7}{k / n * 100 if n else 0:>7.0f}%"
              f"{f'{miss:.0f}/{total:.0f}':>12}")

    print("\n" + "-" * 78)
    print("제외 관점 - 이 조건이면 그날 접는다 (버리는 날 / 같이 버리는 케이스)")
    print("-" * 78)
    print(f"{'접는 조건':>30}{'버린 날':>8}{'그중 공친 날':>12}{'버린 케이스':>11}{'남은 날 적중':>11}")
    for label, m in {
        "대형주 비중 >= 85%": d["res_share"] >= 0.85,
        "대형주 비중 >= 80%": d["res_share"] >= 0.80,
        "top10 최고등락 < 10%": d["max_ret10"] < 10,
        "둘 중 하나라도(85% / <10%)": (d["res_share"] >= 0.85) | (d["max_ret10"] < 10),
        "둘 다(85% & <10%)": (d["res_share"] >= 0.85) & (d["max_ret10"] < 10),
        "둘 다(80% & <10%)": (d["res_share"] >= 0.80) & (d["max_ret10"] < 10),
        "둘 다(80% & <15%)": (d["res_share"] >= 0.80) & (d["max_ret10"] < 15),
        "둘 중 하나(80% / +7%종목<2)": (d["res_share"] >= 0.80) | (d["n_ret7"] < 2),
    }.items():
        n = int(m.sum())
        if n == 0:
            print(f"{label:>30}{0:>8}")
            continue
        dead = int((~d.loc[m, "hit"]).sum())
        lost = int(d.loc[m, "n_case"].sum())
        keep = d[~m]
        print(f"{label:>30}{n:>8}{f'{dead}({dead/n*100:.0f}%)':>12}{f'{lost}/{int(total)}':>11}"
              f"{keep['hit'].mean()*100:>10.0f}%")

    out = "results/clean20_day_filter.csv"
    d.to_csv(out, encoding="utf-8-sig")
    print(f"\n원본: {out}")


def demo() -> None:
    """index_day가 10:00 이후 봉을 안 보는지(룩어헤드) 확인."""
    idx = pd.date_range("2026-01-02 09:00", "2026-01-02 15:30", freq="1min")
    s = pd.Series(range(len(idx)), index=idx, dtype=float)
    k15 = s.resample("15min").last().dropna()
    used = k15[k15.index.time < TEN]
    last = used.index[-1]
    assert last.time() < TEN, last                      # 판단 시각 이후 봉은 안 본다
    closed = last + pd.Timedelta(minutes=14)            # 그 봉이 실제로 확정되는 시각
    assert closed.time() < TEN, closed                  # 확정까지도 판단 시각 전이어야 한다
    assert used.iloc[-1] == s.loc[closed], "15분봉은 자기 구간 끝까지만 담아야 한다"
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    report()
