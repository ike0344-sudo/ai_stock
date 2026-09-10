"""52주 신고가+골든크로스 — 나머지 절반: 종목선택에 정보가 있는가.
사전등록(`docs/RL_DISCIPLINE_STOCK_SELECTION_PREREGISTRATION.md`) 그대로.
lead 7차지시(2026-09-02) — **이 줄기의 마지막 라운드.**

지난 라운드(`newhigh52w_rl_discipline.py`)와 대칭: 거기선 종목 고정·타이밍
무작위였다. 여기선 **타이밍(entry_date) 고정·종목 무작위**. 대조군 둘:
(A) 그 창 3조+ 전체 유니버스 무작위, (B) 그중 그 창에 52주 신고가를 낸
종목만 무작위(골든크로스가 더하는 게 있는지는 이걸로만 판단).

## 재사용 (새 백테스트 로직 없음)
`newhigh52w_golden_cross._walk_exit`/`COST`/`simulate_trades`,
`newhigh52w_portfolio_sim.to_candidates`/`simulate_window_portfolio`,
`newhigh52w_yearly_windows._codes_over_cap`,
`newhigh52w_rolling_windows.rolling_windows`,
`newhigh52w_rl_discipline._code_arrays`/`judge_buried`,
`portfolio_sim.simulate_slot_portfolio`.

실행: python -m backtesting.newhigh52w_stock_selection_control
"""
import os

import numpy as np
import pandas as pd

import backtesting.newhigh52w_golden_cross as m
import backtesting.newhigh52w_portfolio_sim as pfs
import backtesting.newhigh52w_yearly_windows as yw
import backtesting.portfolio_sim as ps
from backtesting.newhigh52w_rl_discipline import N_SEEDS, _code_arrays, judge_buried
from backtesting.newhigh52w_rolling_windows import rolling_windows

LIVE_STOP, LIVE_TARGET = 0.08, 0.24


def population_b_codes(panel: pd.DataFrame, population_a: list[str]) -> list[str]:
    """그 창 기간 중 하루라도 newhigh였던 종목(A의 부분집합) - `add_features`가 이미
    계산해 둔 `newhigh` 컬럼 재사용, 새 신호계산 없음."""
    a_set = set(population_a)
    hit = panel.loc[panel["newhigh"].fillna(False) & panel["code"].isin(a_set), "code"]
    return sorted(hit.unique().tolist())


def _random_stock_trades(entry_dates: list[str], population: list[str], panel: pd.DataFrame,
                          rng: np.random.Generator, code_cache: dict,
                          stop_pct: float | None = LIVE_STOP, target_pct: float | None = LIVE_TARGET,
                          hold_days: int | None = None) -> tuple[pd.DataFrame, int]:
    """entry_dates(실제 신호 그대로, 순서·중복 유지) 각각에 population에서 균등무작위로
    뽑은 종목을 배정. 그 종목이 그 날짜(또는 그 다음 첫 거래일)에 데이터가 없으면(창
    끝 이후로 밀려나거나 상장폐지 등) 드롭 - 드롭 건수도 같이 반환.

    `hold_days`(선택, 기본 None=기존 stop/target 방식): 지정하면 손절·익절 대신 N거래일
    강제매도(`simulate_trades`와 같은 `_walk_exit(max_idx=...)` 배관, lead 8차지시)."""
    rows, dropped = [], 0
    for entry_date in entry_dates:
        code = rng.choice(population)
        arr = code_cache.get(code)
        if arr is None:
            arr = _code_arrays(panel, code)
            code_cache[code] = arr
        dates = arr["dates"]
        if len(dates) == 0:
            dropped += 1
            continue
        entry_idx = int(np.searchsorted(dates, entry_date, side="left"))
        if entry_idx >= len(dates):
            dropped += 1
            continue
        entry_price = arr["opens"][entry_idx]
        stop_price = entry_price * (1 - stop_pct) if stop_pct is not None else -np.inf
        target_price = entry_price * (1 + target_pct) if target_pct is not None else np.inf
        max_idx = entry_idx + hold_days if hold_days is not None else None
        exit_idx, exit_price, _reason = m._walk_exit(arr["opens"], arr["highs"], arr["lows"], arr["closes"],
                                                        entry_idx, stop_price, target_price, max_idx=max_idx)
        gross = exit_price / entry_price - 1
        rows.append({"code": code, "entry_date": str(dates[entry_idx]), "exit_date": str(dates[exit_idx]),
                     "net_pct": gross - m.COST})
    return pd.DataFrame(rows), dropped


