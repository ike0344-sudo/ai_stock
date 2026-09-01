"""홀드아웃 개봉 — 2026-09-01, **일회성**. 사전 판정 기준은
`state/agent_reports/backtest-agent_20260901-015509_holdout_open.md`에
결과를 보기 전에 먼저 적었다 — 이 스크립트는 그 기준을 확정한 뒤에만
실행한다. 이 구간(2026-06-05~2026-08-28)은 이후 다시 검증용으로 못 쓴다
— 재사용/재실행 목적의 모듈이 아니다(다른 코드에서 이 파일을 import하지
말 것).

구성: 기준선 그대로(7조건 전부 ON), `results/regime_on_trades.csv`
재사용(재스캔 안 함, 081152 리포트가 쓴 파일과 건수·기간 일치 확인됨).
ML on(0.3) 모델은 홀드아웃 이전 데이터로만 학습.

실행: python -m backtesting.holdout_open_20260901
"""
import pandas as pd

from .final_strategy import RECOMMENDED_MAX_CONCURRENT_POSITIONS, RECOMMENDED_PROBA_THRESHOLD
from .ml_entry_filter import FEATURE_COLUMNS, train_entry_filter_model, predict_quality_proba
from .portfolio_sim import monthly_profit_breakdown, simulate_slot_portfolio
from .regime_filter_ab import _holdout_cutoff
from .validate_strategy1 import MODEL_KWARGS, TRADE_COLUMNS, compute_portfolio_metrics

# 사전 판정 기준(위 리포트와 동일한 값) - 결과를 본 뒤 바꾸지 않는다.
MIN_TRADES = 30
CONFIRM_PF = 1.0
FAIL_PF = 0.80


def classify_verdict(total_return_pct: float, profit_factor: float, n_trades: int) -> str:
    if n_trades < MIN_TRADES:
        return "판단보류(표본부족)"
    if total_return_pct > 0 and profit_factor >= CONFIRM_PF:
        return "확증"
    if total_return_pct <= 0 or profit_factor < FAIL_PF:
        return "실패(재현 실패)"
    return "혼조(그레이존)"


def run() -> dict:
    baseline = pd.read_csv("results/regime_on_trades.csv", parse_dates=["entry_time", "exit_time"])
    holdout_start, start, end = _holdout_cutoff(baseline)

    pre_holdout = baseline[baseline["entry_time"].dt.date < holdout_start].reset_index(drop=True)
    holdout = baseline[baseline["entry_time"].dt.date >= holdout_start].reset_index(drop=True)

    portfolio_off = simulate_slot_portfolio(
        holdout[TRADE_COLUMNS], initial_capital=10_000_000,
        max_concurrent_positions=RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    )
    metrics_off = compute_portfolio_metrics(portfolio_off)
    monthly_off = monthly_profit_breakdown(portfolio_off)
    verdict_off = classify_verdict(metrics_off["total_return_pct"], metrics_off["profit_factor"], metrics_off["n_trades"])
    results = {"ML off": {"metrics": metrics_off, "monthly": monthly_off, "verdict": verdict_off,
                           "n_candidates": len(holdout)}}

    trained = train_entry_filter_model(
        pre_holdout[FEATURE_COLUMNS], (pre_holdout["pct"] > 0).astype(int),
        model_type="random_forest", **MODEL_KWARGS,
    )
    proba = predict_quality_proba(trained, holdout[FEATURE_COLUMNS])
    ml_on_df = holdout.loc[proba[proba >= RECOMMENDED_PROBA_THRESHOLD].index]
    portfolio_on = simulate_slot_portfolio(
        ml_on_df[TRADE_COLUMNS], initial_capital=10_000_000,
        max_concurrent_positions=RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    )
    metrics_on = compute_portfolio_metrics(portfolio_on)
    monthly_on = monthly_profit_breakdown(portfolio_on)
    verdict_on = classify_verdict(metrics_on["total_return_pct"], metrics_on["profit_factor"], metrics_on["n_trades"])
    results["ML on(0.3)"] = {"metrics": metrics_on, "monthly": monthly_on, "verdict": verdict_on,
                              "n_candidates": len(ml_on_df)}

    return {"holdout_start": holdout_start, "start": start, "end": end,
            "n_pre_holdout": len(pre_holdout), "n_holdout_candidates": len(holdout), "results": results}


def main():
    out = run()
    print(f"홀드아웃 구간: {out['holdout_start']} ~ {out['end']} "
          f"(전체 커버 {out['start']}~{out['end']})")
    print(f"홀드아웃 이전(ML 학습용) {out['n_pre_holdout']}건, "
          f"홀드아웃 원시후보 {out['n_holdout_candidates']}건")
    for label, r in out["results"].items():
        m = r["metrics"]
        print(f"\n=== {label} ===")
        print(f"원시후보 {r['n_candidates']}건 -> 채택(taken) {m['n_trades']}건 "
              f"(스킵 {m.get('skipped_count', '-')}건)")
        print(f"승률 {m['win_rate_pct']:.1f}% | PF {m['profit_factor']:.3f} | "
              f"평균R배수 {m['avg_r_multiple']:.3f} | 합산수익률 {m['total_return_pct']:.2f}% | "
              f"MDD {m['mdd_pct']:.2f}%")
        print(f"판정: {r['verdict']}")
        print("월별:")
        print(r["monthly"].to_string(index=False) if not r["monthly"].empty else "(거래 없음)")

    return out


if __name__ == "__main__":
    main()
