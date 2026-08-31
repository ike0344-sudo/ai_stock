"""6,000만원 자본으로 운용했을 때의 월별 손익.

자본 배분: 하루에 나온 후보에 균등 분배(같은 날 3건이면 2,000만원씩).
미체결 레그는 현금으로 남으므로 그만큼 손익이 0이다 — simulate()가 이미
"배정자본 대비 수익률"을 돌려주므로 여기서는 곱하기만 한다.

단리(매번 6,000만원 고정)와 복리(직전 잔고를 재투입) 둘 다 낸다.
손절/체결 기준은 당일 고점(09:00부터)이다.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pullback_ladder_backtest as L

L.DAY_PEAK = True                      # 당일 고점 기준
CAPITAL = 60_000_000
RULE4 = "--rule4" in sys.argv
L.RULE4 = RULE4

PLANS = {
    "3분할 -2/-4/돌파 (손절-5%)":
        ({"market": 0.0, "dips": [(1 / 3, 2.0), (1 / 3, 4.0)], "breakout": 1 / 3, "bo_buf": 0.0}, 5.0),
    "B안 2분할 -2/돌파+0.3 (손절-4%)":
        ({"market": 0.0, "dips": [(0.5, 2.0)], "breakout": 0.5, "bo_buf": 0.3}, 4.0),
    "A안 2분할 -1/돌파+0.3 (손절-5%)":
        ({"market": 0.0, "dips": [(0.5, 1.0)], "breakout": 0.5, "bo_buf": 0.3}, 5.0),
    "참고: 전량 10:00 (손절-5%)":
        ({"market": 1.0, "dips": [], "breakout": 0.0, "bo_buf": 0.0}, 5.0),
}


def collect() -> pd.DataFrame:
    cand = L.candidates()
    rows = []
    for i, (code, g) in enumerate(cand.groupby("stock_code"), 1):
        print(f"\r[{i}/{cand['stock_code'].nunique()}] {code}", end="", file=sys.stderr)
        path = os.path.join(L.MINUTE_DIR, f"{code}.csv")
        if not os.path.exists(path):
            continue
        minute = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        want = set(g["date"])
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in want:
                continue
            rec = {"date": date, "code": code}
            ok = True
            for name, (plan, stop) in PLANS.items():
                out = L.simulate(bars, plan, stop)
                if out is None:
                    ok = False
                    break
                rec[name] = out[0]
            if ok:
                rows.append(rec)
    print(file=sys.stderr)
    return pd.DataFrame(rows)


def monthly(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """하루 후보에 자본을 균등 분배했을 때의 일별/월별 수익률."""
    per_day = df.groupby("date")[col].mean()          # 균등 분배 = 그날 수익률의 평균
    m = per_day.groupby(per_day.index.to_period("M"))
    return pd.DataFrame({
        "거래일": m.size(),
        "수익률": m.sum(),                             # 단리 기준 월 합계 %
        "손익(만원)": m.sum() * CAPITAL / 100 / 10_000,
    })


def report(df: pd.DataFrame) -> None:
    n_days = df["date"].nunique()
    print("=" * 96)
    print(f"자본 {CAPITAL/100_000_000:.2f}억 · {'3배제+4조건' if RULE4 else '3배제'} 후보 "
          f"{len(df)}건 / {n_days}거래일 ({len(df)/n_days:.1f}건/일)")
    print(f"기간 {df['date'].min().date()} ~ {df['date'].max().date()} · 하루 후보에 자본 균등 분배 · 비용 0.25% 반영")
    print("=" * 96)

    tables = {k: monthly(df, k) for k in PLANS}
    idx = tables[list(PLANS)[0]].index

    print(f"\n{'월':>9}{'거래일':>6}" + "".join(f"{k.split(' ')[0]:>16}" for k in PLANS))
    for p in idx:
        line = f"{str(p):>9}{tables[list(PLANS)[0]].loc[p, '거래일']:>6}"
        for k in PLANS:
            line += f"{tables[k].loc[p, '손익(만원)']:>15,.0f}만"
        print(line)

    print("\n" + "-" * 96)
    print(f"{'전략':>30}{'총손익':>13}{'월평균':>11}{'수익률':>9}{'승월':>7}{'최악월':>12}{'최대낙폭':>11}")
    print("-" * 96)
    for k in PLANS:
        t = tables[k]
        per_day = df.groupby("date")[k].mean()
        eq = np.cumsum(per_day.to_numpy()) * CAPITAL / 100
        mdd = (np.maximum.accumulate(eq) - eq).max()
        tot = t["손익(만원)"].sum()
        print(f"{k:>30}{tot:>11,.0f}만{tot/len(t):>9,.0f}만"
              f"{t['수익률'].sum():>8.1f}%{(t['손익(만원)'] > 0).sum():>4}/{len(t):<3}"
              f"{t['손익(만원)'].min():>10,.0f}만{-mdd/10_000:>10,.0f}만")

    print("\n" + "-" * 96)
    print("복리 운용(직전 잔고 재투입) 시 최종 잔고")
    print("-" * 96)
    for k in PLANS:
        per_day = df.groupby("date")[k].mean()
        bal = CAPITAL * np.prod(1 + per_day.to_numpy() / 100)
        print(f"{k:>30}  {bal/100_000_000:>6.2f}억  ({bal/CAPITAL - 1:+.1%})")

    print("\n" + "-" * 96)
    print("건당 통계 (자본 배분 전, 아이디어 1건 기준)")
    print("-" * 96)
    print(f"{'전략':>30}{'n':>6}{'승률':>8}{'기대값':>9}{'평균익':>9}{'평균손':>9}{'최악':>8}")
    for k in PLANS:
        a = df[k].to_numpy()
        nz = a[a != 0]
        print(f"{k:>30}{len(a):>6}{(a > 0).mean()*100:>7.1f}%{a.mean():>8.2f}%"
              f"{nz[nz > 0].mean():>8.2f}%{nz[nz <= 0].mean():>8.2f}%{a.min():>7.1f}%")


if __name__ == "__main__":
    report(collect())
