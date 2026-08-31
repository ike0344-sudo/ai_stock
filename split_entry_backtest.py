"""10:00 스캔 후보에 대한 분할매수 + 빠른 손절 백테스트.

중요: 모집단은 "+20% 간 종목"이 아니라 10:00 시점에 후보였던 전부다.
승자만 모아놓고 진입/청산을 짜면 실제로는 재현 불가능한 성과가 나온다.

후보 정의(전부 10:00에 확정되는 값):
  대금 top10, 10시 전 +20% 미도달, 시가갭 < 15%
  10시까지 눌림 <= 5%, 첫 5분 대금비중 <= 0.15, 10시 레인지 위치 >= 0.7
  (--rule4 를 주면 등락률 7%+ / 레인지 0.8+ / 대금 1.5배+ / 20일 신고가까지 요구)

체결 가정
  1차는 10:00 종가 시장가, 2·3차는 그 가격 기준 지정가(저가가 닿으면 체결).
  손절/익절은 해당 봉의 시가가 이미 지나쳤으면 시가로, 아니면 트리거가로 체결.
  15:20에 남은 물량은 종가 청산. 왕복 비용 COST_PCT.

수익률은 "아이디어 1건에 배정한 자본" 기준이다. 2·3차가 미체결이면 그만큼
현금으로 남았다고 보고 0% 수익으로 처리한다 — 실전 자금 배분과 같게 맞춘 것.
"""
import os
import sys
from itertools import product

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import load

MINUTE_DIR = "data/stocks/minute"
COST_PCT = 0.25          # 왕복 비용(세금+수수료+슬리피지)
ENTRY_MIN = 600          # 10:00
EXIT_MIN = 920           # 15:20 강제 청산
RULE4 = "--rule4" in sys.argv

# (이름, [(비중, 트리거%)]) — 트리거 0은 시장가, 음수는 1차가 대비 지정가
ENTRIES = [
    ("전량 10:00", [(1.00, 0.0)]),
    ("2분할 0/-1.5", [(0.50, 0.0), (0.50, -1.5)]),
    ("2분할 0/-3", [(0.50, 0.0), (0.50, -3.0)]),
    ("3분할 0/-1.5/-3", [(0.34, 0.0), (0.33, -1.5), (0.33, -3.0)]),
]
TRAILS = [2.0, 3.0, 4.0, 5.0, 7.0]
TP1 = [None, 5.0, 10.0]  # 절반 익절 지점(나머지는 트레일링)


def candidates() -> pd.DataFrame:
    b = load()
    live = b[(~b["already_20_by_10"]) & (b["open_gap_pct"] < 15)]
    m = ((live["max_dd_to_10_pct"] <= 5) & (live["first5_value_share"] <= 0.15)
         & (live["pos_in_range_10"] >= 0.7))
    if RULE4:
        m &= ((live["ret_at_10_pct"] >= 7) & (live["pos_in_range_10"] >= 0.8)
              & (live["value_vs_20d_avg"] >= 1.5) & (live["high_vs_20d_high_pct"] >= 0))
    return live[m]


def simulate(bars: pd.DataFrame, legs, trail: float, tp1: float | None) -> float | None:
    """10:00 이후 경로를 걸으며 분할 체결·손절·익절. 배정자본 대비 수익률(%)."""
    mins = bars.index.hour * 60 + bars.index.minute
    seg = bars[(mins >= ENTRY_MIN) & (mins <= EXIT_MIN)]
    if len(seg) < 5:
        return None
    o = seg["open"].to_numpy(); h = seg["high"].to_numpy()
    lo = seg["low"].to_numpy(); c = seg["close"].to_numpy()

    p0 = c[0]                       # 10:00 봉 종가 = 1차 진입가
    limits = [(w, p0 * (1 + t / 100)) for w, t in legs]
    filled = [False] * len(legs)
    qty = 0.0; cost = 0.0           # 체결 비중과 평균단가 누적
    qty += limits[0][0]; cost += limits[0][0] * p0; filled[0] = True
    peak = h[0]
    realized = 0.0                  # 확정 손익(비중 가중, %)
    tp_done = False

    for i in range(1, len(seg)):
        # 추가 분할 체결 — 저가가 지정가에 닿으면
        for k in range(1, len(legs)):
            if not filled[k] and lo[i] <= limits[k][1]:
                filled[k] = True
                qty += limits[k][0]
                cost += limits[k][0] * min(limits[k][1], o[i])
        avg = cost / qty
        peak = max(peak, h[i])

        stop = peak * (1 - trail / 100)
        if tp1 is not None and not tp_done and h[i] >= avg * (1 + tp1 / 100):
            px = max(avg * (1 + tp1 / 100), o[i])
            realized += qty / 2 * (px / avg - 1) * 100
            qty /= 2
            tp_done = True
        if lo[i] <= stop:                       # 트레일링 손절/익절 이탈
            px = min(stop, o[i])
            realized += qty * (px / avg - 1) * 100
            return realized - COST_PCT * (qty + (qty if tp_done else 0))

    avg = cost / qty if qty else p0
    realized += qty * (c[-1] / avg - 1) * 100   # 15:20 종가 청산
    return realized - COST_PCT


