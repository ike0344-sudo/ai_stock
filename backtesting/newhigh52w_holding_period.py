"""52주 신고가+골든크로스 — 선별기 방향: 청산규칙 전부 버리고 보유기간만.
사전등록(`docs/NEWHIGH52W_HOLDING_PERIOD_PREREGISTRATION.md`) 그대로.
lead 8차지시(사용자 승인, 2026-09-02).

진입은 하나도 안 바꾼다. 청산은 오직 "N거래일 뒤 강제매도"
(`simulate_trades(..., stop_pct=None, target_pct=None, hold_days=N)`,
`_walk_exit`의 `max_idx` 배관 재사용 - 새 청산 분기 없음).

## 재사용
`newhigh52w_golden_cross.simulate_trades`(hold_days 인자),
`newhigh52w_portfolio_sim.simulate_window_portfolio`/`compute_mdd`,
`portfolio_sim.simulate_slot_portfolio`,
`newhigh52w_yearly_windows.universe_buy_and_hold`/`_codes_over_cap`,
`newhigh52w_stock_selection_control.population_b_codes`/
`random_population_distribution`(hold_days 인자),
`newhigh52w_rolling_windows.rolling_windows`.

실행: python -m backtesting.newhigh52w_holding_period
"""
import os

import numpy as np
import pandas as pd

import backtesting.newhigh52w_golden_cross as m
import backtesting.newhigh52w_portfolio_sim as pfs
import backtesting.newhigh52w_yearly_windows as yw
from backtesting.newhigh52w_rolling_windows import rolling_windows
from backtesting.newhigh52w_stock_selection_control import population_b_codes, random_population_distribution

N_GRID = [5, 10, 20, 40, 60, 120]
SLOT_GRID = [5, 10, 20, "unlimited"]
IS_FRACTION = 0.6


def resolve_slots(slot_spec, n_trades: int) -> int:
    """"무제한" = 그 조합의 실제 신호건수를 슬롯수로(스킵0 보장, 자본/신호건수로 진짜
    동일가중) - 사전등록 §"무제한" 구현정의, 새 포트폴리오 엔진 없음."""
    if slot_spec == "unlimited":
        return max(n_trades, 1)
    return slot_spec


def compute_calmar(portfolio_ret: float, mdd: float) -> float:
    return portfolio_ret if mdd == 0 else portfolio_ret / mdd


def run_real_grid(windows: list[tuple[str, str]], shares: pd.Series) -> pd.DataFrame:
    """N6 x 슬롯4 x 정의2 격자를 22개 창(또는 부분집합) 전부에 대해 실측. 반환 행 하나가
    (창,정의,N,슬롯) 한 조합."""
    rows = []
    for start, end in windows:
        print(f"[격자] {start}~{end} 실행...", flush=True)
        m.PERIOD_START, m.PERIOD_END = start, end
        panel_raw = m.load_panel()
        panel = m.add_features(panel_raw)
        for def_name in m.GOLDEN_CROSS_DEFS:
            for N in N_GRID:
                trades = m.simulate_trades(panel, shares, def_name, stop_pct=None, target_pct=None, hold_days=N)
                n_signals = len(trades)
                for slot_spec in SLOT_GRID:
                    slots = resolve_slots(slot_spec, n_signals)
                    sim = pfs.simulate_window_portfolio(trades, max_slots=slots)
                    rows.append({
                        "start": start, "end": end, "def": def_name, "N": N, "slot_spec": str(slot_spec),
                        "slots_resolved": slots, "n_signals": n_signals, "taken": sim["taken"],
                        "skipped": sim["skipped"], "portfolio_ret": sim["portfolio_ret"], "mdd": sim["mdd"],
                        "calmar": compute_calmar(sim["portfolio_ret"], sim["mdd"]),
                    })
    return pd.DataFrame(rows)


def rank_is(is_grid: pd.DataFrame) -> pd.DataFrame:
    return (is_grid.groupby(["def", "N", "slot_spec"])["calmar"].mean()
            .reset_index().sort_values("calmar", ascending=False).reset_index(drop=True))


