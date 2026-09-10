"""RL 알고리즘 대신 RL 규율 넷 적용 — 사전등록
(`docs/RL_DISCIPLINE_PREREGISTRATION.md`) 그대로 실행. (lead 6차지시,
2026-09-02) **RL 알고리즘 자체는 안 씀** — 새 백테스트 엔진도 안 만든다.

## 재사용 (새로 만든 건 접합부뿐)
- `portfolio_sim.simulate_slot_portfolio` — 5슬롯 포트폴리오
- `metrics._max_drawdown_pct`/`_sharpe_ratio` — 위험지표(SlotTrade->Trade
  어댑터만 신규, `newhigh52w_portfolio_sim.compute_mdd/compute_sharpe`)
- `grid_search._param_combinations` — 격자 생성
- `newhigh52w_golden_cross.simulate_trades`/`_walk_exit`/`COST` — 진입·청산
  (인자만 바꿔 씀, `_walk_exit`는 무작위 진입일 재추첨에도 그대로 재사용)
- `newhigh52w_rolling_windows.rolling_windows` — 22개 창

## 실행 순서 (사전등록 §순서 그대로)
(4) 무작위 진입 대조군을 먼저 돌린다. 묻히면 거기서 멈추고 (1)(2)(3)은
"실행 안 함"으로 보고서에 남긴다 - 코드도 그만큼만 돈다(안 쓸 계산을
미리 다 안 함).

실행: python -m backtesting.newhigh52w_rl_discipline
"""
import os

import numpy as np
import pandas as pd

import backtesting.newhigh52w_golden_cross as m
import backtesting.newhigh52w_portfolio_sim as pfs
import backtesting.portfolio_sim as ps
from backtesting.grid_search import _param_combinations
from backtesting.newhigh52w_rolling_windows import rolling_windows

N_SEEDS = 20
IS_FRACTION = 0.6
STOP_GRID = [0.04, 0.06, 0.08, 0.10, 0.12, 0.15]
TARGET_GRID = [0.08, 0.12, 0.16, 0.24, 0.32, 0.50, None]
LIVE_STOP, LIVE_TARGET = 0.08, 0.24  # 현행 규칙(격자 안의 한 점)

# 묻힘 판정 기준(사전등록 §규율4, 결과 보고 안 바꿈)
BURIED_MEDIAN_PCTL = 50.0
BURIED_WIN_SHARE = 0.5


def _code_arrays(panel: pd.DataFrame, code: str) -> dict:
    grp = panel[panel["code"] == code].sort_values("date").reset_index(drop=True)
    return {
        "opens": grp["open"].to_numpy(dtype=float), "highs": grp["high"].to_numpy(dtype=float),
        "lows": grp["low"].to_numpy(dtype=float), "closes": grp["close"].to_numpy(dtype=float),
        "dates": grp["date"].to_numpy(),
    }


def _random_trades(codes_multiset: list[str], code_arrays: dict, rng: np.random.Generator,
                    stop_pct: float = LIVE_STOP, target_pct: float | None = LIVE_TARGET) -> pd.DataFrame:
    """종목 분포(codes_multiset, 실제 신호와 동일 - 중복 포함)는 고정, 진입일만 그 종목의
    창 내 거래일 중 균등무작위로 재추첨. 청산은 `_walk_exit` 그대로(현행 룰 -8%/+24%만
    사용 - 타이밍 정보량만 격리, 사전등록 §규율4 한계 명시)."""
    rows = []
    for code in codes_multiset:
        arr = code_arrays[code]
        n = len(arr["opens"])
        if n < 2:
            continue
        entry_idx = int(rng.integers(0, n - 1))
        entry_price = arr["opens"][entry_idx]
        stop_price = entry_price * (1 - stop_pct)
        target_price = entry_price * (1 + target_pct) if target_pct is not None else np.inf
        exit_idx, exit_price, _reason = m._walk_exit(arr["opens"], arr["highs"], arr["lows"], arr["closes"],
                                                        entry_idx, stop_price, target_price)
        gross = exit_price / entry_price - 1
        rows.append({"code": code, "entry_date": str(arr["dates"][entry_idx]),
                     "exit_date": str(arr["dates"][exit_idx]), "net_pct": gross - m.COST})
    return pd.DataFrame(rows)


