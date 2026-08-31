"""60선 위 효과는 독립적인 신호인가, 아침 강세의 대리변수인가.

    python why60_probe.py

"코스피가 15분 60선 위면 클린20이 더 나온다"(54% vs 37%)는 결과가 나왔지만,
60선 위라는 건 결국 "최근 2~3일 대비 지금 지수가 높다"는 뜻이라 오늘 아침 지수가
올랐다는 사실과 거의 같은 말일 수 있다. 그렇다면 새 신호가 아니라 이미 보고 있는
것(코스피 10시 등락률, top10 최고 등락률)의 대리변수다.

세 단계로 벗겨본다.
  [1] 60선 위/아래와 코스피 당일 등락률이 얼마나 겹치나
  [2] 코스피 등락률을 층으로 고정하고도 60선 효과가 남나
  [3] top10 최고 등락률까지 고정하면 남는 게 있나
"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import wilson
from clean20_day_filter import day_table
from noday_regime import DIRTY_FROM, regimes


def frame() -> pd.DataFrame:
    d = day_table().join(regimes())
    d = d[d.index < DIRTY_FROM].dropna(subset=["pos", "trend"])
    d["above"] = d["pos"] == "위"
    return d


def cell(g: pd.DataFrame) -> str:
    if len(g) < 8:
        return f"{len(g):>3}일  표본부족"
    k, n = int(g["hit"].sum()), len(g)
    lo, hi = wilson(k, n)
    return f"{n:>3}일  {k/n*100:>3.0f}%  [{lo:.0f}-{hi:.0f}]"


def main() -> None:
    d = frame()
    base = d["hit"].mean()
    print("=" * 78)
    print(f"60선 효과의 정체  |  {len(d)}거래일 · 기준선 {base*100:.0f}%")
    print("=" * 78)

    print("\n[1] 60선 위/아래는 그날 코스피 등락률과 얼마나 겹치나")
    print(f"{'':>10}{'일수':>6}{'코스피 10시 등락률 중앙':>24}{'플러스 마감 비율':>18}")
    for lab, m in [("60선 위", d["above"]), ("60선 아래", ~d["above"])]:
        g = d[m]
        print(f"{lab:>10}{len(g):>6}{g['코스피_ret10'].median():>23.2f}%"
              f"{(g['코스피_ret10'] > 0).mean()*100:>17.0f}%")
    r = d["above"].astype(float).corr(d["코스피_ret10"])
    print(f"\n  상관계수 {r:+.3f} — 60선 위 여부와 코스피 10시 등락률")

    print("\n[2] 코스피 10시 등락률을 고정하고 60선 효과가 남나")
    print(f"{'코스피 10시':>14}{'60선 위':>22}{'60선 아래':>22}")
    for lo_, hi_, lab in [(-99, -0.5, "-0.5% 미만"), (-0.5, 0.2, "-0.5~+0.2%"),
                          (0.2, 0.8, "+0.2~+0.8%"), (0.8, 99, "+0.8% 이상")]:
        s = d[(d["코스피_ret10"] >= lo_) & (d["코스피_ret10"] < hi_)]
        print(f"{lab:>14}{cell(s[s['above']]):>22}{cell(s[~s['above']]):>22}")

    print("\n[3] top10 최고 등락률까지 고정하면")
    print(f"{'최고 등락률':>14}{'60선 위':>22}{'60선 아래':>22}")
    for lo_, hi_, lab in [(0, 15, "15% 미만"), (15, 20, "15~20%"),
                          (20, 25, "20~25%"), (25, 99, "25% 이상")]:
        s = d[(d["max_ret10"] >= lo_) & (d["max_ret10"] < hi_)]
        print(f"{lab:>14}{cell(s[s['above']]):>22}{cell(s[~s['above']]):>22}")

    print("\n[4] 순서를 뒤집어 — 최고 등락률 효과는 60선을 고정해도 남나")
    print(f"{'60선':>10}{'최고등락 <20%':>22}{'최고등락 >=20%':>22}")
    for lab, m in [("위", d["above"]), ("아래", ~d["above"])]:
        s = d[m]
        print(f"{lab:>10}{cell(s[s['max_ret10'] < 20]):>22}{cell(s[s['max_ret10'] >= 20]):>22}")

    print("\n" + "-" * 78)
    print("한 줄 요약용 수치")
    print("-" * 78)
    for lab, m in [("60선 위", d["above"]), ("60선 아래", ~d["above"])]:
        g = d[m]
        print(f"{lab:>10} 단독: {g['hit'].mean()*100:.0f}%   "
              f"최고등락 20% 이상인 날만: {g[g['max_ret10'] >= 20]['hit'].mean()*100:.0f}%"
              f" ({len(g[g['max_ret10'] >= 20])}일)")


def demo() -> None:
    """층화 비교의 전제 - 층 안에서는 통제 변수가 실제로 비슷해야 한다."""
    d = pd.DataFrame({"x": [1.0, 1.1, 5.0, 5.2], "g": [True, False, True, False]})
    low = d[d["x"] < 3]
    assert abs(low[low["g"]]["x"].mean() - low[~low["g"]]["x"].mean()) < 0.3
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
