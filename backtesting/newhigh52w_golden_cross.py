"""52주 신고가 + 골든크로스 진입 백테스트 — 사전등록
(`docs/NEWHIGH52W_GOLDEN_CROSS_PREREGISTRATION.md`) 그대로 실행.
(큐 지시, 사용자 직접지시 2026-09-02)

## 재사용
`daily_cache.load_daily_all`(파케이 캐시), `theme_rank_prereg_measure.COST`
(0.52% 왕복, 재사용 — 새 비용상수 정의 안 함).

실행: python -m backtesting.newhigh52w_golden_cross
"""
import os
import time

import numpy as np
import pandas as pd

from backtesting.daily_cache import load_daily_all
from backtesting.theme_rank_prereg_measure import COST

UNIVERSE_CSV = "kospi-theme-engine/data/reference/universe.csv"
LOOKBACK_52W = 252
MARKET_CAP_MIN = 3_000_000_000_000  # 3조원
PERIOD_START = "2025-09-01"
PERIOD_END = "2026-08-31"
STOP_PCT = 0.08
TARGET_PCT = 0.24
GOLDEN_CROSS_DEFS = {"5_20": (5, 20), "20_60": (20, 60)}
CONCENTRATION_TOPK = 5


def load_panel() -> pd.DataFrame:
    panel = load_daily_all()[["date", "open", "high", "low", "close", "code"]]
    panel = panel[panel["date"] <= PERIOD_END]  # 사전등록 §1: 로컬 데이터가 더 길어도 지정 종료일까지만
    return panel.sort_values(["code", "date"]).reset_index(drop=True)


def load_shares(path: str = UNIVERSE_CSV) -> pd.Series:
    u = pd.read_csv(path, dtype={"code": str})
    return u.set_index("code")["shares"]