def random_control_distribution(panel: pd.DataFrame, real_trades: pd.DataFrame, n_seeds: int = N_SEEDS,
                                 stop_pct: float = LIVE_STOP, target_pct: float | None = LIVE_TARGET) -> list[float]:
    if real_trades.empty:
        return []
    codes_multiset = real_trades["code"].tolist()
    code_arrays = {c: _code_arrays(panel, c) for c in set(codes_multiset)}
    rets = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        rand_trades = _random_trades(codes_multiset, code_arrays, rng, stop_pct, target_pct)
        result = ps.simulate_slot_portfolio(pfs.to_candidates(rand_trades), initial_capital=pfs.DEFAULT_CAPITAL,
                                             max_concurrent_positions=pfs.DEFAULT_MAX_SLOTS)
        rets.append(result.final_capital / result.initial_capital - 1)
    return rets


def run_random_control(windows: list[tuple[str, str]], shares: pd.Series) -> pd.DataFrame:
    rows = []
    for start, end in windows:
        print(f"[(4)무작위대조군] {start}~{end} 실행...", flush=True)
        m.PERIOD_START, m.PERIOD_END = start, end
        panel_raw = m.load_panel()
        panel = m.add_features(panel_raw)
        for def_name in m.GOLDEN_CROSS_DEFS:
            real_trades = m.simulate_trades(panel, shares, def_name, stop_pct=LIVE_STOP, target_pct=LIVE_TARGET)
            n_signals = len(real_trades)
            if real_trades.empty:
                rows.append({"start": start, "end": end, "def": def_name, "n_signals": 0,
                             "real_portfolio_ret": float("nan"), "random_median": float("nan"),
                             "random_p25": float("nan"), "random_p75": float("nan"),
                             "percentile_rank": float("nan"), "n_seeds": 0})
                continue
            real_sim = pfs.simulate_window_portfolio(real_trades)
            rand_rets = random_control_distribution(panel, real_trades)
            rand_arr = np.array(rand_rets)
            pctl = float(100.0 * np.mean(rand_arr <= real_sim["portfolio_ret"]))
            rows.append({
                "start": start, "end": end, "def": def_name, "n_signals": n_signals,
                "real_portfolio_ret": real_sim["portfolio_ret"], "random_median": float(np.median(rand_arr)),
                "random_p25": float(np.percentile(rand_arr, 25)), "random_p75": float(np.percentile(rand_arr, 75)),
                "percentile_rank": pctl, "n_seeds": len(rand_rets),
            })
    return pd.DataFrame(rows)


def judge_buried(df: pd.DataFrame) -> dict:
    valid = df.dropna(subset=["percentile_rank"])
    median_pctl = float(valid["percentile_rank"].median()) if len(valid) else float("nan")
    win_share = float((valid["percentile_rank"] >= 50.0).mean()) if len(valid) else float("nan")
    buried = (median_pctl <= BURIED_MEDIAN_PCTL) or (win_share < BURIED_WIN_SHARE)
    return {"n_valid_combos": len(valid), "median_percentile": median_pctl,
            "win_share": win_share, "buried": bool(buried)}


