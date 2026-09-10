"""10일 고점 대비 위치가 다음 움직임을 가르는가 — 사전등록
(`docs/HIGH10_POSITION_PREREGISTRATION.md`) 그대로 실행. (lead 지시, 사용자 발제
2026-09-02)

## 재사용 (중복 구현 금지)
- `daily_bar_prereg_measure`의 `build_calendar`/`rebalance_grid`/`portfolio_return`/
  `intraday_only_return`/`IS_RANGE`/`OOS_RANGE`/`HORIZON`/`REBALANCE_STEP`/`_split`
  — 신호와 무관한 범용 그리드/체결 헬퍼라 그대로 가져다 쓴다.
- `theme_rank_prereg_measure`의 `COST`(0.0052)/`T_CRIT`(1.65)/`one_sample_ttest`/
  `_verdict` — t검정 로직 중복 구현 금지.
- `universe.daily_top_n_from_local` — AL 대금상위 D-1 확정 유니버스.

## 신호
`ratio[c,t] = close[c,t] / max(high[c, t-10..t-1])` (당일 제외 직전 10거래일 고점).
bin 경계는 사전등록에 라운드넘버로 고정(breakout>=1.00, near>=0.95, far<0.95) —
데이터 보고 안 고름.

## 갭/장중 분리
TOTAL(t+1 시가 -> t+1+5거래일 종가, 실제 체결가능)과 INTRADAY(그 5일간 매일
시가->종가 복리, 갭 제외, 진단용)를 각각 기존 헬퍼로 구하고, GAP은 텔레스코핑
항등식 `(1+TOTAL)/(1+INTRADAY)-1`으로 잔차 계산(새 공식 아님).

실행: python -m backtesting.high10_position_prereg_measure
"""
import os
import time

import numpy as np
import pandas as pd

from backtesting.daily_bar_prereg_measure import (
    HORIZON,
    IS_RANGE,
    OOS_RANGE,
    _split,
    build_calendar,
    intraday_only_return,
    portfolio_return,
    rebalance_grid,
)
from backtesting.daily_cache import load_daily_all
from backtesting.theme_rank_prereg_measure import COST, T_CRIT, _verdict, one_sample_ttest
from backtesting.universe import daily_top_n_from_local

DAILY_DIR = "data/stocks/daily"
LOOKBACK = 10
TOP_N = 35
NEAR_BAND = 0.95
SENSITIVITY_BANDS = (0.97, 0.92)  # 3%p / 8%p, IS 전용 참고표(주 판정과 분리)
MIN_DAYS = 200
CONCENTRATION_TOPK = 5
CONCENTRATION_LIMIT = 0.50
BINS = ("breakout", "near", "far")

# (가설, bin, 예측방향) — 사전등록 §0/§9
HYPOTHESES = [("A(관성)", "breakout", "positive"), ("B(저항)", "near", "negative")]


def load_panel(daily_dir: str = DAILY_DIR) -> pd.DataFrame:
    panel = load_daily_all(daily_dir)[["date", "open", "high", "low", "close", "code"]]
    return panel.sort_values(["code", "date"]).reset_index(drop=True)


def _assign_bin(ratio: pd.Series, near_band: float) -> pd.Series:
    bins = np.select([ratio >= 1.0, ratio >= near_band], ["breakout", "near"], default="far")
    return pd.Series(bins, index=ratio.index, dtype=object).where(ratio.notna())


def add_features(panel: pd.DataFrame, near_band: float = NEAR_BAND) -> pd.DataFrame:
    panel = panel.copy()
    high10 = panel.groupby("code")["high"].transform(
        lambda s: s.shift(1).rolling(LOOKBACK, min_periods=LOOKBACK).max()
    )
    panel["high10"] = high10
    panel["ratio"] = panel["close"] / panel["high10"]
    panel["bin"] = _assign_bin(panel["ratio"], near_band)
    return panel


def load_universe_by_date(daily_dir: str = DAILY_DIR, top_n: int = TOP_N) -> dict[str, set[str]]:
    raw = daily_top_n_from_local(daily_dir, top_n)
    return {ts.strftime("%Y-%m-%d"): codes for ts, codes in raw.items()}


