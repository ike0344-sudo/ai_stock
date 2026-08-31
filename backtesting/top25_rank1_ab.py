"""전략1 신규조건(거래대금25위+상승률1등, strategy-agent 구현) A/B — 켠/끈 x
ML threshold 0.3/0.5. 결과 보고 좋은 쪽을 채택하지 않는다(단순 나열).

재스캔 없이 사후 컬럼필터로 처리한다(속도 우선순위 조정, 2026-08-29) — 신규조건은
"이미 통과한 후보 중 그 순간 rank1이었나"만 추가로 요구하므로, 기존 스캔(조건1~7,
results/regime_on_trades.csv)에 entry_time이 rank1_by_minute와 일치하는지만 사후로
붙이면 detect_final_entries에 조건을 켜서 재스캔한 것과 동일하다 — 15종목 표본으로
0건 불일치 확인(아래 verify_posthoc_equivalence). 이걸로 재스캔 1회(약 4분) +
intraday_top_n_return_rank1_by_minute 중복호출을 피한다(그 함수 자체는 1045종목
기준 약 25분 걸리는 게 이미 확인된 고정비용 - 벡터화를 시도했으나 결과가 달라져
되돌렸고 원본을 그대로 쓴다).

홀드아웃 미개봉, 폴드 정렬은 gate_ab_check.gate_ab_per_fold의 고정 start/end로 보장.

실행: python -m backtesting.top25_rank1_ab
"""
import argparse
from datetime import timedelta

import pandas as pd

from . import gate_ab_check as gab
from . import regime_filter_ab as rab
from .ml_entry_filter import FEATURE_COLUMNS, InsufficientTrainingDataError, predict_quality_proba, train_entry_filter_model
from .ml.walk_forward import split as wf_split
from .universe import intraday_top_n_return_rank1_by_minute
from .validate_strategy1 import MODEL_KWARGS

MIN_FOLD_TRADES = 30


def build_condition_dfs(baseline_df: pd.DataFrame, data_dir: str = "data") -> tuple[pd.DataFrame, pd.DataFrame]:
    rank1 = intraday_top_n_return_rank1_by_minute(data_dir, trading_value_rank_n=25)
    is_rank1 = baseline_df.apply(lambda r: rank1.get(r["entry_time"]) == r["code"], axis=1)
    on_df = baseline_df[is_rank1].reset_index(drop=True)
    off_df = baseline_df  # 조건 off = 기존 전략1(조건1~7) 그대로
    return on_df, off_df


