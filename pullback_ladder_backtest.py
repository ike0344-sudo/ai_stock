"""눌림 3분할(-2% / -4% / 직전고점 돌파) 진입 백테스트.

사용자 아이디어: 러닝 고점에서 -2%에 1차, -4%에 2차, 다시 올라와 그 고점을
돌파할 때 3차. 눌림을 기다렸다 받고 회복을 확인하며 태운다.

모집단은 10:00 스캔 후보 전체(승자+패자)다. "+20%까지 갈 종목"만 골라
검증하면 눌림에서 받는 전략은 항상 좋아 보인다 — 실제로는 눌린 뒤 그대로
무너지는 케이스가 같은 조건에서 나온다.

비교 대상
  A 전량 (컷오프 시각) 시장가       (직전 백테스트의 최고 조합)
  B 눌림 3분할 -2 / -4 / 고점돌파  (사용자 아이디어)
  C 눌림 2분할 -2 / 고점돌파
  D 고점돌파 1회만 (2% 이상 눌린 뒤 회복 확인)
"""
import os
import sys
from itertools import product

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean20_conditions import load

MINUTE_DIR = "data/stocks/minute"
COST_PCT = 0.25
_CUT = os.environ.get("SCAN_CUTOFF", "1000")   # 진입 시각 - 피처 컷오프와 같이 움직인다
ENTRY_MIN, EXIT_MIN = int(_CUT[:2]) * 60 + int(_CUT[2:]), 920
ENTRY_PLAN = f"A 전량 {_CUT[:2]}:{_CUT[2:]}"
RULE4 = "--rule4" in sys.argv
# --daycut: 그날 대금 top10의 10시 최고 등락률이 이 값 미만이면 하루를 통째로 접는다.
# (clean20_day_filter.py: 270일 중 35일이 걸리고 그중 91%가 실제로 공친 날)
DAY_CUT = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--daycut=")), 0))
# --kdqmin: 전일 코스닥 거래대금(조)이 이 값 미만이면 접는다. 전일 값이라 룩어헤드 없음.
KDQ_MIN = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--kdqmin=")), 0))
# --kdq930: 09:00~09:30 코스닥 누적 대금(조)이 이 값 미만이면 접는다. 10:00 진입 전에
# 확정되는 값이라 룩어헤드는 없지만, 분봉 캐시가 없는 날은 통째로 빠진다 - 기준선과
# 비교할 땐 0.001 같은 최소값으로 같은 날짜 집합을 만들어 맞춰야 한다.
KDQ_930 = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--kdq930=")), 0))
# --daypeak: 눌림 트리거와 손절을 09:00부터의 당일 고점 기준으로 잡는다.
# (기본은 10:00 이후 고점 기준 — 10시 전 고점이 이미 높으면 두 기준이 크게 갈린다)
DAY_PEAK = "--daypeak" in sys.argv

PLANS = {
    ENTRY_PLAN: {"market": 1.0, "dips": [], "breakout": 0.0},
    "B 3분할 -2/-4/돌파": {"market": 0.0, "dips": [(1 / 3, 2.0), (1 / 3, 4.0)], "breakout": 1 / 3},
    "C 2분할 -2/돌파": {"market": 0.0, "dips": [(0.5, 2.0)], "breakout": 0.5},
    "D 돌파 1회만": {"market": 0.0, "dips": [], "breakout": 1.0},
}
TRAILS = [3.0, 4.0, 5.0, 7.0]