def compute_daily_series(panel: pd.DataFrame, universe_by_date: dict[str, set[str]],
                          bins: tuple[str, ...] = BINS) -> pd.DataFrame:
    """리밸런스 시점(비중첩, 5거래일 그리드)마다 bin별/유니버스 TOTAL·INTRADAY
    수익률 한 행. 표본 단위 = 그 날(§8)."""
    calendar = build_calendar(panel)
    grid = rebalance_grid(calendar)
    pivot_open = panel.pivot(index="date", columns="code", values="open")
    pivot_close = panel.pivot(index="date", columns="code", values="close")
    group_by_date = dict(tuple(panel.groupby("date")))

    rows = []
    for i in grid:
        t = calendar[i]
        entry_date, exit_date = calendar[i + 1], calendar[i + 1 + HORIZON]
        cross = group_by_date.get(t)
        universe = universe_by_date.get(t, set())
        if cross is None or not universe:
            continue
        cross = cross[cross["code"].isin(universe)]
        if cross.empty:
            continue

        row = {"date": t, "n_universe": len(cross)}
        u_codes = cross["code"].tolist()
        row["universe_total"], _ = portfolio_return(u_codes, entry_date, exit_date, pivot_open, pivot_close)
        row["universe_intraday"], _ = intraday_only_return(u_codes, calendar, i + 1, pivot_open, pivot_close)

        for b in bins:
            codes = cross.loc[cross["bin"] == b, "code"].tolist()
            total_ret, n = portfolio_return(codes, entry_date, exit_date, pivot_open, pivot_close)
            intraday_ret, _ = intraday_only_return(codes, calendar, i + 1, pivot_open, pivot_close)
            row[f"{b}_total"], row[f"{b}_intraday"], row[f"{b}_n"] = total_ret, intraday_ret, n
        rows.append(row)

    return pd.DataFrame(rows)


def add_derived(df: pd.DataFrame, bins: tuple[str, ...] = BINS) -> pd.DataFrame:
    df = df.copy()
    for b in bins:
        df[f"{b}_gap"] = (1 + df[f"{b}_total"]) / (1 + df[f"{b}_intraday"]) - 1
        df[f"{b}_total_net"] = df[f"{b}_total"] - COST
        df[f"{b}_intraday_net"] = df[f"{b}_intraday"] - COST
        df[f"{b}_excess_total"] = df[f"{b}_total"] - df["universe_total"]
        df[f"{b}_excess_intraday"] = df[f"{b}_intraday"] - df["universe_intraday"]
    return df


def _direction_ok(mean: float, t: float, direction: str) -> bool:
    if np.isnan(mean) or np.isnan(t):
        return False
    return (mean > 0 and t >= T_CRIT) if direction == "positive" else (mean < 0 and t <= -T_CRIT)


def _concentration_flag(values: np.ndarray, direction: str, topk: int = CONCENTRATION_TOPK,
                         limit: float = CONCENTRATION_LIMIT) -> tuple[bool, str]:
    v = values[~np.isnan(values)]
    if len(v) == 0:
        return False, "N/A(표본없음)"
    total = v.sum()
    sign_ok = (total > 0) if direction == "positive" else (total < 0)
    if not sign_ok or total == 0:
        return False, "N/A(부호불일치)"
    order = np.argsort(-v) if direction == "positive" else np.argsort(v)
    top_sum = v[order[:topk]].sum()
    ratio = top_sum / total
    return (ratio > limit), f"{ratio*100:.1f}%"