def add_features(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    g = panel.groupby("code")
    panel["high252"] = g["high"].transform(
        lambda s: s.shift(1).rolling(LOOKBACK_52W, min_periods=LOOKBACK_52W).max()
    )
    panel["newhigh"] = panel["close"] > panel["high252"]

    for w in sorted({v for pair in GOLDEN_CROSS_DEFS.values() for v in pair}):
        panel[f"sma{w}"] = g["close"].transform(lambda s, w=w: s.rolling(w, min_periods=w).mean())

    g2 = panel.groupby("code")
    for name, (short, long_) in GOLDEN_CROSS_DEFS.items():
        s_now, l_now = panel[f"sma{short}"], panel[f"sma{long_}"]
        s_prev, l_prev = g2[f"sma{short}"].shift(1), g2[f"sma{long_}"].shift(1)
        panel[f"golden_{name}"] = (s_prev <= l_prev) & (s_now > l_now)
        panel[f"signal_{name}"] = panel["newhigh"] & panel[f"golden_{name}"]
    return panel


def _walk_exit(opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                entry_idx: int, stop_price: float, target_price: float,
                max_idx: int | None = None) -> tuple[int, float, str]:
    """진입일(entry_idx)부터 매일 고가/저가로 손절/익절 판정. 같은 날 둘 다 닿으면 손절
    우선(사전등록 §4). 체결가: 손절은 min(시가,손절가)(갭다운 시 시가 - 낙관적으로 안 잡음),
    익절은 목표가 그대로(갭업 초과분 안 얹음 - 보수적). 끝까지 안 닿으면 마지막 종가로 만료.

    `max_idx`(선택, 기본 None=하위호환): 지정하면 그 인덱스(포함)까지만 걷는다 - 손절/익절이
    한 번도 안 걸려도 `min(max_idx, n-1)`에서 강제로 "만료" 처리(보유기간 N=`entry_idx+N`을
    max_idx로 넘겨 구현 - lead 8차지시, `newhigh52w_holding_period.py`). 새 청산 분기 없음,
    기존 stop/target 판정 로직 그대로에 걷는 범위만 좁힘."""
    n = len(opens)
    end = n if max_idx is None else min(n, max_idx + 1)
    for j in range(entry_idx, end):
        hit_stop, hit_target = lows[j] <= stop_price, highs[j] >= target_price
        if hit_stop:
            return j, min(stop_price, opens[j]), "stop_both" if hit_target else "stop"
        if hit_target:
            return j, target_price, "target"
    last = end - 1
    return last, closes[last], "expiry"


def simulate_trades(panel: pd.DataFrame, shares: pd.Series, def_name: str,
                     stop_pct: float | None = STOP_PCT, target_pct: float | None = TARGET_PCT,
                     hold_days: int | None = None) -> pd.DataFrame:
    """stop_pct/target_pct 기본값은 사전등록 규칙(-8%/+24%) 그대로 - 진입 로직은 안 바꾸고
    청산만 격리해서 비교하려는 후속 지시(lead, 2026-09-02 B항)를 위해 선택적으로 바꿀 수 있게
    열어둠. `None`이면 그 경계를 끄는 것(무한대) - `target_pct=None`은 "익절 상한 없음",
    `stop_pct=target_pct=None`은 "청산 없음(구간 끝까지 보유)"과 동치(둘 다 안 걸려 `_walk_exit`가
    자연히 만료/마지막종가로 떨어짐 - 새 분기 안 만듦).

    `hold_days`(선택, 기본 None): 지정하면 `entry_idx+hold_days`를 `_walk_exit`의 `max_idx`로
    넘겨 그 이상은 안 본다 - "N거래일 뒤 무조건 매도"(lead 8차지시, 손절·익절 전부 끔:
    `stop_pct=target_pct=None, hold_days=N`으로 호출). 이 반환 exit_idx가 그대로 다음 신호
    스킵판정(`pos_open_end`)에 쓰이므로 보유기간이 짧을수록 재진입 기회가 자연히 늘어난다
    (새 게이팅 로직 없음 - 기존 로직이 그대로 정확한 exit_idx를 받아 처리)."""
    trades = []
    sig_col = f"signal_{def_name}"
    for code, grp in panel.groupby("code"):
        share_ct = shares.get(code, np.nan)
        if np.isnan(share_ct):
            continue  # 사전등록 §2: shares 없는 종목은 필터 대상에서 아예 제외
        grp = grp.reset_index(drop=True)
        sig = grp[sig_col].to_numpy()
        opens, highs = grp["open"].to_numpy(dtype=float), grp["high"].to_numpy(dtype=float)
        lows, closes = grp["low"].to_numpy(dtype=float), grp["close"].to_numpy(dtype=float)
        dates = grp["date"].to_numpy()
        n = len(grp)
        pos_open_end = -1

        for t in np.flatnonzero(sig):
            if t <= pos_open_end:
                continue  # 이미 포지션 보유 중(사전등록 §4 구현결정) - 중복 스킵
            entry_idx = t + 1
            if entry_idx >= n:
                continue
            entry_date = str(dates[entry_idx])
            if not (PERIOD_START <= entry_date <= PERIOD_END):
                continue
            cap = share_ct * closes[entry_idx]
            if cap < MARKET_CAP_MIN:
                continue

            entry_price = opens[entry_idx]
            stop_price = entry_price * (1 - stop_pct) if stop_pct is not None else -np.inf
            target_price = entry_price * (1 + target_pct) if target_pct is not None else np.inf
            max_idx = entry_idx + hold_days if hold_days is not None else None
            exit_idx, exit_price, reason = _walk_exit(opens, highs, lows, closes, entry_idx,
                                                        stop_price, target_price, max_idx=max_idx)
            gross = exit_price / entry_price - 1
            trades.append({
                "code": code, "def": def_name, "signal_date": str(dates[t]),
                "entry_date": entry_date, "entry_price": entry_price,
                "exit_date": str(dates[exit_idx]), "exit_reason": reason,
                "exit_price": exit_price, "gross_pct": gross, "net_pct": gross - COST,
                "market_cap": cap, "hold_days": exit_idx - entry_idx,
            })
            pos_open_end = exit_idx

    return pd.DataFrame(trades)


def buy_and_hold_control(panel: pd.DataFrame, codes: list[str]) -> tuple[float, int]:
    """§6: 같은 기간(2025-09-01~2026-08-31) 같은 종목군 단순보유, 동일가중 평균."""
    rets = []
    for code in codes:
        grp = panel[(panel["code"] == code) & (panel["date"] >= PERIOD_START)]
        if grp.empty:
            continue
        grp = grp.sort_values("date")
        rets.append(grp["close"].iloc[-1] / grp["close"].iloc[0] - 1)
    return (float(np.mean(rets)) if rets else float("nan")), len(rets)


def summarize(trades: pd.DataFrame, panel: pd.DataFrame, def_name: str) -> list[str]:
    lines = [f"=== 정의 {def_name} ==="]
    if trades.empty:
        return lines + ["  거래 0건 - 판정 불가(표본부족)"]

    n = len(trades)
    win_rate = (trades["net_pct"] > 0).mean()
    gross_mean, net_mean = trades["gross_pct"].mean(), trades["net_pct"].mean()
    reason_counts = trades["exit_reason"].value_counts().to_dict()
    n_codes = trades["code"].nunique()
    max_per_code = trades["code"].value_counts().max()

    ctrl_ret, ctrl_n = buy_and_hold_control(panel, trades["code"].unique().tolist())

    lines += [
        f"  거래건수={n} (서로다른종목={n_codes}, 한종목최대거래수={max_per_code})",
        f"  승률(net>0)={win_rate*100:.1f}%",
        f"  거래당 평균 gross={gross_mean*100:.3f}% / net={net_mean*100:.3f}%",
        f"  청산사유: {reason_counts}",
        f"  대조군(동일종목군 단순보유, {PERIOD_START}~{PERIOD_END})={ctrl_ret*100:.3f}% (n={ctrl_n}종목) "
        f"-> 전략(net) {'초과' if net_mean > ctrl_ret else '못 이김'} "
        f"(초과분={(net_mean-ctrl_ret)*100:.3f}%p)",
    ]

    by_month = trades["entry_date"].str[:7].value_counts().sort_index()
    lines.append(f"  진입월별 건수: {by_month.to_dict()}")

    top_codes = trades["code"].value_counts().head(CONCENTRATION_TOPK).to_dict()
    lines.append(f"  종목별 거래건수 상위{CONCENTRATION_TOPK}: {top_codes}")
    return lines


def main():
    t0 = time.time()
    print("일봉 패널 로드...", flush=True)
    panel_raw = load_panel()
    shares = load_shares()
    print(f"로드 {time.time()-t0:.1f}초 | {panel_raw['code'].nunique():,}종목, "
          f"{len(panel_raw):,}행, shares 있는 종목 {shares.notna().sum():,}", flush=True)

    panel = add_features(panel_raw)

    os.makedirs("results", exist_ok=True)
    all_trades = []
    for def_name in GOLDEN_CROSS_DEFS:
        t1 = time.time()
        trades = simulate_trades(panel, shares, def_name)
        print(f"[{def_name}] 시뮬레이션 {time.time()-t1:.1f}초 | 신호->거래 {len(trades)}건", flush=True)
        trades.to_csv(f"results/newhigh52w_golden_cross_{def_name}.csv", index=False)
        all_trades.append(trades)

    print(flush=True)
    for def_name, trades in zip(GOLDEN_CROSS_DEFS, all_trades):
        for line in summarize(trades, panel_raw, def_name):
            print(line, flush=True)
        print(flush=True)

    return all_trades


if __name__ == "__main__":
    main()
