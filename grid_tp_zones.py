"""손절 -2% 고정, 익절 목표치를 포함한 넓은 파라미터 구간에서 승률>=60% 지점 탐색.

단일 시뮬레이션(익절 사실상 무제한)으로 경로를 뽑아, 여러 익절 후보값에 대한
결과를 한번에 평가하는 방식으로 효율화한다.
"""
import os
import random

import pandas as pd

from backtesting.breakout_reversal import detect_entries, simulate_trade_path

SPLIT_DATE = pd.Timestamp("2026-03-26")
STOP_LOSS_PCT = 0.02  # 고정
UNREACHABLE_TP = 0.999  # 사실상 무제한 (경로 전체를 뽑기 위한 트릭)

random.seed(42)
all_codes = [f.replace(".csv", "") for f in os.listdir("data/stocks/minute")]
sample_codes = random.sample(all_codes, 60)

train_prep, test_prep = {}, {}
for code in sample_codes:
    df = pd.read_csv(f"data/stocks/minute/{code}.csv", index_col=0, parse_dates=True)
    for split_name, prep_dict, cond in [("train", train_prep, df.index < SPLIT_DATE), ("test", test_prep, df.index >= SPLIT_DATE)]:
        sub = df[cond]
        if not sub.empty:
            prep_dict[code] = sub

print(f"train={len(train_prep)} test={len(test_prep)}", flush=True)

window_minutes_grid = [3, 5]
min_trade_value_grid = [4_000_000_000, 6_000_000_000, 10_000_000_000]
min_return_pct_grid = [0.01, 0.015, 0.02, 0.03]
tp_candidates = [0.005, 0.008, 0.01, 0.015, 0.02, 0.025, 0.03]


def run_paths(data_dict, window_minutes, min_trade_value, min_return_pct):
    """(stock, entry_idx)별 무제한익절 경로들을 모아 반환."""
    all_paths = []
    for code, df in data_dict.items():
        entries = detect_entries(df, window_minutes, min_trade_value, min_return_pct)
        if entries.sum() == 0:
            continue
        entry_positions = [i for i, v in enumerate(entries.to_numpy()) if v]
        for i in entry_positions:
            path = simulate_trade_path(df, i, take_profit_pct=UNREACHABLE_TP, stop_loss_pct=STOP_LOSS_PCT)
            all_paths.append(path)
    return all_paths


def evaluate_at_tp(paths, tp):
    pcts = []
    for path in paths:
        hit = next((net_pct for _, net_pct, _ in path.path if net_pct >= tp), None)
        pcts.append(tp if hit is not None else path.net_pnl_pct)
    pcts = pd.Series(pcts)
    return len(pcts), (pcts > 0).mean(), pcts.mean()


results = []
for wm in window_minutes_grid:
    for mtv in min_trade_value_grid:
        for mrp in min_return_pct_grid:
            paths = run_paths(train_prep, wm, mtv, mrp)
            if len(paths) < 20:
                continue
            for tp in tp_candidates:
                n, win_rate, avg_pnl = evaluate_at_tp(paths, tp)
                results.append(
                    {"window_minutes": wm, "min_trade_value_eok": mtv / 1e8, "min_return_pct": mrp,
                     "take_profit_pct": tp, "n_trades": n, "win_rate": win_rate, "avg_pnl_pct": avg_pnl}
                )
            print(f"done: window={wm} trade_value={mtv/1e8}억 return={mrp} (paths={len(paths)})", flush=True)

results_df = pd.DataFrame(results)
qualified = results_df[results_df["n_trades"] >= 30]
top15 = qualified.sort_values("win_rate", ascending=False).head(15)
print("\n=== TRAIN 승률 상위 15 ===", flush=True)
print(top15.to_string(index=False), flush=True)

above_60 = qualified[qualified["win_rate"] >= 0.60]
print(f"\n=== 승률 60% 이상 조합 수: {len(above_60)} ===", flush=True)
if not above_60.empty:
    print(above_60.sort_values("win_rate", ascending=False).to_string(index=False), flush=True)

# TRAIN 상위 8개를 TEST에서 재검증
print("\n=== TEST(아웃오브샘플) 재검증 ===", flush=True)
test_rows = []
for _, row in top15.head(8).iterrows():
    test_paths = run_paths(test_prep, int(row["window_minutes"]), row["min_trade_value_eok"] * 1e8, row["min_return_pct"])
    if not test_paths:
        continue
    n, win_rate, avg_pnl = evaluate_at_tp(test_paths, row["take_profit_pct"])
    test_rows.append(
        {
            "window_minutes": row["window_minutes"], "min_trade_value_eok": row["min_trade_value_eok"],
            "min_return_pct": row["min_return_pct"], "take_profit_pct": row["take_profit_pct"],
            "train_win_rate": row["win_rate"], "train_avg_pnl": row["avg_pnl_pct"],
            "test_n_trades": n, "test_win_rate": win_rate, "test_avg_pnl": avg_pnl,
        }
    )
    print(test_rows[-1], flush=True)

with open("grid_tp_zones_results.txt", "w", encoding="utf-8") as f:
    f.write("=== TRAIN top15 ===\n" + top15.to_string(index=False) + "\n\n")
    f.write(f"=== 60%+ combos: {len(above_60)} ===\n")
    if not above_60.empty:
        f.write(above_60.to_string(index=False) + "\n\n")
    f.write("=== TEST ===\n" + pd.DataFrame(test_rows).to_string(index=False) + "\n")
