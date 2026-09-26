"""ORB x RVOL 상승전조 연구 — IS/Validation/OOS 분석 + 기각조건 판정.

사전등록: results/qtai_orb_rvol_preregistration.md §6~9 (결과 보기 **전** 작성).
이 스크립트는 사전등록에 적힌 절차를 순서대로 실행한다 — 결과를 보고 절차를 바꾸지 않는다.

실행: python -m backtesting.qtai_orb_rvol_analyze
산출: results/qtai_orb_rvol_analysis.json, results/qtai_orb_rvol_grid.csv
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.t0_forward_return import round_trip_cost_pct  # noqa: E402  (재사용, 복붙 금지)

SIGNALS = "results/qtai_orb_rvol_signals.csv"
OUT_JSON = "results/qtai_orb_rvol_analysis.json"
OUT_GRID = "results/qtai_orb_rvol_grid.csv"

# 사전등록 §6 — canonical 303거래일 캘린더 기준 시간순 분할
IS_RANGE = ("2025-07-01", "2026-02-10")
VAL_RANGE = ("2026-02-11", "2026-06-05")
OOS_RANGE = ("2026-06-08", "2026-09-23")

FEATURES = ["rvol_norm", "or_range_pct", "cum_value_today", "ret_5min_pre"]
MAIN_HORIZON = 60                 # 사전등록 §5 — 주 판정 horizon
ALL_HORIZONS = (1, 3, 5, 10, 15, 30, 60)
MIN_CELL_N = 10                   # 기각조건 (f)
DEFAULT_SLIPPAGE = 0.001
SLIPPAGE_1_5X = 0.0015            # 기각조건 (g)
ONSET_THRESHOLD = 0.02            # 기각조건 (d): 직전 5분 +2%
OFFICIAL_ORN = 15                 # 사전등록 §6-5 — 공식 채택/기각 판정은 ORN=15만


def load_signals() -> pd.DataFrame:
    d = pd.read_csv(SIGNALS, low_memory=False, dtype={"symbol": str})
    return d


def split_by_date(d: pd.DataFrame) -> dict[str, pd.DataFrame]:
    def seg(rng):
        return d[(d["date"] >= rng[0]) & (d["date"] <= rng[1])].copy()
    return {"IS": seg(IS_RANGE), "VAL": seg(VAL_RANGE), "OOS": seg(OOS_RANGE)}


def day_clustered_mean_ci(values: np.ndarray, dates: np.ndarray, n_boot: int = 2000,
                          seed: int = 0) -> dict:
    """일자 단위로 묶은 평균의 부트스트랩 CI(사전등록 §8) — 행 단위 분산은 자기상관을
    무시해 과신뢰구간이 되므로, precursor_master_analyze.day_mean_ci와 같은 접근으로
    일자 평균을 먼저 낸 뒤 그 위에서 재표본."""
    ok = np.isfinite(values)
    v, dts = values[ok], dates[ok]
    if len(v) == 0:
        return {"mean": np.nan, "lo": np.nan, "hi": np.nan, "n": 0, "n_days": 0}
    u = np.unique(dts)
    per_day = np.array([v[dts == x].mean() for x in u])
    mean = float(per_day.mean())
    if len(per_day) < 2:
        return {"mean": mean, "lo": np.nan, "hi": np.nan, "n": len(v), "n_days": len(per_day)}
    rng = np.random.default_rng(seed)
    boot = per_day[rng.integers(0, len(per_day), size=(n_boot, len(per_day)))].mean(axis=1)
    lo, hi = float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))
    return {"mean": mean, "lo": lo, "hi": hi, "n": len(v), "n_days": len(per_day)}


def summarize(d: pd.DataFrame, horizon: int = MAIN_HORIZON,
              slippage_rate: float = DEFAULT_SLIPPAGE) -> dict:
    if d is None or d.empty:
        return {"n": 0, "n_symbols": 0, "n_days": 0}
    gross = d[f"ret_{horizon}m"].to_numpy()
    cost = round_trip_cost_pct(d["entry_price"].to_numpy(), slippage_rate=slippage_rate)
    net = gross - cost
    mfe = d[f"mfe_{horizon}m"].to_numpy()
    mae = d[f"mae_{horizon}m"].to_numpy()
    pos = net[net > 0].sum()
    neg = -net[net < 0].sum()
    pf = float(pos / neg) if neg > 0 else (float("inf") if pos > 0 else float("nan"))
    ci = day_clustered_mean_ci(net, d["date"].to_numpy())
    return {
        "n": int(len(d)),
        "n_symbols": int(d["symbol"].nunique()),
        "n_days": int(d["date"].nunique()),
        "win_rate": float((net > 0).mean()),
        "mean_gross": float(np.nanmean(gross)),
        "mean_net": float(np.nanmean(net)),
        "median_net": float(np.nanmedian(net)),
        "mean_mfe": float(np.nanmean(mfe)),
        "mean_mae": float(np.nanmean(mae)),
        "profit_factor": pf,
        "net_ci_lo": ci["lo"],
        "net_ci_hi": ci["hi"],
        "net_mean_dayclustered": ci["mean"],
        "n_days_clustered": ci["n_days"],
    }


def candidate_selection(is_df: pd.DataFrame, features=FEATURES,
                        horizon: int = MAIN_HORIZON) -> pd.DataFrame:
    """사전등록 §4-4 — 4피처 x 상위/하위10% = 8후보의 IS 성과를 전부 계산."""
    rows = []
    for feat in features:
        vals = is_df[feat].to_numpy(dtype=float)
        finite = np.isfinite(vals)
        if finite.sum() < 20:
            continue
        q10, q90 = np.nanpercentile(vals[finite], [10, 90])
        for direction, thresh in (("top10", q90), ("bottom10", q10)):
            sub = is_df[is_df[feat] >= thresh] if direction == "top10" else is_df[is_df[feat] <= thresh]
            summ = summarize(sub, horizon)
            summ.update({"feature": feat, "direction": direction, "threshold": float(thresh)})
            rows.append(summ)
    return pd.DataFrame(rows)


def select_best(cand_df: pd.DataFrame) -> dict | None:
    """사전등록 §6-2 — IS 평균 순수익(60분) 최고 1개 선정(n>=10인 후보만 대상)."""
    if cand_df.empty:
        return None
    valid = cand_df[cand_df["n"] >= MIN_CELL_N]
    if valid.empty:
        return None
    best = valid.loc[valid["mean_net"].idxmax()]
    return best.to_dict()


def apply_rule(d: pd.DataFrame, feature: str, direction: str, threshold: float) -> pd.DataFrame:
    if direction == "top10":
        return d[d[feature] >= threshold]
    return d[d[feature] <= threshold]


def random_benchmark(pop_df: pd.DataFrame, n: int, horizon: int = MAIN_HORIZON,
                     n_draws: int = 30, seed: int = 0) -> dict:
    """사전등록 §7 — 같은 표본크기로 30회 무작위 추출, 평균±표준편차."""
    N = len(pop_df)
    if N == 0 or n == 0:
        return {"mean": float("nan"), "std": float("nan"), "n_draws": 0}
    n = min(n, N)
    gross_all = pop_df[f"ret_{horizon}m"].to_numpy()
    cost_all = round_trip_cost_pct(pop_df["entry_price"].to_numpy())
    net_all = gross_all - cost_all
    rng = np.random.default_rng(seed)
    means = [net_all[rng.choice(N, size=n, replace=False)].mean() for _ in range(n_draws)]
    return {"mean": float(np.mean(means)), "std": float(np.std(means)), "n_draws": n_draws}


def onset_isolated(d: pd.DataFrame, threshold: float = ONSET_THRESHOLD) -> pd.DataFrame:
    """기각조건 (d) — 직전 5분 +2%이상 상승한 '이미 랠리 중' 신호 제외.
    ret_5min_pre가 NaN인 행(온셋 판정 불가)은 배제 대상이 아니므로 그대로 남긴다."""
    return d[~(d["ret_5min_pre"] >= threshold)]


def stock_contribution(d: pd.DataFrame, horizon: int = MAIN_HORIZON) -> pd.Series:
    gross = d[f"ret_{horizon}m"].to_numpy()
    cost = round_trip_cost_pct(d["entry_price"].to_numpy())
    net = gross - cost
    tmp = d[["symbol"]].copy()
    tmp["_net"] = net
    return tmp.groupby("symbol")["_net"].sum().sort_values(ascending=False)


def run_orn_pipeline(df: pd.DataFrame, orn: int, features=FEATURES,
                     horizon: int = MAIN_HORIZON) -> dict:
    sub = df[df["orn"] == orn].copy()
    splits = split_by_date(sub)
    is_df, val_df, oos_df = splits["IS"], splits["VAL"], splits["OOS"]

    cand_df = candidate_selection(is_df, features, horizon)
    result: dict = {
        "orn": orn,
        "is_n": len(is_df), "val_n": len(val_df), "oos_n": len(oos_df),
        "candidates": cand_df.to_dict("records"),
    }

    best = select_best(cand_df)
    result["winner"] = best
    if best is None:
        result["oos_summary"] = {"n": 0}
        return result

    feat, direction, threshold = best["feature"], best["direction"], best["threshold"]

    val_sel = apply_rule(val_df, feat, direction, threshold)
    oos_sel = apply_rule(oos_df, feat, direction, threshold)

    result["val_summary"] = summarize(val_sel, horizon)
    result["oos_summary"] = summarize(oos_sel, horizon)
    result["is_control"] = summarize(is_df, horizon)
    result["val_control"] = summarize(val_df, horizon)
    result["oos_control"] = summarize(oos_df, horizon)

    result["oos_random_benchmark"] = random_benchmark(oos_df, len(oos_sel), horizon)

    onset_iso = onset_isolated(oos_sel)
    result["onset_isolated_summary"] = summarize(onset_iso, horizon)
    result["onset_excluded_n"] = int(len(oos_sel) - len(onset_iso))

    contrib = stock_contribution(oos_sel, horizon)
    result["top_contributors"] = {k: float(v) for k, v in contrib.head(5).items()}
    if len(contrib) >= 1:
        excl1 = oos_sel[~oos_sel["symbol"].isin(contrib.index[:1])]
        result["oos_excl_top1"] = summarize(excl1, horizon)
        result["excl_top1_symbols"] = contrib.index[:1].tolist()
    if len(contrib) >= 2:
        excl2 = oos_sel[~oos_sel["symbol"].isin(contrib.index[:2])]
        result["oos_excl_top2"] = summarize(excl2, horizon)
        result["excl_top2_symbols"] = contrib.index[:2].tolist()

    result["oos_slippage_1_5x"] = summarize(oos_sel, horizon, slippage_rate=SLIPPAGE_1_5X)

    return result


def evaluate_rejection_criteria(result: dict) -> dict:
    """사전등록 §9 — 기각조건 7개 판정."""
    v: dict = {}
    winner = result.get("winner")
    oos = result.get("oos_summary", {"n": 0})
    val = result.get("val_summary", {"n": 0})
    n_oos = oos.get("n", 0)
    n_val = val.get("n", 0)
    n_is_winner = winner.get("n", 0) if winner else 0

    cells_ok = (winner is not None) and all(n >= MIN_CELL_N for n in [n_is_winner, n_val, n_oos])
    v["f_min_sample"] = {
        "판정": "통과" if cells_ok else "걸림(판정불가 칸 존재)",
        "is_winner_n": n_is_winner, "val_n": n_val, "oos_n": n_oos,
    }

    if winner is None or n_oos < MIN_CELL_N:
        undecidable = "판정불가(OOS 표본 부족 또는 유효 규칙 없음)"
        for k in ["a_oos_positive", "b_beats_control", "c_ci_excludes_zero",
                  "d_onset_isolation", "e_stock_generalization", "g_slippage_1_5x"]:
            v[k] = {"판정": undecidable}
        return v

    oos_net = oos["mean_net"]
    v["a_oos_positive"] = {"판정": "통과" if oos_net > 0 else "걸림", "oos_net": oos_net}

    control_net = result["oos_control"]["mean_net"]
    rb = result["oos_random_benchmark"]
    beats_control = oos_net > control_net
    beats_random = (oos_net > rb["mean"]) if not np.isnan(rb.get("mean", np.nan)) else True
    v["b_beats_control"] = {
        "판정": "통과" if (beats_control and beats_random) else "걸림",
        "oos_net": oos_net, "control_net": control_net,
        "random_mean": rb.get("mean"), "random_std": rb.get("std"),
    }

    ci_lo, ci_hi = oos.get("net_ci_lo"), oos.get("net_ci_hi")
    ci_valid = ci_lo is not None and ci_hi is not None and not (np.isnan(ci_lo) or np.isnan(ci_hi))
    ci_excludes_zero = ci_valid and (ci_lo > 0 or ci_hi < 0)
    v["c_ci_excludes_zero"] = {
        "판정": ("통과" if ci_excludes_zero else "걸림") if ci_valid else "판정불가(CI 계산불가)",
        "ci_lo": ci_lo, "ci_hi": ci_hi,
    }

    onset = result.get("onset_isolated_summary", {})
    onset_net = onset.get("mean_net", float("nan"))
    if oos_net > 0:
        collapsed = (not np.isnan(onset_net)) and (onset_net <= 0.5 * oos_net)
        v["d_onset_isolation"] = {
            "판정": "걸림" if collapsed else "통과",
            "oos_net": oos_net, "onset_isolated_net": onset_net,
            "onset_excluded_n": result.get("onset_excluded_n"),
        }
    else:
        v["d_onset_isolation"] = {
            "판정": "해당없음(원래 순수익 0 이하 — 붕괴를 논할 양의 효과가 없음)",
            "oos_net": oos_net, "onset_isolated_net": onset_net,
        }

    excl1 = result.get("oos_excl_top1", {}).get("mean_net", float("nan"))
    excl2 = result.get("oos_excl_top2", {}).get("mean_net", float("nan"))
    sign_orig = np.sign(oos_net)
    flip1 = (not np.isnan(excl1)) and np.sign(excl1) != sign_orig
    flip2 = (not np.isnan(excl2)) and np.sign(excl2) != sign_orig
    v["e_stock_generalization"] = {
        "판정": "걸림" if (flip1 or flip2) else "통과",
        "oos_net": oos_net, "excl_top1_net": excl1, "excl_top2_net": excl2,
    }

    slip_net = result.get("oos_slippage_1_5x", {}).get("mean_net", float("nan"))
    if oos_net > 0:
        flip_slip = (not np.isnan(slip_net)) and slip_net <= 0
        v["g_slippage_1_5x"] = {"판정": "걸림" if flip_slip else "통과",
                                  "oos_net": oos_net, "slip_1_5x_net": slip_net}
    else:
        v["g_slippage_1_5x"] = {
            "판정": "해당없음(원래 순수익 0 이하 — 비용 증가는 반전을 만들 수 없음)",
            "oos_net": oos_net, "slip_1_5x_net": slip_net,
        }

    return v


def build_horizon_grid(df: pd.DataFrame) -> pd.DataFrame:
    """사전등록 §5 — 목표수익률/horizon을 미리 고정하지 않고 격자로 전부 보고."""
    rows = []
    for orn in (5, 15, 30):
        sub_orn = df[df["orn"] == orn]
        splits = split_by_date(sub_orn)
        for split_name, sub in splits.items():
            for h in ALL_HORIZONS:
                s = summarize(sub, horizon=h)
                s.update({"orn": orn, "split": split_name, "horizon": h})
                rows.append(s)
    return pd.DataFrame(rows)


def main() -> int:
    df = load_signals()
    print(f"신호 {len(df):,}건 로드 (ORN 3종 합산)")

    grid = build_horizon_grid(df)
    os.makedirs("results", exist_ok=True)
    grid.to_csv(OUT_GRID, index=False)
    print(f"horizon 격자 저장: {OUT_GRID} ({len(grid)}행)")

    all_results = {}
    for orn in (OFFICIAL_ORN, 5, 30):
        print(f"\n{'='*60}\nORN={orn}분 파이프라인 실행"
              f"{' [공식 판정]' if orn == OFFICIAL_ORN else ' [민감도 참고용]'}\n{'='*60}")
        res = run_orn_pipeline(df, orn)
        # 사전등록 §6-5: 공식 채택/기각 판정은 ORN=15만 쓰지만, 기각조건 판정 자체는
        # 투명성을 위해 5/30에도 똑같이 계산해 "참고용"으로 나란히 보고한다(결과를 보고
        # 판정 대상 ORN을 바꾸는 것을 막기 위해 공식 여부는 이미 §6-5에서 고정돼 있음).
        rej = evaluate_rejection_criteria(res)
        all_results[str(orn)] = {"pipeline": res, "rejection": rej,
                                  "is_official": orn == OFFICIAL_ORN}

        print(f"IS n={res['is_n']:,} VAL n={res['val_n']:,} OOS n={res['oos_n']:,}")
        if res.get("winner"):
            w = res["winner"]
            print(f"IS 최선 규칙: {w['feature']} {w['direction']} "
                  f"(문턱={w['threshold']:.6g}) IS n={w['n']} IS 평균순수익={w['mean_net']*100:.4f}%")
            print(f"  VAL 적용: n={res['val_summary']['n']} 평균순수익={res['val_summary']['mean_net']*100:.4f}%")
            oos_s = res["oos_summary"]
            print(f"  OOS 적용: n={oos_s['n']} 평균순수익={oos_s['mean_net']*100:.4f}% "
                  f"CI=[{oos_s['net_ci_lo']*100:.4f}%, {oos_s['net_ci_hi']*100:.4f}%]")
        else:
            print("  유효한 IS 규칙 없음(모든 후보 n<10)")

        print("\n기각조건 판정:")
        for k, vv in rej.items():
            print(f"  {k}: {vv.get('판정')}")

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n\n전체 분석 저장: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
