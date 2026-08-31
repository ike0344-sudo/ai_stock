"""ATR 기반 손절 vs 고정 2.5% 손절 A/B — strategy_1 워크포워드 비교.

기존 파이프라인(detect_final_entries → simulate_trade_path → tiered exit →
ML 워크포워드 → 슬롯 포트폴리오)을 그대로 쓰고, 바꾸는 건 손절폭 하나뿐이다.
TIERS도 손절폭에 비례해 스케일한다 — 손절만 넓히고 익절을 고정하면 손익비가
망가지기 때문.

R 배수는 거래별 실제 손절폭으로 나눈다. validate_strategy1.py는 전역
STOP_LOSS_PCT로 나누는데, 손절폭이 종목마다 달라지면 그 계산이 무의미해진다.

실행: python atr_stop_ab.py            (스캔 후 .cache/atr_ab_scan.pkl 캐시)
      python atr_stop_ab.py --rescan
"""
import argparse
import os
import pickle

import numpy as np
import pandas as pd

from backtesting.breakout_reversal import simulate_trade_path
from backtesting.final_strategy import (
    MIN_TRADE_VALUE,
    N_DAY_HIGH,
    RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    RECOMMENDED_PROBA_THRESHOLD,
    STOP_LOSS_PCT,
    TIERS,
    TOP_N,
    UNREACHABLE_PCT,
    WINDOW_MINUTES,
    detect_final_entries,
    evaluate_tiered_exit_from_path_with_exit_idx,
    load_kospi_regime_by_day,
)
from backtesting.ml.walk_forward import split as wf_split
from backtesting.ml_entry_filter import (
    FEATURE_COLUMNS,
    InsufficientTrainingDataError,
    extract_entry_features,
    predict_quality_proba,
    train_entry_filter_model,
)
from backtesting.portfolio_sim import simulate_slot_portfolio
from backtesting.universe import daily_top_n_from_local

MODEL_KWARGS = {"n_estimators": 300, "max_depth": 6, "min_samples_leaf": 20, "n_jobs": -1}
TRADE_COLUMNS = ["code", "entry_time", "exit_time", "pct"]
CACHE = os.path.join(".cache", "atr_ab_scan.pkl")
ATR_N = 20

# 비교할 손절 규칙: atr_pct(%) -> 손절폭(비율)
#
# 1차 결과에서 ATR 변형의 평균손절폭이 전부 상한선(5.99/7.99)에 붙었다 — 진입시점
# ATR% 중앙값이 7.64라 1.5배면 죄다 상한에 걸려, 사실상 고정 6%/8% 손절이었다.
# 그래서 고정 6%/8%를 대조군으로 넣는다. ATR 변형이 이들을 못 이기면 ATR은 불필요하고
# 상수만 넓히면 되는 것. 마지막 둘은 상한을 12%로 풀어 실제로 종목마다 변하게 한 것.
VARIANTS = {
    "고정 2.5% (현행)": lambda a: STOP_LOSS_PCT,
    "고정 6% (대조군)": lambda a: 0.06,
    "고정 8% (대조군)": lambda a: 0.08,
    "ATR1.0x 3~12%": lambda a: min(max(1.0 * a / 100, 0.03), 0.12),
    "ATR1.5x 3~12%": lambda a: min(max(1.5 * a / 100, 0.03), 0.12),
}


def atr_pct_series(daily: pd.DataFrame, n: int = ATR_N) -> pd.Series:
    """일자별 ATR%. shift(1)로 전일까지만 반영 — 진입일 당일 캔들을 쓰면 미래 참조."""
    tr = np.maximum(
        daily.high - daily.low,
        np.maximum((daily.high - daily.close.shift()).abs(), (daily.low - daily.close.shift()).abs()),
    )
    return (tr.rolling(n).mean() / daily.close * 100).shift(1)