def evaluate_block(df: pd.DataFrame, bin_name: str, metric: str, direction: str,
                    hyp_label: str) -> list[str]:
    net_col, excess_col = f"{bin_name}_{metric}_net", f"{bin_name}_excess_{metric}"
    is_df = _split(df, IS_RANGE).dropna(subset=[net_col, excess_col])
    oos_df = _split(df, OOS_RANGE).dropna(subset=[net_col, excess_col])
    n_is, n_oos = len(is_df), len(oos_df)

    lines = [f"[{hyp_label}/{bin_name}/{metric}] IS 비어있지 않은 날={n_is} "
             f"(최소 {MIN_DAYS} {'충족' if n_is >= MIN_DAYS else '미달'}), OOS={n_oos}"]
    if n_is < MIN_DAYS:
        lines.append(f"[{hyp_label}/{bin_name}/{metric}] 판단보류 (표본부족)")
        return lines

    is_net = is_df[net_col].to_numpy(dtype=float)
    oos_net = oos_df[net_col].to_numpy(dtype=float) if n_oos else np.array([])
    is_excess = is_df[excess_col].to_numpy(dtype=float)

    mean_is, t_is, _ = one_sample_ttest(is_net)
    r1 = not _direction_ok(mean_is, t_is, direction)
    lines.append(f"  IS net 평균={mean_is*100:.3f}% t={t_is:.2f} -> R1({direction} 방향/유의성)="
                 f"{'발동' if r1 else '미발동'}")

    mean_ex, t_ex, _ = one_sample_ttest(is_excess)
    r2 = not _direction_ok(mean_ex, t_ex, direction)
    lines.append(f"  IS 초과분(대조군 대비) 평균={mean_ex*100:.3f}% t={t_ex:.2f} -> "
                 f"R2(대조군 무의미)={'발동' if r2 else '미발동'}")

    if n_oos == 0:
        r3 = True
        lines.append("  OOS 표본 0건 -> R3(OOS부호반전)=발동(비교불가로 실패 처리)")
        mean_oos = float("nan")
    else:
        mean_oos, t_oos, _ = one_sample_ttest(oos_net)
        r3 = np.sign(mean_oos) != np.sign(mean_is) if not np.isnan(mean_is) else True
        lines.append(f"  OOS net 평균={mean_oos*100:.3f}% t={t_oos:.2f} -> "
                     f"R3(OOS부호반전)={'발동' if r3 else '미발동'}")

    r5, r5_desc = _concentration_flag(is_net, direction)
    lines.append(f"  IS 상위{CONCENTRATION_TOPK}일 기여비율={r5_desc} -> R5(날짜편중)="
                 f"{'발동' if r5 else '미발동'}")

    n_flags = sum([r1, r2, r3, r5])
    if n_flags == 0:
        verdict = "PASS(잠정 채택)"
    elif n_flags == 1:
        verdict = "조건부 PASS(약함)"
    else:
        verdict = "REJECT"
    lines.append(f"[{hyp_label}/{bin_name}/{metric}] 발동 {n_flags}개 -> {_verdict(n_flags < 2, verdict)}")
    return lines


def sensitivity_table(panel_raw: pd.DataFrame, universe_by_date: dict[str, set[str]]) -> list[str]:
    """§7 민감도 확인 - IS만, 참고표(주 판정 안 바꿈)."""
    lines = ["[민감도] near-band 폭 변경 (IS 전용, 참고자료)"]
    for band in SENSITIVITY_BANDS:
        panel = add_features(panel_raw, near_band=band)
        df = add_derived(compute_daily_series(panel, universe_by_date))
        is_df = _split(df, IS_RANGE).dropna(subset=["near_total_net"])
        if len(is_df) < MIN_DAYS:
            lines.append(f"  near_band={band}: IS {len(is_df)}일 미달, 판단보류")
            continue
        mean, t, n = one_sample_ttest(is_df["near_total_net"].to_numpy(dtype=float))
        lines.append(f"  near_band={band}: IS TOTAL net 평균={mean*100:.3f}% t={t:.2f} n={n}")
    return lines


def report_descriptive(df: pd.DataFrame, bins: tuple[str, ...] = BINS) -> list[str]:
    lines = ["[기술통계] bin별 일평균 종목수 / 빈 날 비율 (IS+OOS 합산)"]
    for b in bins:
        n_col = f"{b}_n"
        nonzero = df[n_col] > 0
        lines.append(f"  {b}: 평균종목수(비어있지않은날)={df.loc[nonzero, n_col].mean():.1f}, "
                     f"빈 날 비율={(~nonzero).mean()*100:.1f}% ({(~nonzero).sum()}/{len(df)}일)")
    return lines


def main():
    t0 = time.time()
    print("일봉 패널 로드...", flush=True)
    panel_raw = load_panel()
    universe_by_date = load_universe_by_date()
    print(f"로드 {time.time()-t0:.1f}초 | {panel_raw['code'].nunique():,}종목, "
          f"{len(panel_raw):,}행, 유니버스 {len(universe_by_date):,}일", flush=True)

    panel = add_features(panel_raw)
    t1 = time.time()
    df = add_derived(compute_daily_series(panel, universe_by_date))
    print(f"일별 시계열 계산 {time.time()-t1:.1f}초 | 리밸런스 시점 {len(df):,}건", flush=True)

    os.makedirs("results", exist_ok=True)
    df.to_csv("results/high10_position_prereg_daily.csv", index=False)

    for line in report_descriptive(df):
        print(line, flush=True)
    print(flush=True)

    for hyp_label, bin_name, direction in HYPOTHESES:
        for metric in ("total", "intraday"):
            for line in evaluate_block(df, bin_name, metric, direction, hyp_label):
                print(line, flush=True)
        print(flush=True)

    for line in sensitivity_table(panel_raw, universe_by_date):
        print(line, flush=True)

    return df


if __name__ == "__main__":
    main()
