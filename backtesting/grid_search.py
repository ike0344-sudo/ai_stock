"""파라미터 조합 반복 실행 + In/Out-of-sample(규칙 기반) 또는 워크포워드(ML) 분리.

Design: docs/02-design/features/strategy-backtesting.design.md §4.1, §4.3
"""
from datetime import date
from itertools import product

from . import metrics, simulator
from .data_loader import load_history
from .ml import model as ml_model
from .ml.features import build_features
from .ml.labeling import make_labels
from .ml.walk_forward import split as walk_forward_split
from .types import GridSearchResult, PerformanceMetrics


def _param_combinations(param_grid: dict) -> list[dict]:
    keys = list(param_grid.keys())
    values_product = product(*(param_grid[k] for k in keys))
    return [dict(zip(keys, values)) for values in values_product]


def run_rule_based(
    client,
    stock_codes: list[str],
    strategy,
    param_grid: dict,
    start: date,
    end: date,
    interval: str = "day",
    initial_capital: float = 10_000_000,
    commission_rate: float = 0.00015,
    slippage_rate: float = 0.001,
    tax_rate: float = simulator.DEFAULT_TAX_RATE,
    in_sample_ratio: float = 0.7,
    use_local_data: bool = True,
    data_dir: str = "data",
) -> list[GridSearchResult]:
    """규칙 기반 전략(MA/RSI 등)을 종목·파라미터 조합별로 백테스트.

    use_local_data=True(기본값)면 download-universe/update-top35가 받아둔
    로컬 data/를 우선 사용해 라이브 API 호출 없이 빠르게 돈다. 로컬에 없는
    종목/기간은 자동으로 API 폴백.
    """
    results: list[GridSearchResult] = []

    for stock_code in stock_codes:
        try:
            candles = load_history(
                client, stock_code, start, end, interval=interval,
                use_local_data=use_local_data, data_dir=data_dir,
            )
        except Exception:
            continue
        if candles.empty:
            continue

        split_idx = int(len(candles) * in_sample_ratio)
        in_sample = candles.iloc[:split_idx]
        out_of_sample = candles.iloc[split_idx:]
        if in_sample.empty or out_of_sample.empty:
            continue

        for params in _param_combinations(param_grid):
            try:
                signals_is = strategy.evaluate(in_sample, params)
                signals_oos = strategy.evaluate(out_of_sample, params)
            except ValueError:
                continue  # 잘못된 파라미터 조합 (예: short_window >= long_window)

            trades_is = simulator.run(
                in_sample, signals_is, commission_rate, slippage_rate, initial_capital, stock_code,
                tax_rate=tax_rate,
            )
            trades_oos = simulator.run(
                out_of_sample, signals_oos, commission_rate, slippage_rate, initial_capital, stock_code,
                tax_rate=tax_rate,
            )

            results.append(
                GridSearchResult(
                    stock_code=stock_code,
                    strategy_name=strategy.name,
                    params=params,
                    in_sample=metrics.compute(trades_is, in_sample, initial_capital),
                    out_of_sample=metrics.compute(trades_oos, out_of_sample, initial_capital),
                    trades=trades_is + trades_oos,
                    benchmark_is_return_pct=metrics.buy_and_hold_return_pct(in_sample),
                    benchmark_oos_return_pct=metrics.buy_and_hold_return_pct(out_of_sample),
                )
            )

    return results


