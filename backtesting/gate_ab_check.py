"""ML 진입필터 게이트가 실제로 선별을 하는지, 아니면 거래 수만 줄이는지 확인.

validate_strategy1.run_walk_forward는 "게이트 켠" 결과(OOS 158건, +평균R 0.00)만 낸다.
그걸 "게이트 없음" 전체표본(1722건, 평균R -0.08)과 비교하면 표본(구간)이 다른 채로
비교하는 것이라 게이트의 실력을 판정할 수 없다 — 같은 워크포워드 폴드의 같은 OOS
후보집합 안에서 게이트를 껐을 때(그 폴드 후보 전부 진입)와 켰을 때(ML 통과분만
진입)를 나란히 비교해야 한다.

기존 함수만 조합한다(신규 시뮬레이션 로직 없음):
- validate_strategy1.scan_all_trades/compute_portfolio_metrics/MODEL_KWARGS/TRADE_COLUMNS
- ml.walk_forward.split (IS/OOS 날짜 분할)
- ml_entry_filter.train_entry_filter_model/predict_quality_proba
- portfolio_sim.simulate_slot_portfolio

실행: python -m backtesting.gate_ab_check
      (이미 스캔한 거래를 재사용하려면 --trades-csv results/strategy1_trades_full.csv)
"""
import argparse
from datetime import date

import pandas as pd

from .final_strategy import RECOMMENDED_MAX_CONCURRENT_POSITIONS, RECOMMENDED_PROBA_THRESHOLD
from .ml.walk_forward import split as wf_split
from .ml_entry_filter import (
    FEATURE_COLUMNS,
    InsufficientTrainingDataError,
    predict_quality_proba,
    train_entry_filter_model,
)
from .portfolio_sim import simulate_slot_portfolio
from .validate_strategy1 import MODEL_KWARGS, TRADE_COLUMNS, compute_portfolio_metrics, scan_all_trades


def _train_and_predict_per_fold(trades_df: pd.DataFrame, splits: list) -> list[dict]:
    """폴드마다 딱 한 번만 학습+예측한다 — A/B도 threshold sweep도 이 결과를 재사용
    (threshold를 바꿀 때마다 재학습하면 3폴드 x 9임계값 = 27번 학습하게 된다)."""
    fold_data = []
    for sp in splits:
        is_df = trades_df[trades_df["entry_time"].dt.date.between(sp.train_start, sp.train_end)]
        oos_df = trades_df[trades_df["entry_time"].dt.date.between(sp.test_start, sp.test_end)]

        if oos_df.empty:
            fold_data.append({"split": sp, "oos_df": oos_df, "proba": None, "status": "skipped (OOS 후보 없음)"})
            continue
        try:
            labels = (is_df["pct"] > 0).astype(int)
            trained = train_entry_filter_model(is_df[FEATURE_COLUMNS], labels, model_type="random_forest", **MODEL_KWARGS)
        except InsufficientTrainingDataError as exc:
            fold_data.append({"split": sp, "oos_df": oos_df, "proba": None, "status": f"skipped ({exc})"})
            continue

        proba = predict_quality_proba(trained, oos_df[FEATURE_COLUMNS])
        fold_data.append({"split": sp, "oos_df": oos_df, "proba": proba, "status": "ok"})
    return fold_data


def _portfolio_metrics(df: pd.DataFrame, initial_capital: float, max_concurrent_positions: int) -> dict:
    portfolio = simulate_slot_portfolio(
        df[TRADE_COLUMNS], initial_capital=initial_capital, max_concurrent_positions=max_concurrent_positions
    )
    return compute_portfolio_metrics(portfolio)


