"""매도·손절 규칙 최적화. 진입은 앞서 최적으로 나온 두 가지를 고정하고 청산만 바꾼다.

지금까지는 "당일 고점 -X% 트레일링 + 15:20 종가"만 봤다. 여기서 추가로 본 것:
  본전 스톱  이익이 B% 나면 손절선을 평균단가로 올린다
  스톱 조임  이익이 T% 나면 트레일을 좁은 값으로 바꾼다
  시간 손절  지정 시각까지 이익이 없으면 그냥 나온다
  부분 익절  +P%에서 절반 정리, 나머지는 트레일링으로 끌기

모집단은 10:00 스캔 후보 전체(승자+패자). 기준가/손절은 당일 고점(09:00부터).
"""
import os
import sys
from itertools import product

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pullback_ladder_backtest import COST_PCT, ENTRY_MIN, EXIT_MIN, candidates

CAPITAL = 60_000_000
RULE4 = "--rule4" in sys.argv

ENTRIES = {
    "전량 10:00": {"market": 1.0, "dips": [], "breakout": 0.0, "bo_buf": 0.0},
    "사다리 -1/돌파": {"market": 0.0, "dips": [(0.5, 1.0)], "breakout": 0.5, "bo_buf": 0.3},
}
TRAILS = [4.0, 5.0, 6.0]
TIGHTEN = [None, (5.0, 3.0), (8.0, 3.0)]   # (이익 T%부터, 트레일 tight%)
BREAKEVEN = [None, 5.0]                     # 이익 B%부터 손절선을 평균단가로
TIMESTOP = [None, 720]                      # 12:00까지 이익 없으면 청산
PARTIAL = [None, 8.0]                       # +P%에서 절반 정리


def simulate(bars, entry, trail, tighten, be, tstop, partial):
    mins = bars.index.hour * 60 + bars.index.minute
    seg = bars[(mins >= ENTRY_MIN) & (mins <= EXIT_MIN)]
    if len(seg) < 5:
        return None
    o = seg["open"].to_numpy(); h = seg["high"].to_numpy()
    lo = seg["low"].to_numpy(); c = seg["close"].to_numpy()
    tm = (seg.index.hour * 60 + seg.index.minute).to_numpy()
    pre_high = float(bars[mins < ENTRY_MIN]["high"].max())

    qty = cost = 0.0
    peak = max(h[0], pre_high)
    ref_peak = None
    dips = entry["dips"]
    dip_done = [False] * len(dips)
    bo_done = entry["breakout"] <= 0
    realized = 0.0
    half_done = partial is None

    if entry["market"] > 0:
        qty = entry["market"]; cost = qty * c[0]

    for i in range(len(seg)):
        for k, (w, depth) in enumerate(dips):
            trig = peak * (1 - depth / 100)
            if not dip_done[k] and lo[i] <= trig:
                dip_done[k] = True
                qty += w; cost += w * min(trig, o[i])
                if ref_peak is None:
                    ref_peak = peak
        if not bo_done and ref_peak is not None:
            trig = ref_peak * (1 + entry["bo_buf"] / 100)
            if h[i] >= trig:
                bo_done = True
                qty += entry["breakout"]; cost += entry["breakout"] * max(trig, o[i])

        if qty > 0:
            avg = cost / qty
            gain_hi = (h[i] / avg - 1) * 100          # 그 봉에서 찍은 최대 평가익

            if not half_done and gain_hi >= partial:  # 부분 익절
                px = max(avg * (1 + partial / 100), o[i])
                realized += qty / 2 * (px / avg - 1) * 100 - COST_PCT * qty / 2
                qty /= 2; cost /= 2; half_done = True   # 평균단가는 유지되어야 한다

            tr = trail                                # 스톱 조임
            if tighten and gain_hi >= tighten[0]:
                tr = tighten[1]
            stop = peak * (1 - tr / 100)
            if be is not None and gain_hi >= be:      # 본전 스톱
                stop = max(stop, avg)

            if lo[i] <= stop:
                px = min(stop, o[i])
                return realized + qty * (px / avg - 1) * 100 - COST_PCT * qty

            if tstop is not None and tm[i] >= tstop and c[i] <= avg:
                return realized + qty * (c[i] / avg - 1) * 100 - COST_PCT * qty

        peak = max(peak, h[i])

    if qty == 0:
        return realized
    return realized + qty * (c[-1] / (cost / qty) - 1) * 100 - COST_PCT * qty