def run_ml_walk_forward(
    client,
    stock_codes: list[str],
    param_grid: dict,
    start: date,
    end: date,
    interval: str = "5",
    initial_capital: float = 10_000_000,
    commission_rate: float = 0.00015,
    slippage_rate: float = 0.001,
    tax_rate: float = simulator.DEFAULT_TAX_RATE,
    train_days: int = 30,
    test_days: int = 5,
    step_days: int = 5,
    label_horizon_minutes: int = 30,
    label_return_threshold: float = 0.005,
    model_type: str = "random_forest",
    use_local_data: bool = True,
    data_dir: str = "data",
) -> list[GridSearchResult]:
    """데이트레이딩 ML 전략을 워크포워드로 학습/검증하며 종목·파라미터 조합별로 집계.

    각 워크포워드 분할의 학습 구간 성과(in_sample)와 검증 구간 성과(out_of_sample)를
    평균하여 과최적화 여부(두 값의 격차)를 판단할 수 있게 한다.

    use_local_data 동작은 run_rule_based와 동일 (기본 True — 로컬 data/ 우선 사용).
    """
    from .strategies.ml_strategy import MLStrategy

    strategy = MLStrategy()
    results: list[GridSearchResult] = []

    for stock_code in stock_codes:
        try:
            candles = load_history(
                client, stock_code, start, end, interval=interval,
                use_local_data=use_local_data, data_dir=data_dir,
            )
        except Exception:
            continue
        if candles.empty:
            continue

        wf_splits = walk_forward_split(start, end, train_days, test_days, step_days)

        for params in _param_combinations(param_grid):
            is_metrics_list: list[PerformanceMetrics] = []
            oos_metrics_list: list[PerformanceMetrics] = []
            is_benchmark_list: list[float] = []
            oos_benchmark_list: list[float] = []
            all_trades = []

            for wf in wf_splits:
                train_candles = candles.loc[str(wf.train_start):str(wf.train_end)]
                test_candles = candles.loc[str(wf.test_start):str(wf.test_end)]
                if train_candles.empty or test_candles.empty:
                    continue

                features = build_features(train_candles)
                labels = make_labels(train_candles, label_horizon_minutes, label_return_threshold)

                try:
                    trained = ml_model.train(features, labels, model_type=model_type)
                except ml_model.InsufficientTrainingDataError:
                    continue

                eval_params = {**params, "model": trained}

                train_signals = strategy.evaluate(train_candles, eval_params)
                train_trades = simulator.run(
                    train_candles, train_signals, commission_rate, slippage_rate,
                    initial_capital, stock_code, force_eod_close=True, tax_rate=tax_rate,
                )
                is_metrics_list.append(metrics.compute(train_trades, train_candles, initial_capital))
                is_benchmark_list.append(metrics.buy_and_hold_return_pct(train_candles))

                test_signals = strategy.evaluate(test_candles, eval_params)
                test_trades = simulator.run(
                    test_candles, test_signals, commission_rate, slippage_rate,
                    initial_capital, stock_code, force_eod_close=True, tax_rate=tax_rate,
                )
                oos_metrics_list.append(metrics.compute(test_trades, test_candles, initial_capital))
                oos_benchmark_list.append(metrics.buy_and_hold_return_pct(test_candles))
                all_trades.extend(test_trades)

            if not oos_metrics_list:
                continue

            results.append(
                GridSearchResult(
                    stock_code=stock_code,
                    strategy_name=strategy.name,
                    params=params,
                    in_sample=_average_metrics(is_metrics_list),
                    out_of_sample=_average_metrics(oos_metrics_list),
                    trades=all_trades,
                    benchmark_is_return_pct=sum(is_benchmark_list) / len(is_benchmark_list),
                    benchmark_oos_return_pct=sum(oos_benchmark_list) / len(oos_benchmark_list),
                )
            )

    return results


def _average_metrics(metrics_list: list[PerformanceMetrics]) -> PerformanceMetrics:
    n = len(metrics_list)
    return PerformanceMetrics(
        total_return_pct=sum(m.total_return_pct for m in metrics_list) / n,
        cagr_pct=sum(m.cagr_pct for m in metrics_list) / n,
        win_rate_pct=sum(m.win_rate_pct for m in metrics_list) / n,
        max_drawdown_pct=max(m.max_drawdown_pct for m in metrics_list),
        sharpe_ratio=sum(m.sharpe_ratio for m in metrics_list) / n,
        num_trades=sum(m.num_trades for m in metrics_list),
    )