def scan(data_dir: str = "data") -> pd.DataFrame:
    """진입 하나당 한 행. 경로를 메모리에 쌓지 않도록 변형별 pct/exit_idx를
    스캔 루프 안에서 바로 계산한다."""
    daily_top35 = daily_top_n_from_local(os.path.join(data_dir, "stocks", "daily"), top_n=TOP_N)
    regime_by_day = load_kospi_regime_by_day(data_dir)
    minute_dir = os.path.join(data_dir, "stocks", "minute")
    daily_dir = os.path.join(data_dir, "stocks", "daily")

    rows = []
    files = sorted(f for f in os.listdir(minute_dir) if f.endswith(".csv"))
    for i, filename in enumerate(files):
        if i % 100 == 0:
            print(f"  scan {i}/{len(files)} ... trades={len(rows)}", flush=True)
        code = filename[: -len(".csv")]
        daily_path = os.path.join(daily_dir, filename)
        if not os.path.exists(daily_path):
            continue
        minute_df = pd.read_csv(os.path.join(minute_dir, filename), index_col=0, parse_dates=True)
        daily_df = pd.read_csv(daily_path, index_col=0, parse_dates=True)

        entries = detect_final_entries(minute_df, daily_df, code, daily_top35, regime_by_day)
        if entries.sum() == 0:
            continue
        atr_by_day = atr_pct_series(daily_df)

        for pos in (j for j, v in enumerate(entries.to_numpy()) if v):
            entry_ts = minute_df.index[pos]
            atr = atr_by_day.get(entry_ts.normalize(), np.nan)
            # ATR 없는 종목(상장 20일 미만 등)은 양쪽 표본을 같게 유지하려고 통째로 제외
            if not np.isfinite(atr) or atr <= 0:
                continue
            path = simulate_trade_path(
                minute_df, pos, take_profit_pct=UNREACHABLE_PCT, stop_loss_pct=UNREACHABLE_PCT
            ).path
            row = {
                "code": code,
                "entry_time": entry_ts,
                "atr_pct": float(atr),
                **extract_entry_features(minute_df, pos, WINDOW_MINUTES, MIN_TRADE_VALUE, daily_df, N_DAY_HIGH),
            }
            for name, rule in VARIANTS.items():
                stop_pct = rule(atr)
                tiers = tuple(t * stop_pct / STOP_LOSS_PCT for t in TIERS)
                pct, exit_idx = evaluate_tiered_exit_from_path_with_exit_idx(path, tiers, stop_pct)
                row[f"pct::{name}"] = pct
                row[f"exit::{name}"] = minute_df.index[exit_idx]
                row[f"stop::{name}"] = stop_pct
            rows.append(row)
    return pd.DataFrame(rows)


def metrics(result, stop_by_key: dict) -> dict:
    """R 배수를 거래별 실제 손절폭으로 나눈다 — 손절폭이 종목마다 다르면 전역
    STOP_LOSS_PCT 나눗셈(validate_strategy1.py:131)은 의미가 없다."""
    taken = result.taken_trades
    n = len(taken)
    if n == 0:
        return dict(n_trades=0, win_rate_pct=0.0, profit_factor=0.0, avg_r=0.0,
                    total_return_pct=0.0, mdd_pct=0.0, avg_stop_pct=0.0)
    wins = [t for t in taken if t.profit > 0]
    gross_loss = -sum(t.profit for t in taken if t.profit <= 0)
    equity = peak = result.initial_capital
    mdd = 0.0
    for t in sorted(taken, key=lambda t: t.exit_time):
        equity += t.profit
        peak = max(peak, equity)
        if peak > 0:
            mdd = max(mdd, (peak - equity) / peak)
    stops = [stop_by_key[(t.code, t.entry_time)] for t in taken]
    return dict(
        n_trades=n,
        win_rate_pct=len(wins) / n * 100,
        profit_factor=(sum(t.profit for t in wins) / gross_loss) if gross_loss > 0 else float("inf"),
        avg_r=float(np.mean([t.pct / s for t, s in zip(taken, stops)])),
        total_return_pct=(result.final_capital / result.initial_capital - 1) * 100,
        mdd_pct=mdd * 100,
        avg_stop_pct=float(np.mean(stops)) * 100,
    )


