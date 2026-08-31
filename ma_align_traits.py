"""코스피 15분봉 60선/120선 배열과 클린20의 관계.

    python ma_align_traits.py

정배열(60>120) / 역배열(60<120) / 혼재로 나눠 종목 성격과 결과를 비교한다.
120봉 = 15분 x 120 = 30시간 ≈ 4.6거래일이라 데이터 시작 직후 몇 건은 판정 불가다.
below60_traits.frame()을 그대로 재사용해 60선 위/아래 분류와 교차 비교도 같이 본다.
"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from below60_traits import FEATURES, frame
from clean20_conditions import auc, wilson

KOSPI = "data/index/minute/001.csv"


def align() -> pd.Series:
    """15분봉 기준 60선-120선 이격(%). 양수면 정배열. 장 사이는 버리고 거래시간 봉만 잇는다."""
    close = pd.read_csv(KOSPI, index_col=0, parse_dates=True).sort_index()["close"]
    k = close.resample("15min").last().dropna()
    ma60, ma120 = k.rolling(60).mean(), k.rolling(120).mean()
    return ((ma60 / ma120 - 1) * 100).where(ma120.notna())


def classify(c: pd.DataFrame) -> pd.DataFrame:
    g = align()
    state, spread = [], []
    for _, r in c.iterrows():
        w = g.loc[r["date"] + pd.Timedelta(hours=9):
                  f"{r['date']:%Y-%m-%d} {r['t20_time']}"].dropna()
        if len(w) == 0:
            state.append("판정불가"); spread.append(float("nan")); continue
        state.append("정배열" if (w > 0).all() else ("역배열" if (w < 0).all() else "혼재"))
        spread.append(w.mean())
    return c.assign(align=state, spread=spread)


def combo(c: pd.DataFrame) -> None:
    """두 축(배열 / 60선 위치)이 서로 얼마나 겹치는가, 조합별로 결과가 갈리는가."""
    import numpy as np

    # (1) 하루 단위 구조적 상관 - 케이스가 아니라 전 거래일에서 두 축이 같이 움직이나
    sp, ab = align().dropna(), _above60()
    d = pd.DataFrame({"sp": sp, "ab": ab}).dropna()
    key = d.index.normalize()
    day = pd.DataFrame({
        "정역": np.where(d["sp"].groupby(key).mean() > 0, "정배열", "역배열"),
        "위아래": np.where(d["ab"].groupby(key).mean() > 0.5, "60선 위", "60선 아래"),
    }, index=pd.Index(key.unique()))
    t = pd.crosstab(day["정역"], day["위아래"])
    exp = np.outer(t.sum(1), t.sum(0)) / t.values.sum()
    v = float(np.sqrt(((t.values - exp) ** 2 / exp).sum() / t.values.sum()))
    print(f"\n[전 거래일 {len(day)}일] 두 축의 구조적 상관  Cramer V = {v:.3f}")
    print(t.to_string())
    for al in t.index:
        print(f"  {al}일 중 60선 위 비율 {t.loc[al, '60선 위'] / t.loc[al].sum() * 100:.0f}%")

    # (2) 케이스 6칸 - 조합마다 결과가 다른가
    print(f"\n조합별 클린20 결과")
    print(f"{'배열':>8}{'60선':>8}{'건수':>6}{'+20% 지킴':>16}{'+10%':>7}{'종가':>8}{'소요':>7}{'주가':>9}")
    pos = c["x"].map(lambda x: "아래" if x == 0 else ("위" if x == 1 else "교차"))
    for al in ("역배열", "정배열"):
        for p in ("아래", "교차", "위"):
            g = c[(c["align"] == al) & (pos == p)]
            if len(g) == 0:
                continue
            k = int((g["close_ret_pct"] >= 20).sum())
            lo, hi = wilson(k, len(g))
            print(f"{al:>8}{p:>8}{len(g):>6}{f'{k/len(g)*100:.0f}% [{lo:.0f}-{hi:.0f}]':>16}"
                  f"{(g['close_ret_pct'] >= 10).mean()*100:>6.0f}%{g['close_ret_pct'].median():>7.1f}%"
                  f"{g['minutes_to_20'].median():>6.0f}분{10 ** g['price_log'].median()/1e4:>8.1f}만")


def _above60() -> pd.Series:
    from clean20_report import kospi_above_60
    return kospi_above_60().dropna().astype(float)


def line(label: str, r: pd.Series, base: int) -> None:
    print(f"{label:>10}{len(r):>6}{len(r)/base*100:>7.0f}%", end="")


def main() -> None:
    c = classify(frame())
    up, dn, mx = c[c["align"] == "정배열"], c[c["align"] == "역배열"], c[c["align"] == "혼재"]
    print("=" * 74)
    print(f"코스피 15분 60선/120선 배열별 클린20  |  전체 {len(c)}건")
    print(f"  정배열 {len(up)} · 역배열 {len(dn)} · 혼재 {len(mx)} · 판정불가 {int((c['align']=='판정불가').sum())}")
    print("=" * 74)

    print(f"\n{'지표':>20}{'AUC(역vs정)':>13}{'역배열':>10}{'혼재':>10}{'정배열':>10}")
    rows = sorted(((abs(auc(dn[col], up[col]) - 0.5), auc(dn[col], up[col]), col, name)
                   for col, name in FEATURES), reverse=True)
    for _, a, col, name in rows:
        star = " ***" if abs(a - 0.5) >= 0.15 else (" *" if abs(a - 0.5) >= 0.08 else "")
        print(f"{name:>20}{a:>13.3f}{dn[col].median():>10.2f}"
              f"{mx[col].median() if len(mx) else float('nan'):>10.2f}{up[col].median():>10.2f}{star}")
    print("\n  AUC>0.5 = 역배열 케이스가 더 큰 값 · *** 편차 0.15 이상 / * 0.08 이상")

    print(f"\n{'':>10}{'건수':>6}{'10시전 도달':>12}{'+20%까지':>10}{'+20% 지킴':>11}{'+10% 이상':>10}{'중앙 종가':>10}")
    for label, g in [("역배열", dn), ("혼재", mx), ("정배열", up)]:
        if len(g) == 0:
            continue
        k = int((g["close_ret_pct"] >= 20).sum())
        lo, hi = wilson(k, len(g))
        print(f"{label:>10}{len(g):>6}{(g['t20_time'] <= '10:00').mean()*100:>11.0f}%"
              f"{g['minutes_to_20'].median():>9.0f}분{f'{k/len(g)*100:.0f}% [{lo:.0f}-{hi:.0f}]':>16}"
              f"{(g['close_ret_pct'] >= 10).mean()*100:>9.0f}%{g['close_ret_pct'].median():>9.1f}%")

    print("\n60선 위치와 겹쳐보기 (건수)")
    pos = c["x"].map(lambda v: "아래" if v == 0 else ("위" if v == 1 else ("교차" if pd.notna(v) else "-")))
    t = pd.crosstab(c["align"], pos).reindex(index=["역배열", "혼재", "정배열", "판정불가"],
                                             columns=["아래", "교차", "위"], fill_value=0)
    print(f"{'':>10}{'60선 아래':>10}{'교차':>8}{'60선 위':>9}{'합':>6}")
    for name, r in t.iterrows():
        if r.sum() == 0:
            continue
        print(f"{name:>10}{int(r['아래']):>10}{int(r['교차']):>8}{int(r['위']):>9}{int(r.sum()):>6}")

    combo(c)

    print("\n이격(60/120, %) 5분위별 결과")
    q = pd.qcut(c["spread"].dropna(), 5, duplicates="drop")
    print(f"{'구간':>18}{'건수':>6}{'+20% 지킴':>11}{'+10%':>8}{'+20%까지':>10}{'주가(만원)':>11}")
    for b, g in c.dropna(subset=["spread"]).groupby(q, observed=True):
        print(f"{f'{b.left:+.2f} ~ {b.right:+.2f}':>18}{len(g):>6}"
              f"{(g['close_ret_pct'] >= 20).mean()*100:>10.0f}%{(g['close_ret_pct'] >= 10).mean()*100:>7.0f}%"
              f"{g['minutes_to_20'].median():>10.0f}{10 ** g['price_log'].median()/1e4:>11.1f}")


def demo() -> None:
    """정/역배열 판정 - 구간에 부호가 섞이면 혼재여야 한다."""
    f = lambda w: "정배열" if (w > 0).all() else ("역배열" if (w < 0).all() else "혼재")
    assert f(pd.Series([0.3, 0.1])) == "정배열"
    assert f(pd.Series([-0.3, -0.1])) == "역배열"
    assert f(pd.Series([0.3, -0.1])) == "혼재"
    assert f(pd.Series([0.0, 0.2])) == "혼재"      # 0은 어느 쪽도 아니다
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
