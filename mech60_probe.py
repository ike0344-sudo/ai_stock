"""60선 위일 때 왜 잘 오르나 - 시장 메커니즘 가설별 증거 찾기.

    python mech60_probe.py

실제 프로그램매매/알고리즘 로직은 OHLCV로 볼 수 없다. 대신 각 가설이 참이라면
데이터에 남아야 할 흔적을 찾는다.

  H1 유동성 유입   : 지수 강세면 시장 전체 대금이 는다 -> 코스피/코스닥 일대금
  H2 위험선호 회전 : 돈이 소형·저가주로 내려간다 -> top10 주가, 코스닥 비중
  H3 브레드스 확대 : 대장 하나가 아니라 여럿이 같이 간다 -> +7% 종목 수, 업종 수
  H4 자기실현     : 이평 기준 시스템 매매가 몰린다 -> 60선 돌파 직후 대금 급증
  H5 종목 자금집중 : 개별 종목에 평소 대비 더 몰린다 -> 대금/20일평균
"""
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import auc, load
from clean20_day_filter import day_table
from kospi_value_burst import daily_value
from noday_regime import DIRTY_FROM, regimes


def frame() -> pd.DataFrame:
    d = day_table().join(regimes())
    d = d[d.index < DIRTY_FROM].dropna(subset=["pos"])
    d["above"] = d["pos"] == "위"

    f = load()
    f = f[f["date"] < DIRTY_FROM]
    g = f.groupby("date")
    d["price_med"] = d.index.map(g["price_log"].median().map(lambda v: 10 ** v / 1e4))
    d["val_ratio_med"] = d.index.map(g["value_vs_20d_avg"].median())
    d["top20_value"] = d.index.map(g["cum_value_eok"].sum())
    d["n_up3"] = d.index.map(f.assign(u=f["ret_at_10_pct"] >= 3).groupby("date")["u"].sum())
    for code, name in [("001", "코스피대금"), ("101", "코스닥대금")]:
        d[name] = d.index.map(daily_value(code)["value_mw"] / 1e6)
    d["코스닥비중"] = d["코스닥대금"] / (d["코스닥대금"] + d["코스피대금"]) * 100
    return d


ROWS = [
    ("H1 유동성", "코스피대금", "코스피 일대금(조)"),
    ("H1 유동성", "코스닥대금", "코스닥 일대금(조)"),
    ("H1 유동성", "top20_value", "top20 10시 대금(억)"),
    ("H2 위험선호", "코스닥비중", "코스닥 대금 비중(%)"),
    ("H2 위험선호", "price_med", "top10 주가 중앙(만원)"),
    ("H3 브레드스", "n_ret7", "10시 +7% 종목 수"),
    ("H3 브레드스", "n_up3", "10시 +3% 종목 수"),
    ("H3 브레드스", "n_high20", "20일신고가 종목 수"),
    ("H3 브레드스", "max_ret10", "top10 최고 등락률(%)"),
    ("H5 종목집중", "val_ratio_med", "대금/20일평균 중앙"),
    ("H5 종목집중", "res_share", "대형주 대금 비중"),
]


def main() -> None:
    d = frame()
    up, dn = d[d["above"]], d[~d["above"]]
    print("=" * 80)
    print(f"60선 위 {len(up)}일 vs 아래 {len(dn)}일 — 어떤 메커니즘의 흔적이 있나")
    print("=" * 80)
    print(f"{'가설':>12}{'지표':>22}{'60선 위':>11}{'60선 아래':>11}{'배수':>8}{'AUC':>8}")
    last = None
    for hyp, col, name in ROWS:
        if col not in d:
            continue
        a, b = up[col].median(), dn[col].median()
        if hyp != last:
            print()
            last = hyp
        print(f"{hyp:>12}{name:>22}{a:>11.2f}{b:>11.2f}{a/b if b else float('nan'):>8.2f}x"
              f"{auc(up[col], dn[col]):>8.3f}")

    print("\n" + "-" * 80)
    print("H4 자기실현 — 60선을 갓 넘은 날 vs 계속 위였던 날")
    print("-" * 80)
    # 어제는 아래였는데 오늘 위 = 갓 돌파. 시스템 매매가 몰린다면 여기서 대금이 튄다.
    prev = d["above"].shift(1)
    fresh = d[(d["above"]) & (prev == False)]
    kept = d[(d["above"]) & (prev == True)]
    print(f"{'':>16}{'일수':>7}{'적중':>8}{'코스피대금(조)':>15}{'top20대금(억)':>15}{'+7%종목':>9}")
    for lab, g in [("갓 돌파", fresh), ("계속 위", kept), ("계속 아래", d[(~d["above"]) & (prev == False)])]:
        if len(g) < 5:
            continue
        print(f"{lab:>16}{len(g):>7}{g['hit'].mean()*100:>7.0f}%{g['코스피대금'].median():>15.1f}"
              f"{g['top20_value'].median():>15.0f}{g['n_ret7'].median():>9.1f}")

    print("\n" + "-" * 80)
    print("대장 하나만 가나, 여럿이 가나 (최고 등락률 20% 이상인 날만)")
    print("-" * 80)
    s = d[d["max_ret10"] >= 20]
    print(f"{'':>12}{'일수':>7}{'적중':>8}{'+7% 종목 수':>13}{'+3% 종목 수':>13}{'신고가 수':>11}")
    for lab, g in [("60선 위", s[s["above"]]), ("60선 아래", s[~s["above"]])]:
        print(f"{lab:>12}{len(g):>7}{g['hit'].mean()*100:>7.0f}%{g['n_ret7'].median():>13.1f}"
              f"{g['n_up3'].median():>13.1f}{g['n_high20'].median():>11.1f}")


def demo() -> None:
    """'갓 돌파' 판정은 어제 상태를 써야 한다 - 오늘만 보면 계속 위였던 날과 안 갈린다."""
    a = pd.Series([False, True, True, False, True])
    prev = a.shift(1)
    assert (a & (prev == False)).tolist() == [False, True, False, False, True]
    assert (a & (prev == True)).tolist() == [False, False, True, False, False]
    print("demo ok")


if __name__ == "__main__":
    demo() if "--demo" in sys.argv else main()
