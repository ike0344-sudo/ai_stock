"""아직 안 본 각도 세 개 - 시간축·아깝게 놓친 날·종목 재등장.

    python edge_probe.py

지금까지는 전부 "그날 안에서" 봤다(10시 지표, 지수 국면). 여기서는 축을 바꾼다.
  [A] 어제와 오늘 - 케이스는 뭉쳐 다니나, 흩어져 있나
  [B] 아깝게 놓친 날 - +15~20%에서 멈춘 날과 +20%를 넘긴 날은 뭐가 달랐나
  [C] 종목의 재등장 - 한 번 클린20을 낸 종목은 얼마 만에 또 내나

수집이 밀린 2026-07-20 이후는 순위가 가짜라 통째로 뺀다.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import load, wilson
from clean20_list import select

DIRTY_FROM = pd.Timestamp("2026-07-20")
DAILY_DIR = "data/stocks/daily"


def day_hits() -> pd.DataFrame:
    """거래일별 케이스 발생 여부 + 그날 top10이 실제로 최고 몇 %까지 갔나."""
    f = load()
    f = f[f["date"] < DIRTY_FROM]
    cases, _ = select(dd=5.0, max_gap=15.0)
    hit_days = set(cases[cases["date"] < DIRTY_FROM]["date"])

    # 그날 top10의 당일 최고 상승률(전일종가 대비) - 일봉에서 직접
    peak = {}
    for code, g in f.groupby("stock_code"):
        path = os.path.join(DAILY_DIR, f"{code}.csv")
        if not os.path.exists(path):
            continue
        d = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        pc = d["close"].shift(1)
        ret = (d["high"] / pc - 1) * 100
        for dt in g["date"]:
            v = ret.get(dt)
            if v is not None and not pd.isna(v):
                peak[dt] = max(peak.get(dt, -99), float(v))

    days = sorted(f["date"].unique())
    return pd.DataFrame({
        "hit": [d in hit_days for d in days],
        "day_peak": [peak.get(d, np.nan) for d in days],
    }, index=pd.DatetimeIndex(days))


def probe_a(d: pd.DataFrame) -> None:
    print("=" * 74)
    print("[A] 케이스는 뭉쳐 다니나 — 어제 결과가 오늘을 예고하나")
    print("=" * 74)
    prev = d["hit"].shift(1)
    base = d["hit"].mean()
    print(f"{'어제':>16}{'일수':>7}{'오늘 적중':>11}{'배수':>8}{'95%CI':>12}")
    for label, m in [("나왔음", prev == True), ("공쳤음", prev == False)]:
        g = d[m.fillna(False)]
        k, n = int(g["hit"].sum()), len(g)
        lo, hi = wilson(k, n)
        print(f"{label:>16}{n:>7}{f'{k}/{n} {k/n*100:.0f}%':>11}{k/n/base:>8.2f}x{f'[{lo:.0f}-{hi:.0f}]':>12}")

    # 연속 공친 일수별 - 오래 굶었으면 반등하나(평균회귀), 더 굶나(관성)
    streak, out = 0, []
    for v in d["hit"]:
        out.append(streak)
        streak = 0 if v else streak + 1
    d = d.assign(dry=out)
    print(f"\n{'직전 연속 공친 일수':>18}{'일수':>7}{'적중':>10}{'95%CI':>12}")
    for lo_, hi_, lab in [(0, 1, "0일(어제 나옴)"), (1, 2, "1일"), (2, 3, "2일"), (3, 99, "3일 이상")]:
        g = d[(d["dry"] >= lo_) & (d["dry"] < hi_)]
        if len(g) < 5:
            continue
        k, n = int(g["hit"].sum()), len(g)
        a, b = wilson(k, n)
        print(f"{lab:>18}{n:>7}{f'{k/n*100:.0f}%':>10}{f'[{a:.0f}-{b:.0f}]':>12}")

    # 실제 뭉침이 무작위보다 심한가 - 같은 적중률로 섞었을 때의 최장 연속과 비교
    rng = np.random.default_rng(0)
    obs = max((len(s) for s in "".join("H" if v else "." for v in d["hit"]).split(".")), default=0)
    sim = [max((len(s) for s in "".join("H" if v else "." for v in rng.permutation(d["hit"].values)).split(".")), default=0)
           for _ in range(2000)]
    print(f"\n최장 연속 적중: 실제 {obs}일 · 무작위 섞기 중앙 {int(np.median(sim))}일 "
          f"(실제가 더 긴 경우 {np.mean([obs > s for s in sim])*100:.0f}%)")


def probe_b(d: pd.DataFrame) -> None:
    print("\n" + "=" * 74)
    print("[B] 아깝게 놓친 날 — 그날 최고가 +15~20%에서 멈춘 날")
    print("=" * 74)
    near = d[(d["day_peak"] >= 15) & (d["day_peak"] < 20)]
    over = d[d["day_peak"] >= 20]
    under = d[d["day_peak"] < 15]
    print(f"{'그날 최고 상승률':>18}{'일수':>7}{'클린20 나옴':>13}")
    for lab, g in [("15% 미만", under), ("15~20% (아깝다)", near), ("20% 이상", over)]:
        if len(g) == 0:
            continue
        print(f"{lab:>18}{len(g):>7}{f'{int(g.hit.sum())}/{len(g)} {g.hit.mean()*100:.0f}%':>13}")

    print(f"\n20% 넘긴 날 {len(over)}일 중 클린20이 안 나온 날 {int((~over['hit']).sum())}일"
          f" ({(~over['hit']).mean()*100:.0f}%) — 갔는데 경로가 지저분했거나 갭이 컸던 날")


def probe_c() -> None:
    print("\n" + "=" * 74)
    print("[C] 종목의 재등장 — 한 번 낸 종목은 얼마 만에 또 내나")
    print("=" * 74)
    cases, _ = select(dd=5.0, max_gap=15.0)
    cases = cases[cases["date"] < DIRTY_FROM].sort_values(["stock_code", "date"])
    gaps = cases.groupby("stock_code")["date"].diff().dt.days.dropna()
    n_stock = cases["stock_code"].nunique()
    print(f"케이스 {len(cases)}건 · 종목 {n_stock}개 · 재등장 {len(gaps)}회")
    if len(gaps):
        q = gaps.quantile([0.25, 0.5, 0.75])
        print(f"재등장 간격(일): 중앙 {q[0.5]:.0f} · 25~75% {q[0.25]:.0f}~{q[0.75]:.0f} · 최소 {gaps.min():.0f}")
        for lim in (7, 14, 30):
            print(f"  {lim}일 이내 재등장: {int((gaps <= lim).sum())}회 ({(gaps <= lim).mean()*100:.0f}%)")
    print("\n반복 등장 상위")
    for name, c in cases["name"].value_counts().head(6).items():
        g = cases[cases["name"] == name]
        print(f"{name:>14}{c:>4}회   종가 중앙 {g['close_ret_pct'].median():>5.1f}%"
              f"   낙폭 중앙 {g['max_dd_pct'].median():.2f}%")
    once = cases["stock_code"].value_counts()
    print(f"\n한 번만 나온 종목 {int((once == 1).sum())}개 / 두 번 이상 {int((once >= 2).sum())}개")
    multi = cases[cases["stock_code"].isin(once[once >= 2].index)]
    solo = cases[cases["stock_code"].isin(once[once == 1].index)]
    print(f"  두 번 이상 종목의 종가 중앙 {multi['close_ret_pct'].median():.1f}%"
          f" vs 한 번만 {solo['close_ret_pct'].median():.1f}%")


def main() -> None:
    d = day_hits()
    print(f"대상 {len(d)}거래일 ({d.index.min().date()} ~ {d.index.max().date()})\n")
    probe_a(d)
    probe_b(d)
    probe_c()


def demo() -> None:
    """연속 공친 일수 계산 - 오늘 값은 '어제까지'의 연속이어야 한다(오늘 결과를 쓰면 룩어헤드)."""
    hits = [True, False, False, True, False]
    streak, out = 0, []
    for v in hits:
        out.append(streak)
        streak = 0 if v else streak + 1
    assert out == [0, 0, 1, 2, 0], out
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
