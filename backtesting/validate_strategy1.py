"""strategy_1(final_strategy.detect_final_entries + ML 진입필터 + tiered exit)의
워크포워드 백테스트 검증 — 학습 구간(IS)과 검증 구간(OOS)을 시간순으로 분리해
승률/손익비(R)/MDD/수익률을 재는, 실전 투입 여부 판단용 스크립트.

기존 함수 조합만 사용한다(신규 시뮬레이션 로직 없음):
- final_strategy.detect_final_entries / evaluate_tiered_exit_from_path_with_exit_idx
- breakout_reversal.simulate_trade_path (UNREACHABLE tp/sl로 전체 경로 추출)
- ml_entry_filter.extract_entry_features / train_entry_filter_model / predict_quality_proba
- portfolio_sim.simulate_slot_portfolio (동시보유 슬롯 시뮬레이션, 슬롯 부족 시 스킵)
- ml.walk_forward.split (IS/OOS 날짜 분할, train_end < test_start 강제)

새로 작성한 부분은 딱 세 가지뿐이다: (1) 전 종목 스캔 후 code/entry_time/exit_time/pct/
ML피처를 한 행에 모으는 루프(build_training_dataset과 같은 스캔이지만 시각 정보를
버리지 않음), (2) 폴드별 IS 학습 → OOS 예측 → 필터링을 반복하는 롤링 워크포워드,
(3) equity curve 기반 승률/손익비/MDD 집계.

실행: python -m backtesting.validate_strategy1
"""
import argparse
import os

import pandas as pd

from .breakout_reversal import detect_entries_batch_duckdb, simulate_trade_path
from .entry_filters import intraday_new_high_filter_batch_duckdb, no_prior_drawdown_filter_batch_duckdb
from .final_strategy import (
    DRAWDOWN_THRESHOLD,
    MIN_RETURN_PCT,
    MIN_TRADE_VALUE,
    N_DAY_HIGH,
    RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    RECOMMENDED_PROBA_THRESHOLD,
    STOP_LOSS_PCT,
    TOP_N,
    UNREACHABLE_PCT,
    WINDOW_MINUTES,
    detect_final_entries,
    evaluate_tiered_exit_from_path_with_exit_idx,
    load_kospi_regime_by_day,
)
from .ml.walk_forward import split as wf_split
from .ml_entry_filter import (
    FEATURE_COLUMNS,
    InsufficientTrainingDataError,
    extract_entry_features,
    predict_quality_proba,
    train_entry_filter_model,
)
from .portfolio_sim import simulate_slot_portfolio
from .universe import daily_top_n_from_local

# train_and_save_final_model과 동일한 하이퍼파라미터 (동일 조건에서 재학습하기 위함).
# random_state는 train_entry_filter_model이 자체적으로 42를 넘기므로 여기서는 지정하지 않는다.
MODEL_KWARGS = {"n_estimators": 300, "max_depth": 6, "min_samples_leaf": 20, "n_jobs": -1}

TRADE_COLUMNS = ["code", "entry_time", "exit_time", "pct"]


