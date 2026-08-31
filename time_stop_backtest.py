"""시간 손절: 고가갱신이 N분 넘게 안 나오면 청산한다.

pullback_recovery_minutes.py에서 조정 왕복(고점->재돌파) 중앙이 3분으로 나온 걸
그대로 규칙으로 만든 것 — "3분 안에 재돌파 안 나오면 손절"이 실제로 돈이 되는지.

fixed_rule_backtest.py와 진입/익절/비용/모집단을 똑같이 맞췄다(전일比 +10% 터치 진입,
+20% 익절, 15:20 종가 청산, 왕복비용 0.25%). 손절 규칙 하나만 갈아끼워야 비교가 된다.
모집단도 그대로 대금 top10 종목-일자 전체다 — "+20% 간 종목"만 보면 손절 규칙이 항상
손해로 나온다(그 종목들은 정의상 안 털렸으니까).

시계는 러닝 고점이 찍힌 봉부터 센다(왕복 기준). 갱신 없이 N분이 지나면 그 봉 종가에
나간다. TRIGGER_PCT를 주면 "고점 대비 그만큼 밀린 적이 있을 때만" 시간 손절을
적용한다 — 0이면 순수하게 "N분간 신고가 없음"만 본다.

    python time_stop_backtest.py            # 시간손절 그리드 + 고정손절/무손절 비교
    python time_stop_backtest.py --demo     # 청산 판정 자체검증
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
ENTRY_LV = 10.0   # 전일比 진입 수준
TARGET_LV = 20.0  # 전일比 익절 수준
EXIT_MIN = 920    # 15:20
FIXED_STOP_PCT = 4.0  # 비교용 고정 손절(fixed_rule_backtest.py와 동일)


def run_day(bars: pd.DataFrame, pc: float, hold_min: float | None,
            trigger_pct: float = 0.0, fixed_stop: float | None = None,
            entry_from_min: int = 0) -> dict | None:
    """하루치 1분봉에 규칙을 태운다. hold_min=None이면 시간 손절 없음.

    entry_from_min: 이 시각(분) 이전에는 진입하지 않는다. 4조건처럼 10:00에 확정되는
    필터를 쓸 때 09시대 진입을 허용하면 룩어헤드가 된다. 이미 +10%를 넘긴 상태면
    그 시각 이후 첫 봉 시가에 들어간다.

    같은 봉에서 손절가와 익절가가 모두 닿으면 손절로 본다(보수적) — 시간 손절은
    가격 트리거가 아니라 봉 종가 청산이라 익절 판정을 먼저 한다."""
    mins = bars.index.hour * 60 + bars.index.minute
    seg = bars[mins <= EXIT_MIN]
    if len(seg) < 5:
        return None
    h, lo = seg["high"].to_numpy(), seg["low"].to_numpy()
    o, c = seg["open"].to_numpy(), seg["close"].to_numpy()
    ts = seg.index

    trig = pc * (1 + ENTRY_LV / 100)
    hit = np.flatnonzero((h >= trig) & (mins[mins <= EXIT_MIN].to_numpy() >= entry_from_min))
    if hit.size == 0:
        return None                      # +10%를 못 찍으면 진입 자체가 없다
    i0 = int(hit[0])
    entry = max(trig, o[i0])             # 갭으로 넘겼으면 시가 체결
    target = pc * (1 + TARGET_LV / 100)
    stop_px = entry * (1 - fixed_stop / 100) if fixed_stop else None

    def out(px: float, how: str, i: int) -> dict:
        return {"ret": (px / entry - 1) * 100 - COST_PCT, "how": how,
                "t_entry": ts[i0].strftime("%H:%M"), "held": int((ts[i] - ts[i0]).total_seconds() // 60)}

    peak, peak_i = h[i0], i0
    trough_since_peak = lo[i0]
    for i in range(i0, len(seg)):
        if stop_px is not None and lo[i] <= stop_px:
            return out(min(stop_px, o[i]) if i > i0 else stop_px, "손절", i)
        if h[i] >= target:
            return out(max(target, o[i]) if i > i0 else target, "익절", i)
        if h[i] > peak:                  # 고가갱신 — 시계를 다시 건다
            peak, peak_i, trough_since_peak = h[i], i, lo[i]
            continue
        trough_since_peak = min(trough_since_peak, lo[i])
        if hold_min is None:
            continue
        elapsed = (ts[i] - ts[peak_i]).total_seconds() / 60
        pulled = trough_since_peak <= peak * (1 - trigger_pct / 100)
        if elapsed >= hold_min and pulled:
            return out(c[i], "시간손절", i)
    return out(c[-1], "종가", len(seg) - 1)


def build(rules: dict[str, dict], pop: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """분봉을 종목당 한 번만 읽고 모든 규칙을 같은 날짜에 태운다 — 규칙마다 전체를
    다시 도는 것보다 훨씬 빠르고, 규칙 간 모집단이 어긋날 여지도 없앤다."""
    pop = load() if pop is None else pop
    pop = pop[pop["open_gap_pct"] < 15]
    rows: dict[str, list] = {name: [] for name in rules}
    codes = pop["stock_code"].nunique()
    for i, (code, g) in enumerate(pop.groupby("stock_code"), 1):
        print(f"\r[{i}/{codes}] {code}", end="", file=sys.stderr)
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
            for name, kw in rules.items():
                r = run_day(bars, float(pc), **kw)
                if r:
                    rows[name].append({"date": date, "stock_code": code, "name": want[date], **r})
    print(file=sys.stderr)
    return {name: pd.DataFrame(v) for name, v in rows.items()}


def stats(df: pd.DataFrame) -> dict:
    a = df["ret"].to_numpy()
    win, loss = a[a > 0], a[a <= 0]
    per_day = df.groupby("date")["ret"].mean()
    eq = np.cumsum(per_day.to_numpy())
    m = per_day.groupby(per_day.index.to_period("M")).sum()
    return {
        "n": len(a), "win": len(win) / len(a) * 100,
        "avg_win": win.mean() if len(win) else 0.0,
        "avg_loss": loss.mean() if len(loss) else 0.0,
        "exp": a.mean(), "worst": a.min(),
        "mdd": (np.maximum.accumulate(eq) - eq).max(),
        "month": m.mean(), "pos_month": (m > 0).sum(), "n_month": len(m),
        "target_pct": (df["how"] == "익절").mean() * 100,
        "held": df["held"].median(),
    }


def report(results: dict[str, pd.DataFrame], label: str = "대금 top10 전체") -> None:
    print("=" * 104)
    print(f"고가갱신 N분 미발생 시 청산   [{label} · 전일比 +{ENTRY_LV:g}% 터치 진입 · "
          f"+{TARGET_LV:g}% 익절 · 비용 {COST_PCT}%]")
    print("=" * 104)
    any_df = next(iter(results.values()))
    print(f"기간 {any_df['date'].min().date()} ~ {any_df['date'].max().date()} · "
          f"진입 {len(any_df)}건 ({any_df['date'].nunique()}일)")
    print()
    print(f"{'규칙':>22}{'승률':>8}{'익절':>8}{'평균익':>9}{'평균손':>9}{'기대값':>9}"
          f"{'월평균':>11}{'최대낙폭':>11}{'수익월':>8}{'보유':>7}")
    print("-" * 104)
    for name, df in results.items():
        s = stats(df)
        print(f"{name:>22}{s['win']:>7.1f}%{s['target_pct']:>7.1f}%{s['avg_win']:>+8.2f}%"
              f"{s['avg_loss']:>+8.2f}%{s['exp']:>+8.2f}%"
              f"{s['month'] * CAPITAL / 100 / 1e4:>9,.0f}만{s['mdd'] * CAPITAL / 100 / 1e4:>9,.0f}만"
              f"{s['pos_month']:>4}/{s['n_month']:<3}{s['held']:>6.0f}분")

    print("\n" + "-" * 104)
    print("청산 사유 구성")
    print("-" * 104)
    print(f"{'규칙':>22}" + "".join(f"{h:>16}" for h in ["익절", "손절", "시간손절", "종가"]))
    for name, df in results.items():
        cells = ""
        for how in ["익절", "손절", "시간손절", "종가"]:
            g = df[df["how"] == how]
            cells += f"{len(g):>6}건{g['ret'].mean() if len(g) else 0:>+8.1f}%" if len(g) else f"{'-':>16}"
        print(f"{name:>22}{cells}")


def demo() -> None:
    """시간 손절 / 익절 / 고정 손절 판정 자체검증."""
    idx = pd.date_range("2026-01-02 09:00", periods=8, freq="1min")
    mk = lambda h, l: pd.DataFrame({"open": l, "high": h, "low": l, "close": l}, index=idx)

    # i=1에 +10%(110) 터치해 진입, 고점은 i=2의 111. 갱신 없이 횡보하다 3분 뒤 종가 청산
    flat_h = [100, 110.5, 111, 110, 110, 110, 110, 110]
    flat_l = [99, 109, 110, 108, 108, 108, 108, 108]
    r = run_day(mk(flat_h, flat_l), 100.0, hold_min=3)
    assert r["how"] == "시간손절" and r["held"] == 4, r      # 고점 i=2, 3분 경과 i=5

    # 갱신이 계속 나오면 시계가 다시 걸려서 안 털리고 +20% 익절
    r = run_day(mk([100, 110.5, 111, 112, 113, 114, 120, 120],
                   [99, 109, 110, 111, 112, 113, 119, 119]), 100.0, hold_min=3)
    assert r["how"] == "익절" and r["ret"] > 8, r

    # 시간 손절 없이 두면 같은 횡보에서 종가까지 들고 간다
    assert run_day(mk(flat_h, flat_l), 100.0, hold_min=None)["how"] == "종가"

    # 트리거 1%: 고점 111 대비 1%(=109.89) 아래로 안 밀리면 시간이 지나도 안 나간다
    r = run_day(mk(flat_h, [99, 109, 110, 110, 110, 110, 110, 110]),
                100.0, hold_min=3, trigger_pct=1.0)
    assert r["how"] == "종가", r

    # 고정 손절 4%: entry 110 -> 105.6 이탈
    r = run_day(mk([100, 110.5, 110, 110, 110, 110, 110, 110],
                   [99, 109, 105, 105, 105, 105, 105, 105]), 100.0, hold_min=None, fixed_stop=4.0)
    assert r["how"] == "손절", r
    print("demo ok")


RULE4_MIN = 600  # 10:00 - 4조건이 확정되는 시각. 이 전에 진입하면 룩어헤드다


def rule4_mask(pop: pd.DataFrame) -> pd.Series:
    """clean20_conditions.report()의 "10시 시점에 전부 관측 가능한" 4조건.
    이미 10시에 +20%인 날은 익절 여지가 없어 뺀다."""
    return ((pop["ret_at_10_pct"] >= 7) & (pop["pos_in_range_10"] >= 0.8)
            & (pop["value_vs_20d_avg"] >= 1.5) & (pop["high_vs_20d_high_pct"] >= 0)
            & ~pop["already_20_by_10"])


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()

    if "--rule4" in sys.argv:
        # 진입 시각을 10:00으로 늦춘 것 자체의 효과와 4조건 필터의 효과를 갈라 보려고
        # 같은 진입 규칙의 전체 모집단을 나란히 돌린다.
        rules = {name: {**kw, "entry_from_min": RULE4_MIN} for name, kw in {
            "3분 미갱신": {"hold_min": 3},
            "5분 미갱신": {"hold_min": 5},
            "10분 미갱신": {"hold_min": 10},
            "20분 미갱신": {"hold_min": 20},
            f"고정 -{FIXED_STOP_PCT:g}% 손절": {"hold_min": None, "fixed_stop": FIXED_STOP_PCT},
            "손절 없음": {"hold_min": None},
        }.items()}
        whole = load()
        report(build(rules, whole), "대금 top10 전체 · 10시 이후 진입")
        print()
        report(build(rules, whole[rule4_mask(whole)]), "4조건 통과만 · 10시 이후 진입")
        sys.exit()

    rules = {
        "2분 미갱신": {"hold_min": 2},
        "3분 미갱신": {"hold_min": 3},
        "5분 미갱신": {"hold_min": 5},
        "10분 미갱신": {"hold_min": 10},
        "3분+1% 밀림": {"hold_min": 3, "trigger_pct": 1.0},
        "5분+1% 밀림": {"hold_min": 5, "trigger_pct": 1.0},
        "10분+1% 밀림": {"hold_min": 10, "trigger_pct": 1.0},
        f"고정 -{FIXED_STOP_PCT:g}% 손절": {"hold_min": None, "fixed_stop": FIXED_STOP_PCT},
        "손절 없음": {"hold_min": None},
    }
    report(build(rules))
