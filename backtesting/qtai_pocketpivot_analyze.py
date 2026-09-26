"""Pocket Pivot 사전등록(§6~9) 분석 — IS 조건표 → Validation 문턱 확정 → OOS 1회 적용
→ 대조군 → 기각조건 7개 판정.

사전등록: results/qtai_pocketpivot_preregistration.md
입력: results/qtai_pocketpivot_signals.csv, results/qtai_pocketpivot_full_universe_cache.parquet
      (둘 다 backtesting/qtai_pocketpivot_scan.py 산출물)

실행: python -m backtesting.qtai_pocketpivot_analyze
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

RESULTS_DIR = "results"
HORIZONS = (5, 10, 20, 40, 60)
LIQUIDITY_KEYS = ("3e8", "5e8", "10e8")
LIQUIDITY_LABELS = {"3e8": "3억원", "5e8": "5억원", "10e8": "10억원"}  # CSV 재로드 시 "3e8"가
# 과학표기 float(3.000000e+08)로 자동형변환되는 표시 혼란 방지(계산 로직엔 영향 없음, 리포트 가독성용)
PRIMARY_HORIZON = 20  # §6: Validation 문턱 확정용 대표 horizon (사전 지정)
MIN_N_VALIDATION_CONFIRM = 30
FALLBACK_COMBO = {"liquidity": "5e8", "context": "off"}  # §6-3 사전지정 fallback
N_RANDOM_DRAWS = 30
RANDOM_SEED_BASE = 1000
BOOTSTRAP_DRAWS = 5000
BOOTSTRAP_SEED = 42
SLIPPAGE_SENSITIVITY_MULT = 1.5
DEFAULT_SLIPPAGE_RATE = 0.001  # backtesting.breakout_reversal.DEFAULT_SLIPPAGE_RATE (재확인용 상수)


def trade_stats(returns: pd.Series) -> dict:
    r = returns.dropna()
    n = len(r)
    if n == 0:
        return {"n": 0, "win_rate_pct": np.nan, "profit_factor": np.nan,
                "mean_pct": np.nan, "median_pct": np.nan, "sharpe": np.nan}
    wins, losses = r[r > 0], r[r <= 0]
    gross_profit, gross_loss = wins.sum(), -losses.sum()
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else np.inf
    win_rate = len(wins) / n * 100
    mean, median = r.mean(), r.median()
    std = r.std(ddof=1) if n >= 2 else np.nan
    sharpe = (mean / std * np.sqrt(n)) if std and std > 0 else np.nan
    return {"n": n, "win_rate_pct": win_rate, "profit_factor": profit_factor,
            "mean_pct": mean * 100, "median_pct": median * 100, "sharpe": sharpe}


def day_clustered_mean_se(df: pd.DataFrame, col: str, date_col: str = "date") -> tuple[float, float, int, int]:
    daily = df.groupby(date_col)[col].mean()
    n_days = daily.notna().sum()
    mean = float(df[col].mean()) if len(df) else np.nan
    se = float(daily.std(ddof=1) / np.sqrt(n_days)) if n_days > 1 else np.nan
    return mean, se, len(df[col].dropna()), int(n_days)


def bootstrap_ci_date_clustered(df: pd.DataFrame, col: str, date_col: str = "date",
                                 n_draws: int = BOOTSTRAP_DRAWS, seed: int = BOOTSTRAP_SEED) -> tuple[float, float]:
    """사전등록 기각조건(c): 일자 단위로 평균을 낸 뒤 그 일자평균들을 리샘플."""
    daily = df.groupby(date_col)[col].mean().dropna()
    if len(daily) < 2:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    vals = daily.to_numpy()
    draws = vals[rng.integers(0, len(vals), size=(n_draws, len(vals)))].mean(axis=1)
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def combo_row(df: pd.DataFrame, split: str, liquidity: str, context: str, horizon: int) -> dict:
    sub = df[df["split"] == split].copy()
    sub = sub[sub[f"liquidity_ok_{liquidity}"]]
    if context == "on":
        sub = sub[sub["context_on"]]
    elif context == "off":
        sub = sub[~sub["context_on"]]
    col = f"net_ret_{horizon}"
    sub = sub.dropna(subset=[col])
    stats = trade_stats(sub[col])
    mean, se, n, n_days = day_clustered_mean_se(sub, col) if len(sub) else (np.nan, np.nan, 0, 0)
    lo, hi = bootstrap_ci_date_clustered(sub, col) if len(sub) >= 10 else (np.nan, np.nan)
    gross_col = f"ret_{horizon}"
    gross_mean = sub[gross_col].mean() * 100 if len(sub) else np.nan
    return {
        "split": split, "liquidity_floor": LIQUIDITY_LABELS[liquidity], "context": context, "horizon": horizon,
        "n": stats["n"], "n_days_triggered": n_days,
        "gross_mean_pct": gross_mean,
        "net_mean_pct": stats["mean_pct"], "net_median_pct": stats["median_pct"],
        "net_day_clustered_se_pct": se * 100 if pd.notna(se) else np.nan,
        "win_rate_pct": stats["win_rate_pct"], "profit_factor": stats["profit_factor"],
        "sharpe_trade": stats["sharpe"],
        "net_ci95_lo_pct": lo * 100 if pd.notna(lo) else np.nan,
        "net_ci95_hi_pct": hi * 100 if pd.notna(hi) else np.nan,
    }


def build_condition_table(df: pd.DataFrame, split: str) -> pd.DataFrame:
    rows = []
    for liquidity in LIQUIDITY_KEYS:
        for context in ("on", "off"):
            for horizon in HORIZONS:
                rows.append(combo_row(df, split, liquidity, context, horizon))
    return pd.DataFrame(rows)


def confirm_validation_threshold(validation_table: pd.DataFrame) -> dict:
    """§6: Validation에서 net_ret_20 평균이 가장 큰, n>=30인 양(+)의 조합을 1회 확정."""
    cand = validation_table[(validation_table["horizon"] == PRIMARY_HORIZON)
                             & (validation_table["n"] >= MIN_N_VALIDATION_CONFIRM)
                             & (validation_table["net_mean_pct"] > 0)]
    if cand.empty:
        return {"liquidity": FALLBACK_COMBO["liquidity"], "context": FALLBACK_COMBO["context"],
                "fallback_used": True, "reason": "조건을 만족하는 조합 없음(Validation 불확정) -> 사전지정 기본값 사용"}
    best = cand.sort_values("net_mean_pct", ascending=False).iloc[0]
    return {"liquidity": best["liquidity"], "context": best["context"], "fallback_used": False,
            "reason": f"Validation net_ret_20 최댓값(n={best['n']:.0f}, mean={best['net_mean_pct']:.3f}%)"}


def random_entry_control(universe: pd.DataFrame, split: str, liquidity: str, n_sample: int,
                          horizon: int, n_draws: int = N_RANDOM_DRAWS) -> dict:
    """대조군(a): 같은 split·같은 유동성 문턱의 "진입가능" 전체 행에서 무작위 N개, 30회."""
    pop = universe[(universe["split"] == split) & (universe[f"liquidity_ok_{liquidity}"])
                   & universe["entry_price"].notna()]
    col = f"net_ret_{horizon}"
    pop = pop.dropna(subset=[col])
    if len(pop) < n_sample or n_sample == 0:
        return {"n_population": len(pop), "n_sample": n_sample, "mean_of_draws_pct": np.nan,
                "std_of_draws_pct": np.nan, "n_draws": 0}
    vals = pop[col].to_numpy()
    means = []
    for i in range(n_draws):
        rng = np.random.default_rng(RANDOM_SEED_BASE + i)
        idx = rng.choice(len(vals), size=n_sample, replace=False)
        means.append(vals[idx].mean())
    means = np.array(means)
    return {"n_population": len(pop), "n_sample": n_sample, "mean_of_draws_pct": float(means.mean()) * 100,
            "std_of_draws_pct": float(means.std(ddof=1)) * 100, "n_draws": n_draws}


def up_day_only_control(universe: pd.DataFrame, split: str, liquidity: str, horizon: int) -> dict:
    """대조군(b): 포켓피봇 거래량 조건 없이 상승일이면 전부(같은 유동성 문턱)."""
    pop = universe[(universe["split"] == split) & (universe[f"liquidity_ok_{liquidity}"])
                   & universe["up_day"] & universe["entry_price"].notna()]
    col = f"net_ret_{horizon}"
    pop = pop.dropna(subset=[col])
    stats = trade_stats(pop[col])
    mean, se, n, n_days = day_clustered_mean_se(pop, col) if len(pop) else (np.nan, np.nan, 0, 0)
    return {"n": stats["n"], "n_days": n_days, "net_mean_pct": stats["mean_pct"],
            "net_median_pct": stats["median_pct"], "win_rate_pct": stats["win_rate_pct"],
            "profit_factor": stats["profit_factor"], "sharpe_trade": stats["sharpe"]}


def leave_one_out_codes(sub: pd.DataFrame, col: str, k: int = 2) -> pd.DataFrame:
    """기각조건(d): 종목별 net_ret 합(총 기여 PnL) 상위 k개를 순차 제외했을 때 평균 재계산."""
    contrib = sub.groupby("code")[col].sum().sort_values(ascending=False)
    rows = [{"excluded": "없음(전체)", "n": len(sub), "mean_pct": sub[col].mean() * 100}]
    excluded_codes = []
    for i in range(1, k + 1):
        excluded_codes.append(contrib.index[i - 1])
        remain = sub[~sub["code"].isin(excluded_codes)]
        rows.append({"excluded": f"상위{i}개 제외({','.join(excluded_codes)})",
                     "n": len(remain), "mean_pct": remain[col].mean() * 100 if len(remain) else np.nan})
    return pd.DataFrame(rows)


def slippage_sensitivity_net(sub: pd.DataFrame, horizon: int, mult: float = SLIPPAGE_SENSITIVITY_MULT) -> pd.Series:
    """기각조건(g): 슬리피지 mult배 재계산. round_trip_cost_pct 공식을 그대로 풀어서
    이미 저장된 cost_pct(기본 슬리피지 기준)에서 슬리피지 성분만 추가로 늘린다.
    cost_pct = commission*2 + tax + per_side_slippage*2 (per_side_slippage=max(0.001, tick_pct)).
    entry_price가 없어 tick_pct를 재계산할 수 없는 경우를 피하려 signals.csv의
    entry_price로 직접 재계산한다(round_trip_cost_pct 재사용)."""
    from backtesting.t0_forward_return import round_trip_cost_pct
    new_cost = round_trip_cost_pct(sub["entry_price"].to_numpy(), slippage_rate=DEFAULT_SLIPPAGE_RATE * mult)
    gross_col = f"ret_{horizon}"
    return sub[gross_col] - new_cost


def main():
    signals = pd.read_csv(f"{RESULTS_DIR}/qtai_pocketpivot_signals.csv", dtype={"code": str}, low_memory=False)
    universe = pd.read_parquet(f"{RESULTS_DIR}/qtai_pocketpivot_full_universe_cache.parquet")

    print(f"signals: {len(signals):,}행, universe: {len(universe):,}행\n")

    # 1) IS 조건표 (6조합 x 5horizon = 30행, 서술적)
    is_table = build_condition_table(signals, "IS")
    is_table.to_csv(f"{RESULTS_DIR}/qtai_pocketpivot_IS_condition_table.csv", index=False)
    print("=== IS 조건별 성과표(6조합 x 5horizon) ===")
    print(is_table.to_string(index=False))

    # 2) Validation 조건표 + 문턱 확정
    validation_table = build_condition_table(signals, "Validation")
    validation_table.to_csv(f"{RESULTS_DIR}/qtai_pocketpivot_Validation_condition_table.csv", index=False)
    print("\n=== Validation 조건별 성과표(6조합 x 5horizon) ===")
    print(validation_table.to_string(index=False))

    confirmed = confirm_validation_threshold(validation_table)
    print(f"\n=== §6 문턱 확정 결과 ===\n{json.dumps(confirmed, ensure_ascii=False, indent=2)}")

    liquidity, context = confirmed["liquidity"], confirmed["context"]

    # 3) OOS에 1회 적용 (확정 조합, 5 horizon 전부)
    oos_rows = [combo_row(signals, "OOS", liquidity, context, h) for h in HORIZONS]
    oos_table = pd.DataFrame(oos_rows)
    oos_table.to_csv(f"{RESULTS_DIR}/qtai_pocketpivot_OOS_confirmed_table.csv", index=False)
    print(f"\n=== OOS 확정조합(liquidity={liquidity}, context={context}) 5horizon 성과 ===")
    print(oos_table.to_string(index=False))

    oos_primary = oos_table[oos_table["horizon"] == PRIMARY_HORIZON].iloc[0]

    # 4) 대조군 (a)(b) — OOS, 확정 유동성 문턱, 대표 horizon(20) + 5horizon 전부
    oos_sub_confirmed = signals[(signals["split"] == "OOS") & (signals[f"liquidity_ok_{liquidity}"])
                                 & (signals["context_on"] if context == "on" else ~signals["context_on"])]
    n_sample_oos = int(oos_sub_confirmed[f"net_ret_{PRIMARY_HORIZON}"].notna().sum())

    control_rows = []
    for h in HORIZONS:
        sub_h = oos_sub_confirmed.dropna(subset=[f"net_ret_{h}"])
        n_h = len(sub_h)
        rand = random_entry_control(universe, "OOS", liquidity, n_h, h)
        updown = up_day_only_control(universe, "OOS", liquidity, h)
        control_rows.append({"horizon": h, "pocketpivot_n": n_h,
                              "pocketpivot_net_mean_pct": sub_h[f"net_ret_{h}"].mean() * 100 if n_h else np.nan,
                              "random_control_mean_pct": rand["mean_of_draws_pct"],
                              "random_control_std_pct": rand["std_of_draws_pct"],
                              "random_control_n_population": rand["n_population"],
                              "updown_control_n": updown["n"],
                              "updown_control_net_mean_pct": updown["net_mean_pct"],
                              "updown_control_win_rate_pct": updown["win_rate_pct"],
                              "updown_control_pf": updown["profit_factor"]})
    control_table = pd.DataFrame(control_rows)
    control_table.to_csv(f"{RESULTS_DIR}/qtai_pocketpivot_OOS_controls.csv", index=False)
    print("\n=== OOS 대조군 비교(5horizon) ===")
    print(control_table.to_string(index=False))

    control_primary = control_table[control_table["horizon"] == PRIMARY_HORIZON].iloc[0]

    # 5) 기각조건 판정
    verdicts = {}

    # (a) OOS 순수익 <= 0
    verdicts["a_net_le_0"] = bool(oos_primary["net_mean_pct"] <= 0)

    # (b) 대조군 못 이김
    beats_random = oos_primary["net_mean_pct"] > control_primary["random_control_mean_pct"]
    beats_updown = oos_primary["net_mean_pct"] > control_primary["updown_control_net_mean_pct"]
    verdicts["b_fails_vs_control"] = bool(not (beats_random and beats_updown))
    verdicts["b_detail"] = {"beats_random": bool(beats_random), "beats_updown": bool(beats_updown)}

    # (c) 부트스트랩 95%CI가 0을 포함
    ci_lo, ci_hi = oos_primary["net_ci95_lo_pct"], oos_primary["net_ci95_hi_pct"]
    verdicts["c_ci_includes_0"] = bool(pd.notna(ci_lo) and pd.notna(ci_hi) and ci_lo <= 0 <= ci_hi)
    verdicts["c_detail"] = {"ci95": [ci_lo, ci_hi]}

    # (d) 상위 1~2 종목 제외 시 결론(양수 & 대조군 우위) 뒤집힘
    loo = leave_one_out_codes(oos_sub_confirmed.dropna(subset=[f"net_ret_{PRIMARY_HORIZON}"]),
                               f"net_ret_{PRIMARY_HORIZON}", k=2)
    loo.to_csv(f"{RESULTS_DIR}/qtai_pocketpivot_OOS_leave_one_out.csv", index=False)
    print("\n=== 기각조건(d) 상위 기여 종목 제외 ===")
    print(loo.to_string(index=False))
    base_positive = oos_primary["net_mean_pct"] > 0
    loo_flip = any((row["mean_pct"] > 0) != base_positive for _, row in loo.iloc[1:].iterrows())
    verdicts["d_loo_flip"] = bool(loo_flip)

    # (e) context on/off 방향 반전 (OOS, 대표 horizon)
    on_row = oos_table_all = combo_row(signals, "OOS", liquidity, "on", PRIMARY_HORIZON)
    off_row = combo_row(signals, "OOS", liquidity, "off", PRIMARY_HORIZON)
    sign_on = np.sign(on_row["net_mean_pct"]) if pd.notna(on_row["net_mean_pct"]) else np.nan
    sign_off = np.sign(off_row["net_mean_pct"]) if pd.notna(off_row["net_mean_pct"]) else np.nan
    verdicts["e_context_flip"] = bool(pd.notna(sign_on) and pd.notna(sign_off) and sign_on != sign_off and sign_on != 0 and sign_off != 0)
    verdicts["e_detail"] = {"context_on_net_mean_pct": on_row["net_mean_pct"], "context_off_net_mean_pct": off_row["net_mean_pct"]}

    # (f) 표본 10건 미만 칸 판정불가 표시 (전체 조건표에서 카운트)
    n_below10 = int((pd.concat([is_table, validation_table, oos_table])["n"] < 10).sum())
    verdicts["f_n_cells_below_10_flagged"] = n_below10

    # (g) 슬리피지 1.5배 시 부호 반전
    sens_series = slippage_sensitivity_net(oos_sub_confirmed.dropna(subset=[f"ret_{PRIMARY_HORIZON}", "entry_price"]), PRIMARY_HORIZON)
    sens_mean = float(sens_series.mean()) * 100 if len(sens_series) else np.nan
    verdicts["g_slippage_1.5x_net_mean_pct"] = sens_mean
    verdicts["g_sign_flip"] = bool(pd.notna(sens_mean) and (np.sign(sens_mean) != np.sign(oos_primary["net_mean_pct"])) and sens_mean != 0)

    overall_rejected = any([verdicts["a_net_le_0"], verdicts["b_fails_vs_control"], verdicts["c_ci_includes_0"],
                             verdicts["d_loo_flip"], verdicts["g_sign_flip"]])
    verdicts["overall_rejected"] = bool(overall_rejected)

    print("\n=== 기각조건 7개 판정 (OOS, 확정조합, horizon=20 기준) ===")
    print(json.dumps(verdicts, ensure_ascii=False, indent=2, default=str))

    with open(f"{RESULTS_DIR}/qtai_pocketpivot_verdicts.json", "w", encoding="utf-8") as f:
        json.dump({"confirmed_combo": confirmed, "verdicts": verdicts}, f, ensure_ascii=False, indent=2, default=str)

    return {
        "is_table": is_table, "validation_table": validation_table, "confirmed": confirmed,
        "oos_table": oos_table, "control_table": control_table, "loo": loo, "verdicts": verdicts,
    }


if __name__ == "__main__":
    main()
