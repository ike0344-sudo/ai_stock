""""클린20이 나오는 날"의 초상 - 지금까지 뽑은 일 단위 지표를 한 판에 모아 비교한다.

    python clean20_day_profile.py

전부 10:00에 확정되는 값이다(전일 대금/지수 60선 포함). 케이스 나온 날 vs 공친 날의
중앙값과 AUC를 나란히 놓고, 마지막에 상위 지표들의 조합을 본다.
"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import auc, wilson
from clean20_day_filter import day_table
from kospi_value_burst import daily_value
from rotation_days import day_structure

FEATURES = [
    ("max_ret10", "top10 최고 등락률(%)"),
    ("n_ret7", "10시 +7% 종목 수"),
    ("n_strong_sector_share", "1위 업종 비중(강세 중)"),
    ("n_high20", "20일 신고가 종목 수"),
    ("n_rule4", "4조건 통과 수"),
    ("n_sector", "강세가 걸친 업종 수"),
    ("res_share", "상주 대형주 대금 비중"),
    ("코스닥_전일", "코스닥 전일 대금(조)"),
    ("코스피_전일", "코스피 전일 대금(조)"),
    ("코스피_ret10", "코스피 10시 등락률(%)"),
    ("코스닥_ret10", "코스닥 10시 등락률(%)"),
]


def frame() -> pd.DataFrame:
    d = day_table()
    s = day_structure()
    d["n_sector"] = s["n_sector"]
    d["n_strong_sector_share"] = s["top_share"]
    for name, code in [("코스피", "001"), ("코스닥", "101")]:
        v = daily_value(code)["value_mw"] / 1e6
        d[f"{name}_전일"] = d.index.map(v.shift(1))
    return d


def main() -> None:
    d = frame()
    hit, miss = d[d["hit"]], d[~d["hit"]]
    print("=" * 80)
    print(f"클린20이 나온 날 {len(hit)}일  vs  공친 날 {len(miss)}일  (총 {len(d)}거래일)")
    print("=" * 80)
    print(f"{'지표':>24}{'AUC':>7}{'나온 날':>11}{'공친 날':>11}{'차이':>10}")

    rows = sorted(((abs(auc(hit[c], miss[c]) - 0.5), auc(hit[c], miss[c]), c, n)
                   for c, n in FEATURES if c in d), reverse=True)
    for _, a, col, name in rows:
        mh, mm = hit[col].median(), miss[col].median()
        star = " ***" if abs(a - 0.5) >= 0.10 else (" *" if abs(a - 0.5) >= 0.05 else "")
        print(f"{name:>24}{a:>7.3f}{mh:>11.2f}{mm:>11.2f}{mh - mm:>+10.2f}{star}")
    print("\n  *** AUC 편차 0.10 이상 / * 0.05 이상 · 60선 위 비율은 아래 별도")

    for name in ("코스피", "코스닥"):
        col = f"{name}_60"
        print(f"{name} 15분 60선 위 비율 : 나온 날 {hit[col].mean()*100:.0f}%"
              f" · 공친 날 {miss[col].mean()*100:.0f}%")

    print("\n" + "-" * 80)
    print("상위 지표 조합 - 몇 개나 만족하나 (기준선 %.0f%%)" % (d["hit"].mean() * 100))
    print("-" * 80)
    checks = {
        "최고 등락률 >= 15%": d["max_ret10"] >= 15,
        "+7% 종목 >= 3": d["n_ret7"] >= 3,
        "1위 업종 비중 >= 0.33": d["n_strong_sector_share"].fillna(1) >= 0.33,
        "대형주 대금 비중 < 80%": d["res_share"] < 0.80,
    }
    d["score"] = sum(c.astype(int) for c in checks.values())
    print(f"{'조건':>24}{'일수':>7}{'적중':>7}{'비율':>8}{'케이스/일':>10}{'95%CI':>13}")
    for label, m in checks.items():
        n, k = int(m.sum()), int(d.loc[m, "hit"].sum())
        lo, hi = wilson(k, n)
        print(f"{label:>24}{n:>7}{k:>7}{k/n*100:>7.0f}%{d.loc[m,'n_case'].mean():>10.2f}"
              f"{f'[{lo:.0f}-{hi:.0f}]':>13}")
    print()
    print(f"{'만족 개수':>24}{'일수':>7}{'적중':>7}{'비율':>8}{'케이스/일':>10}{'95%CI':>13}")
    for s in range(5):
        m = d["score"] == s
        n = int(m.sum())
        if n == 0:
            continue
        k = int(d.loc[m, "hit"].sum())
        lo, hi = wilson(k, n)
        print(f"{f'{s}개':>24}{n:>7}{k:>7}{k/n*100:>7.0f}%{d.loc[m,'n_case'].mean():>10.2f}"
              f"{f'[{lo:.0f}-{hi:.0f}]':>13}")

    out = "results/clean20_day_profile.csv"
    d.to_csv(out, encoding="utf-8-sig")
    print(f"\n원본: {out}")


def demo() -> None:
    """AUC 방향 - 나온 날이 크면 0.5 초과여야 한다."""
    hit, miss = pd.Series([5.0, 6, 7]), pd.Series([1.0, 2, 3])
    assert auc(hit, miss) == 1.0
    assert auc(miss, hit) == 0.0
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