def run_oos_eval(best_combo: dict, oos_real_rows: pd.DataFrame, oos_windows: list[tuple[str, str]],
                  shares: pd.Series) -> dict:
    """뽑힌 조합 하나만 OOS 9개 창에서: 실제(이미 계산된 격자에서 재사용, 재시뮬레이션 없음) +
    현금/유니버스/무작위A·B 대조군(이번에 처음 계산 - 격자패스엔 없던 것)."""
    def_name, N, slot_spec = best_combo["def"], best_combo["N"], best_combo["slot_spec"]
    rows, random_a_pooled, random_b_pooled = [], [], []

    for start, end in oos_windows:
        print(f"[OOS대조군] {start}~{end} 실행...", flush=True)
        m.PERIOD_START, m.PERIOD_END = start, end
        panel_raw = m.load_panel()
        panel = m.add_features(panel_raw)
        univ_ret, _univ_n = yw.universe_buy_and_hold(panel_raw, shares, start)
        pop_a = yw._codes_over_cap(panel_raw, shares, start)
        pop_b = population_b_codes(panel, pop_a)

        real_row = oos_real_rows[(oos_real_rows["start"] == start) & (oos_real_rows["def"] == def_name)
                                  & (oos_real_rows["N"] == N) & (oos_real_rows["slot_spec"] == str(slot_spec))]
        port_ret = float(real_row["portfolio_ret"].iloc[0]) if len(real_row) else float("nan")
        n_signals = int(real_row["n_signals"].iloc[0]) if len(real_row) else 0
        slots = int(real_row["slots_resolved"].iloc[0]) if len(real_row) else resolve_slots(slot_spec, 0)

        trades_for_dates = m.simulate_trades(panel, shares, def_name, stop_pct=None, target_pct=None, hold_days=N)
        entry_dates = trades_for_dates["entry_date"].tolist()

        rand_a, _drop_a = random_population_distribution(panel, entry_dates, pop_a, stop_pct=None,
                                                           target_pct=None, hold_days=N, max_slots=slots) \
            if entry_dates and pop_a else ([], 0)
        rand_b, _drop_b = random_population_distribution(panel, entry_dates, pop_b, stop_pct=None,
                                                           target_pct=None, hold_days=N, max_slots=slots) \
            if entry_dates and pop_b else ([], 0)
        random_a_pooled += rand_a
        random_b_pooled += rand_b

        rows.append({"start": start, "end": end, "n_signals": n_signals, "portfolio_ret": port_ret,
                     "universe_ret": univ_ret, "random_a_median": float(np.median(rand_a)) if rand_a else float("nan"),
                     "random_b_median": float(np.median(rand_b)) if rand_b else float("nan")})

    oos_df = pd.DataFrame(rows)
    med_port = float(oos_df["portfolio_ret"].median())
    med_univ = float(oos_df["universe_ret"].median())
    med_rand_b = float(np.median(random_b_pooled)) if random_b_pooled else float("nan")

    r1 = (not np.isnan(med_rand_b)) and med_port < med_rand_b
    r2 = (not np.isnan(med_univ)) and med_port < med_univ
    r3 = med_port <= 0
    return {
        "oos_df": oos_df, "median_portfolio_ret": med_port, "median_universe_ret": med_univ,
        "median_random_b_pooled": med_rand_b, "random_a_pooled": random_a_pooled,
        "random_b_pooled": random_b_pooled, "R1_below_random_b": r1, "R2_below_universe": r2,
        "R3_nonpositive": r3, "rejected": bool(r1 or r2 or r3),
    }


def turnover_cost_table(full_grid: pd.DataFrame) -> pd.DataFrame:
    """N별(무제한 슬롯 기준=스킵없는 진짜 회전) 총 거래건수·총비용. 무제한 슬롯이라야
    자본제약 없이 "그 신호를 다 받았으면 몇 번 거래했을지"를 보여준다."""
    unlimited = full_grid[full_grid["slot_spec"] == "unlimited"]
    g = unlimited.groupby(["def", "N"])["taken"].sum().reset_index()
    g["total_cost_pct_points"] = g["taken"] * m.COST * 100  # 건당 0.52%p x 건수(단순 합, 참고용)
    return g.sort_values(["def", "N"])


def main():
    shares = m.load_shares()
    windows = rolling_windows()
    n_is = int(len(windows) * IS_FRACTION)
    is_windows, oos_windows = windows[:n_is], windows[n_is:]
    is_starts, oos_starts = {w[0] for w in is_windows}, {w[0] for w in oos_windows}
    print(f"창 {len(windows)}개 (IS {len(is_windows)} / OOS {len(oos_windows)})", flush=True)

    full_grid = run_real_grid(windows, shares)
    os.makedirs("results", exist_ok=True)
    full_grid.to_csv("results/newhigh52w_holding_period_grid.csv", index=False)

    is_grid = full_grid[full_grid["start"].isin(is_starts)]
    is_summary = rank_is(is_grid)
    is_summary.to_csv("results/newhigh52w_holding_period_is_ranking.csv", index=False)
    best = is_summary.iloc[0]
    best_combo = {"def": best["def"], "N": int(best["N"]), "slot_spec": best["slot_spec"]}
    best_rank = 1
    print(f"\n[IS 1등] {best_combo} IS평균calmar={best['calmar']:.4f} (96칸 중 1등)", flush=True)

    oos_real_rows = full_grid[full_grid["start"].isin(oos_starts)]
    oos_eval = run_oos_eval(best_combo, oos_real_rows, oos_windows, shares)
    oos_eval["oos_df"].to_csv("results/newhigh52w_holding_period_oos.csv", index=False)

    cost_table = turnover_cost_table(full_grid)
    cost_table.to_csv("results/newhigh52w_holding_period_cost_turnover.csv", index=False)

    print(f"\n=== OOS 판정 ({best_combo}) ===", flush=True)
    print(f"OOS 포트폴리오수익 중앙값={oos_eval['median_portfolio_ret']*100:.3f}% "
          f"유니버스중앙값={oos_eval['median_universe_ret']*100:.3f}% "
          f"무작위B중앙값(풀링)={oos_eval['median_random_b_pooled']*100:.3f}%", flush=True)
    print(f"R1(무작위B미만)={oos_eval['R1_below_random_b']} R2(유니버스미만)={oos_eval['R2_below_universe']} "
          f"R3(0이하)={oos_eval['R3_nonpositive']} -> {'기각' if oos_eval['rejected'] else '채택(잠정)'}", flush=True)

    print("\n=== N별 회전·비용(무제한슬롯 기준) ===", flush=True)
    for _, r in cost_table.iterrows():
        print(f"[{r['def']}/N={r['N']}] 총거래={r['taken']}건 총비용(단순합)={r['total_cost_pct_points']:.2f}%p",
              flush=True)

    return full_grid, is_summary, best_combo, oos_eval, cost_table


if __name__ == "__main__":
    main()