def _no_leak_threshold_per_fold(trades_df: pd.DataFrame, splits: list, thresholds: list[float]) -> pd.DataFrame:
    """리크 없는 임계값 선택: 폴드의 IS(학습구간) 안에서만 0.3/0.5 중 기대값(평균pct)이
    높은 쪽을 고르고, 그 선택을 그 폴드의 OOS에 적용한다. OOS를 본 적이 없으니 리크가
    아니다 - 폴드마다 다른 값이 뽑히면 그 자체가 "임계값이 불안정하다"는 정보다."""
    rows = []
    for i, sp in enumerate(splits, 1):
        is_df = trades_df[trades_df["entry_time"].dt.date.between(sp.train_start, sp.train_end)]
        oos_df = trades_df[trades_df["entry_time"].dt.date.between(sp.test_start, sp.test_end)]
        if oos_df.empty or len(is_df) < 50:
            rows.append({"fold": i, "chosen_threshold": None, "reason": "IS 표본 부족 또는 OOS 없음"})
            continue
        try:
            labels = (is_df["pct"] > 0).astype(int)
            trained = train_entry_filter_model(is_df[FEATURE_COLUMNS], labels, model_type="random_forest", **MODEL_KWARGS)
        except InsufficientTrainingDataError as exc:
            rows.append({"fold": i, "chosen_threshold": None, "reason": str(exc)})
            continue

        is_proba = predict_quality_proba(trained, is_df[FEATURE_COLUMNS])
        best_th, best_avg = None, float("-inf")
        for th in thresholds:
            kept = is_df.loc[is_proba[is_proba >= th].index]
            if len(kept) < 10:
                continue
            avg = kept["pct"].mean()
            if avg > best_avg:
                best_avg, best_th = avg, th
        if best_th is None:
            rows.append({"fold": i, "chosen_threshold": None, "reason": "IS 내 후보 부족(모든 threshold)"})
            continue

        oos_proba = predict_quality_proba(trained, oos_df[FEATURE_COLUMNS])
        applied = oos_df.loc[oos_proba[oos_proba >= best_th].index]
        wins = applied[applied["pct"] > 0]
        gp, gl = wins["pct"].sum(), -applied[applied["pct"] <= 0]["pct"].sum()
        pf = (gp / gl) if gl > 0 else float("inf")
        rows.append({
            "fold": i, "chosen_threshold": best_th, "is_avg_pct_at_choice": round(best_avg * 100, 3),
            "oos_n_trades": len(applied), "oos_win_rate_pct": round(len(wins) / len(applied) * 100, 1) if len(applied) else 0.0,
            "oos_profit_factor": round(pf, 3) if pf != float("inf") else pf,
        })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--baseline-csv", default="results/regime_on_trades.csv")
    parser.add_argument("--train-days", type=int, default=150)
    parser.add_argument("--test-days", type=int, default=45)
    parser.add_argument("--step-days", type=int, default=45)
    args = parser.parse_args()

    baseline_df = pd.read_csv(args.baseline_csv, parse_dates=["entry_time", "exit_time"])
    print(f"기준선(조건1~7) 거래 {len(baseline_df)}건 캐시 재사용: {args.baseline_csv}")

    print("rank1_by_minute 계산 중 (전 종목 매분 비교, 약 25분 예상)...")
    on_df, off_df = build_condition_dfs(baseline_df, args.data_dir)
    print(f"조건 ON(25위+1등) 거래 {len(on_df)}건 / 조건 OFF(기존) 거래 {len(off_df)}건")

    holdout_start, start, end = rab._holdout_cutoff(baseline_df)
    fold_end = holdout_start - timedelta(days=1)
    print(f"홀드아웃 {holdout_start}~{end} 미개봉, 폴드 구간 {start}~{fold_end}")

    if len(on_df) < MIN_FOLD_TRADES:
        print(f"\n*** 조건 ON 전체 표본이 {len(on_df)}건으로 30건 미만 - 폴드 분해는 참고용으로만 표시하고 판정에 안 쓴다 ***")

    pd.set_option("display.width", 220)
    results = {}
    for cond_label, df in [("ON(25위+1등)", on_df), ("OFF(기존)", off_df)]:
        for th in (0.3, 0.5):
            key = f"{cond_label} th={th}"
            if df.empty:
                print(f"\n### {key}: 거래 0건, 스킵 ###")
                continue
            ab = gab.gate_ab_per_fold(df, args.train_days, args.test_days, args.step_days,
                                       proba_threshold=th, start=start, end=fold_end)
            results[key] = ab
            print(f"\n### {key} ###")
            print(ab.to_string(index=False))

    if not on_df.empty:
        splits = wf_split(start, fold_end, args.train_days, args.test_days, args.step_days)
        print("\n### 참고: 리크 없는 폴드별 임계값 선택(IS로 0.3/0.5 중 고르고 그 폴드 OOS에만 적용) ###")
        print(_no_leak_threshold_per_fold(on_df, splits, [0.3, 0.5]).to_string(index=False))
        print("(이 표는 임계값을 채택하려는 게 아니라 폴드마다 선택이 흔들리는지 보는 참고용)")

        print("\n### 비용 민감도 (조건ON 원시 후보) ###")
        rab.cost_sensitivity(on_df, [0.0020, 0.0030, 0.0040, rab.EMBEDDED_ROUNDTRIP_COST_PCT])

    print("\n### 데이터 한계 (universe.intraday_top_n_return_rank1_by_minute docstring 재확인) ###")
    print("- 로컬 분봉 1045종목뿐 -> 실제 [0184] 전종목 순위보다 위로 밀림 (항상 낙관 편향)")
    print("- 로컬 분봉은 정규장만이라 시간외 거래대금 미반영 (ka10032와 다를 수 있음)")


if __name__ == "__main__":
    main()