def scan_all_trades(
    data_dir: str = "data",
    disabled_conditions: frozenset[str] = frozenset(),
    top25_return_rank1_by_minute: dict | None = None,
    use_duckdb_conditions: bool = False,
) -> pd.DataFrame:
    """로컬 유니버스 전체에 strategy_1 진입 조건을 적용해, 거래 하나당 한 행
    (code/entry_time/exit_time/pct/ML 피처)으로 모은다. final_strategy.build_training_dataset과
    같은 스캔이지만 entry_time/exit_time/code도 보존해 포트폴리오 시뮬레이션에 쓴다.

    disabled_conditions/top25_return_rank1_by_minute는 final_strategy.detect_final_entries에
    그대로 넘긴다(A/B 비교용) — 조건 이름(예: "regime")을 넣으면 그 조건만 빼고 나머지는
    동일하게 스캔하고, top25_return_rank1_by_minute(universe.intraday_top_n_return_rank1_by_minute
    결과)를 주면 25위+상승률1등 조건이 추가된다.

    use_duckdb_conditions=True: base_entries/new_high/no_drawdown 세 조건을 종목별로
    반복 계산하지 않고 DuckDB 배치 함수로 전체 유니버스를 한 번에 미리 계산해 넘긴다
    (detect_entries_batch_duckdb/intraday_new_high_filter_batch_duckdb/
    no_prior_drawdown_filter_batch_duckdb — 전부 pandas 버전과 1:1 동치 검증됨).
    기본값 False면 기존 pandas 경로 그대로(기존 호출부 전부 영향 없음). 이 스위치
    자체가 회귀 테스트다 — True/False 결과가 정확히 같아야 안전하다는 뜻(2026-08-30
    lead 지시로 new_high 제거 검증을 pandas 경로로 확정한 뒤, 그 숫자를 기준선으로
    이 스위치의 동일성을 확인했다 — state/agent_reports/backtest-agent_20260830-*.md)."""
    daily_top35 = daily_top_n_from_local(os.path.join(data_dir, "stocks", "daily"), top_n=TOP_N)
    regime_by_day = load_kospi_regime_by_day(data_dir)
    minute_dir = os.path.join(data_dir, "stocks", "minute")
    daily_dir = os.path.join(data_dir, "stocks", "daily")

    precomputed_base_entries = precomputed_new_high = precomputed_no_drawdown = None
    if use_duckdb_conditions:
        precomputed_base_entries = detect_entries_batch_duckdb(data_dir, WINDOW_MINUTES, MIN_TRADE_VALUE, MIN_RETURN_PCT)
        precomputed_new_high = intraday_new_high_filter_batch_duckdb(data_dir)
        precomputed_no_drawdown = no_prior_drawdown_filter_batch_duckdb(data_dir, DRAWDOWN_THRESHOLD)

    rows = []
    for filename in sorted(os.listdir(minute_dir)):
        if not filename.endswith(".csv"):
            continue
        code = filename[: -len(".csv")]
        daily_path = os.path.join(daily_dir, filename)
        if not os.path.exists(daily_path):
            continue

        minute_df = pd.read_csv(os.path.join(minute_dir, filename), index_col=0, parse_dates=True)
        daily_df = pd.read_csv(daily_path, index_col=0, parse_dates=True)

        entries = detect_final_entries(
            minute_df, daily_df, code, daily_top35, regime_by_day,
            disabled_conditions=disabled_conditions, top25_return_rank1_by_minute=top25_return_rank1_by_minute,
            precomputed_base_entries=precomputed_base_entries,
            precomputed_new_high=precomputed_new_high,
            precomputed_no_drawdown=precomputed_no_drawdown,
        )
        if entries.sum() == 0:
            continue

        for pos in (i for i, v in enumerate(entries.to_numpy()) if v):
            full_path = simulate_trade_path(
                minute_df, pos, take_profit_pct=UNREACHABLE_PCT, stop_loss_pct=UNREACHABLE_PCT
            ).path
            pct, exit_idx = evaluate_tiered_exit_from_path_with_exit_idx(full_path)
            feats = extract_entry_features(minute_df, pos, WINDOW_MINUTES, MIN_TRADE_VALUE, daily_df, N_DAY_HIGH)
            rows.append(
                {
                    "code": code,
                    "entry_time": minute_df.index[pos],
                    "exit_time": minute_df.index[exit_idx],
                    "pct": pct,
                    **feats,
                }
            )

    return pd.DataFrame(rows)


def compute_portfolio_metrics(result) -> dict:
    """simulate_slot_portfolio 결과 하나로 승률/손익비/평균R/총수익률/MDD/거래건수를
    집계한다. MDD는 exit_time 순으로 계좌 잔고를 재생한 equity curve 기준."""
    taken = result.taken_trades
    n = len(taken)
    if n == 0:
        return {
            "n_trades": 0, "skipped_count": result.skipped_count, "win_rate_pct": 0.0,
            "profit_factor": 0.0, "avg_r_multiple": 0.0, "total_return_pct": 0.0, "mdd_pct": 0.0,
        }

    wins = [t for t in taken if t.profit > 0]
    losses = [t for t in taken if t.profit <= 0]
    gross_profit = sum(t.profit for t in wins)
    gross_loss = -sum(t.profit for t in losses)

    equity = result.initial_capital
    peak = equity
    mdd = 0.0
    for t in sorted(taken, key=lambda t: t.exit_time):
        equity += t.profit
        peak = max(peak, equity)
        if peak > 0:
            mdd = max(mdd, (peak - equity) / peak)

    return {
        "n_trades": n,
        "skipped_count": result.skipped_count,
        "win_rate_pct": len(wins) / n * 100,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        # R = 거래 순손익률 / 손절폭(STOP_LOSS_PCT) — 리스크 1단위 대비 평균 손익 근사치.
        "avg_r_multiple": (sum(t.pct for t in taken) / n) / STOP_LOSS_PCT,
        "total_return_pct": (result.final_capital / result.initial_capital - 1) * 100,
        "mdd_pct": mdd * 100,
    }


