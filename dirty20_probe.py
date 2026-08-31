"""갔지만 더럽게 간 케이스 — 손절폭을 넓히면 얼마를 더 잡고 얼마를 더 잃나.

    python dirty20_probe.py

지금까지는 낙폭 5% 이내(클린20)만 봤다. 하지만 +20%에 도달한 케이스의 상당수가
경로에서 5%를 깨고 갔다. 그 케이스들이
  (1) 10:00 시점에 클린과 구분되는가 — 구분되면 미리 피할 수 있다
  (2) 손절을 넓혀서 잡을 값어치가 있는가 — 넓힌 손절은 실패한 날에도 그대로 적용된다
를 본다. (2)는 도달한 케이스만 보면 항상 "넓힐수록 좋다"가 나오므로, 실제 손익은
pullback_ladder_backtest의 트레일 스윕(모집단 전체)으로 확인한다.

수집이 밀린 2026-07-20 이후는 제외한다.
"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import auc, load, wilson
from clean20_list import day_close_ret

DIRTY_FROM = pd.Timestamp("2026-07-20")
MAX_GAP = 15.0
FEATURES = [
    ("ret_at_10_pct", "10시 등락률(%)"),
    ("max_dd_to_10_pct", "10시까지 눌림(%)"),
    ("pos_in_range_10", "10시 레인지 위치"),
    ("upper_wick_ratio", "10시 윗꼬리 비율"),
    ("first5_value_share", "첫 5분 대금비중"),
    ("value_vs_20d_avg", "대금/20일평균"),
    ("open_gap_pct", "시가갭(%)"),
    ("high_vs_20d_high_pct", "10시고가/20일고가(%)"),
    ("atr20_pct", "20일 ATR(%)"),
    ("d5_ret_pct", "최근 5일 수익률(%)"),
    ("price_log", "주가(log10)"),
]


def frame() -> pd.DataFrame:
    df = load()
    df = df[(df["date"] < DIRTY_FROM) & df["reached"] & (df["open_gap_pct"] < MAX_GAP)]
    # 갭으로 09:03 이내 직행한 건은 경로가 없어 손절 논의 대상이 아니다
    df = df[df["minutes_to_20"] > 3].copy()
    # close_ret_pct는 select()에서만 붙는다 - 여기선 모집단이 달라서 직접 계산한다
    df["close_ret_pct"] = day_close_ret(df)
    return df


def main() -> None:
    d = frame()
    clean, dirty = d[d["max_dd_pct"] <= 5], d[d["max_dd_pct"] > 5]
    print("=" * 76)
    print(f"+20% 도달 {len(d)}건 (갭 직행 제외)  |  낙폭 5% 이내 {len(clean)} · 초과 {len(dirty)}")
    print("=" * 76)

    print("\n[1] 손절폭을 넓히면 얼마나 더 잡히나")
    print(f"{'손절폭':>8}{'커버 건수':>10}{'비율':>8}{'추가 확보':>10}{'종가 +20% 지킴':>15}")
    prev = 0
    for stop in (3, 4, 5, 6, 7, 8, 10, 99):
        g = d[d["max_dd_pct"] <= stop]
        held = (g["close_ret_pct"] >= 20).mean() * 100 if len(g) else 0
        lab = "제한없음" if stop == 99 else f"{stop}%"
        print(f"{lab:>8}{len(g):>10}{len(g)/len(d)*100:>7.0f}%{len(g)-prev:>10}{held:>14.0f}%")
        prev = len(g)

    print("\n  ↑ 넓힐수록 커버가 느는 건 당연하다(도달한 케이스만 본 표).")
    print("    실제 손익은 못 간 날에도 같은 손절이 적용되므로 아래 [3]을 봐야 한다.")

    print("\n[2] 10:00에 클린과 더러움이 구분되나")
    print(f"{'지표':>20}{'AUC':>8}{'클린 중앙':>11}{'더러움 중앙':>12}")
    rows = sorted(((abs(auc(clean[c], dirty[c]) - 0.5), auc(clean[c], dirty[c]), c, n)
                   for c, n in FEATURES), reverse=True)
    for _, a, col, name in rows:
        star = " ***" if abs(a - 0.5) >= 0.10 else (" *" if abs(a - 0.5) >= 0.05 else "")
        print(f"{name:>20}{a:>8.3f}{clean[col].median():>11.2f}{dirty[col].median():>12.2f}{star}")

    print("\n  AUC>0.5 = 클린이 더 큰 값 · *** 편차 0.10 이상 / * 0.05 이상")

    print("\n[3] 5~7% 구간(손절을 넓혀야 잡히는 케이스)은 어떤 놈들인가")
    band = d[(d["max_dd_pct"] > 5) & (d["max_dd_pct"] <= 7)]
    print(f"{'':>20}{'클린(≤5%)':>12}{'5~7%':>10}{'7% 초과':>10}")
    deep = d[d["max_dd_pct"] > 7]
    for col, name in [("close_ret_pct", "종가(%)"), ("minutes_to_20", "+20%까지(분)"),
                      ("ret_at_10_pct", "10시 등락률(%)"), ("max_dd_to_10_pct", "10시까지 눌림(%)"),
                      ("pos_in_range_10", "10시 레인지 위치"), ("n_ep_ge3", "3% 이상 조정 횟수")]:
        if col not in d:
            continue
        print(f"{name:>20}{clean[col].median():>12.2f}{band[col].median():>10.2f}{deep[col].median():>10.2f}")
    for label, g in [("클린(≤5%)", clean), ("5~7%", band), ("7% 초과", deep)]:
        k, n = int((g["close_ret_pct"] >= 20).sum()), len(g)
        lo, hi = wilson(k, n)
        print(f"{('  ' + label + ' 종가 +20% 지킴'):>28}{f'{k}/{n} {k/n*100:.0f}%':>12}  95%CI[{lo:.0f}-{hi:.0f}]")

    print("\n[4] 10시 이후 도달분만 — 실제로 살 수 있었던 자리")
    late = d[d["t20_time"] > "10:00"]
    lc, ld = late[late["max_dd_pct"] <= 5], late[late["max_dd_pct"] > 5]
    print(f"10시 이후 도달 {len(late)}건 중 클린 {len(lc)} · 더러움 {len(ld)}")
    print(f"{'지표':>20}{'AUC':>8}{'클린':>10}{'더러움':>10}")
    for _, a, col, name in sorted(
            ((abs(auc(lc[c], ld[c]) - 0.5), auc(lc[c], ld[c]), c, n) for c, n in FEATURES),
            reverse=True)[:5]:
        print(f"{name:>20}{a:>8.3f}{lc[col].median():>10.2f}{ld[col].median():>10.2f}")


def demo() -> None:
    """손절폭 커버는 단조 증가해야 한다 - 넓힌 손절이 좁은 손절보다 적게 잡으면 계산이 틀린 것."""
    d = pd.DataFrame({"max_dd_pct": [2.0, 4.5, 6.0, 9.0]})
    counts = [int((d["max_dd_pct"] <= s).sum()) for s in (3, 5, 7, 99)]
    assert counts == [1, 2, 3, 4], counts
    assert counts == sorted(counts)
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
