"""테마 안에서 여러 종목이 순환하는 날의 손익 — 사용자 관찰 검증.

    python theme_rotation.py

관찰: "테마가 여러 종목 순환할 때 상승하기 힘들다." 섹터 개수(rotation_days.py)와는
다른 이야기다. 그쪽은 강세가 여러 업종에 걸친 날을 봤고, 여기는 **한 업종 안에서**
대금이 여러 종목으로 갈라진 날을 본다.

지표는 10:00에 확정되는 것만 쓴다 — 같은 업종에서 대금 top10에 함께 올라온 동료 수.
"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rotation_days import trades
from theme_days import build

CROWD = 3   # 동료 이만큼 이상이면 "테마 내 순환"


def joined() -> pd.DataFrame:
    df = build()
    t = trades()
    t["date"] = pd.to_datetime(t["date"])
    return t.merge(df[["date", "stock_code", "sector", "peers", "peers_strong"]],
                   left_on=["date", "code"], right_on=["date", "stock_code"], how="left")


def line(label: str, g: pd.DataFrame) -> None:
    if not len(g):
        print(f"  {label:<26}{0:>5}")
        return
    print(f"  {label:<26}{len(g):>5}{g['ret'].mean():>9.2f}%"
          f"{(g['ret'] > 0).mean() * 100:>6.0f}%{g['ret'].sum():>8.0f}%")


def main() -> None:
    m = joined()
    print(f"{'조건':<28}{'건수':>5}{'평균손익':>9}{'승률':>7}{'합계':>8}")
    line("전체", m)
    for lo, hi, lab in [(0, 0, "동료 0 (혼자)"), (1, 1, "동료 1"), (2, 2, "동료 2"),
                        (CROWD, 99, f"동료 {CROWD}+ (순환)")]:
        line(lab, m[(m["peers"] >= lo) & (m["peers"] <= hi)])
    print()
    line(f"동료 {CROWD}+ 제외 후", m[m["peers"] < CROWD])

    print("\n연도별 — 제외가 실제로 도움이 됐나")
    m["y"] = m["date"].dt.year
    print(f"  {'연도':<6}{'전체건':>6}{'전체합계':>9}{'제외후건':>8}{'제외후합계':>11}")
    for y, g in m.groupby("y"):
        k = g[g["peers"] < CROWD]
        print(f"  {y:<6}{len(g):>6}{g['ret'].sum():>8.0f}%{len(k):>8}{k['ret'].sum():>10.0f}%")

    # 규칙으로 쓸 수 있는지는 총손익이 늘었느냐로 판단한다. 건수만 줄고 합계가 그대로면
    # "기댓값 0 구간"일 뿐 배제 규칙은 아니다.
    full, cut = m["ret"].sum(), m[m["peers"] < CROWD]["ret"].sum()
    print(f"\n총손익 {full:.0f}% → {cut:.0f}% ({cut - full:+.0f}%p) · "
          f"건수 {len(m)} → {(m['peers'] < CROWD).sum()}")


if __name__ == "__main__":
    main()