def run_walk_forward(
    trades_df: pd.DataFrame,
    train_days: int = 240,
    test_days: int = 60,
    step_days: int = 60,
    # ⚠️ 이 두 기본값은 워크포워드로 검증된 게 아니라 단일 IS 구간(final_strategy.py의
    # RECOMMENDED_* 주석 참고)에서 고른 값이다 — 여기서 "기본값"으로 그대로 물려받으면
    # 이 함수의 OOS 결과가 실은 그 값으로 최적화된 IS 성과를 재확인하는 꼴이 된다.
    proba_threshold: float = RECOMMENDED_PROBA_THRESHOLD,
    max_concurrent_positions: int = RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    initial_capital: float = 10_000_000,
) -> dict:
    """IS(train) 구간 거래로만 ML 필터를 학습해 OOS(test) 구간에 적용하는 롤링
    워크포워드. 폴드가 진행될수록 최신 데이터로 재학습하며, wf_split이 train_end <
    test_start를 강제하므로 미래 데이터가 학습에 섞이지 않는다. 폴드별 OOS 채택
    거래를 시간순으로 이어붙인 뒤 하나의 포트폴리오로 시뮬레이션한다."""
    if trades_df.empty:
        empty_metrics = compute_portfolio_metrics(
            simulate_slot_portfolio(pd.DataFrame(columns=TRADE_COLUMNS), initial_capital, max_concurrent_positions)
        )
        return {"folds": [], "metrics": empty_metrics, "combined_oos_trades": trades_df}

    start = trades_df["entry_time"].min().date()
    end = trades_df["entry_time"].max().date()
    splits = wf_split(start, end, train_days, test_days, step_days)

    fold_reports = []
    oos_frames = []

    for sp in splits:
        is_df = trades_df[trades_df["entry_time"].dt.date.between(sp.train_start, sp.train_end)]
        oos_df = trades_df[trades_df["entry_time"].dt.date.between(sp.test_start, sp.test_end)]

        fold = {
            "train_start": sp.train_start, "train_end": sp.train_end,
            "test_start": sp.test_start, "test_end": sp.test_end,
            "n_is_trades": len(is_df), "n_oos_candidates": len(oos_df),
        }

        if oos_df.empty:
            fold["status"] = "skipped (OOS 후보 없음)"
            fold_reports.append(fold)
            continue

        try:
            labels = (is_df["pct"] > 0).astype(int)
            trained = train_entry_filter_model(is_df[FEATURE_COLUMNS], labels, model_type="random_forest", **MODEL_KWARGS)
        except InsufficientTrainingDataError as exc:
            fold["status"] = f"skipped ({exc})"
            fold_reports.append(fold)
            continue

        proba = predict_quality_proba(trained, oos_df[FEATURE_COLUMNS])
        filtered = oos_df.loc[proba[proba >= proba_threshold].index]

        fold["n_oos_taken_after_ml"] = len(filtered)
        fold["status"] = "ok"
        fold_reports.append(fold)
        oos_frames.append(filtered)

    combined_oos = pd.concat(oos_frames) if oos_frames else trades_df.iloc[0:0]
    portfolio = simulate_slot_portfolio(
        combined_oos[TRADE_COLUMNS], initial_capital=initial_capital, max_concurrent_positions=max_concurrent_positions
    )
    metrics = compute_portfolio_metrics(portfolio)

    return {"folds": fold_reports, "metrics": metrics, "combined_oos_trades": combined_oos}