def simulate(bars: pd.DataFrame, plan: dict, trail: float) -> tuple[float, int] | None:
    """배정자본 대비 수익률(%)과 체결 레그 수. 미체결분은 현금(0%)."""
    mins = bars.index.hour * 60 + bars.index.minute
    seg = bars[(mins >= ENTRY_MIN) & (mins <= EXIT_MIN)]
    if len(seg) < 5:
        return None
    o = seg["open"].to_numpy(); h = seg["high"].to_numpy()
    lo = seg["low"].to_numpy(); c = seg["close"].to_numpy()
    pre_high = float(bars[mins < ENTRY_MIN]["high"].max()) if DAY_PEAK else -np.inf

    qty = 0.0; cost = 0.0; legs = 0
    peak = max(h[0], pre_high)
    start = 0 if DAY_PEAK else 1     # 당일 고점 기준이면 10:00 봉부터 체결 판정
    ref_peak = None          # 눌림이 시작된 고점 — 3차(돌파) 기준가
    dip_done = [False] * len(plan["dips"])
    bo_done = plan["breakout"] <= 0

    if plan["market"] > 0:                       # A안: 진입 시각 종가에 전량
        qty = plan["market"]; cost = qty * c[0]; legs = 1

    # market2 = (비중, 분) — 그 시각 종가에 2차 시장가. 분할 진입(09:30 + 10:00)용.
    m2w, m2min = plan.get("market2", (0.0, 0))
    seg_mins = (seg.index.hour * 60 + seg.index.minute).to_numpy()

    for i in range(start, len(seg)):
        if m2w > 0 and seg_mins[i] >= m2min:
            qty += m2w; cost += m2w * c[i]; legs += 1; m2w = 0.0
        # 1) 눌림 지정가 체결 — 러닝 고점 기준
        for k, (w, depth) in enumerate(plan["dips"]):
            trig = peak * (1 - depth / 100)
            if not dip_done[k] and lo[i] <= trig:
                dip_done[k] = True; legs += 1
                px = min(trig, o[i])
                qty += w; cost += w * px
                if ref_peak is None:
                    ref_peak = peak              # 이 고점을 되찾으면 3차
        # 2) 돌파 체결 — 눌림을 겪은 뒤 그 고점 회복
        bo_trig = None if ref_peak is None else ref_peak * (1 + plan.get("bo_buf", 0.0) / 100)
        if not bo_done and bo_trig is not None and h[i] >= bo_trig:
            bo_done = True; legs += 1
            px = max(bo_trig, o[i])
            qty += plan["breakout"]; cost += plan["breakout"] * px
        # D안은 눌림 레그가 없으니 2% 눌림 자체를 기준점으로 잡는다
        if not plan["dips"] and not bo_done and ref_peak is None and lo[i] <= peak * 0.98:
            ref_peak = peak

        if qty > 0:                              # 3) 트레일링 손절
            avg = cost / qty
            stop = peak * (1 - trail / 100)
            if lo[i] <= stop:
                px = min(stop, o[i])
                return (qty * (px / avg - 1) * 100 - COST_PCT * qty, legs)
        peak = max(peak, h[i])

    if qty == 0:
        return (0.0, 0)                          # 진입 자체가 없던 날
    return (qty * (c[-1] / (cost / qty) - 1) * 100 - COST_PCT * qty, legs)


def candidates() -> pd.DataFrame:
    b = load()
    live = b[(~b["already_20_by_10"]) & (b["open_gap_pct"] < 15)]
    m = ((live["max_dd_to_10_pct"] <= 5) & (live["first5_value_share"] <= 0.15)
         & (live["pos_in_range_10"] >= 0.7))
    if RULE4:
        m &= ((live["ret_at_10_pct"] >= 7) & (live["pos_in_range_10"] >= 0.8)
              & (live["value_vs_20d_avg"] >= 1.5) & (live["high_vs_20d_high_pct"] >= 0))
    if DAY_CUT > 0:
        # 하루 판정은 top10 전체(이미 +20% 간 종목 포함)로 — 10:00에 화면에 보이는 그대로
        day_max = b.groupby("date")["ret_at_10_pct"].max()
        m &= live["date"].map(day_max) >= DAY_CUT
    if KDQ_MIN > 0:
        from kospi_value_burst import daily_value
        prev = (daily_value("101")["value_mw"] / 1e6).shift(1)   # 백만원 -> 조원, 전일치
        m &= live["date"].map(prev) >= KDQ_MIN
    if KDQ_930 > 0:
        import kospi_value_burst as K
        K.SEG = (540, 570)                                       # 09:00~09:29
        m &= live["date"].map(K.segments("101")["seg_value_jo"]).fillna(-1) >= KDQ_930
    return live[m]


