"""파라미터 조합 반복 실행 + In/Out-of-sample(규칙 기반) 또는 워크포워드(ML) 분리.

Design: docs/02-design/features/strategy-backtesting.design.md §4.1, §4.3
"""
import concurrent.futures as cf
import os
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


def _jobs() -> int:
    """쓸 프로세스 수. BACKTEST_JOBS 로 조절하고 기본은 코어 수.

    1 로 두면 프로세스를 안 띄운다 — 결과가 병렬과 같은지 대조할 때 쓴다.
    """
    try:
        n = int(os.environ.get("BACKTEST_JOBS", "0"))
    except ValueError:
        n = 0
    return n if n > 0 else (os.cpu_count() or 4)


_CANDLES: dict = {}        # 프로세스마다 종목별 캔들 캐시


def _candles(stock_code, start, end, interval, data_dir):
    """워커가 스스로 읽는다. DataFrame 을 태스크마다 피클하면 그게 더 비싸다.

    본 프로세스가 이미 한 번 읽어 로컬 캐시를 채워 뒀으므로 여기서는 파일만 읽는다
    (실측 0.00초). client=None 이라 API 폴백은 없다 — 그래서 병렬 경로는
    use_local_data=True 일 때만 쓴다.
    """
    key = (stock_code, interval)
    if key not in _CANDLES:
        _CANDLES[key] = load_history(None, stock_code, start, end, interval=interval,
                                     use_local_data=True, data_dir=data_dir)
    return _CANDLES[key]


def _combo_task(packed):
    """워커용. 캔들을 직접 읽어 _one_combo 에 넘긴다."""
    (params, strategy, stock_code, split_idx, start, end, interval, data_dir,
     commission_rate, slippage_rate, initial_capital, tax_rate) = packed
    c = _candles(stock_code, start, end, interval, data_dir)
    return _one_combo((params, strategy, c.iloc[:split_idx], c.iloc[split_idx:], stock_code,
                       commission_rate, slippage_rate, initial_capital, tax_rate))


def _one_combo(packed):
    """파라미터 조합 하나. 순차 경로와 **같은 코드**를 부르도록 여기 한 번만 적는다."""
    (params, strategy, in_sample, out_of_sample, stock_code,
     commission_rate, slippage_rate, initial_capital, tax_rate) = packed
    try:
        signals_is = strategy.evaluate(in_sample, params)
        signals_oos = strategy.evaluate(out_of_sample, params)
    except ValueError:
        return None            # 잘못된 파라미터 조합 (예: short_window >= long_window)

    trades_is = simulator.run(
        in_sample, signals_is, commission_rate, slippage_rate, initial_capital, stock_code,
        tax_rate=tax_rate,
    )
    trades_oos = simulator.run(
        out_of_sample, signals_oos, commission_rate, slippage_rate, initial_capital, stock_code,
        tax_rate=tax_rate,
    )
    return GridSearchResult(
        stock_code=stock_code,
        strategy_name=strategy.name,
        params=params,
        in_sample=metrics.compute(trades_is, in_sample, initial_capital),
        out_of_sample=metrics.compute(trades_oos, out_of_sample, initial_capital),
        trades=trades_is + trades_oos,
        benchmark_is_return_pct=metrics.buy_and_hold_return_pct(in_sample),
        benchmark_oos_return_pct=metrics.buy_and_hold_return_pct(out_of_sample),
    )


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
    combos = _param_combinations(param_grid)
    jobs = _jobs()

    # 종목별로 캔들을 먼저 읽는다. 로컬 캐시를 채우는 일이기도 해서, 뒤이어 워커가
    # 파일만 읽으면 된다. API 폴백이 필요한 종목도 여기서 해결된다.
    loaded = []
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
        if split_idx <= 0 or split_idx >= len(candles):
            continue
        loaded.append((stock_code, candles, split_idx))

    tasks = len(loaded) * len(combos)
    bars = sum(len(c) for _, c, _ in loaded) / max(len(loaded), 1)
    # 조합당 비용 ≈ 봉수 × 65µs (2026-08-29 실측: 403봉 26ms). Windows 는 프로세스를
    # 띄우는 데만 워커당 2초쯤 든다(pandas 재임포트) — 작은 격자에서는 병렬이 **더
    # 느리다**(실측 1.7초 -> 10.8초). 그래서 순차 예상이 충분히 클 때만 나눈다.
    est_sec = tasks * bars * 65e-6
    parallel = jobs > 1 and use_local_data and est_sec > 15

    if parallel:
        packed = [(p, strategy, code, idx, start, end, interval, data_dir,
                   commission_rate, slippage_rate, initial_capital, tax_rate)
                  for code, _, idx in loaded for p in combos]
        with cf.ProcessPoolExecutor(max_workers=min(jobs, len(packed))) as ex:
            for r in ex.map(_combo_task, packed,
                            chunksize=max(1, len(packed) // (jobs * 4) or 1)):
                if r is not None:
                    results.append(r)
        return results

    for stock_code, candles, split_idx in loaded:
        in_sample, out_of_sample = candles.iloc[:split_idx], candles.iloc[split_idx:]
        for params in combos:
            r = _one_combo((params, strategy, in_sample, out_of_sample, stock_code,
                            commission_rate, slippage_rate, initial_capital, tax_rate))
            if r is not None:
                results.append(r)

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
