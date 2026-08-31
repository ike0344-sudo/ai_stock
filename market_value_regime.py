"""시장 거래대금 레짐(코스피/코스닥 조 단위)과 클린20 발생의 관계.

    python market_value_regime.py

사용자 제안 밴드
    코스피  <8조 위험 / 8~10조 평범 / 10조+ 좋음
    코스닥  <6조 위험 / 6~8조 평범 / 8조+ 좋음

당일 대금은 10:00에 모른다(룩어헤드) - 실제로 쓰려면 전일 대금이나 10시까지 누적을
써야 하므로 셋 다 나눠서 잰다.
"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import wilson
from clean20_day_filter import day_table
from kospi_value_burst import daily_value

BANDS = {"코스피": [(0, 8, "위험"), (8, 10, "평범"), (10, 1e9, "좋음")],
         "코스닥": [(0, 6, "위험"), (6, 8, "평범"), (8, 1e9, "좋음")]}
CODE = {"코스피": "001", "코스닥": "101"}


def table(d: pd.DataFrame, col: str, bands: list, title: str) -> None:
    base = d["hit"].mean()
    print(f"\n{title}")
    print(f"{'구간':>18}{'일수':>7}{'적중일':>8}{'비율':>8}{'배수':>7}{'케이스':>8}{'일당':>7}{'95%CI':>12}")
    for lo, hi, name in bands:
        m = (d[col] >= lo) & (d[col] < hi)
        n = int(m.sum())
        if n == 0:
            print(f"{f'{name} {lo:g}~{hi:g}조' if hi < 1e8 else f'{name} {lo:g}조+':>18}{0:>7}")
            continue
        k, c = int(d.loc[m, "hit"].sum()), int(d.loc[m, "n_case"].sum())
        a, b = wilson(k, n)
        tag = f"{name} {lo:g}~{hi:g}조" if hi < 1e8 else f"{name} {lo:g}조+"
        print(f"{tag:>18}{n:>7}{k:>8}{k/n*100:>7.0f}%{k/n/base:>6.2f}x{c:>8}{c/n:>7.2f}"
              f"{f'[{a:.0f}-{b:.0f}]':>12}")


def main() -> None:
    d = day_table()
    for name, code in CODE.items():
        v = daily_value(code)["value_mw"] / 1e6           # 백만원 -> 조원
        d[name] = d.index.map(v)
        d[f"{name}_전일"] = d.index.map(v.shift(1))

    print("=" * 78)
    print(f"시장 대금 레짐과 클린20  |  {len(d)}거래일 · 기준선 적중 {d['hit'].mean()*100:.0f}%"
          f" · 케이스 {int(d['n_case'].sum())}건")
    print("=" * 78)
    for name in CODE:
        q = d[name].quantile([0, .25, .5, .75, 1])
        print(f"{name} 일대금(조): 최소 {q[0]:.1f} / 25% {q[.25]:.1f} / 중앙 {q[.5]:.1f}"
              f" / 75% {q[.75]:.1f} / 최대 {q[1]:.1f}")

    print("\n" + "-" * 78)
    print("[1] 제안 밴드 그대로 (당일 대금 - 10:00엔 모르는 값, 참고용)")
    print("-" * 78)
    for name, bands in BANDS.items():
        table(d, name, bands, f"{name} 당일 대금")

    print("\n" + "-" * 78)
    print("[2] 같은 밴드를 전일 대금에 적용 (10:00에 실제로 아는 값)")
    print("-" * 78)
    for name, bands in BANDS.items():
        table(d, f"{name}_전일", bands, f"{name} 전일 대금")

    print("\n" + "-" * 78)
    print("[3] 이 기간에 맞춰 재보정 - 3분위 컷")
    print("-" * 78)
    for name in CODE:
        t = d[name].quantile([1/3, 2/3])
        bands = [(0, t[1/3], "하위"), (t[1/3], t[2/3], "중간"), (t[2/3], 1e9, "상위")]
        table(d, name, bands, f"{name} 당일 대금 3분위")
        t2 = d[f"{name}_전일"].quantile([1/3, 2/3])
        table(d, f"{name}_전일", [(0, t2[1/3], "하위"), (t2[1/3], t2[2/3], "중간"),
                                 (t2[2/3], 1e9, "상위")], f"{name} 전일 대금 3분위")

    out = "results/market_value_regime.csv"
    d.to_csv(out, encoding="utf-8-sig")
    print(f"\n원본: {out}")


def demo() -> None:
    """밴드 경계가 [lo, hi)로 겹치지 않는지 - 8조가 '위험'과 '평범' 양쪽에 들면 합이 틀어진다."""
    d = pd.DataFrame({"코스피": [7.9, 8.0, 9.9, 10.0], "hit": [True] * 4, "n_case": [1] * 4})
    counts = [int(((d["코스피"] >= lo) & (d["코스피"] < hi)).sum()) for lo, hi, _ in BANDS["코스피"]]
    assert counts == [1, 2, 1], counts
    assert sum(counts) == len(d)
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
