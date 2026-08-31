"""하루 안에서 익절 -> 재진입을 반복하는 사이클 매매.

앞선 백테스트는 전부 "하루 1회 진입, 트레일 걸리면 끝"이었다. 그래서 좁은 손절이
항상 나빴다 — 털리면 그날 끝이니까. 재진입이 가능하면 좁은 손절의 의미가 달라진다.

사이클 규칙
  FLAT  당일 고점 -dip% 지정가에 진입, 또는 당일 고점 +buf% 돌파에 진입(먼저 오는 쪽)
  LONG  진입 후 러닝 고점 대비 -trail% 이탈 시 전량 청산(익절이든 손절이든 동일)
        목표가(+target%)를 주면 거기서도 청산
  청산 후 다음 봉부터 다시 FLAT — 최대 max_cycles회까지 반복
  15:20 잔여 청산. --overnight 이면 익일 시가 청산.

비교 기준: 하루 1회 진입 + 트레일 -5% (기존 최적안).
"""
import os
import sys
from itertools import product

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pullback_ladder_backtest import COST_PCT, ENTRY_MIN, EXIT_MIN, candidates

CAPITAL = 60_000_000
OVERNIGHT = "--overnight" in sys.argv
DIPS = [1.0, 2.0]              # 눌림 진입 깊이
TRAILS = [1.5, 2.0, 3.0, 5.0]  # 사이클 트레일(익절 겸 손절)
TARGETS = [None, 5.0]          # 목표가 청산
CYCLES = [1, 2, 3, 99]         # 하루 최대 진입 횟수
BUF = 0.3                      # 돌파 확인폭


def run_day(bars: pd.DataFrame, dip: float, trail: float, target: float | None,
            max_cycles: int, nxt_open: float | None) -> tuple[float, int] | None:
    """하루치 수익률(%)과 진입 횟수. 자본은 매 사이클 전액 투입."""
    mins = bars.index.hour * 60 + bars.index.minute
    seg = bars[(mins >= ENTRY_MIN) & (mins <= EXIT_MIN)]
    if len(seg) < 5:
        return None
    o = seg["open"].to_numpy(); h = seg["high"].to_numpy()
    lo = seg["low"].to_numpy(); c = seg["close"].to_numpy()
    day_peak = max(float(bars[mins < ENTRY_MIN]["high"].max()), h[0])

    total = 0.0; cycles = 0
    entry = None; ep = 0.0          # 진입가, 진입 후 러닝 고점
    cooldown = -1

    for i in range(len(seg)):
        if entry is None:
            if cycles < max_cycles and i > cooldown:
                dip_trig = day_peak * (1 - dip / 100)
                bo_trig = day_peak * (1 + BUF / 100)
                if lo[i] <= dip_trig:                 # 눌림 체결
                    entry = min(dip_trig, o[i]); ep = h[i]; cycles += 1
                elif h[i] >= bo_trig:                 # 돌파 체결
                    entry = max(bo_trig, o[i]); ep = h[i]; cycles += 1
        else:
            ep = max(ep, h[i])
            stop = ep * (1 - trail / 100)
            hit_target = target is not None and h[i] >= entry * (1 + target / 100)
            if hit_target:
                px = max(entry * (1 + target / 100), o[i])
                total += (px / entry - 1) * 100 - COST_PCT
                entry = None; cooldown = i
            elif lo[i] <= stop:
                px = min(stop, o[i])
                total += (px / entry - 1) * 100 - COST_PCT
                entry = None; cooldown = i
        day_peak = max(day_peak, h[i])

    if entry is not None:
        last = nxt_open if (OVERNIGHT and nxt_open is not None and np.isfinite(nxt_open)) else c[-1]
        total += (last / entry - 1) * 100 - COST_PCT
    return (total, cycles)