def main() -> None:
    cand = candidates()
    grid = list(product(ENTRIES, TRAILS, TIGHTEN, BREAKEVEN, TIMESTOP, PARTIAL))
    print(f"후보 {len(cand)}건 × 조합 {len(grid)}개", file=sys.stderr)
    res = {g: [] for g in grid}
    dates = []

    for i, (code, g) in enumerate(cand.groupby("stock_code"), 1):
        print(f"\r[{i}/{cand['stock_code'].nunique()}] {code}", end="", file=sys.stderr)
        path = os.path.join("data/stocks/minute", f"{code}.csv")
        if not os.path.exists(path):
            continue
        minute = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        want = set(g["date"])
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in want:
                continue
            first = True
            for key in grid:
                en, tr, tg, be, ts, pt = key
                r = simulate(bars, ENTRIES[en], tr, tg, be, ts, pt)
                if r is None:
                    break
                res[key].append(r)
                if first:
                    dates.append(date); first = False
    print(file=sys.stderr)

    d = pd.Series(dates)
    rows = []
    for k, v in res.items():
        a = np.array(v)
        if len(a) != len(d):
            continue
        per_day = pd.Series(a, index=d).groupby(level=0).mean()
        eq = np.cumsum(per_day.to_numpy())
        mdd = (np.maximum.accumulate(eq) - eq).max()
        months = per_day.groupby(per_day.index.to_period("M")).sum()
        rows.append({
            "진입": k[0], "트레일": k[1],
            "조임": "-" if not k[2] else f"+{k[2][0]:g}→{k[2][1]:g}",
            "본전": "-" if k[3] is None else f"+{k[3]:g}",
            "시간": "-" if k[4] is None else "12시",
            "부분익절": "-" if k[5] is None else f"+{k[5]:g}",
            "승률": (a > 0).mean() * 100, "기대값": a.mean(),
            "월평균": months.mean() * CAPITAL / 100 / 1e4,
            "MDD": mdd * CAPITAL / 100 / 1e4,
            "누적": eq[-1] * CAPITAL / 100 / 1e4,
            "승월": (months > 0).sum(), "월수": len(months),
        })
    df = pd.DataFrame(rows)
    df["효율"] = df["월평균"] / df["MDD"].clip(lower=1)

    print("=" * 112)
    print(f"매도·손절 규칙 스윕 ({'3배제+4조건' if RULE4 else '3배제'} 후보, 자본 6,000만원, 비용 {COST_PCT}%)")
    print("=" * 112)

    def show(title, dd):
        print(f"\n{title}")
        print(f"{'진입':>14}{'트레일':>7}{'조임':>9}{'본전':>6}{'시간':>6}{'부분익절':>9}"
              f"{'승률':>7}{'기대값':>8}{'월평균':>10}{'MDD':>10}{'누적':>10}{'승월':>7}")
        for _, r in dd.iterrows():
            print(f"{r['진입']:>14}{r['트레일']:>6.0f}%{r['조임']:>9}{r['본전']:>6}{r['시간']:>6}"
                  f"{r['부분익절']:>9}{r['승률']:>6.1f}%{r['기대값']:>7.2f}%"
                  f"{r['월평균']:>8,.0f}만{r['MDD']:>8,.0f}만{r['누적']:>8,.0f}만"
                  f"{r['승월']:>4}/{r['월수']:<2}")

    show("[월평균 손익 상위 12]", df.sort_values("월평균", ascending=False).head(12))
    show("[낙폭 대비 효율 상위 12]", df.sort_values("효율", ascending=False).head(12))
    show("[기존안: 트레일만, 추가 규칙 없음]",
         df[(df["조임"] == "-") & (df["본전"] == "-") & (df["시간"] == "-") & (df["부분익절"] == "-")]
         .sort_values(["진입", "트레일"]))

    print("\n" + "-" * 112)
    print("규칙별 평균 월손익 (나머지 조건은 평균 처리)")
    print("-" * 112)
    for col in ["진입", "트레일", "조임", "본전", "시간", "부분익절"]:
        g = df.groupby(col)["월평균"].mean()
        print(f"{col:>8} : " + "   ".join(f"{k}={v:,.0f}만" for k, v in g.items()))


if __name__ == "__main__":
    main()
