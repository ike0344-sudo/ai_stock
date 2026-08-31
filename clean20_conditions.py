"""고점比 -5%를 안 깨고 +20%까지 가는 종목("클린 20")의 조건 탐색.

모집단: 대금 top10(10:00 장중누적대금 순위) 종목-일자 전체.
라벨  : reach20_path_drawdown의 09:00~최초+20% 경로 최대낙폭(러닝고점比) <= 5%.

두 가지 질문을 나눠 답한다.
  [A] 서술 — 클린으로 간 케이스는 지저분하게 간 케이스와 뭐가 달랐나 (사후)
  [B] 예측 — 10:00 시점 정보만으로 클린 20을 골라낼 수 있나 (10시 전 이미 +20%면 제외)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOP_N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--top=")), 10))
MAX_DD = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--dd=")), 5))
FEATURES = [
    ("ret_at_10_pct", "10시 등락률(전일比)"),
    ("high_at_10_pct", "10시까지 고가(전일比)"),
    ("open_gap_pct", "시가 갭"),
    ("cum_value_eok", "10시 누적대금(억)"),
    ("value_vs_prev_day", "10시대금/전일종일대금"),
    ("value_vs_20d_avg", "10시대금/20일평균"),
    ("max_dd_to_10_pct", "10시까지 최대눌림"),
    ("pos_in_range_10", "10시 종가의 레인지 위치"),
    ("upper_wick_ratio", "10시까지 윗꼬리 비율"),
    ("first5_value_share", "첫 5분 대금 비중"),
    ("prev_day_ret_pct", "전일 등락률"),
    ("d5_ret_pct", "최근 5일 수익률"),
    ("high_vs_20d_high_pct", "10시고가/20일고가"),
    ("atr20_pct", "20일 ATR%"),
    ("price_log", "주가(log10)"),
]


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    m = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (max(0.0, c - m) * 100, min(1.0, c + m) * 100)


def auc(pos: pd.Series, neg: pd.Series) -> float:
    """Mann-Whitney AUC — 0.5면 무의미, 1.0/0.0이면 완전분리."""
    pos, neg = pos.dropna(), neg.dropna()
    if pos.empty or neg.empty:
        return 0.5
    r = pd.concat([pos, neg]).rank()
    return (r.iloc[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def load() -> pd.DataFrame:
    suf = "" if os.environ.get("SCAN_CUTOFF", "1000") == "1000" else f'_{os.environ["SCAN_CUTOFF"]}'
    f = pd.read_csv(f"results/reach20_features{suf}.csv", parse_dates=["date"], dtype={"stock_code": str})
    f = f[f["rank_10am"] <= TOP_N]
    p = pd.read_csv(f"results/reach20_path_drawdown{suf}_top{TOP_N}.csv", parse_dates=["date"],
                    dtype={"stock_code": str})
    df = f.merge(p[["date", "stock_code", "max_dd_pct", "t20_time", "minutes_to_20", "n_ep_ge3"]],
                 on=["date", "stock_code"], how="left")
    df["reached"] = df["max_dd_pct"].notna()
    df["clean"] = df["reached"] & (df["max_dd_pct"] <= MAX_DD)
    return df


def compare(df: pd.DataFrame, label_a: str, a: pd.DataFrame, label_b: str, b: pd.DataFrame) -> None:
    rows = []
    for col, name in FEATURES:
        rows.append((abs(auc(a[col], b[col]) - 0.5), auc(a[col], b[col]), col, name))
    rows.sort(reverse=True)
    print(f"{'피처':>24}{'AUC':>7}{label_a+' 중앙':>14}{label_b+' 중앙':>14}{'차이':>10}")
    for _, au, col, name in rows:
        ma, mb = a[col].median(), b[col].median()
        star = " ***" if abs(au - 0.5) >= 0.10 else (" *" if abs(au - 0.5) >= 0.05 else "")
        print(f"{name:>24}{au:>7.3f}{ma:>13.2f}{mb:>13.2f}{ma-mb:>+10.2f}{star}")


def bins_table(df: pd.DataFrame, col: str, name: str, target: str) -> None:
    q = pd.qcut(df[col], 5, duplicates="drop")
    print(f"\n{name}")
    print(f"{'구간':>26}{'n':>7}{'클린20':>8}{'비율':>8}{'95% CI':>15}")
    for b, g in df.groupby(q, observed=True):
        k = int(g[target].sum())
        lo, hi = wilson(k, len(g))
        print(f"{f'{b.left:g} ~ {b.right:g}':>26}{len(g):>7}{k:>8}{k/len(g)*100:>7.1f}%"
              f"{f'[{lo:.0f}-{hi:.0f}]':>15}")


def report(df: pd.DataFrame) -> None:
    n, nr, nc = len(df), int(df["reached"].sum()), int(df["clean"].sum())
    print("=" * 92)
    print(f"고점比 -{MAX_DD:g}%를 안 깨고 +20% 도달('클린 20')의 조건   [대금 top{TOP_N}]")
    print("=" * 92)
    print(f"기간     : {df['date'].min().date()} ~ {df['date'].max().date()} ({df['date'].nunique()}일)")
    print(f"모집단   : {n:,}건 (top{TOP_N} 종목-일자)")
    print(f"+20% 도달: {nr:,}건 ({nr/n*100:.1f}%)")
    print(f"클린 20  : {nc:,}건 (모집단의 {nc/n*100:.1f}%, 도달 케이스의 {nc/nr*100:.1f}%)  <- 기준선")

    reach = df[df["reached"]]
    clean, dirty = reach[reach["clean"]], reach[~reach["clean"]]
    print("\n" + "=" * 92)
    print(f"[A] 클린({len(clean)}건) vs 지저분({len(dirty)}건) — 둘 다 +20%는 갔음. 뭐가 달랐나")
    print("=" * 92)
    compare(df, "클린", clean, "지저분", dirty)
    print("\n  *** AUC 편차 0.10 이상 / * 0.05 이상")

    print("\n[A-2] 경로 자체의 차이")
    for col, name, unit in [("max_dd_pct", "경로 최대낙폭", "%"), ("minutes_to_20", "+20%까지 소요", "분"),
                            ("n_ep_ge3", "3% 이상 조정 횟수", "회")]:
        print(f"{name:>18} : 클린 중앙 {clean[col].median():>6.1f}{unit}   "
              f"지저분 중앙 {dirty[col].median():>6.1f}{unit}")
    for label, g in [("클린", clean), ("지저분", dirty)]:
        early = (g["t20_time"] <= "10:00").mean() * 100
        print(f"{label:>18} : 10시 이전 +20% 도달 {early:.0f}%")

    live = df[~df["already_20_by_10"]]
    lc = int(live["clean"].sum())
    print("\n" + "=" * 92)
    print(f"[B] 10:00 의사결정 관점 — 이미 +20%인 {int(df['already_20_by_10'].sum())}건 제외")
    print("=" * 92)
    print(f"판단 대상 {len(live):,}건 중 클린 20 {lc}건 = {lc/len(live)*100:.2f}%  <- 이 기준선을 이겨야 함")
    print("\n단변량 판별력 (클린 vs 나머지 전부)")
    compare(live, "클린", live[live["clean"]], "나머지", live[~live["clean"]])

    top = sorted(FEATURES, key=lambda x: -abs(auc(live[live["clean"]][x[0]],
                                                 live[~live["clean"]][x[0]]) - 0.5))[:4]
    print("\n" + "-" * 92)
    print("상위 4개 피처의 5분위별 클린 20 발생률")
    print("-" * 92)
    for col, name in top:
        bins_table(live, col, name, "clean")

    print("\n" + "-" * 92)
    print("복합 조건 (10시 시점에 전부 관측 가능)")
    print("-" * 92)
    rules = {
        "10시 등락률 >= 7%": live["ret_at_10_pct"] >= 7,
        "레인지 위치 >= 0.8": live["pos_in_range_10"] >= 0.8,
        "윗꼬리 <= 0.2": live["upper_wick_ratio"] <= 0.2,
        "대금 >= 20일평균 1.5배": live["value_vs_20d_avg"] >= 1.5,
        "20일고가 돌파(>=0%)": live["high_vs_20d_high_pct"] >= 0,
    }
    print(f"{'조건':>34}{'n':>7}{'클린':>7}{'비율':>8}{'배수':>8}{'95% CI':>15}")
    base = lc / len(live)
    combo = pd.Series(True, index=live.index)
    for label, m in rules.items():
        k, tot = int(live.loc[m, "clean"].sum()), int(m.sum())
        lo, hi = wilson(k, tot)
        print(f"{label:>34}{tot:>7}{k:>7}{k/tot*100:>7.1f}%{k/tot/base:>7.2f}x"
              f"{f'[{lo:.0f}-{hi:.0f}]':>15}")
    print()
    for label, m in rules.items():
        combo &= m
        k, tot = int(live.loc[combo, "clean"].sum()), int(combo.sum())
        if tot < 10:
            print(f"{('누적 + ' + label):>34}{tot:>7}      (표본 부족, 중단)")
            break
        lo, hi = wilson(k, tot)
        print(f"{('누적 + ' + label):>34}{tot:>7}{k:>7}{k/tot*100:>7.1f}%{k/tot/base:>7.2f}x"
              f"{f'[{lo:.0f}-{hi:.0f}]':>15}")

    print()
    print("-" * 92)
    print(f"+20% 도달을 전제로 했을 때 클린일 확률 (도달 {int(df['reached'].sum())}건 중 클린 {int(df['clean'].sum())}건 = "
          f"{df[df['reached']]['clean'].mean()*100:.1f}%가 기준선)")
    print("-" * 92)
    reach2 = df[df["reached"]]
    cond = {
        "10시까지 눌림 <= 3%": reach2["max_dd_to_10_pct"] <= 3,
        "10시까지 눌림 <= 5%": reach2["max_dd_to_10_pct"] <= 5,
        "주가 >= 3만원": reach2["price_log"] >= np.log10(30000),
        "전일 등락률 <= 5%": reach2["prev_day_ret_pct"] <= 5,
        "최근 5일 수익률 <= 15%": reach2["d5_ret_pct"] <= 15,
        "대금/20일평균 <= 3배": reach2["value_vs_20d_avg"] <= 3,
        "첫 5분 대금비중 <= 0.15": reach2["first5_value_share"] <= 0.15,
    }
    print(f"{'조건':>34}{'n':>7}{'클린':>7}{'비율':>8}{'배수':>8}{'95% CI':>15}")
    b2 = reach2["clean"].mean()
    for label, m in cond.items():
        k, tot = int(reach2.loc[m, "clean"].sum()), int(m.sum())
        lo, hi = wilson(k, tot)
        print(f"{label:>34}{tot:>7}{k:>7}{k/tot*100:>7.1f}%{k/tot/b2:>7.2f}x"
              f"{f'[{lo:.0f}-{hi:.0f}]':>15}")
    print()
    c2 = pd.Series(True, index=reach2.index)
    for label in ["10시까지 눌림 <= 5%", "주가 >= 3만원", "전일 등락률 <= 5%", "최근 5일 수익률 <= 15%"]:
        c2 &= cond[label]
        k, tot = int(reach2.loc[c2, "clean"].sum()), int(c2.sum())
        if tot < 10:
            print(f"{('누적 + ' + label):>34}{tot:>7}      (표본 부족, 중단)")
            break
        lo, hi = wilson(k, tot)
        print(f"{('누적 + ' + label):>34}{tot:>7}{k:>7}{k/tot*100:>7.1f}%{k/tot/b2:>7.2f}x"
              f"{f'[{lo:.0f}-{hi:.0f}]':>15}")


def demo() -> None:
    """AUC/Wilson 자체검증."""
    assert abs(auc(pd.Series([3, 4, 5]), pd.Series([0, 1, 2])) - 1.0) < 1e-9
    assert abs(auc(pd.Series([0, 1, 2]), pd.Series([0, 1, 2])) - 0.5) < 1e-9
    lo, hi = wilson(5, 10)
    assert lo < 50 < hi and 0 < lo and hi < 100, (lo, hi)
    assert wilson(0, 0) == (0.0, 0.0)
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    report(load())
