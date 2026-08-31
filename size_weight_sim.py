"""전일 코스닥 거래대금으로 진입 사이즈를 가중하면 나아지나.

    python size_weight_sim.py

컷(--kdqmin)은 후보를 통째로 버려서 손해였다. 버리는 대신 비중만 줄이면 다른지 본다.
가중은 선형이라 건별 수익률만 뽑아두면 어떤 배분이든 재계산된다 - 시뮬레이션은
한 번만 돌리고 배분표를 갈아끼운다.

자본 효율 = Σ(w x r) / Σw  (같은 자본을 굴렸을 때의 건당 기대값)
총수익    = Σ(w x r)        (1건 풀사이즈를 1로 놓은 누적)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pullback_ladder_backtest as L
from kospi_value_burst import daily_value

PLAN, TRAIL = "A 전량 10:00", 5.0


def trades() -> pd.DataFrame:
    """일컷10%까지 적용한 후보의 건별 수익률 + 그날의 전일 코스닥 대금(조)."""
    L.DAY_PEAK, L.DAY_CUT, L.KDQ_MIN = True, 10.0, 0.0
    cand = L.candidates()
    rows = []
    for code, g in cand.groupby("stock_code"):
        path = os.path.join(L.MINUTE_DIR, f"{code}.csv")
        if not os.path.exists(path):
            continue
        minute = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        want = set(g["date"])
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in want:
                continue
            out = L.simulate(bars, L.PLANS[PLAN], TRAIL)
            if out is not None:
                rows.append({"date": date, "code": code, "ret": out[0]})

    df = pd.DataFrame(rows)
    prev = (daily_value("101")["value_mw"] / 1e6).shift(1)
    df["kdq"] = df["date"].map(prev)
    return df.dropna(subset=["kdq"])


def evaluate(df: pd.DataFrame, weights: dict[str, pd.Series]) -> None:
    flat = df["ret"].mean()
    print(f"{'배분':>26}{'평균비중':>9}{'자본효율':>10}{'총수익':>9}{'vs균등':>9}")
    for label, w in weights.items():
        tot = float((w * df["ret"]).sum())
        eff = tot / w.sum()
        print(f"{label:>26}{w.mean():>9.2f}{eff:>9.2f}%{tot:>8.0f}%{eff - flat:>+8.2f}%p")


def main() -> None:
    df = trades()
    q = df["kdq"].quantile([1 / 3, 2 / 3])
    df["band"] = pd.cut(df["kdq"], [-1, q[1 / 3], q[2 / 3], 1e9], labels=["하위", "중간", "상위"])

    print("=" * 68)
    print(f"{PLAN} 트레일 -{TRAIL:g}% · 3배제+일컷10% · {len(df)}건")
    print("=" * 68)
    print(f"컷: 하위 <{q[1/3]:.1f}조 / 중간 ~{q[2/3]:.1f}조 / 상위 {q[2/3]:.1f}조+  (전일 코스닥 대금)")
    print(f"\n{'구간':>10}{'n':>6}{'승률':>8}{'평균':>9}{'평균익':>9}{'평균손':>9}{'합계':>9}")
    for b, g in df.groupby("band", observed=True):
        w = g[g["ret"] > 0]["ret"]
        l = g[g["ret"] <= 0]["ret"]
        print(f"{b:>10}{len(g):>6}{(g['ret']>0).mean()*100:>7.1f}%{g['ret'].mean():>8.2f}%"
              f"{w.mean() if len(w) else 0:>8.2f}%{l.mean() if len(l) else 0:>8.2f}%{g['ret'].sum():>8.0f}%")

    lo, mid = df["band"] == "하위", df["band"] == "중간"
    hi = df["band"] == "상위"
    one = pd.Series(1.0, index=df.index)
    print()
    evaluate(df, {
        "균등(기준)": one,
        "역가중 1.5/1.0/0.5": lo * 1.5 + mid * 1.0 + hi * 0.5,
        "역가중 1.5/1.0/0.0(상위배제)": lo * 1.5 + mid * 1.0,
        "정가중 0.5/1.0/1.5": lo * 0.5 + mid * 1.0 + hi * 1.5,
        "정가중 0.0/1.0/1.5(하위배제)": mid * 1.0 + hi * 1.5,
        "연속 역가중 (중앙/대금)": (df["kdq"].median() / df["kdq"]).clip(0.5, 2.0),
        "연속 정가중 (대금/중앙)": (df["kdq"] / df["kdq"].median()).clip(0.5, 2.0),
    })

    print("\n상관: 전일 코스닥 대금 vs 건별 수익률"
          f"  피어슨 {df['kdq'].corr(df['ret']):+.3f} · 스피어만 {df['kdq'].corr(df['ret'], method='spearman'):+.3f}")


def demo() -> None:
    """자본효율이 가중의 정의와 맞는지 - 좋은 쪽에 2배 실으면 균등보다 높아야 한다."""
    df = pd.DataFrame({"ret": [10.0, -2.0]})
    w = pd.Series([2.0, 1.0])
    assert abs((w * df["ret"]).sum() / w.sum() - 6.0) < 1e-9      # (20-2)/3
    assert abs(df["ret"].mean() - 4.0) < 1e-9
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
