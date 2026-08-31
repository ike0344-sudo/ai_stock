"""순환매 장세(강세가 여러 섹터로 흩어진 날) 판별과 손익 영향.

    python rotation_days.py

사용자 관찰: 섹터가 2개 이상 형성되는 순환매 날에 손실이 잘 난다.
케이스 발생률이 아니라 실제 건별 손익으로 검증한다 - 발생률 지표는 이미 여러 번
손익과 반대로 나왔다.

순환매 정의 두 가지(둘 다 10:00에 확정):
    섹터수  - 10시 등락률 +7% 강세 종목이 걸쳐 있는 업종 수
    테마수  - 그중 같은 업종에 강세가 2개 이상 뭉친 업종의 수 (사용자가 말한 "형성")
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pullback_ladder_backtest as L
from clean20_conditions import wilson
from theme_days import build

PLAN, TRAIL = "A 전량 10:00", 5.0


def day_structure() -> pd.DataFrame:
    """하루 한 줄: 강세 종목의 업종 구조 + 클린20 결과."""
    df = build()
    strong = df[df["strong"]]
    per_sector = strong.groupby(["date", "sector"]).size()

    d = df.groupby("date").agg(hit=("case", "any"), n_case=("case", "sum"),
                               n_strong=("strong", "sum"))
    d["n_sector"] = per_sector.groupby("date").size().reindex(d.index).fillna(0)
    d["n_theme"] = per_sector[per_sector >= 2].groupby("date").size().reindex(d.index).fillna(0)
    d["top_share"] = (per_sector.groupby("date").max() / d["n_strong"]).reindex(d.index)
    return d


def trades() -> pd.DataFrame:
    """3배제+일컷10% 후보의 건별 수익률 (size_weight_sim과 같은 설정)."""
    L.DAY_PEAK, L.DAY_CUT, L.KDQ_MIN, L.KDQ_930 = True, 10.0, 0.0, 0.0
    cand = L.candidates()
    rows = []
    for code, g in cand.groupby("stock_code"):
        path = os.path.join(L.MINUTE_DIR, f"{code}.csv")
        if not os.path.exists(path):
            continue
        minute = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        want = set(g["date"])
        for date, bars in minute.groupby(minute.index.normalize()):
            if date in want:
                out = L.simulate(bars, L.PLANS[PLAN], TRAIL)
                if out is not None:
                    rows.append({"date": date, "code": code, "ret": out[0]})
    return pd.DataFrame(rows)


def band(d: pd.DataFrame, t: pd.DataFrame, col: str, cuts: list, name: str) -> None:
    base_hit, base_ret = d["hit"].mean(), t["ret"].mean()
    print(f"\n{name}")
    print(f"{'구간':>12}{'일수':>7}{'적중':>7}{'케이스/일':>10}{'건수':>7}{'평균손익':>10}"
          f"{'승률':>8}{'합계':>8}")
    for i, lo in enumerate(cuts):
        hi = cuts[i + 1] if i + 1 < len(cuts) else 99
        m = (d[col] >= lo) & (d[col] < hi)
        n = int(m.sum())
        if n == 0:
            continue
        days = set(d.index[m])
        g = t[t["date"].isin(days)]
        lab = f"{lo:g}개" if hi == 99 and i == len(cuts) - 1 else f"{lo:g}"
        lab = f"{lo:g}+" if hi == 99 else f"{lo:g}~{hi-1:g}"
        print(f"{lab:>12}{n:>7}{d.loc[m,'hit'].mean()*100:>6.0f}%{d.loc[m,'n_case'].mean():>10.2f}"
              f"{len(g):>7}{g['ret'].mean() if len(g) else 0:>9.2f}%"
              f"{(g['ret']>0).mean()*100 if len(g) else 0:>7.0f}%{g['ret'].sum():>7.0f}%")
    print(f"{'전체':>12}{len(d):>7}{base_hit*100:>6.0f}%{d['n_case'].mean():>10.2f}"
          f"{len(t):>7}{base_ret:>9.2f}%{(t['ret']>0).mean()*100:>7.0f}%{t['ret'].sum():>7.0f}%")


def main() -> None:
    d, t = day_structure(), trades()
    print("=" * 78)
    print(f"순환매 판별  |  {len(d)}거래일 · 진입 {len(t)}건 ({PLAN} 트레일 -{TRAIL:g}%)")
    print("=" * 78)

    band(d, t, "n_theme", [0, 1, 2], "강세 2개+ 뭉친 업종 수 (사용자 정의 '섹터 형성')")
    band(d, t, "n_sector", [1, 2, 3, 4, 5], "강세 종목이 걸친 업종 수")

    print("\n" + "-" * 78)
    print("강세 3개 이상인 날만 - 같은 수의 강세가 뭉쳤나 흩어졌나")
    print("-" * 78)
    sub = d[d["n_strong"] >= 3]
    print(f"{'구간':>16}{'일수':>7}{'적중':>7}{'건수':>7}{'평균손익':>10}{'승률':>8}{'합계':>8}")
    for lab, m in [("뭉침(1섹터)", sub["n_theme"] <= 1), ("순환(2섹터+)", sub["n_theme"] >= 2)]:
        days = set(sub.index[m])
        g = t[t["date"].isin(days)]
        lo, hi = wilson(int((g["ret"] > 0).sum()), len(g)) if len(g) else (0, 0)
        print(f"{lab:>16}{int(m.sum()):>7}{sub.loc[m,'hit'].mean()*100:>6.0f}%{len(g):>7}"
              f"{g['ret'].mean():>9.2f}%{(g['ret']>0).mean()*100:>7.0f}%{g['ret'].sum():>7.0f}%")

    print("\n" + "-" * 78)
    print("최고 업종 쏠림도(강세 중 1위 업종 비중)")
    print("-" * 78)
    x = d.dropna(subset=["top_share"])
    x = x[x["n_strong"] >= 3]
    q = pd.qcut(x["top_share"], 3, duplicates="drop")
    print(f"{'구간':>16}{'일수':>7}{'적중':>7}{'건수':>7}{'평균손익':>10}{'승률':>8}{'합계':>8}")
    for b, g in x.groupby(q, observed=True):
        tt = t[t["date"].isin(set(g.index))]
        print(f"{f'{b.left:.2f}~{b.right:.2f}':>16}{len(g):>7}{g['hit'].mean()*100:>6.0f}%"
              f"{len(tt):>7}{tt['ret'].mean():>9.2f}%{(tt['ret']>0).mean()*100:>7.0f}%{tt['ret'].sum():>7.0f}%")


def demo() -> None:
    """n_theme는 '강세 2개 이상 업종'만 세야 한다 - 1개짜리를 세면 순환매가 과대집계된다."""
    s = pd.Series([3, 1, 2], index=pd.MultiIndex.from_tuples(
        [("d", "A"), ("d", "B"), ("d", "C")], names=["date", "sector"]))
    assert s.groupby("date").size().iloc[0] == 3          # 강세가 걸친 업종 수
    assert s[s >= 2].groupby("date").size().iloc[0] == 2  # 뭉친 업종은 A, C 둘
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