def run_grid_and_is_oos(windows: list[tuple[str, str]], shares: pd.Series) -> tuple[pd.DataFrame, dict]:
    """규율(2)+(3). (4)에서 안 묻혔을 때만 호출한다."""
    n_is = int(len(windows) * IS_FRACTION)
    is_windows, oos_windows = windows[:n_is], windows[n_is:]
    grid = _param_combinations({"stop_pct": STOP_GRID, "target_pct": TARGET_GRID})

    rows = []
    for start, end in is_windows:
        print(f"[(2)/(3) IS] {start}~{end} 실행...", flush=True)
        m.PERIOD_START, m.PERIOD_END = start, end
        panel_raw = m.load_panel()
        panel = m.add_features(panel_raw)
        for def_name in m.GOLDEN_CROSS_DEFS:
            for combo in grid:
                trades = m.simulate_trades(panel, shares, def_name, **combo)
                sim = pfs.simulate_window_portfolio(trades)
                mdd = sim["mdd"]
                calmar = sim["portfolio_ret"] if mdd == 0 else sim["portfolio_ret"] / mdd
                rows.append({"phase": "IS", "start": start, "end": end, "def": def_name,
                             "stop_pct": combo["stop_pct"], "target_pct": combo["target_pct"],
                             "portfolio_ret": sim["portfolio_ret"], "mdd": mdd, "calmar": calmar,
                             "mdd_zero": mdd == 0})

    is_df = pd.DataFrame(rows)
    is_summary = (is_df.groupby(["def", "stop_pct", "target_pct"])["calmar"].mean()
                  .reset_index().sort_values("calmar", ascending=False))
    best = is_summary.iloc[0]
    best_params = {"def": best["def"], "stop_pct": best["stop_pct"], "target_pct": best["target_pct"]}
    print(f"[(3) IS 1등] {best_params} IS평균calmar={best['calmar']:.3f}", flush=True)

    oos_rows = []
    for start, end in oos_windows:
        print(f"[(3) OOS] {start}~{end} 실행...", flush=True)
        m.PERIOD_START, m.PERIOD_END = start, end
        panel_raw = m.load_panel()
        panel = m.add_features(panel_raw)
        trades = m.simulate_trades(panel, shares, best_params["def"],
                                    stop_pct=best_params["stop_pct"], target_pct=best_params["target_pct"])
        sim = pfs.simulate_window_portfolio(trades)
        mdd = sim["mdd"]
        calmar = sim["portfolio_ret"] if mdd == 0 else sim["portfolio_ret"] / mdd
        oos_rows.append({"phase": "OOS", "start": start, "end": end, **best_params,
                         "portfolio_ret": sim["portfolio_ret"], "mdd": mdd, "calmar": calmar, "mdd_zero": mdd == 0})
    oos_df = pd.DataFrame(oos_rows)

    return pd.concat([is_df, oos_df], ignore_index=True), {"is_summary": is_summary, "best_params": best_params,
                                                             "n_is": len(is_windows), "n_oos": len(oos_windows)}


def main():
    shares = m.load_shares()
    windows = rolling_windows()
    os.makedirs("results", exist_ok=True)

    control_df = run_random_control(windows, shares)
    control_df.to_csv("results/newhigh52w_rl_random_control.csv", index=False)
    verdict = judge_buried(control_df)
    print(f"\n=== (4) 무작위대조군 판정 === n유효조합={verdict['n_valid_combos']} "
          f"중앙백분위={verdict['median_percentile']:.1f} 승률(>=50%)={verdict['win_share']*100:.1f}% "
          f"-> {'묻힘(BURIED)' if verdict['buried'] else '안 묻힘'}", flush=True)

    if verdict["buried"]:
        print("\n묻혔다 - 사전등록대로 여기서 멈춘다. (1)(2)(3) 실행 안 함.", flush=True)
        return control_df, verdict, None, None

    print("\n안 묻혔다 - (1)(2)(3) 진행.", flush=True)
    grid_df, grid_meta = run_grid_and_is_oos(windows, shares)
    grid_df.to_csv("results/newhigh52w_rl_grid_is_oos.csv", index=False)
    grid_meta["is_summary"].to_csv("results/newhigh52w_rl_is_ranking.csv", index=False)
    return control_df, verdict, grid_df, grid_meta


if __name__ == "__main__":
    main()
