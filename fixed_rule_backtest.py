"""가장 단순한 규칙: 전일比 +10% 터치에 매수, 진입가 -4% 손절, 전일比 +20% 익절.

모집단은 대금 top10 종목-일자 전체다. "+20% 간 종목"만 보면 손익비가 무한대로
나오니 의미가 없다. +10%를 찍은 날은 전부 진입한 것으로 본다.

같은 1분봉 안에서 손절가와 익절가가 모두 닿으면 손절로 처리한다(보수적 가정).
둘 다 안 닿으면 15:20 종가 청산.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import load

MINUTE_DIR = "data/stocks/minute"
DAILY_DIR = "data/stocks/daily"
CAPITAL = 60_000_000
COST_PCT = 0.25
ENTRY_LV = 10.0      # 전일比 진입 수준
STOP_PCT = 4.0       # 진입가 대비 손절
TARGET_LV = 20.0     # 전일比 익절 수준
EXIT_MIN = 920       # 15:20


def run_day(bars: pd.DataFrame, pc: float) -> dict | None:
    mins = bars.index.hour * 60 + bars.index.minute
    seg = bars[mins <= EXIT_MIN]
    if len(seg) < 5:
        return None
    h = seg["high"].to_numpy(); lo = seg["low"].to_numpy()
    o = seg["open"].to_numpy(); c = seg["close"].to_numpy()

    trig = pc * (1 + ENTRY_LV / 100)
    hit = np.flatnonzero(h >= trig)
    if hit.size == 0:
        return None                      # +10%를 못 찍으면 진입 자체가 없다
    i0 = int(hit[0])
    entry = max(trig, o[i0])             # 갭으로 넘겼으면 시가 체결
    stop = entry * (1 - STOP_PCT / 100)
    target = pc * (1 + TARGET_LV / 100)

    for i in range(i0, len(seg)):
        low_hit = lo[i] <= stop
        high_hit = h[i] >= target
        if low_hit:                      # 같은 봉이면 손절 우선(보수적)
            px = min(stop, o[i]) if i > i0 else stop
            return {"ret": (px / entry - 1) * 100 - COST_PCT, "how": "손절",
                    "t_entry": seg.index[i0].strftime("%H:%M"), "bars": i - i0}
        if high_hit:
            px = max(target, o[i]) if i > i0 else target
            return {"ret": (px / entry - 1) * 100 - COST_PCT, "how": "익절",
                    "t_entry": seg.index[i0].strftime("%H:%M"), "bars": i - i0}
    return {"ret": (c[-1] / entry - 1) * 100 - COST_PCT, "how": "종가",
            "t_entry": seg.index[i0].strftime("%H:%M"), "bars": len(seg) - 1 - i0}


def build(filtered: bool) -> pd.DataFrame:
    b = load()
    pop = b[b["open_gap_pct"] < 15]
    if filtered:
        pop = pop[(pop["max_dd_to_10_pct"] <= 5) & (pop["first5_value_share"] <= 0.15)
                  & (pop["pos_in_range_10"] >= 0.7)]
    rows = []
    for i, (code, g) in enumerate(pop.groupby("stock_code"), 1):
        print(f"\r[{i}/{pop['stock_code'].nunique()}] {code}", end="", file=sys.stderr)
        mpath = os.path.join(MINUTE_DIR, f"{code}.csv")
        dpath = os.path.join(DAILY_DIR, f"{code}.csv")
        if not (os.path.exists(mpath) and os.path.exists(dpath)):
            continue
        prev_close = pd.read_csv(dpath, index_col=0, parse_dates=True).sort_index()["close"].shift(1)
        minute = pd.read_csv(mpath, index_col=0, parse_dates=True).sort_index()
        want = dict(zip(g["date"], g["name"]))
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in want:
                continue
            pc = prev_close.get(date, np.nan)
            if pd.isna(pc) or pc <= 0:
                continue
            r = run_day(bars, float(pc))
            if r:
                rows.append({"date": date, "stock_code": code, "name": want[date], **r})
    print(file=sys.stderr)
    return pd.DataFrame(rows)


def report(df: pd.DataFrame, n_pop: int, label: str) -> None:
    a = df["ret"].to_numpy()
    win = a[a > 0]; loss = a[a <= 0]
    n_month = df["date"].dt.to_period("M").nunique()
    per_day = df.groupby("date")["ret"].mean()
    eq = np.cumsum(per_day.to_numpy())
    mdd = (np.maximum.accumulate(eq) - eq).max()
    m = per_day.groupby(per_day.index.to_period("M")).sum()

    print("\n" + "=" * 88)
    print(f"[{label}]  모집단 {n_pop:,}건 중 +10% 터치 {len(df)}건 ({len(df)/n_pop*100:.1f}%)")
    print("=" * 88)
    print(f"{'청산 사유':>10}{'건수':>7}{'비율':>8}{'평균수익':>10}")
    for how, g in df.groupby("how"):
        print(f"{how:>10}{len(g):>7}{len(g)/len(df)*100:>7.1f}%{g['ret'].mean():>9.2f}%")

    print(f"\n승률       {len(win)/len(a)*100:.1f}%  ({len(win)}승 {len(loss)}패)")
    print(f"평균 수익   {win.mean():+.2f}%     평균 손실 {loss.mean():+.2f}%")
    print(f"손익비     {abs(win.mean()/loss.mean()):.2f}  "
          f"(기대값 {a.mean():+.2f}%/건)")
    print(f"최고 {a.max():+.1f}%   최악 {a.min():+.1f}%")
    print(f"\n월평균 손익 {m.mean()*CAPITAL/100/1e4:,.0f}만원  "
          f"최대낙폭 {mdd*CAPITAL/100/1e4:,.0f}만원  수익월 {(m>0).sum()}/{len(m)}")
    print(f"익절까지 소요 중앙 {df[df['how']=='익절']['bars'].median():.0f}분   "
          f"손절까지 중앙 {df[df['how']=='손절']['bars'].median():.0f}분")
    print(f"진입 시각: " + "  ".join(
        f"{h}시 {c}건" for h, c in df["t_entry"].str[:2].value_counts().sort_index().items()))


def demo() -> None:
    """손절/익절 판정 자체검증."""
    idx = pd.date_range("2026-01-02 09:00", periods=5, freq="1min")
    # 전일종가 100 -> 110 터치 후 105.6 이탈 = 손절
    down = pd.DataFrame({"open": [104, 109, 108, 106, 105], "high": [105, 111, 109, 107, 106],
                         "low": [103, 108, 106, 105.5, 104], "close": [104, 110, 107, 106, 105]}, idx)
    r = run_day(down, 100.0)
    assert r["how"] == "손절" and r["ret"] < -3.5, r
    # 110 터치 후 120 도달 = 익절
    up = pd.DataFrame({"open": [104, 109, 112, 116, 119], "high": [105, 111, 115, 118, 121],
                       "low": [103, 108, 111, 115, 118], "close": [104, 110, 114, 117, 120]}, idx)
    r = run_day(up, 100.0)
    assert r["how"] == "익절" and 8 < r["ret"] < 9.2, r
    assert run_day(up, 1000.0) is None            # +10% 미달이면 진입 없음
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    for filtered, label in [(False, "대금 top10 전체"), (True, "3배제 필터 통과분만")]:
        b = load()
        pop = b[b["open_gap_pct"] < 15]
        if filtered:
            pop = pop[(pop["max_dd_to_10_pct"] <= 5) & (pop["first5_value_share"] <= 0.15)
                      & (pop["pos_in_range_10"] >= 0.7)]
        df = build(filtered)
        report(df, len(pop), label)