def run_full_sample_baseline(
    trades_df: pd.DataFrame,
    proba_threshold: float = RECOMMENDED_PROBA_THRESHOLD,
    max_concurrent_positions: int = RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    initial_capital: float = 10_000_000,
) -> dict:
    """ML 필터를 전체 데이터로 학습해 같은 전체 데이터에 그대로 적용한 In-Sample
    성과 (train-entry-model의 기본 학습 방식과 동일). 워크포워드 OOS 결과와 격차가
    크면 과최적화(성과 부풀림) 신호로 본다."""
    labels = (trades_df["pct"] > 0).astype(int)
    trained = train_entry_filter_model(trades_df[FEATURE_COLUMNS], labels, model_type="random_forest", **MODEL_KWARGS)
    proba = predict_quality_proba(trained, trades_df[FEATURE_COLUMNS])
    filtered = trades_df.loc[proba[proba >= proba_threshold].index]
    portfolio = simulate_slot_portfolio(filtered[TRADE_COLUMNS], initial_capital, max_concurrent_positions)
    return compute_portfolio_metrics(portfolio)


def run_no_filter_baseline(
    trades_df: pd.DataFrame,
    max_concurrent_positions: int = RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    initial_capital: float = 10_000_000,
) -> dict:
    """ML 필터 없이 strategy_1 진입조건(조건1~8)+tiered exit 자체만의 전체 표본 성과."""
    portfolio = simulate_slot_portfolio(trades_df[TRADE_COLUMNS], initial_capital, max_concurrent_positions)
    return compute_portfolio_metrics(portfolio)


def _fmt_pf(pf: float) -> str:
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def print_report(no_filter: dict, in_sample: dict, wf_result: dict) -> None:
    rows = [
        ("ML필터 없음 (전체표본, 조건1~8+tiered exit만)", no_filter),
        ("ML필터 In-Sample (학습=검증 전체표본, 참고용)", in_sample),
        ("ML필터 워크포워드 OOS (롤링 재학습, 신뢰 가능)", wf_result["metrics"]),
    ]
    print("\n=== strategy_1 성과 요약 (동시보유 슬롯 포트폴리오 기준) ===")
    print(f"{'구분':50s} {'거래수':>6s} {'승률%':>7s} {'손익비':>7s} {'평균R':>7s} {'총수익%':>8s} {'MDD%':>6s}")
    for label, m in rows:
        print(
            f"{label:50s} {m['n_trades']:>6d} {m['win_rate_pct']:>7.1f} {_fmt_pf(m['profit_factor']):>7s} "
            f"{m['avg_r_multiple']:>7.2f} {m['total_return_pct']:>8.1f} {m['mdd_pct']:>6.1f}"
        )

    print("\n=== 워크포워드 폴드별 상세 ===")
    for f in wf_result["folds"]:
        print(f)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--train-days", type=int, default=240)
    parser.add_argument("--test-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=60)
    parser.add_argument("--proba-threshold", type=float, default=RECOMMENDED_PROBA_THRESHOLD)
    parser.add_argument("--max-concurrent-positions", type=int, default=RECOMMENDED_MAX_CONCURRENT_POSITIONS)
    parser.add_argument("--initial-capital", type=float, default=10_000_000)
    parser.add_argument("--trades-csv", default=None, help="스캔한 거래 전체(피처 포함)를 저장할 CSV 경로(선택)")
    args = parser.parse_args()

    print("전 종목 스캔 중 (final_strategy.detect_final_entries 조건 적용)...")
    trades_df = scan_all_trades(args.data_dir)
    if trades_df.empty:
        print("진입 신호가 하나도 없습니다 — 데이터/조건을 확인하세요.")
        return

    print(
        f"총 진입 신호 {len(trades_df)}건, 종목 {trades_df['code'].nunique()}개, "
        f"기간 {trades_df['entry_time'].min()} ~ {trades_df['entry_time'].max()}"
    )
    if args.trades_csv:
        trades_df.to_csv(args.trades_csv, index=False)
        print(f"전체 거래 원본 저장: {args.trades_csv}")

    no_filter = run_no_filter_baseline(trades_df, args.max_concurrent_positions, args.initial_capital)
    in_sample = run_full_sample_baseline(
        trades_df, args.proba_threshold, args.max_concurrent_positions, args.initial_capital
    )
    wf_result = run_walk_forward(
        trades_df, args.train_days, args.test_days, args.step_days,
        args.proba_threshold, args.max_concurrent_positions, args.initial_capital,
    )
    print_report(no_filter, in_sample, wf_result)


if __name__ == "__main__":
    main()