def _variant_frame(df: pd.DataFrame, name: str):
    t = df.rename(columns={f"pct::{name}": "pct", f"exit::{name}": "exit_time"})
    stop_by_key = dict(zip(zip(df["code"], df["entry_time"]), df[f"stop::{name}"]))
    return t, stop_by_key


def walk_forward(df, name, train_days=240, test_days=60, step_days=60,
                 proba_threshold=RECOMMENDED_PROBA_THRESHOLD,
                 max_pos=RECOMMENDED_MAX_CONCURRENT_POSITIONS, capital=10_000_000):
    t, stop_by_key = _variant_frame(df, name)
    splits = wf_split(t["entry_time"].min().date(), t["entry_time"].max().date(),
                      train_days, test_days, step_days)
    oos = []
    for sp in splits:
        is_df = t[t["entry_time"].dt.date.between(sp.train_start, sp.train_end)]
        oos_df = t[t["entry_time"].dt.date.between(sp.test_start, sp.test_end)]
        if oos_df.empty:
            continue
        try:
            trained = train_entry_filter_model(
                is_df[FEATURE_COLUMNS], (is_df["pct"] > 0).astype(int),
                model_type="random_forest", **MODEL_KWARGS,
            )
        except InsufficientTrainingDataError:
            continue
        proba = predict_quality_proba(trained, oos_df[FEATURE_COLUMNS])
        oos.append(oos_df.loc[proba[proba >= proba_threshold].index])
    combined = pd.concat(oos) if oos else t.iloc[0:0]
    return metrics(simulate_slot_portfolio(combined[TRADE_COLUMNS], capital, max_pos), stop_by_key)


def no_filter(df, name, max_pos=RECOMMENDED_MAX_CONCURRENT_POSITIONS, capital=10_000_000):
    t, stop_by_key = _variant_frame(df, name)
    return metrics(simulate_slot_portfolio(t[TRADE_COLUMNS], capital, max_pos), stop_by_key)


def show(title, rows):
    print(f"\n=== {title} ===")
    print(f"{'손절 규칙':18s} {'거래수':>6s} {'승률%':>7s} {'손익비':>7s} {'평균R':>7s} {'총수익%':>9s} {'MDD%':>7s} {'평균손절%':>9s}")
    for label, m in rows:
        pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(f"{label:18s} {m['n_trades']:>6d} {m['win_rate_pct']:>7.1f} {pf:>7s} "
              f"{m['avg_r']:>7.2f} {m['total_return_pct']:>9.1f} {m['mdd_pct']:>7.1f} {m['avg_stop_pct']:>9.2f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rescan", action="store_true")
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    if args.rescan or not os.path.exists(CACHE):
        print("스캔 중 (수 분 소요)...", flush=True)
        df = scan(args.data_dir)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "wb") as fh:
            pickle.dump(df, fh)
    else:
        with open(CACHE, "rb") as fh:
            df = pickle.load(fh)

    print(f"\n총 진입 {len(df)}건 · {df['entry_time'].min().date()} ~ {df['entry_time'].max().date()}")
    print(f"진입시점 ATR% — 중앙값 {df['atr_pct'].median():.2f} / 25% {df['atr_pct'].quantile(.25):.2f} "
          f"/ 75% {df['atr_pct'].quantile(.75):.2f} / 최대 {df['atr_pct'].max():.2f}")

    show("ML필터 없음 (조건1~8 + tiered exit, 전체표본)", [(n, no_filter(df, n)) for n in VARIANTS])
    show("ML필터 워크포워드 OOS (신뢰 가능)", [(n, walk_forward(df, n)) for n in VARIANTS])


if __name__ == "__main__":
    main()