def random_population_distribution(panel: pd.DataFrame, entry_dates: list[str], population: list[str],
                                    n_seeds: int = N_SEEDS, stop_pct: float | None = LIVE_STOP,
                                    target_pct: float | None = LIVE_TARGET,
                                    hold_days: int | None = None,
                                    max_slots: int = pfs.DEFAULT_MAX_SLOTS) -> tuple[list[float], int]:
    if not population or not entry_dates:
        return [], 0
    code_cache: dict = {}
    rets, total_dropped = [], 0
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        rand_trades, dropped = _random_stock_trades(entry_dates, population, panel, rng, code_cache,
                                                      stop_pct=stop_pct, target_pct=target_pct, hold_days=hold_days)
        total_dropped += dropped
        result = ps.simulate_slot_portfolio(pfs.to_candidates(rand_trades), initial_capital=pfs.DEFAULT_CAPITAL,
                                             max_concurrent_positions=max_slots)
        rets.append(result.final_capital / result.initial_capital - 1)
    return rets, total_dropped


def run_stock_selection_control(windows: list[tuple[str, str]], shares: pd.Series) -> pd.DataFrame:
    rows = []
    for start, end in windows:
        print(f"[종목선택대조군] {start}~{end} 실행...", flush=True)
        m.PERIOD_START, m.PERIOD_END = start, end
        panel_raw = m.load_panel()
        panel = m.add_features(panel_raw)
        pop_a = yw._codes_over_cap(panel_raw, shares, start)
        pop_b = population_b_codes(panel, pop_a)

        for def_name in m.GOLDEN_CROSS_DEFS:
            real_trades = m.simulate_trades(panel, shares, def_name, stop_pct=LIVE_STOP, target_pct=LIVE_TARGET)
            n_signals = len(real_trades)
            if real_trades.empty:
                for pop_name in ("A_전체유니버스", "B_52주신고가만"):
                    rows.append(_na_row(start, end, def_name, pop_name, n_signals))
                continue

            real_sim = pfs.simulate_window_portfolio(real_trades)
            entry_dates = real_trades["entry_date"].tolist()

            for pop_name, population in (("A_전체유니버스", pop_a), ("B_52주신고가만", pop_b)):
                if not population:
                    rows.append(_na_row(start, end, def_name, pop_name, n_signals))
                    continue
                rand_rets, dropped = random_population_distribution(panel, entry_dates, population)
                if not rand_rets:
                    rows.append(_na_row(start, end, def_name, pop_name, n_signals))
                    continue
                rand_arr = np.array(rand_rets)
                pctl = float(100.0 * np.mean(rand_arr <= real_sim["portfolio_ret"]))
                rows.append({
                    "start": start, "end": end, "def": def_name, "population": pop_name,
                    "n_signals": n_signals, "population_size": len(population),
                    "real_portfolio_ret": real_sim["portfolio_ret"], "random_median": float(np.median(rand_arr)),
                    "random_p25": float(np.percentile(rand_arr, 25)), "random_p75": float(np.percentile(rand_arr, 75)),
                    "percentile_rank": pctl, "n_seeds": len(rand_rets), "dropped_draws": dropped,
                })
    return pd.DataFrame(rows)


def _na_row(start, end, def_name, pop_name, n_signals) -> dict:
    return {"start": start, "end": end, "def": def_name, "population": pop_name, "n_signals": n_signals,
            "population_size": 0, "real_portfolio_ret": float("nan"), "random_median": float("nan"),
            "random_p25": float("nan"), "random_p75": float("nan"), "percentile_rank": float("nan"),
            "n_seeds": 0, "dropped_draws": 0}


def main():
    shares = m.load_shares()
    windows = rolling_windows()
    os.makedirs("results", exist_ok=True)

    df = run_stock_selection_control(windows, shares)
    df.to_csv("results/newhigh52w_stock_selection_control.csv", index=False)

    print("\n=== 대조군별 묻힘 판정 (44개 조합 합산) ===", flush=True)
    verdicts = {}
    for pop_name in ("A_전체유니버스", "B_52주신고가만"):
        sub = df[df["population"] == pop_name]
        v = judge_buried(sub)
        verdicts[pop_name] = v
        print(f"[{pop_name}] n유효={v['n_valid_combos']} 중앙백분위={v['median_percentile']:.1f} "
              f"승률={v['win_share']*100:.1f}% -> {'묻힘' if v['buried'] else '안 묻힘'}", flush=True)

    a_buried, b_buried = verdicts["A_전체유니버스"]["buried"], verdicts["B_52주신고가만"]["buried"]
    if a_buried and b_buried:
        verdict_label = "둘 다 묻힘 - 줄기 완전 종결"
    elif (not a_buried) and b_buried:
        verdict_label = "A만 안 묻힘 - 매매신호 아니라 종목선별기 성격(골든크로스 무의미)"
    elif (not a_buried) and (not b_buried):
        verdict_label = "둘 다 안 묻힘 - 골든크로스 타이밍에 정보 있음"
    else:
        verdict_label = "A는 묻히고 B는 안 묻힘(드문 패턴) - 그대로 기록"
    print(f"\n=== 최종 해석 === {verdict_label}", flush=True)

    return df, verdicts, verdict_label


if __name__ == "__main__":
    main()
