"""거르면 되는 종목 — 배제 규칙별 효과 측정.

지금까지 분석에서 "이런 종목은 -5%를 깨더라" 로 나온 신호들을 배제 규칙으로 바꾸고,
규칙마다 두 가지를 잰다.
  버리는 양 : 얼마나 많은 케이스가 걸러지나
  버리는 값 : 그중 진짜 좋은 케이스(클린 20)를 얼마나 같이 버리나

좋은 배제 규칙 = 많이 버리면서 클린은 거의 안 버리는 것.
"""
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import load, wilson
from preday_traits import OUT as PRE_OUT

MAX_DD = 5.0


def rules(df: pd.DataFrame) -> dict[str, pd.Series]:
    """True = 배제 대상. 전부 10:00 시점에 확정되는 값."""
    return {
        "10시까지 눌림 > 5%": df["max_dd_to_10_pct"] > 5,
        "첫 5분 대금비중 > 0.15": df["first5_value_share"] > 0.15,
        "10시 레인지 위치 < 0.7": df["pos_in_range_10"] < 0.7,
        "대금 > 20일평균 3배": df["value_vs_20d_avg"] > 3,
        "시가 갭 < -1%": df["open_gap_pct"] < -1,
        "전날 MA20 이격 > 25%": df["dev_ma20"] > 25,
        "전날 5일 수익률 > 20%": df["ret_5d"] > 20,
        "전일 등락률 > 8%": df["ret_1d"] > 8,
    }


def report(df: pd.DataFrame, label: str) -> None:
    n, k = len(df), int(df["target"].sum())
    base = k / n * 100
    print("\n" + "=" * 96)
    print(f"[{label}]  {n:,}건 중 클린20 {k}건 = {base:.2f}%")
    print("=" * 96)
    print(f"{'배제 규칙':>24}{'버림':>8}{'버림%':>8}{'클린손실':>9}{'손실%':>8}"
          f"{'남은 클린률':>11}{'개선':>8}")
    r = rules(df)
    for name, m in r.items():
        drop, lost = int(m.sum()), int(df.loc[m, "target"].sum())
        keep = df[~m]
        rate = keep["target"].mean() * 100 if len(keep) else 0
        print(f"{name:>24}{drop:>8}{drop/n*100:>7.0f}%{lost:>9}{lost/max(k,1)*100:>7.0f}%"
              f"{rate:>10.2f}%{rate/base:>7.2f}x")

    print("\n누적 적용 (위에서부터 순서대로 다 거른다)")
    keep = pd.Series(True, index=df.index)
    for name, m in r.items():
        keep &= ~m
        kk, tot = int(df.loc[keep, "target"].sum()), int(keep.sum())
        if tot == 0:
            break
        lo, hi = wilson(kk, tot)
        print(f"{('  - ' + name):>28} -> 남은 {tot:>5}건  클린 {kk:>3}건  "
              f"{kk/tot*100:>5.2f}% ({kk/tot*100/base:.2f}x)  95%CI [{lo:.1f}-{hi:.1f}]")
    print(f"\n  최종: 클린 {int(df['target'].sum())}건 중 {int(df.loc[keep,'target'].sum())}건 보존"
          f" ({df.loc[keep,'target'].sum()/max(k,1)*100:.0f}%), 후보는 {n:,} -> {int(keep.sum()):,}건으로 축소")


def main() -> None:
    base = load()
    base["target"] = (base["reached"] & (base["max_dd_pct"] <= MAX_DD)
                      & (base["minutes_to_20"] > 3))
    pre = pd.read_csv(PRE_OUT, parse_dates=["date"], dtype={"stock_code": str})
    df = base.merge(pre[["date", "stock_code", "dev_ma20", "ret_5d", "ret_1d"]],
                    on=["date", "stock_code"], how="inner", suffixes=("", "_pre"))

    report(df[~df["already_20_by_10"]], "10시 판단 대상 — 아직 +20% 안 간 종목")
    report(df[df["reached"]], "+20% 도달이 확정된 케이스만 — 흔들릴 놈 골라내기")


def demo() -> None:
    """규칙이 전부 '배제=True' 방향인지 확인 — 부호 뒤집히면 결과가 정반대가 된다."""
    df = pd.DataFrame({
        "max_dd_to_10_pct": [3.0, 9.0], "first5_value_share": [0.1, 0.3],
        "pos_in_range_10": [0.9, 0.4], "value_vs_20d_avg": [2.0, 5.0],
        "open_gap_pct": [2.0, -4.0], "dev_ma20": [5.0, 40.0],
        "ret_5d": [3.0, 30.0], "ret_1d": [1.0, 12.0],
    })
    for name, m in rules(df).items():
        assert m.tolist() == [False, True], (name, m.tolist())
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    main()