def main() -> None:
    cand = candidates()
    grid = [(d, t, tg, mc) for d, t, tg, mc in product(DIPS, TRAILS, TARGETS, CYCLES)]
    print(f"후보 {len(cand)}건 × 조합 {len(grid)}개  (오버나이트 {'ON' if OVERNIGHT else 'OFF'})",
          file=sys.stderr)
    res = {k: [] for k in grid}
    cyc = {k: [] for k in grid}
    dates = []

    for i, (code, g) in enumerate(cand.groupby("stock_code"), 1):
        print(f"\r[{i}/{cand['stock_code'].nunique()}] {code}", end="", file=sys.stderr)
        mpath = os.path.join("data/stocks/minute", f"{code}.csv")
        dpath = os.path.join("data/stocks/daily", f"{code}.csv")
        if not (os.path.exists(mpath) and os.path.exists(dpath)):
            continue
        daily = pd.read_csv(dpath, index_col=0, parse_dates=True).sort_index()
        nxt = daily["open"].shift(-1)
        minute = pd.read_csv(mpath, index_col=0, parse_dates=True).sort_index()
        want = set(g["date"])
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in want:
                continue
            no = nxt.get(date, np.nan)
            first = True
            for k in grid:
                out = run_day(bars, k[0], k[1], k[2], k[3], float(no) if pd.notna(no) else None)
                if out is None:
                    break
                res[k].append(out[0]); cyc[k].append(out[1])
                if first:
                    dates.append(date); first = False
    print(file=sys.stderr)

    d = pd.Series(dates)
    n_month = d.dt.to_period("M").nunique()
    rows = []
    for k, v in res.items():
        a = np.array(v)
        if len(a) != len(d):
            continue
        per_day = pd.Series(a, index=d).groupby(level=0).mean()
        eq = np.cumsum(per_day.to_numpy())
        mdd = (np.maximum.accumulate(eq) - eq).max()
        m = per_day.groupby(per_day.index.to_period("M")).sum()
        rows.append({
            "눌림": k[0], "트레일": k[1], "목표": "-" if k[2] is None else f"+{k[2]:g}",
            "최대회": "무제한" if k[3] > 10 else k[3],
            "평균진입": np.mean(cyc[k]), "승률": (a > 0).mean() * 100, "기대값": a.mean(),
            "월평균": m.mean() * CAPITAL / 100 / 1e4, "MDD": mdd * CAPITAL / 100 / 1e4,
            "승월": (m > 0).sum(), "월수": len(m),
        })
    df = pd.DataFrame(rows)

    print("=" * 104)
    print(f"익절 후 재진입 사이클 매매  (후보 {len(d)}건, {n_month}개월, 자본 6,000만원, "
          f"오버나이트 {'ON' if OVERNIGHT else 'OFF'})")
    print("=" * 104)

    def show(title, dd):
        print(f"\n{title}")
        print(f"{'눌림':>6}{'트레일':>7}{'목표':>6}{'최대회':>7}{'평균진입':>9}{'승률':>8}"
              f"{'기대값':>9}{'월평균':>10}{'MDD':>10}{'승월':>8}")
        for _, r in dd.iterrows():
            print(f"{r['눌림']:>5.0f}%{r['트레일']:>6.1f}%{r['목표']:>6}{str(r['최대회']):>7}"
                  f"{r['평균진입']:>9.2f}{r['승률']:>7.1f}%{r['기대값']:>8.2f}%"
                  f"{r['월평균']:>8,.0f}만{r['MDD']:>8,.0f}만{r['승월']:>5}/{r['월수']:<2}")

    show("[월평균 상위 12]", df.sort_values("월평균", ascending=False).head(12))
    show("[1회 진입만 — 재진입 없음]", df[df["최대회"] == 1].sort_values("월평균", ascending=False))

    print("\n" + "-" * 104)
    print("최대 진입 횟수별 평균 (다른 조건 평균 처리) — 재진입이 실제로 값을 만드는가")
    print("-" * 104)
    for col in ["최대회", "트레일", "눌림", "목표"]:
        g = df.groupby(col)["월평균"].mean()
        print(f"{col:>8} : " + "   ".join(f"{k}={v:,.0f}만" for k, v in g.items()))


if __name__ == "__main__":
    main()
