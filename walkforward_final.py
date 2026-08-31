"""최종 조합(3배제 + 일컷 + 순환매 컷 + 트레일)의 워크포워드 검증.

    python walkforward_final.py

일컷 10%, 순환매 1/3, 트레일 -5%는 전 구간을 다 보고 고른 값이라 그대로 못 믿는다.
분기 단위로 앵커드(누적 학습) 워크포워드를 돌린다 - 과거 구간에서 파라미터를 *고르고*
다음 분기에서만 성과를 잰다. 비교 대상은 아무 컷도 안 건 3배제 고정 규칙.

건별 수익률은 트레일별로 한 번만 시뮬레이션하고, 컷은 그 위에서 마스크로만 적용한다
(컷이 진입 시점을 바꾸지 않으므로 결과가 같다).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pullback_ladder_backtest as L
from clean20_conditions import wilson
from rotation_days import day_structure

TRAILS = [3.0, 4.0, 5.0, 7.0]
DAYCUTS = [0.0, 7.0, 10.0, 15.0]       # 0 = 컷 없음
ROTS = [0.0, 0.25, 0.33, 0.40]         # 0 = 컷 없음. 강세 3개+ 인 날에만 적용
CACHE = "results/walkforward_trades.csv"
MIN_TRAIN = 60                          # 학습 구간 최소 건수


def trade_table() -> pd.DataFrame:
    """3배제만 통과한 후보의 트레일별 수익률 + 그날 지표. 한 번 만들고 캐시."""
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE, parse_dates=["date"], dtype={"code": str})

    L.DAY_PEAK, L.DAY_CUT, L.KDQ_MIN, L.KDQ_930, L.RULE4 = True, 0.0, 0.0, 0.0, False
    cand = L.candidates()
    plan = L.PLANS[L.ENTRY_PLAN]
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
            for t in TRAILS:
                out = L.simulate(bars, plan, t)
                r[f"t{t:g}"] = np.nan if out is None else out[0]
            rows.append(r)

    t = pd.DataFrame(rows).dropna()
    d = day_structure()
    for c in ["n_strong", "top_share"]:
        t[c] = t["date"].map(d[c])
    t["max_ret"] = t["date"].map(L.load().groupby("date")["ret_at_10_pct"].max())
    t.to_csv(CACHE, index=False, encoding="utf-8-sig")
    return t


def mask(t: pd.DataFrame, daycut: float, rot: float) -> pd.Series:
    m = pd.Series(True, index=t.index)
    if daycut > 0:
        m &= t["max_ret"] >= daycut
    if rot > 0:
        m &= ~((t["n_strong"] >= 3) & (t["top_share"] < rot))
    return m


def best_params(train: pd.DataFrame) -> tuple[float, float, float, float]:
    """학습 구간에서 누적수익 최대 조합. 표본이 얇으면 컷 없는 쪽으로 남는다."""
    best = (-1e9, 5.0, 0.0, 0.0)
    for trail in TRAILS:
        for dc in DAYCUTS:
            for rot in ROTS:
                g = train[mask(train, dc, rot)]
                if len(g) < MIN_TRAIN // 2:
                    continue
                s = g[f"t{trail:g}"].sum()
                if s > best[0]:
                    best = (s, trail, dc, rot)
    return best[1], best[2], best[3], best[0]


def summarize(g: pd.DataFrame, col: str) -> str:
    if len(g) == 0:
        return f"{0:>6}{'-':>9}{'-':>8}{'-':>8}"
    r = g[col]
    return f"{len(r):>6}{r.mean():>8.2f}%{(r > 0).mean()*100:>7.0f}%{r.sum():>7.0f}%"


def main() -> None:
    t = trade_table().sort_values("date").reset_index(drop=True)
    t["q"] = t["date"].dt.to_period("Q")
    quarters = sorted(t["q"].unique())

    print("=" * 92)
    print(f"앵커드 워크포워드  |  {t['date'].min().date()} ~ {t['date'].max().date()}"
          f" · 후보 {len(t)}건 · 분기 {len(quarters)}개")
    print("=" * 92)
    print("학습: 직전까지 전부 / 검증: 그 다음 분기. 파라미터는 학습 구간 누적수익 최대로 선택")
    print(f"\n{'검증분기':>9}{'학습건수':>8}{'선택(트레일/일컷/순환)':>22}"
          f"{'건수':>6}{'평균':>9}{'승률':>8}{'합계':>8}{'|':>3}{'고정 3배제 -5%':>18}")

    oos_sel, oos_fix = [], []
    for i in range(1, len(quarters)):
        train = t[t["q"] < quarters[i]]
        test = t[t["q"] == quarters[i]]
        if len(train) < MIN_TRAIN or len(test) == 0:
            continue
        trail, dc, rot, _ = best_params(train)
        g = test[mask(test, dc, rot)]
        col = f"t{trail:g}"
        oos_sel.append(g[col])
        oos_fix.append(test["t5"])
        tag = f"-{trail:g}% / {dc:g}% / {rot:g}"
        print(f"{str(quarters[i]):>9}{len(train):>8}{tag:>22}{summarize(g, col)}{'|':>3}"
              f"{summarize(test, 't5'):>18}")

    sel = pd.concat(oos_sel) if oos_sel else pd.Series(dtype=float)
    fix = pd.concat(oos_fix) if oos_fix else pd.Series(dtype=float)
    print("-" * 92)
    print(f"{'OOS 합산':>9}{'':>8}{'선택 규칙':>22}{summarize(pd.DataFrame({'x': sel}), 'x')}"
          f"{'|':>3}{summarize(pd.DataFrame({'x': fix}), 'x'):>18}")
    if len(sel):
        lo, hi = wilson(int((sel > 0).sum()), len(sel))
        print(f"\n선택 규칙 OOS 승률 95%CI [{lo:.0f}-{hi:.0f}]%")

    print("\n" + "-" * 92)
    print("고정 규칙을 분기별로 - 최종 조합이 매 분기 재현되나 (트레일 -5%)")
    print("-" * 92)
    print(f"{'분기':>9}{'3배제만':>26}{'|':>3}{'+일컷10+순환0.33':>26}")
    for q in quarters:
        g = t[t["q"] == q]
        f = g[mask(g, 10.0, 0.33)]
        print(f"{str(q):>9}{summarize(g, 't5'):>26}{'|':>3}{summarize(f, 't5'):>26}")


def demo() -> None:
    """mask가 두 컷을 AND로 걸고, 강세<3인 날엔 순환매 컷이 안 걸리는지."""
    t = pd.DataFrame({"max_ret": [20.0, 5.0, 20.0], "n_strong": [5, 5, 2],
                      "top_share": [0.2, 0.9, 0.2]})
    m = mask(t, 10.0, 0.33)
    assert m.tolist() == [False, False, True], m.tolist()
    assert mask(t, 0.0, 0.0).all()
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