def gate_ab_per_fold(
    trades_df: pd.DataFrame,
    train_days: int = 240,
    test_days: int = 60,
    step_days: int = 60,
    proba_threshold: float = RECOMMENDED_PROBA_THRESHOLD,
    max_concurrent_positions: int = RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    initial_capital: float = 10_000_000,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """폴드별 + 합산으로 게이트 끔(off, 그 폴드 OOS 후보 전부)과 켬(on, ML 통과분만)의
    포트폴리오 성과를 나란히 반환한다. 같은 폴드·같은 후보집합이므로 직접 비교 가능.

    start/end를 안 주면 trades_df 자신의 entry_time 범위로 잡는다(기존 동작 그대로).
    **서로 다른 두 trades_df를 비교할 때(A/B)는 반드시 같은 start를 밖에서 고정해
    넘겨야 한다** — 그러지 않으면 두 trades_df의 min(entry_time)이 며칠씩 달라
    폴드 경계 자체가 어긋난다(regime_filter_ab.py에서 실측으로 발견한 버그 — 폴드
    시작점은 달력에서 고정돼야지 데이터가 우연히 정하면 안 된다)."""
    start = start if start is not None else trades_df["entry_time"].min().date()
    end = end if end is not None else trades_df["entry_time"].max().date()
    splits = wf_split(start, end, train_days, test_days, step_days)
    fold_data = _train_and_predict_per_fold(trades_df, splits)

    rows = []
    off_frames, on_frames = [], []
    for i, fd in enumerate(fold_data, 1):
        sp = fd["split"]
        base = {"fold": i, "test_start": sp.test_start, "test_end": sp.test_end}
        if fd["status"] != "ok":
            rows.append({**base, "side": "off", "status": fd["status"]})
            rows.append({**base, "side": "on", "status": fd["status"]})
            continue

        oos_df, proba = fd["oos_df"], fd["proba"]
        filtered = oos_df.loc[proba[proba >= proba_threshold].index]

        rows.append({**base, "side": "off", "status": "ok", **_portfolio_metrics(oos_df, initial_capital, max_concurrent_positions)})
        rows.append({**base, "side": "on", "status": "ok", **_portfolio_metrics(filtered, initial_capital, max_concurrent_positions)})
        off_frames.append(oos_df)
        on_frames.append(filtered)

    combined_off = pd.concat(off_frames) if off_frames else trades_df.iloc[0:0]
    combined_on = pd.concat(on_frames) if on_frames else trades_df.iloc[0:0]
    rows.append({"fold": "합산", "test_start": None, "test_end": None, "side": "off", "status": "ok",
                 **_portfolio_metrics(combined_off, initial_capital, max_concurrent_positions)})
    rows.append({"fold": "합산", "test_start": None, "test_end": None, "side": "on", "status": "ok",
                 **_portfolio_metrics(combined_on, initial_capital, max_concurrent_positions)})
    return pd.DataFrame(rows)


def threshold_sensitivity(
    trades_df: pd.DataFrame,
    thresholds: list[float],
    train_days: int = 240,
    test_days: int = 60,
    step_days: int = 60,
    max_concurrent_positions: int = RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    initial_capital: float = 10_000_000,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """같은 폴드·같은 학습모델에서 proba_threshold만 바꿔 합산 OOS 성과가 어떻게
    움직이는지 본다. ⚠️ 여기서 "제일 좋아 보이는" threshold를 골라 쓰면 안 된다 —
    OOS로 고르는 순간 그 선택 자체가 리크다. 예측력이 임계값에 얼마나 민감한지
    (성과 절벽이 있는지) 확인하는 용도로만 쓴다.

    start/end 규칙은 gate_ab_per_fold와 동일 — 여러 trades_df를 비교할 땐 고정해서 넘길 것."""
    start = start if start is not None else trades_df["entry_time"].min().date()
    end = end if end is not None else trades_df["entry_time"].max().date()
    splits = wf_split(start, end, train_days, test_days, step_days)
    fold_data = _train_and_predict_per_fold(trades_df, splits)

    rows = []
    for th in thresholds:
        frames = [
            fd["oos_df"].loc[fd["proba"][fd["proba"] >= th].index]
            for fd in fold_data if fd["status"] == "ok"
        ]
        combined = pd.concat(frames) if frames else trades_df.iloc[0:0]
        rows.append({"proba_threshold": th, **_portfolio_metrics(combined, initial_capital, max_concurrent_positions)})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--trades-csv", default=None, help="이미 스캔한 거래 CSV를 재사용(없으면 새로 스캔)")
    parser.add_argument("--save-trades-csv", default=None, help="새로 스캔한 결과를 저장해 재사용(선택)")
    parser.add_argument("--train-days", type=int, default=240)
    parser.add_argument("--test-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=60)
    parser.add_argument("--proba-threshold", type=float, default=RECOMMENDED_PROBA_THRESHOLD)
    parser.add_argument("--max-concurrent-positions", type=int, default=RECOMMENDED_MAX_CONCURRENT_POSITIONS)
    parser.add_argument("--initial-capital", type=float, default=10_000_000)
    args = parser.parse_args()

    if args.trades_csv:
        trades_df = pd.read_csv(args.trades_csv, parse_dates=["entry_time", "exit_time"])
    else:
        trades_df = scan_all_trades(args.data_dir)
        if args.save_trades_csv:
            trades_df.to_csv(args.save_trades_csv, index=False)
    print(f"거래 {len(trades_df)}건, 종목 {trades_df['code'].nunique()}개")

    pd.set_option("display.width", 200)

    ab_df = gate_ab_per_fold(
        trades_df, args.train_days, args.test_days, args.step_days,
        args.proba_threshold, args.max_concurrent_positions, args.initial_capital,
    )
    print(f"\n=== 게이트 끔(off) vs 켬(on) - 같은 폴드/같은 OOS 후보집합 (threshold={args.proba_threshold}) ===")
    print(ab_df.to_string(index=False))

    thresholds = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    sens_df = threshold_sensitivity(
        trades_df, thresholds, args.train_days, args.test_days, args.step_days,
        args.max_concurrent_positions, args.initial_capital,
    )
    print("\n=== proba_threshold 민감도 (합산 OOS) - 튜닝용 아님, 예측력의 임계값 민감도 확인용 ===")
    print(sens_df.to_string(index=False))


if __name__ == "__main__":
    main()