def run(cand: pd.DataFrame) -> dict:
    """(전략키) -> 케이스별 수익률 배열."""
    res = {(e[0], t, p): [] for e, t, p in product(ENTRIES, TRAILS, TP1)}
    dates = {}
    for i, (code, g) in enumerate(cand.groupby("stock_code"), 1):
        print(f"\r[{i}/{cand['stock_code'].nunique()}] {code}", end="", file=sys.stderr)
        path = os.path.join(MINUTE_DIR, f"{code}.csv")
        if not os.path.exists(path):
            continue
        minute = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        want = set(g["date"])
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in want:
                continue
            for (name, legs), tr, tp in product(ENTRIES, TRAILS, TP1):
                r = simulate(bars, legs, tr, tp)
                if r is not None:
                    res[(name, tr, tp)].append(r)
                    dates.setdefault((name, tr, tp), []).append(date)
    print(file=sys.stderr)
    return res, dates


def report(res: dict, dates: dict) -> None:
    rows = []
    for k, v in res.items():
        if len(v) < 30:
            continue
        a = np.array(v)
        rows.append({
            "진입": k[0], "트레일": k[1], "익절": k[2] or "-",
            "n": len(a), "승률": (a > 0).mean() * 100, "평균": a.mean(),
            "중앙": np.median(a), "합계": a.sum(),
            "평균익": a[a > 0].mean() if (a > 0).any() else 0,
            "평균손": a[a <= 0].mean() if (a <= 0).any() else 0,
            "최악": a.min(), "최고": a.max(),
        })
    df = pd.DataFrame(rows).sort_values("평균", ascending=False)

    print("=" * 104)
    print(f"분할매수 + 트레일링 손절 백테스트  (후보 {rows[0]['n']}건, "
          f"{'3배제+4조건' if RULE4 else '3배제'} 통과, 왕복비용 {COST_PCT}%)")
    print("=" * 104)
    print(f"{'진입':>16}{'트레일':>7}{'익절':>6}{'n':>6}{'승률':>8}{'평균':>8}{'중앙':>8}"
          f"{'평균익':>8}{'평균손':>8}{'최악':>8}{'누적':>9}")
    for _, r in df.head(18).iterrows():
        print(f"{r['진입']:>16}{r['트레일']:>6.0f}%{str(r['익절']):>6}{r['n']:>6}"
              f"{r['승률']:>7.1f}%{r['평균']:>7.2f}%{r['중앙']:>7.2f}%"
              f"{r['평균익']:>7.2f}%{r['평균손']:>7.2f}%{r['최악']:>7.1f}%{r['합계']:>8.0f}%")

    best = df.iloc[0]
    k = (best["진입"], best["트레일"], best["익절"] if best["익절"] != "-" else None)
    a = np.array(res[k]); d = pd.Series(dates[k])
    print("\n" + "-" * 104)
    print(f"최고 조합 상세: {k[0]} / 트레일 -{k[1]:.0f}% / 익절 {k[2] or '없음'}")
    print("-" * 104)
    q = pd.DataFrame({"r": a, "q": d.dt.to_period("Q")})
    print(f"{'분기':>9}{'n':>6}{'승률':>8}{'평균':>8}{'누적':>9}")
    for p, gg in q.groupby("q"):
        print(f"{str(p):>9}{len(gg):>6}{(gg['r'] > 0).mean() * 100:>7.1f}%"
              f"{gg['r'].mean():>7.2f}%{gg['r'].sum():>8.1f}%")
    eq = np.cumsum(a)
    print(f"\n누적 {eq[-1]:.0f}%  최대 자본곡선 낙폭 {(np.maximum.accumulate(eq) - eq).max():.1f}%p"
          f"  손익비 {abs(a[a > 0].mean() / a[a <= 0].mean()):.2f}"
          f"  기대값 {a.mean():.2f}%/건")


def demo() -> None:
    """체결·손절 로직 자체검증."""
    idx = pd.date_range("2026-01-02 10:00", periods=6, freq="1min")
    # 10:00 종가 100 -> 98.5 터치(2차 체결) -> 110 상승 -> 트레일 -5%에 걸려 104.5 청산
    bars = pd.DataFrame(
        {"open": [100, 99, 100, 105, 110, 105], "high": [101, 100, 103, 108, 110, 106],
         "low": [99, 98.4, 99, 104, 108, 100], "close": [100, 99, 102, 107, 109, 101]}, idx)
    r = simulate(bars, [(0.5, 0.0), (0.5, -1.5)], 5.0, None)
    assert r is not None and -3 < r < 8, r
    # 손절만 있고 못 오르는 경우 손실이어야 한다
    down = bars.copy()
    down[["open", "high", "low", "close"]] = [[100, 101, 99, 100], [99, 99, 90, 91],
                                              [91, 92, 88, 89], [89, 90, 85, 86],
                                              [86, 87, 84, 85], [85, 86, 83, 84]]
    assert simulate(down, [(1.0, 0.0)], 3.0, None) < -2
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    cand = candidates()
    print(f"후보 {len(cand)}건 ({cand['date'].nunique()}일, {len(cand)/cand['date'].nunique():.1f}건/일)",
          file=sys.stderr)
    res, dates = run(cand)
    report(res, dates)
