"""눌림으로 사야 하는 자리 vs 돌파로 사야 하는 자리 — 60선 국면별 비교.

    python entry_style_regime.py

같은 후보라도 진입 방식에 따라 결과가 다르다. 60선 위/아래(그리고 정/역배열)로
나눠서 어느 자리에서 어느 방식이 유리한지 본다. 국면 판정은 10:00 이전에 닫힌
15분봉까지만 써서 룩어헤드가 없다.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pullback_ladder_backtest as L
from below60_backtest import below60_by_day
from clean20_conditions import wilson
from ma_align_traits import align

TRAILS = [4.0, 5.0, 7.0]
CACHE = "results/entry_style_regime.csv"
PLANS = {
    "전량 시장가": {"market": 1.0, "dips": [], "breakout": 0.0},
    "눌림 -2% 1회": {"market": 0.0, "dips": [(1.0, 2.0)], "breakout": 0.0},
    "눌림2분할 -2/돌파": {"market": 0.0, "dips": [(0.5, 2.0)], "breakout": 0.5},
    "눌림3분할 -2/-4/돌파": {"market": 0.0, "dips": [(1/3, 2.0), (1/3, 4.0)], "breakout": 1/3},
    "돌파 1회만": {"market": 0.0, "dips": [], "breakout": 1.0},
}


def trades() -> pd.DataFrame:
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE, parse_dates=["date"], dtype={"code": str})

    L.DAY_PEAK, L.DAY_CUT, L.KDQ_MIN, L.KDQ_930, L.RULE4 = True, 0.0, 0.0, 0.0, False
    cand = L.candidates()
    rows = []
    for code, g in cand.groupby("stock_code"):
        path = os.path.join(L.MINUTE_DIR, f"{code}.csv")
        if not os.path.exists(path):
            continue
        minute = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        want = set(g["date"])
        for date, bars in minute.groupby(minute.index.normalize()):
            if date not in want:
                continue
            r = {"date": date, "code": code}
            for name, plan in PLANS.items():
                for t in TRAILS:
                    out = L.simulate(bars, plan, t)
                    r[f"{name}|{t:g}"] = np.nan if out is None else out[0]
            rows.append(r)

    t = pd.DataFrame(rows).dropna(subset=["전량 시장가|5"])
    t["below60"] = t["date"].map(below60_by_day()).fillna(False).astype(bool)
    sp = align().dropna()
    sp = sp[sp.index.time < pd.Timestamp("10:00").time()]
    t["trend"] = t["date"].map(sp.groupby(sp.index.normalize()).last().map(
        lambda v: "정배열" if v > 0 else "역배열"))
    t.to_csv(CACHE, index=False, encoding="utf-8-sig")
    return t


def block(t: pd.DataFrame, title: str) -> None:
    print(f"\n{title}  ({len(t)}건)")
    print(f"{'진입 방식':>22}{'트레일':>7}{'건당':>9}{'승률':>8}{'누적':>9}")
    best = None
    for name in PLANS:
        for tr in TRAILS:
            c = f"{name}|{tr:g}"
            r = t[c]
            s = r.sum()
            mark = ""
            if best is None or s > best[0]:
                best = (s, name, tr)
        # 각 방식의 최적 트레일만 출력해 표를 짧게 유지한다
        bt = max(TRAILS, key=lambda x: t[f"{name}|{x:g}"].sum())
        r = t[f"{name}|{bt:g}"]
        print(f"{name:>22}{bt:>6.0f}%{r.mean():>8.2f}%{(r > 0).mean()*100:>7.0f}%{r.sum():>8.0f}%")
    print(f"{'→ 최고':>22}{best[2]:>6.0f}%   {best[1]} · 누적 {best[0]:.0f}%")


def main() -> None:
    t = trades()
    print("=" * 70)
    print(f"진입 방식 x 국면  |  후보 {len(t)}건 · 3배제 적용 · 10:00 진입")
    print("=" * 70)
    block(t, "[전체]")
    block(t[~t["below60"]], "[60선 위]")
    block(t[t["below60"]], "[60선 아래]")
    for tr in ("정배열", "역배열"):
        block(t[t["trend"] == tr], f"[{tr}]")
    block(t[(t["trend"] == "역배열") & (t["below60"])], "[역배열 + 60선 아래]")


def demo() -> None:
    """눌림 전용 플랜은 돌파 비중이 0이어야 한다 - 섞이면 방식 비교가 무의미해진다."""
    assert PLANS["눌림 -2% 1회"]["breakout"] == 0.0
    assert PLANS["돌파 1회만"]["dips"] == []
    assert abs(sum(w for w, _ in PLANS["눌림3분할 -2/-4/돌파"]["dips"])
               + PLANS["눌림3분할 -2/-4/돌파"]["breakout"] - 1.0) < 1e-9
    print("demo ok")


if __name__ == "__main__":
    demo() if "--demo" in sys.argv else main()
