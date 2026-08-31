"""코스피 15분봉 60선 아래에서 나온 클린20의 공통점.

    python below60_traits.py

시장이 눌려 있는데도 +20%까지 깨끗하게 간 케이스는 어떤 놈들인가. 60선 위(순풍)에서
나온 케이스와 나란히 놓고 뭐가 다른지 본다. 60선 판정은 clean20_report와 같은 값
(09:00~+20% 도달 구간의 15분봉이 60봉 이평 위였던 비율)을 쓴다.
"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import auc, wilson
from clean20_list import select
from clean20_report import kospi_above_60
from theme_days import sectors

FEATURES = [
    ("open_gap_pct", "시가갭(%)"),
    ("ret_at_10_pct", "10시 등락률(%)"),
    ("high_vs_20d_high_pct", "10시고가/20일고가(%)"),
    ("value_vs_20d_avg", "대금/20일평균"),
    ("cum_value_eok", "10시 누적대금(억)"),
    ("first5_value_share", "첫 5분 대금비중"),
    ("max_dd_to_10_pct", "10시까지 눌림(%)"),
    ("pos_in_range_10", "10시 레인지 위치"),
    ("prev_day_ret_pct", "전일 등락률(%)"),
    ("d5_ret_pct", "최근 5일 수익률(%)"),
    ("atr20_pct", "20일 ATR(%)"),
    ("price_log", "주가(log10)"),
    ("rank_10am", "대금순위"),
    ("max_dd_pct", "경로 최대낙폭(%)"),
    ("minutes_to_20", "+20%까지(분)"),
    ("close_ret_pct", "당일 종가(%)"),
]


def frame() -> pd.DataFrame:
    cases, _ = select(dd=5.0, max_gap=15.0)
    above = kospi_above_60()
    ratio = []
    for _, r in cases.iterrows():
        w = above.loc[r["date"] + pd.Timedelta(hours=9):
                      f"{r['date']:%Y-%m-%d} {r['t20_time']}"].dropna()
        ratio.append(w.mean() if len(w) else float("nan"))
    # 교차는 방향이 중요하다 - 아래에서 위로 뚫었나(회복), 위에서 아래로 깨졌나(악화)
    first, last = [], []
    for _, r in cases.iterrows():
        w = above.loc[r["date"] + pd.Timedelta(hours=9):
                      f"{r['date']:%Y-%m-%d} {r['t20_time']}"].dropna()
        first.append(w.iloc[0] if len(w) else None)
        last.append(w.iloc[-1] if len(w) else None)

    # select()가 이미 load()의 피처를 다 달고 나온다 - 다시 merge하면 컬럼이 _x/_y로 갈린다
    cases = cases.assign(x=ratio, x_first=first, x_last=last)
    cases["sector"] = cases["stock_code"].map(sectors()).fillna("미상")
    return cases


def main() -> None:
    c = frame()
    below, mixed, above = c[c["x"] == 0], c[(c["x"] > 0) & (c["x"] < 1)], c[c["x"] == 1]
    print("=" * 76)
    print(f"코스피 15분 60선별 클린20  |  전체 {len(c)}건 "
          f"(아래 {len(below)} · 교차 {len(mixed)} · 위 {len(above)} · 판정불가 {int(c['x'].isna().sum())})")
    print("=" * 76)

    print(f"\n{'지표':>20}{'AUC(교차vs위)':>13}{'교차':>10}{'아래':>10}{'위':>10}")
    rows = sorted(((abs(auc(mixed[col], above[col]) - 0.5), auc(mixed[col], above[col]), col, name)
                   for col, name in FEATURES), reverse=True)
    for _, a, col, name in rows:
        star = " ***" if abs(a - 0.5) >= 0.15 else (" *" if abs(a - 0.5) >= 0.08 else "")
        print(f"{name:>20}{a:>13.3f}{mixed[col].median():>10.2f}"
              f"{below[col].median():>10.2f}{above[col].median():>10.2f}{star}")
    print("\n  AUC>0.5 = 교차 케이스가 60선 위보다 큰 값 · *** 편차 0.15 이상 / * 0.08 이상")

    up = mixed[(mixed["x_first"] == False) & (mixed["x_last"] == True)]
    dn = mixed[(mixed["x_first"] == True) & (mixed["x_last"] == False)]
    other = mixed.drop(up.index).drop(dn.index)
    print(f"\n교차 방향  |  아래→위(회복) {len(up)} · 위→아래(악화) {len(dn)} · 왕복 {len(other)}")
    print(f"{'':>20}{'n':>5}{'60선 위 비율':>12}{'+20%까지(분)':>13}{'당일 종가(%)':>13}{'+20% 지킴':>10}")
    for label, g in [("아래→위 회복", up), ("위→아래 악화", dn), ("왕복", other)]:
        if len(g) == 0:
            continue
        print(f"{label:>20}{len(g):>5}{g['x'].median()*100:>11.0f}%"
              f"{g['minutes_to_20'].median():>13.0f}{g['close_ret_pct'].median():>13.1f}"
              f"{(g['close_ret_pct'] >= 20).mean()*100:>9.0f}%")

    print(f"\n{'도달 시각 분포':>20}{'10시 이전':>11}{'10~12시':>10}{'12시 이후':>11}")
    for label, g in [("60선 아래", below), ("60선 위", above)]:
        e = (g["t20_time"] <= "10:00").mean() * 100
        m = ((g["t20_time"] > "10:00") & (g["t20_time"] <= "12:00")).mean() * 100
        l = (g["t20_time"] > "12:00").mean() * 100
        print(f"{label:>20}{e:>10.0f}%{m:>9.0f}%{l:>10.0f}%")

    print(f"\n{'종가 방어':>20}{'+20% 지킴':>11}{'+10% 이상':>11}{'중앙 종가':>11}")
    for label, g in [("60선 아래", below), ("교차", mixed), ("60선 위", above)]:
        k = int((g["close_ret_pct"] >= 20).sum())
        lo, hi = wilson(k, len(g))
        print(f"{label:>20}{f'{k}/{len(g)} ({k/len(g)*100:.0f}%)':>11}"
              f"{(g['close_ret_pct'] >= 10).mean()*100:>10.0f}%{g['close_ret_pct'].median():>10.1f}%"
              f"   95%CI[{lo:.0f}-{hi:.0f}]")

    print("\n업종 분포 (건수 2 이상)")
    t = pd.crosstab(c["sector"], c["x"].map(lambda v: "아래" if v == 0 else ("위" if v == 1 else "교차")))
    t = t.reindex(columns=["아래", "교차", "위"], fill_value=0)
    t = t[t.sum(axis=1) >= 2].sort_values("아래", ascending=False)
    print(f"{'업종':>20}{'아래':>7}{'교차':>7}{'위':>7}{'아래 비중':>10}")
    for name, r in t.head(10).iterrows():
        tot = r.sum()
        print(f"{name:>20}{int(r['아래']):>7}{int(r['교차']):>7}{int(r['위']):>7}"
              f"{r['아래']/tot*100:>9.0f}%")

    print("\n60선 아래 케이스 전체")
    cols = ["date", "name", "open_gap_pct", "ret_at_10_pct", "max_dd_pct",
            "close_ret_pct", "t20_time", "rank_10am", "sector"]
    b = mixed[cols + ["x"]].sort_values("date")
    b["date"] = b["date"].dt.strftime("%y-%m-%d")
    print(b.to_string(index=False, float_format=lambda v: f"{v:5.1f}"))


def demo() -> None:
    """x 분류 경계 - 0과 1은 각각 '내내 아래/내내 위'여야 하고 그 사이는 교차다."""
    f = lambda v: "아래" if v == 0 else ("위" if v == 1 else "교차")
    assert [f(v) for v in (0.0, 0.01, 0.99, 1.0)] == ["아래", "교차", "교차", "위"]
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