def main() -> None:
    cand = candidates()
    print(f"후보 {len(cand)}건 ({cand['date'].nunique()}일)", file=sys.stderr)
    res = {(n, t): [] for n, t in product(PLANS, TRAILS)}
    legs = {(n, t): [] for n, t in product(PLANS, TRAILS)}
    won20 = {(n, t): [] for n, t in product(PLANS, TRAILS)}

    reached = dict(zip(zip(cand["date"], cand["stock_code"]), cand["reached"]))
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
            for name, plan in PLANS.items():
                for tr in TRAILS:
                    out = simulate(bars, plan, tr)
                    if out is None:
                        continue
                    res[(name, tr)].append(out[0])
                    legs[(name, tr)].append(out[1])
                    won20[(name, tr)].append(bool(reached.get((date, code), False)))
    print(file=sys.stderr)

    print("=" * 108)
    print(f"눌림 3분할 vs 전량 진입  (후보 {len(res[(ENTRY_PLAN, 5.0)])}건, "
          f"{'3배제+4조건' if RULE4 else '3배제'}, 비용 {COST_PCT}%)")
    print("=" * 108)
    print(f"{'전략':>20}{'트레일':>7}{'진입성사':>9}{'평균레그':>9}{'승률':>8}{'기대값':>9}"
          f"{'평균익':>8}{'평균손':>8}{'최악':>8}{'누적':>9}")
    rows = []
    for (name, tr), v in res.items():
        a = np.array(v); lg = np.array(legs[(name, tr)])
        traded = a[lg > 0]
        rows.append({
            "n": name, "t": tr, "fill": (lg > 0).mean() * 100, "legs": lg[lg > 0].mean() if (lg > 0).any() else 0,
            "win": (traded > 0).mean() * 100 if len(traded) else 0, "exp": a.mean(),
            "gain": traded[traded > 0].mean() if (traded > 0).any() else 0,
            "loss": traded[traded <= 0].mean() if (traded <= 0).any() else 0,
            "worst": a.min(), "sum": a.sum(),
        })
    for r in sorted(rows, key=lambda x: (x["n"], x["t"])):
        print(f"{r['n']:>20}{r['t']:>6.0f}%{r['fill']:>8.0f}%{r['legs']:>9.2f}"
              f"{r['win']:>7.1f}%{r['exp']:>8.2f}%{r['gain']:>7.2f}%{r['loss']:>7.2f}%"
              f"{r['worst']:>7.1f}%{r['sum']:>8.0f}%")

    print("\n" + "-" * 108)
    print("+20% 도달 여부로 나눠 본 눌림 3분할 (트레일 -5%) — 아이디어의 전제가 맞았을 때/틀렸을 때")
    print("-" * 108)
    a = np.array(res[("B 3분할 -2/-4/돌파", 5.0)]); w = np.array(won20[("B 3분할 -2/-4/돌파", 5.0)])
    b = np.array(res[(ENTRY_PLAN, 5.0)])
    for lab, m in [("+20% 간 날", w), ("+20% 못 간 날", ~w)]:
        print(f"{lab:>14} n={m.sum():>4}   3분할 평균 {a[m].mean():>6.2f}%   "
              f"전량진입 평균 {b[m].mean():>6.2f}%")


def demo() -> None:
    """레그 체결 순서 자체검증 — -2%, -4%, 고점돌파가 각각 걸려야 한다."""
    idx = pd.date_range("2026-01-02 10:00", periods=8, freq="1min")
    # 100에서 시작 -> 98 -> 96 -> 회복 -> 100 돌파 -> 105
    bars = pd.DataFrame(
        {"open":  [100, 99, 97, 96, 98, 100, 103, 105],
         "high":  [100, 100, 98, 97, 99, 101, 104, 106],
         "low":   [99, 97.9, 95.9, 95.5, 97, 99, 102, 104],
         "close": [100, 98, 96, 96.5, 99, 101, 104, 105]}, idx)
    r, legs = simulate(bars, PLANS["B 3분할 -2/-4/돌파"], 20.0)
    assert legs == 3, legs                    # 세 레그 모두 체결
    assert r > 0, r                           # 105 마감이면 이익
    flat = bars.copy()
    flat[["open", "high", "low", "close"]] = 100.0
    assert simulate(flat, PLANS["B 3분할 -2/-4/돌파"], 5.0) == (0.0, 0)  # 눌림 없으면 미진입
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    main()
