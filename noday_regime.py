"""클린20이 하루도 안 나온 날의 국면 — 15분 60/120 배열 x 60선 위치.

    python noday_regime.py

지금까지 국면 분석은 전부 '나온 케이스' 쪽만 봤다(사후 분류). 여기서는 반대로
거래일 전체를 놓고 공친 날이 어떤 국면이었는지 본다. 판정은 10:00 이전에 닫힌
15분봉까지만 써서 룩어헤드가 없다 - 09:45봉이 마지막(09:59 확정).

2026-07-20 이후는 데이터 수집이 밀려 그날 대금 순위 자체가 가짜다(보유 종목이
45~95개까지 줄었다). 백필이 끝나기 전까지 이 구간은 통째로 뺀다.
"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import auc, wilson
from clean20_day_filter import day_table
from clean20_report import kospi_above_60
from ma_align_traits import align

CUT = pd.Timestamp("10:00").time()
DIRTY_FROM = "2026-07-20"      # 이 날부터 수집이 밀려 순위가 오염됐다


def regimes() -> pd.DataFrame:
    """하루 한 줄: 09:00~10:00의 60선 위치와 10:00 직전 배열."""
    ab = kospi_above_60().dropna()
    ab = ab[(ab.index.time < CUT) & (ab.index.time >= pd.Timestamp("09:00").time())]
    g = ab.groupby(ab.index.normalize())
    pos = g.mean().map(lambda v: "위" if v == 1 else ("아래" if v == 0 else "교차"))

    sp = align().dropna()
    sp = sp[sp.index.time < CUT]
    last = sp.groupby(sp.index.normalize()).last()
    return pd.DataFrame({"pos": pos, "spread": last,
                         "trend": last.map(lambda v: "정배열" if v > 0 else "역배열")}).dropna()


def rate(d: pd.DataFrame, mask: pd.Series, label: str, base: float) -> None:
    n = int(mask.sum())
    if n == 0:
        print(f"{label:>22}{0:>6}")
        return
    k = int(d.loc[mask, "hit"].sum())
    lo, hi = wilson(k, n)
    print(f"{label:>22}{n:>6}{k:>6}{k/n*100:>7.0f}%{k/n/base:>7.2f}x"
          f"{d.loc[mask, 'n_case'].mean():>9.2f}{f'[{lo:.0f}-{hi:.0f}]':>11}")


def main() -> None:
    d = day_table().join(regimes())
    d = d[d.index < DIRTY_FROM].dropna(subset=["pos", "trend"])
    base = d["hit"].mean()

    print("=" * 74)
    print(f"공친 날의 국면  |  {d.index.min().date()} ~ {d.index.max().date()} {len(d)}거래일")
    print(f"  케이스 나온 날 {int(d['hit'].sum())} · 공친 날 {int((~d['hit']).sum())} (기준선 {base*100:.0f}%)")
    print("=" * 74)

    print(f"\n{'구간':>22}{'일수':>6}{'적중':>6}{'비율':>8}{'배수':>7}{'케이스/일':>9}{'95%CI':>11}")
    for t in ("역배열", "정배열"):
        rate(d, d["trend"] == t, t, base)
    print()
    for p in ("아래", "교차", "위"):
        rate(d, d["pos"] == p, f"60선 {p}", base)
    print()
    for t in ("역배열", "정배열"):
        for p in ("아래", "교차", "위"):
            rate(d, (d["trend"] == t) & (d["pos"] == p), f"{t} + 60선 {p}", base)

    print("\n" + "-" * 74)
    print("공친 날 vs 나온 날 — 다른 지표들도 같이")
    print("-" * 74)
    hit, miss = d[d["hit"]], d[~d["hit"]]
    feats = [("spread", "60/120 이격(%)"), ("max_ret10", "top10 최고 등락률(%)"),
             ("n_ret7", "10시 +7% 종목 수"), ("n_high20", "20일신고가 종목 수"),
             ("res_share", "대형주 대금 비중"), ("코스피_ret10", "코스피 10시 등락률(%)"),
             ("코스닥_ret10", "코스닥 10시 등락률(%)")]
    print(f"{'지표':>22}{'AUC':>8}{'나온 날':>10}{'공친 날':>10}")
    for col, name in sorted(feats, key=lambda x: -abs(auc(hit[x[0]], miss[x[0]]) - 0.5)):
        a = auc(hit[col], miss[col])
        star = " ***" if abs(a - 0.5) >= 0.10 else (" *" if abs(a - 0.5) >= 0.05 else "")
        print(f"{name:>22}{a:>8.3f}{hit[col].median():>10.2f}{miss[col].median():>10.2f}{star}")

    print("\n" + "-" * 74)
    print("공친 날을 가장 많이 담는 조합 (공친 날 %d일 기준)" % int((~d["hit"]).sum()))
    print("-" * 74)
    print(f"{'조건':>30}{'해당일':>8}{'그중 공침':>10}{'공친날 점유':>12}")
    dead = int((~d["hit"]).sum())
    for label, m in {
        "역배열": d["trend"] == "역배열",
        "역배열 + 60선 아래": (d["trend"] == "역배열") & (d["pos"] == "아래"),
        "60선 아래": d["pos"] == "아래",
        "이격 < -1%": d["spread"] < -1,
        "역배열 & 최고등락 <15%": (d["trend"] == "역배열") & (d["max_ret10"] < 15),
        "최고등락 <10%": d["max_ret10"] < 10,
    }.items():
        n = int(m.sum())
        if n == 0:
            continue
        k = int((~d.loc[m, "hit"]).sum())
        print(f"{label:>30}{n:>8}{f'{k} ({k/n*100:.0f}%)':>10}{k/dead*100:>11.0f}%")


def demo() -> None:
    """60선 위치 판정 - 평균이 0/1이면 아래/위, 그 사이면 교차."""
    f = lambda v: "위" if v == 1 else ("아래" if v == 0 else "교차")
    assert [f(v) for v in (0.0, 0.25, 0.75, 1.0)] == ["아래", "교차", "교차", "위"]
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
