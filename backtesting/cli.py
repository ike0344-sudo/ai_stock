"""백테스팅 CLI 진입점.

사용 예 (ai_stock/ 디렉터리에서 실행):
    python -m backtesting.cli rule --strategy ma_crossover --stocks 005930,000660 \
        --start 2025-01-01 --end 2026-01-01
    python -m backtesting.cli rule --strategy rsi --stocks 005930 --start 2025-01-01 --end 2026-01-01
    python -m backtesting.cli ml --stocks 005930 --start 2026-01-01 --end 2026-03-01 --interval 5
    python -m backtesting.cli compare --stocks 005930 --start 2025-06-01 --end 2026-07-01 --plot best.png
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd
from dotenv import load_dotenv
from kiwoom_client import KiwoomClient

from . import grid_search, report
from .bracket_scan import scan_bracket_zones, summarize_zones
from .dashboard_monitor import run_dashboard_monitor_loop
from .dashboard_server import run_dashboard_server
from .data_loader import (
    _atomic_to_csv,
    load_full_index_minute_history,
    load_full_minute_history,
    load_history,
    load_index_history,
)
from .final_strategy import RECOMMENDED_PROBA_THRESHOLD, train_and_save_final_model
from .heartbeat import write_heartbeat
from .live_monitor import run_monitor_loop
from .ml_entry_filter import FEATURE_COLUMNS, load_model
from .nasdaq_drop_monitor import DROP_THRESHOLD_PCT, WINDOW_SECONDS, run_nasdaq_drop_monitor
from .orderbook_collector import (
    is_market_open,
    run_collection_loop,
    wait_until_extended_market_open,
    wait_until_market_open,
)
from .oversold_strategy import STOCK_CODE as OVERSOLD_STOCK_CODE
from .oversold_trading_loop import run_oversold_trading_loop
from .risk_manager import RECOMMENDED_MAX_CONCURRENT_POSITIONS
from .screener import top_by_trading_value
from .strategies.envelope import EnvelopeStrategy
from .strategies.ma_crossover import MovingAverageCrossover
from .strategies.rsi_strategy import RsiStrategy
from .strategy3_scalp import DEFAULT_SIGNAL_LOG_PATH as STRATEGY3_DEFAULT_SIGNAL_LOG_PATH
from .strategy3_scalp import run_scalp_monitor_loop
from .strategy4_rank_watch import DEFAULT_SIGNAL_LOG_PATH as STRATEGY4_DEFAULT_SIGNAL_LOG_PATH
from .strategy4_rank_watch import run_rank_watch_loop
from .telegram_order_bot import run_telegram_order_bot
from .trading_loop import run_trading_loop
from .universe import build_liquid_universe, build_topn_union_universe
from .updater import update_top35

INDEX_CODES = {"001": "코스피종합", "101": "코스닥종합"}


def _strategy_state_defaults(strategy: str) -> dict:
    """run-trading의 --strategy로 상태·모델 경로 기본값을 state/{strategy}/,
    models/{strategy}/ 밑으로 네임스페이스한다 — 전략별로 별도 프로세스를 띄워도
    파일이 서로 덮어쓰지 않고, dashboard가 state 루트를 스캔해 전략 목록으로
    자동 인식할 수 있게 한다. --risk-state-path 등 개별 플래그로 명시하면 이 기본값
    대신 그 값이 쓰인다."""
    base = f"state/{strategy}"
    return {
        "model_path": f"models/{strategy}/entry_filter_model.joblib",
        "risk_state_path": f"{base}/risk_state.json",
        "order_log_path": f"{base}/orders.jsonl",
        "pnl_history_path": f"{base}/pnl_history.jsonl",
        "kill_switch_override_path": f"{base}/kill_switch_override.json",
    }


def _write_strategy_config(risk_state_path: str, config: dict) -> None:
    """run-trading 시작 시 실행 파라미터 스냅샷을 risk_state_path와 같은 폴더의
    config.json에 남긴다 — dashboard가 GET /api/config로 읽어 "이 전략이 지금 어떤
    조건값으로 도는지" 보여줄 수 있게 한다(risk_state.json 등 다른 상태 파일과 같은
    폴더에 둬야 대시보드의 전략별 경로 해석 규칙과 맞아떨어진다)."""
    config_path = os.path.join(os.path.dirname(risk_state_path), "config.json")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _build_client() -> KiwoomClient:
    load_dotenv()
    appkey = os.environ["KIWOOM_APPKEY"]
    secretkey = os.environ["KIWOOM_SECRETKEY"]
    is_mock = os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true"
    return KiwoomClient(appkey, secretkey, is_mock=is_mock)


def _save_to_results_dir(df: pd.DataFrame, label: str, results_dir: str = "results") -> None:
    """backtest-dashboard가 조회하는 results/{label}_{YYYYMMDD_HHMMSS}.csv 표준 규칙으로
    자동 저장한다(Design §3.1). 결과가 비어있으면 저장하지 않는다 — 빈 파일이 대시보드
    목록에 의미 없이 쌓이는 것을 방지."""
    if df.empty:
        return
    os.makedirs(results_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(results_dir, f"{label}_{timestamp}.csv")
    report.save_csv(df, path)


def _report(results, args, client=None, plot_interval: str = "day", results_label: str = "backtest") -> None:
    df = report.summarize(results)
    report.print_summary(df)
    if args.csv:
        report.save_csv(df, args.csv)
    _save_to_results_dir(df, results_label, results_dir=getattr(args, "results_dir", "results"))

    if getattr(args, "plot", None) and results:
        best = report.rank_results(results)[0]

        candles = load_history(
            client, best.stock_code, _parse_date(args.start), _parse_date(args.end), interval=plot_interval,
            use_local_data=not args.no_local_data, data_dir=args.data_dir,
        )
        title = f"[{best.strategy_name}] {best.stock_code} {best.params}"
        if best.out_of_sample.num_trades == 0:
            print(f"\n경고: 모든 조합의 OOS 거래가 0건이라 의미 있는 차트를 고를 수 없습니다. {title} 기준으로 시도합니다.")
        report.plot_best(candles, best.trades, title, save_path=args.plot)
        print(f"\n차트 저장됨: {args.plot} (최고 성과: {title})")


def _ma_param_grid(args) -> dict:
    return {
        "short_window": [int(x) for x in args.short_window.split(",")],
        "long_window": [int(x) for x in args.long_window.split(",")],
    }


def _rsi_param_grid(args) -> dict:
    return {
        "period": [int(x) for x in args.rsi_period.split(",")],
        "buy_below": [int(x) for x in args.rsi_buy_below.split(",")],
        "sell_above": [int(x) for x in args.rsi_sell_above.split(",")],
    }


def _ml_param_grid(args) -> dict:
    return {"buy_threshold": [float(x) for x in args.buy_threshold.split(",")]}


def _envelope_param_grid(args) -> dict:
    return {
        "ma_window": [int(x) for x in args.ma_window.split(",")],
        "envelope_pct": [float(x) for x in args.envelope_pct.split(",")],
        "exit_mode": args.exit_mode.split(","),
    }


def _run_rule(args) -> None:
    client = _build_client()
    stock_codes = args.stocks.split(",")

    if args.strategy == "ma_crossover":
        strategy = MovingAverageCrossover()
        param_grid = _ma_param_grid(args)
    elif args.strategy == "rsi":
        strategy = RsiStrategy()
        param_grid = _rsi_param_grid(args)
    else:
        strategy = EnvelopeStrategy()
        param_grid = _envelope_param_grid(args)

    results = grid_search.run_rule_based(
        client,
        stock_codes,
        strategy,
        param_grid,
        start=_parse_date(args.start),
        end=_parse_date(args.end),
        interval=args.interval,
        initial_capital=args.capital,
        commission_rate=args.commission_rate,
        slippage_rate=args.slippage_rate,
        tax_rate=args.tax_rate,
        in_sample_ratio=args.in_sample_ratio,
        use_local_data=not args.no_local_data,
        data_dir=args.data_dir,
    )
    _report(results, args, client, plot_interval=args.interval, results_label=args.strategy)


def _run_ml(args) -> None:
    client = _build_client()
    stock_codes = args.stocks.split(",")

    results = grid_search.run_ml_walk_forward(
        client,
        stock_codes,
        _ml_param_grid(args),
        start=_parse_date(args.start),
        end=_parse_date(args.end),
        interval=args.interval,
        initial_capital=args.capital,
        commission_rate=args.commission_rate,
        slippage_rate=args.slippage_rate,
        tax_rate=args.tax_rate,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        label_horizon_minutes=args.label_horizon_minutes,
        label_return_threshold=args.label_return_threshold,
        model_type=args.model_type,
        use_local_data=not args.no_local_data,
        data_dir=args.data_dir,
    )
    _report(results, args, client, plot_interval=args.interval, results_label="ml")


def _run_compare(args) -> None:
    """규칙 기반(MA/RSI) 전략과 ML 전략을 같은 종목·기간에 대해 실행해 하나의 리포트로 비교.

    Plan FR-16 / Analysis 갭 3(규칙-ML 통합 비교 CLI 미지원)에 대한 수정.
    """
    client = _build_client()
    stock_codes = args.stocks.split(",")
    start = _parse_date(args.start)
    end = _parse_date(args.end)

    use_local_data = not args.no_local_data
    results = []
    results += grid_search.run_rule_based(
        client, stock_codes, MovingAverageCrossover(), _ma_param_grid(args),
        start=start, end=end, interval=args.rule_interval,
        initial_capital=args.capital, commission_rate=args.commission_rate,
        slippage_rate=args.slippage_rate, tax_rate=args.tax_rate, in_sample_ratio=args.in_sample_ratio,
        use_local_data=use_local_data, data_dir=args.data_dir,
    )
    results += grid_search.run_rule_based(
        client, stock_codes, RsiStrategy(), _rsi_param_grid(args),
        start=start, end=end, interval=args.rule_interval,
        initial_capital=args.capital, commission_rate=args.commission_rate,
        slippage_rate=args.slippage_rate, tax_rate=args.tax_rate, in_sample_ratio=args.in_sample_ratio,
        use_local_data=use_local_data, data_dir=args.data_dir,
    )
    results += grid_search.run_ml_walk_forward(
        client, stock_codes, _ml_param_grid(args),
        start=start, end=end, interval=args.ml_interval,
        initial_capital=args.capital, commission_rate=args.commission_rate,
        slippage_rate=args.slippage_rate, tax_rate=args.tax_rate, train_days=args.train_days,
        test_days=args.test_days, step_days=args.step_days,
        label_horizon_minutes=args.label_horizon_minutes,
        label_return_threshold=args.label_return_threshold, model_type=args.model_type,
        use_local_data=use_local_data, data_dir=args.data_dir,
    )

    _report(results, args, client, plot_interval=args.rule_interval, results_label="compare")


def _run_scan_brackets(args) -> None:
    """거래대금 상위 종목을 스크리닝해, 1분봉 매 시점을 매수 시점으로 가정한
    -손절%/+익절% 결과를 사후 스캔하고 종목별·시간대별로 집계한다."""
    client = _build_client()
    trade_date = _parse_date(args.date)

    screened = top_by_trading_value(client, top_n=args.top_n, market=args.market)
    if screened.empty:
        print("스크리닝된 종목이 없습니다.")
        return

    all_outcomes = []
    per_stock_rows = []
    for _, row in screened.iterrows():
        stock_code = row["stock_code"]
        try:
            candles = load_history(
                client, stock_code, trade_date, trade_date, interval="1", use_cache=args.use_cache,
                use_local_data=not args.no_local_data, data_dir=args.data_dir,
            )
        except Exception as exc:
            print(f"경고: {stock_code} ({row['name']}) 조회 실패 - 스킵: {exc}")
            continue
        if candles.empty:
            continue

        outcomes = scan_bracket_zones(candles, args.stop_loss, args.take_profit)
        outcomes["stock_code"] = stock_code
        outcomes["name"] = row["name"]
        all_outcomes.append(outcomes)

        per_stock_rows.append(
            {
                "stock_code": stock_code,
                "name": row["name"],
                "n_entries": len(outcomes),
                "win_rate_pct": (outcomes["outcome"] == "win").mean() * 100,
                "avg_realized_pct": outcomes["realized_pct"].mean(),
            }
        )

    if not all_outcomes:
        print("조회된 캔들 데이터가 없습니다 (휴장일이거나 API 응답이 비어있을 수 있습니다).")
        return

    combined = pd.concat(all_outcomes, ignore_index=True)
    stock_summary = pd.DataFrame(per_stock_rows).sort_values("win_rate_pct", ascending=False)
    time_summary = summarize_zones(combined, bucket_minutes=args.bucket_minutes)

    print(f"\n=== 종목별 요약 ({trade_date}, 손절 -{args.stop_loss*100:.1f}% / 익절 +{args.take_profit*100:.1f}%) ===")
    for _, r in stock_summary.iterrows():
        print(
            f"{r['stock_code']} {r['name']}: n={r['n_entries']} "
            f"win_rate={r['win_rate_pct']:.1f}% avg={r['avg_realized_pct']:+.2f}%"
        )

    print(f"\n=== 시간대별 요약 (전 종목 통합, {args.bucket_minutes}분 단위) ===")
    for _, r in time_summary.iterrows():
        print(f"{r['time_bucket']}: n={r['n']} win_rate={r['win_rate_pct']:.1f}% avg={r['avg_realized_pct']:+.2f}%")

    if args.csv:
        combined.to_csv(args.csv, index=False)
        stock_summary.to_csv(args.csv.replace(".csv", "_by_stock.csv"), index=False)
        time_summary.to_csv(args.csv.replace(".csv", "_by_time.csv"), index=False)
        print(f"\n저장됨: {args.csv} (+ _by_stock.csv, _by_time.csv)")


def _run_download_universe(args) -> None:
    """유동성 상위 종목(+코스피/코스닥 지수)의 일봉·분봉을 data/ 아래에 저장.

    실행 시간이 종목당 API가 보유한 1분봉 이력 길이에 따라 크게 달라질 수 있어
    (수 분~수 시간), 종목마다 진행 로그를 즉시 flush해 백그라운드 실행 중에도
    진행 상황을 tail로 확인할 수 있게 한다.
    """
    client = _build_client()
    daily_start = date.today() - timedelta(days=int(args.daily_years * 365.25))

    if args.criterion == "topn-union":
        print(f"전체 시장 스캔 중 (최근 {args.topn_lookback_days}거래일 거래대금 top{args.topn} 합집합)... 종목 수에 따라 수십 분 소요될 수 있습니다.")
        universe = build_topn_union_universe(
            client, top_n=args.topn, lookback_days=args.topn_lookback_days, market=args.market
        )
    else:
        print(f"유동성 스크리닝 중 (평균거래대금 >= {args.min_avg_trading_value_eok:.0f}억원)...")
        universe = build_liquid_universe(
            client,
            min_avg_trading_value_eok=args.min_avg_trading_value_eok,
            candidate_pool_size=args.candidate_pool_size,
            lookback_days=args.liquidity_lookback_days,
            market=args.market,
        )
    if universe.empty:
        print("조건을 만족하는 종목이 없습니다.")
        return

    daily_dir = os.path.join(args.data_dir, "stocks", "daily")
    minute_dir = os.path.join(args.data_dir, "stocks", "minute")
    index_daily_dir = os.path.join(args.data_dir, "index", "daily")
    index_minute_dir = os.path.join(args.data_dir, "index", "minute")
    for d in (daily_dir, minute_dir, index_daily_dir, index_minute_dir):
        os.makedirs(d, exist_ok=True)

    universe_path = os.path.join(args.data_dir, "universe.csv")
    universe.to_csv(universe_path, index=False)
    print(f"대상 {len(universe)}종목 확정, 목록 저장: {universe_path}")

    ok_count, fail_count = 0, 0
    for i, row in universe.iterrows():
        code, name = row["stock_code"], row["name"]
        try:
            daily = load_history(client, code, daily_start, date.today(), interval="day", use_cache=True)
            _atomic_to_csv(daily, os.path.join(daily_dir, f"{code}.csv"))

            minute = load_full_minute_history(client, code, tic_scope=args.minute_tic_scope, use_cache=True)
            _atomic_to_csv(minute, os.path.join(minute_dir, f"{code}.csv"))

            ok_count += 1
            print(f"[{i + 1}/{len(universe)}] {code} {name}: daily={len(daily)} minute={len(minute)}")
        except Exception as exc:
            fail_count += 1
            print(f"[{i + 1}/{len(universe)}] {code} {name}: 실패 - {exc}")
        sys.stdout.flush()

    print("\n지수 다운로드 중...")
    for index_code, index_name in INDEX_CODES.items():
        try:
            idx_daily = load_index_history(client, index_code, daily_start, date.today(), interval="day", use_cache=True)
            _atomic_to_csv(idx_daily, os.path.join(index_daily_dir, f"{index_code}.csv"))

            idx_minute = load_full_index_minute_history(client, index_code, tic_scope=args.minute_tic_scope, use_cache=True)
            _atomic_to_csv(idx_minute, os.path.join(index_minute_dir, f"{index_code}.csv"))

            print(f"{index_code} {index_name}: daily={len(idx_daily)} minute={len(idx_minute)}")
        except Exception as exc:
            print(f"{index_code} {index_name}: 실패 - {exc}")
        sys.stdout.flush()

    print(f"\n완료: 성공 {ok_count}종목, 실패 {fail_count}종목. 저장 위치: {args.data_dir}/")


def _run_update_top35(args) -> None:
    """오늘 기준 거래대금 top35를 재산정해 일봉/1분봉을 증분 업데이트.

    download-universe로 구축한 넓은 유니버스 위에, 매일 바뀌는 top35 종목의
    최신 데이터만 얹는 용도. 매일 실행되도록 하려면 OS 스케줄러(Windows 작업
    스케줄러 등)에 이 명령을 등록하면 된다 — 이 스크립트 자체는 스케줄링하지 않음.
    """
    client = _build_client()
    print("오늘 거래대금 top35 재산정 및 증분 업데이트 중...")
    summary = update_top35(
        client,
        data_dir=args.data_dir,
        market=args.market,
        daily_years_if_new=args.daily_years,
        minute_tic_scope=args.minute_tic_scope,
        overlap_days=args.overlap_days,
    )

    for _, row in summary.iterrows():
        if row["status"] == "ok":
            print(f"{row['stock_code']} {row['name']}: daily={row['daily_rows']} minute={row['minute_rows']}")
        else:
            print(f"{row['stock_code']} {row['name']}: {row['status']}")

    ok_count = (summary["status"] == "ok").sum()
    print(f"\n완료: 성공 {ok_count}종목, 실패 {len(summary) - ok_count}종목.")


def _run_collect_orderbook(args) -> None:
    """오늘 기준 거래대금 top-N 종목의 호가(ka10004)를 정규장 동안 REST로 폴링해
    data/orderbook/{YYYYMMDD}/{code}.jsonl에 원본 그대로 누적 기록한다.

    호가는 과거 이력 조회 API가 없어 지금부터 쌓아야만 나중에 백테스트에 쓸 수
    있다. 정규장(평일 09:00~15:30) 밖에 실행하면 즉시 종료된다.
    """
    client = _build_client()
    if not is_market_open(pd.Timestamp.now().to_pydatetime()):
        print("현재 정규장 시간이 아닙니다(평일 09:00~15:30). 아무 것도 수집하지 않고 종료합니다.")
        return

    print(f"오늘 거래대금 top{args.top_n} 재산정 중...")
    watchlist = top_by_trading_value(client, top_n=args.top_n, market=args.market)
    if watchlist.empty:
        print("watchlist가 비어있어 종료합니다.")
        return
    stock_codes = list(watchlist["stock_code"])
    print(f"{len(stock_codes)}종목 폴링 시작 (간격 {args.interval_seconds}초, 정규장 종료 시 자동 종료). Ctrl+C로 중단 가능.")

    output_dir = os.path.join(args.data_dir, "orderbook")
    run_collection_loop(client, stock_codes, output_dir=output_dir, interval_seconds=args.interval_seconds)
    print("정규장 종료로 수집을 마쳤습니다.")


def _run_train_entry_model(args) -> None:
    """final_strategy에 확정된 최종 규칙으로 로컬 유니버스 전체를 스캔해 ML 진입필터
    모델을 학습·저장한다 (데이터가 갱신될 때마다 재실행해 최신 상태로 유지하는 용도).
    """
    print("최종 규칙으로 로컬 데이터 전체를 스캔해 학습 데이터 구성 중... (수 분 소요될 수 있습니다)")
    trained, features_df, labels_s = train_and_save_final_model(data_dir=args.data_dir, model_path=args.model_path)

    print(f"\n학습 샘플 {len(features_df)}개, 라벨분포(순손익>0=1)={labels_s.value_counts().to_dict()}")
    importances = sorted(zip(FEATURE_COLUMNS, trained.model.feature_importances_), key=lambda x: -x[1])
    print("\n피처 중요도:")
    for name, imp in importances:
        print(f"  {name}: {imp:.4f}")
    print(f"\n저장 완료: {args.model_path}")


def _run_monitor_signals(args) -> None:
    """정규장 동안 오늘의 top-N 종목을 실시간으로 감시해 신호를 로그로만 남긴다.
    실제 매수 주문은 내지 않는다 — 주문 실행은 별도의 리스크 검토가 필요한 이후
    단계다.

    --strategy strategy_3은 ML 모델/코스피 레짐 없이 3분 거래대금+수익률 조건만
    보는 테스트 모드 전략(strategy3_scalp.py), --strategy strategy_4는 거래대금
    순위 4→3위/5→4위/6→5위 승격만 감시하는 전략(strategy4_rank_watch.py)이라 둘 다
    완전히 다른 실행 경로(텔레그램 알림 포함)로 분기한다 — run-trading의 strategy_2
    분기와 같은 이유(다른 전략을 strategy_1 경로로 잘못 태우는 버그 방지)."""
    client = _build_client()
    strategy = getattr(args, "strategy", "strategy_1")

    if strategy == "strategy_4":
        # strategy_4는 정규장(09:00~15:30)만 감시하므로, 다른 전략들의 통합장
        # (08:00~20:00) 대기 게이트를 타면 08:00~09:00 사이에 시작했을 때 곧바로
        # 종료돼버린다 — 그래서 이 분기는 wait_until_extended_market_open보다 먼저,
        # 정규장 기준 대기로 처리한다.
        if not wait_until_market_open():
            print("현재 정규장 시간이 아닙니다(평일 09:00~15:30). 아무 것도 감시하지 않고 종료합니다.")
            return
        load_dotenv()
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        output_path = args.output if args.output != "signals.jsonl" else STRATEGY4_DEFAULT_SIGNAL_LOG_PATH
        run_rank_watch_loop(
            client, bot_token, chat_id,
            output_path=output_path, top_n=args.top_n, poll_interval_seconds=args.interval_seconds,
        )
        print("정규장 종료로 감시를 마쳤습니다.")
        return

    if not wait_until_extended_market_open():
        print("현재 통합장 시간이 아닙니다(평일 08:00~20:00). 아무 것도 감시하지 않고 종료합니다.")
        return

    if strategy == "strategy_3":
        load_dotenv()
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        output_path = args.output if args.output != "signals.jsonl" else STRATEGY3_DEFAULT_SIGNAL_LOG_PATH
        run_scalp_monitor_loop(
            client, bot_token, chat_id,
            output_path=output_path, top_n=args.top_n, poll_interval_seconds=args.interval_seconds,
        )
        print("통합장 종료로 감시를 마쳤습니다.")
        return

    print(f"모델 로드 중: {args.model_path}")
    trained = load_model(args.model_path)

    print(f"신호 감시 시작 (확률 임계값={args.proba_threshold}, 폴링간격={args.interval_seconds}초). Ctrl+C로 중단 가능.")
    run_monitor_loop(
        client, trained,
        output_path=args.output, data_dir=args.data_dir,
        top_n=args.top_n, proba_threshold=args.proba_threshold,
        poll_interval_seconds=args.interval_seconds,
    )
    print("통합장 종료로 감시를 마쳤습니다.")


def _run_trading(args) -> None:
    """실제 매수/매도 주문이 나가는 유일한 CLI 진입점 (monitor-signals는 관찰 전용,
    주문 없음). 일일 손실 한도와 텔레그램 알림 자격증명은 실수로 누락된 채 실주문이
    나가는 걸 막기 위해 .env에 명시적으로 설정돼 있어야만 시작한다(Plan §8.3 DoD:
    모의투자 검증 없이 바로 실계좌로 넘어가지 않도록 KIWOOM_IS_MOCK 상태도 시작 시 표시).

    load_dotenv()를 함수 맨 앞에서 직접 호출한다 — 예전엔 _build_client() 안에서만
    호출돼서, 그보다 먼저 실행되는 이 함수의 MAX_DAILY_LOSS_KRW/TELEGRAM_* 체크가
    .env를 한 번도 못 읽은 채로 os.environ을 확인해 항상 "설정 안 됨"으로 잘못
    판정하는 버그가 있었다(.env에 값을 제대로 채워도 매번 거부됐던 원인).
    """
    load_dotenv()
    max_daily_loss_raw = os.environ.get("MAX_DAILY_LOSS_KRW")
    if not max_daily_loss_raw:
        print("MAX_DAILY_LOSS_KRW가 .env에 설정되어 있지 않습니다. 실제 감내 가능한 일일 손실 한도(원)를 정하고 .env에 추가한 뒤 다시 실행하세요.")
        return

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID가 .env에 설정되어 있지 않습니다. 체결/오류/kill switch 알림 없이는 실주문을 시작하지 않습니다.")
        return

    strategy = getattr(args, "strategy", "strategy_1")
    defaults = _strategy_state_defaults(strategy)
    risk_state_path = args.risk_state_path or defaults["risk_state_path"]

    client = _build_client()
    # 08:00 대기 구간에도 heartbeat를 계속 찍어야 한다 — 안 그러면 대시보드가 이
    # 프로세스를 "중지됨"으로 오판해 "시작" 버튼으로 중복 실행시키는 사고가 난다
    # (trading_loop.run_trading_loop의 같은 문제를 고친 이유와 동일, 실계좌에서 실측).
    write_heartbeat(os.path.dirname(risk_state_path))
    if not wait_until_extended_market_open(on_wait_tick=lambda: write_heartbeat(os.path.dirname(risk_state_path))):
        print("현재 통합장 시간이 아닙니다(평일 08:00~20:00). 실주문을 시작하지 않고 종료합니다.")
        return

    is_mock = os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true"
    mode_label = "모의투자" if is_mock else "*** 실계좌(실제 자금) ***"

    order_log_path = args.order_log_path or defaults["order_log_path"]
    pnl_history_path = args.pnl_history_path or defaults["pnl_history_path"]
    kill_switch_override_path = args.kill_switch_override_path or defaults["kill_switch_override_path"]

    print(f"[{mode_label}][{strategy}] 실주문 매매를 시작합니다 — 일일손실한도 {float(max_daily_loss_raw):,.0f}원. 중단하려면 Ctrl+C.")

    # strategy 문자열로 실제 실행 로직을 분기한다 — 예전엔 이 분기가 없어서
    # --strategy strategy_2로 실행해도 상태 폴더 이름만 다를 뿐 strategy_1의 ML
    # 진입 로직이 그대로 실행되는 버그가 있었다. strategy_2(과대낙폭 분할매수)는
    # top_n/proba_threshold/max_concurrent_positions/model_path가 아예 적용되지
    # 않는 완전히 다른 전략이라 별도 실행 경로(run_oversold_trading_loop)로 보낸다.
    if strategy == "strategy_2":
        _write_strategy_config(risk_state_path, {
            "strategy": strategy,
            "stock_code": OVERSOLD_STOCK_CODE,
            "total_capital_krw": args.total_capital,
            "interval_seconds": args.interval_seconds,
            "max_daily_loss_krw": float(max_daily_loss_raw),
            "is_mock": is_mock,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        })

        run_oversold_trading_loop(
            client, bot_token, chat_id, float(max_daily_loss_raw),
            risk_state_path=risk_state_path, total_capital_krw=args.total_capital,
            poll_interval_seconds=args.interval_seconds, order_log_path=order_log_path,
            pnl_history_path=pnl_history_path, kill_switch_override_path=kill_switch_override_path,
        )
    else:
        model_path = args.model_path or defaults["model_path"]
        print(f"모델 로드 중: {model_path}")
        trained = load_model(model_path)

        _write_strategy_config(risk_state_path, {
            "strategy": strategy,
            "model_path": model_path,
            "top_n": args.top_n,
            "proba_threshold": args.proba_threshold,
            "max_concurrent_positions": args.max_concurrent_positions,
            "total_capital_krw": args.total_capital,
            "interval_seconds": args.interval_seconds,
            "max_daily_loss_krw": float(max_daily_loss_raw),
            "is_mock": is_mock,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        })

        run_trading_loop(
            client, trained, bot_token, chat_id, float(max_daily_loss_raw),
            risk_state_path=risk_state_path, data_dir=args.data_dir, top_n=args.top_n,
            proba_threshold=args.proba_threshold, max_concurrent_positions=args.max_concurrent_positions,
            total_capital_krw=args.total_capital, poll_interval_seconds=args.interval_seconds,
            order_log_path=order_log_path, pnl_history_path=pnl_history_path,
            kill_switch_override_path=kill_switch_override_path, strategy=strategy,
        )
    print("통합장 종료로 실주문 매매를 마쳤습니다.")


def _run_dashboard(args) -> None:
    """--state-root(기본 state/) 밑의 전략별 폴더(state/{strategy}/risk_state.json 등),
    results/를 읽기 전용으로 서빙하고 top35 갱신만 트리거할 수 있는 로컬 대시보드
    서버를 기동한다. run-trading --strategy로 여러 전략을 별도 프로세스로 띄우면
    각자 state/{strategy}/ 밑에 상태를 쓰고, 대시보드는 그 서브폴더 목록을 스캔해
    전략 선택 UI(GET /api/strategies)로 노출한다. trading_loop.py 등 실주문 로직과는
    완전히 분리된 프로세스다. 서버 기동 자체는 Kiwoom API를 호출하지 않고, "top35
    업데이트" 버튼을 눌렀을 때만 top35_job.py가 지연 생성한 KiwoomClient로 호출한다
    (backtest-dashboard.design.md §4.3) — 자격증명이 .env에 없으면 버튼을 눌렀을 때만
    실패(status: error)하고, 그 외 조회 기능은 정상 동작한다.
    """
    load_dotenv()
    run_dashboard_server(
        state_root=args.state_root,
        results_dir=args.results_dir,
        kiwoom_appkey=os.environ.get("KIWOOM_APPKEY", ""),
        kiwoom_secretkey=os.environ.get("KIWOOM_SECRETKEY", ""),
        kiwoom_is_mock=os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true",
        port=args.port,
        host=args.host,
    )


def _run_telegram_bot(args) -> None:
    """텔레그램 /buy, /sell 명령을 받아 Kiwoom API로 시장가 주문을 내는 봇을
    기동한다(블로킹). run-trading/dashboard와 마찬가지로 별도 프로세스로 띄운다."""
    load_dotenv()
    run_telegram_order_bot(
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        appkey=os.environ.get("KIWOOM_APPKEY", ""),
        secretkey=os.environ.get("KIWOOM_SECRETKEY", ""),
        is_mock=os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true",
    )


RESTART_DELAY_SECONDS = 10.0  # 예상 못 한 종료 후 재시작 전 대기 — 즉시 재시작 무한루프로 API를 몰아치지 않도록


def _run_monitor_nasdaq_drop(args) -> None:
    """나스닥100 선물(NQ=F)이 짧은 시간 안에 급락하면 관련 뉴스 헤드라인과 함께
    텔레그램으로 알린다(주문 없음). 한국 주식 전략들과 달리 정규장/통합장 시간
    제한이 없다 — CME 선물은 평일 거의 24시간 거래된다."""
    load_dotenv()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID가 .env에 설정되어 있지 않습니다. 알림 없이는 감시를 시작하지 않습니다.")
        return

    print(
        f"나스닥100 선물 급락 감시 시작 — {args.window_seconds:.0f}초 내 {args.threshold_pct:+.1f}% 이하 하락 시 "
        f"관련 뉴스와 함께 알림(폴링간격 {args.interval_seconds}초). 중단하려면 Ctrl+C.",
        flush=True,
    )
    # 상시 감시라 run_nasdaq_drop_monitor가 사이클 안에서 못 막은 예외로 죽더라도
    # (내부 try/except 밖의 write_heartbeat 등) 프로세스 자체는 계속 살아 있어야
    # 한다 — Ctrl+C(KeyboardInterrupt)는 그대로 통과시켜 의도된 종료는 막지 않는다.
    while True:
        try:
            run_nasdaq_drop_monitor(
                bot_token, chat_id,
                poll_interval_seconds=args.interval_seconds,
                window_seconds=args.window_seconds,
                threshold_pct=args.threshold_pct,
            )
            break  # 정상 종료(stop 요청) — 재시작하지 않음
        except Exception as exc:
            print(f"나스닥 급락 감시가 예상치 못하게 종료됨 — {RESTART_DELAY_SECONDS}초 후 자동 재시작: {exc}", flush=True)
            time.sleep(RESTART_DELAY_SECONDS)


def _run_monitor_dashboard(args) -> None:
    """트레이딩 대시보드(dashboard_server.py)가 응답하는지 주기적으로 확인해, 응답이
    끊기면/복구되면 텔레그램으로 알린다. 대시보드와 완전히 분리된 프로세스라 대시보드가
    죽거나 멈춰도 이 감시 자체는 영향받지 않는다."""
    load_dotenv()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID가 .env에 설정되어 있지 않습니다. 알림 없이는 감시를 시작하지 않습니다.")
        return

    url = f"http://{args.host}:{args.port}/"
    print(
        f"대시보드 감시 시작 — {url} (폴링간격 {args.interval_seconds:.0f}초). 중단하려면 Ctrl+C.",
        flush=True,
    )
    # 상시 감시라 run_dashboard_monitor_loop가 사이클 안에서 못 막은 예외로 죽더라도
    # 프로세스 자체는 계속 살아 있어야 한다 — monitor-nasdaq-drop과 같은 이유.
    while True:
        try:
            run_dashboard_monitor_loop(
                bot_token, chat_id, url=url, poll_interval_seconds=args.interval_seconds,
            )
            break  # 정상 종료(stop 요청) — 재시작하지 않음
        except Exception as exc:
            print(f"대시보드 감시가 예상치 못하게 종료됨 — {RESTART_DELAY_SECONDS}초 후 자동 재시작: {exc}", flush=True)
            time.sleep(RESTART_DELAY_SECONDS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="전략 백테스팅 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--stocks", required=True, help="쉼표로 구분된 종목코드 목록")
    common.add_argument("--start", required=True, help="YYYY-MM-DD")
    common.add_argument("--end", required=True, help="YYYY-MM-DD")
    common.add_argument("--capital", type=float, default=10_000_000)
    common.add_argument(
        "--commission-rate", type=float,
        default=float(os.environ.get("BACKTEST_COMMISSION_RATE", 0.00015)),
    )
    common.add_argument(
        "--slippage-rate", type=float,
        default=float(os.environ.get("BACKTEST_SLIPPAGE_RATE", 0.001)),
    )
    common.add_argument(
        "--tax-rate", type=float,
        default=float(os.environ.get("BACKTEST_TAX_RATE", 0.0023)),
        help="매도 증권거래세율 (매도 시에만 부과, 기본 0.23%%)",
    )
    common.add_argument("--csv", help="결과 CSV 저장 경로")
    common.add_argument("--plot", help="최고 성과 조합의 매매 시점 차트를 저장할 이미지 경로 (예: best.png)")
    common.add_argument("--data-dir", default="data", help="download-universe/update-top35가 받아둔 로컬 데이터 위치")
    common.add_argument("--results-dir", default="results", help="backtest-dashboard가 조회하는 결과 자동 저장 위치 (--csv와 별개로 항상 저장됨)")
    common.add_argument(
        "--no-local-data", action="store_true",
        help="로컬 data/를 쓰지 않고 항상 라이브 API로 조회 (기본은 로컬 데이터 우선 사용)",
    )

    ma_rsi_args = argparse.ArgumentParser(add_help=False)
    ma_rsi_args.add_argument("--short-window", default="5,10")
    ma_rsi_args.add_argument("--long-window", default="20,60")
    ma_rsi_args.add_argument("--rsi-period", default="14")
    ma_rsi_args.add_argument("--rsi-buy-below", default="30")
    ma_rsi_args.add_argument("--rsi-sell-above", default="70")
    ma_rsi_args.add_argument("--ma-window", default="60", help="엔벨로프 이동평균 기간")
    ma_rsi_args.add_argument("--envelope-pct", default="0.02,0.03,0.05", help="엔벨로프 밴드 폭 비율")
    ma_rsi_args.add_argument("--exit-mode", default="ma_touch,opposite_band", help="엔벨로프 청산 방식")

    ml_args = argparse.ArgumentParser(add_help=False)
    ml_args.add_argument("--train-days", type=int, default=30)
    ml_args.add_argument("--test-days", type=int, default=5)
    ml_args.add_argument("--step-days", type=int, default=5)
    ml_args.add_argument("--label-horizon-minutes", type=int, default=30)
    ml_args.add_argument(
        "--label-return-threshold", type=float,
        default=float(os.environ.get("ML_LABEL_RETURN_THRESHOLD", 0.005)),
    )
    ml_args.add_argument("--model-type", choices=["random_forest", "gradient_boosting"], default="random_forest")
    ml_args.add_argument("--buy-threshold", default="0.5,0.6")

    rule_parser = sub.add_parser("rule", parents=[common, ma_rsi_args], help="규칙 기반 전략(MA/RSI/엔벨로프) 그리드서치")
    rule_parser.add_argument("--strategy", choices=["ma_crossover", "rsi", "envelope"], required=True)
    rule_parser.add_argument("--interval", default="day")
    rule_parser.add_argument("--in-sample-ratio", type=float, default=0.7)
    rule_parser.set_defaults(func=_run_rule)

    ml_parser = sub.add_parser("ml", parents=[common, ml_args], help="데이트레이딩 ML 전략 워크포워드 검증")
    ml_parser.add_argument("--interval", default="5")
    ml_parser.set_defaults(func=_run_ml)

    compare_parser = sub.add_parser(
        "compare", parents=[common, ma_rsi_args, ml_args],
        help="규칙 기반(MA/RSI) + ML 전략을 같은 종목·기간으로 실행해 하나의 리포트로 비교",
    )
    compare_parser.add_argument("--rule-interval", default="day")
    compare_parser.add_argument("--ml-interval", default="5")
    compare_parser.add_argument("--in-sample-ratio", type=float, default=0.7)
    compare_parser.set_defaults(func=_run_compare)

    scan_parser = sub.add_parser(
        "scan-brackets",
        help="거래대금 상위 종목을 스크리닝해 1분봉 -손절%%/+익절%% 매매구간을 사후 스캔",
    )
    scan_parser.add_argument("--date", required=True, help="분석 대상 거래일 YYYY-MM-DD")
    scan_parser.add_argument("--top-n", type=int, default=35)
    scan_parser.add_argument("--market", default="000", help="000=코스피+코스닥 통합, 001=코스피, 101=코스닥")
    scan_parser.add_argument("--stop-loss", type=float, default=0.02, help="손절 비율 (0.02=2%%)")
    scan_parser.add_argument("--take-profit", type=float, default=0.03, help="익절 비율 (0.03=3%%)")
    scan_parser.add_argument("--bucket-minutes", type=int, default=30)
    scan_parser.add_argument("--use-cache", action="store_true")
    scan_parser.add_argument("--csv", help="원본 결과 CSV 저장 경로 (자동으로 _by_stock/_by_time 파생 파일도 생성)")
    scan_parser.add_argument("--data-dir", default="data", help="download-universe/update-top35가 받아둔 로컬 데이터 위치")
    scan_parser.add_argument(
        "--no-local-data", action="store_true",
        help="로컬 data/를 쓰지 않고 항상 라이브 API로 조회 (기본은 로컬 데이터 우선 사용)",
    )
    scan_parser.set_defaults(func=_run_scan_brackets)

    download_parser = sub.add_parser(
        "download-universe",
        help="유동성 상위 종목 + 코스피/코스닥 지수의 일봉·분봉을 data/ 아래에 저장",
    )
    download_parser.add_argument(
        "--criterion", choices=["avg-value", "topn-union"], default="avg-value",
        help="avg-value=최근 N거래일 평균거래대금 임계값, topn-union=최근 N거래일 거래대금 top순위 합집합(전체 시장 스캔, 훨씬 오래 걸림)",
    )
    download_parser.add_argument("--min-avg-trading-value-eok", type=float, default=1000, help="[avg-value] 최근 N거래일 평균 거래대금 하한 (억원)")
    download_parser.add_argument("--liquidity-lookback-days", type=int, default=5, help="[avg-value] 평균 거래대금 계산에 쓸 최근 거래일 수")
    download_parser.add_argument("--candidate-pool-size", type=int, default=150, help="[avg-value] 유동성 필터링 전 순위 API에서 뽑을 후보 수")
    download_parser.add_argument("--topn", type=int, default=35, help="[topn-union] 일별 거래대금 순위 상한")
    download_parser.add_argument("--topn-lookback-days", type=int, default=252, help="[topn-union] 합집합 계산에 쓸 최근 거래일 수")
    download_parser.add_argument("--market", default="000", help="000=코스피+코스닥 통합, 001=코스피, 101=코스닥")
    download_parser.add_argument("--daily-years", type=float, default=5, help="일봉 조회 기간 (년)")
    download_parser.add_argument("--minute-tic-scope", default="1", help="분봉 단위 (1/3/5/10/15/30/45/60분)")
    download_parser.add_argument("--data-dir", default="data", help="저장 루트 디렉터리")
    download_parser.set_defaults(func=_run_download_universe)

    update_parser = sub.add_parser(
        "update-top35",
        help="오늘 기준 거래대금 top35를 재산정해 일봉·분봉을 증분 업데이트 (매일 실행용)",
    )
    update_parser.add_argument("--market", default="000", help="000=코스피+코스닥 통합, 001=코스피, 101=코스닥")
    update_parser.add_argument("--daily-years", type=float, default=5, help="신규 진입 종목의 일봉 조회 기간 (년)")
    update_parser.add_argument("--minute-tic-scope", default="1", help="분봉 단위 (1/3/5/10/15/30/45/60분)")
    update_parser.add_argument("--overlap-days", type=int, default=5, help="기존 데이터가 있어도 겹쳐받을 최근 일수 (정정 시세 반영)")
    update_parser.add_argument("--data-dir", default="data", help="저장 루트 디렉터리 (download-universe와 동일하게 맞출 것)")
    update_parser.set_defaults(func=_run_update_top35)

    orderbook_parser = sub.add_parser(
        "collect-orderbook",
        help="오늘 거래대금 top-N 종목의 호가를 정규장 동안 REST 폴링해 data/orderbook/에 원본 기록 (과거 조회 불가한 데이터라 지금부터 쌓는 용도)",
    )
    orderbook_parser.add_argument("--top-n", type=int, default=35)
    orderbook_parser.add_argument("--market", default="000", help="000=코스피+코스닥 통합, 001=코스피, 101=코스닥")
    orderbook_parser.add_argument("--interval-seconds", type=float, default=3.0, help="종목 한 바퀴 폴링 후 대기 시간(초)")
    orderbook_parser.add_argument("--data-dir", default="data", help="저장 루트 디렉터리")
    orderbook_parser.set_defaults(func=_run_collect_orderbook)

    train_model_parser = sub.add_parser(
        "train-entry-model",
        help="확정된 전략 1번(top35+당일상승률밴드+3분돌파+신고가+무하락+코스피레짐, 손절-2.5%%/분할매도)으로 로컬 데이터 전체를 학습해 ML 진입필터 모델 저장",
    )
    train_model_parser.add_argument("--data-dir", default="data", help="download-universe/update-top35가 받아둔 로컬 데이터 위치")
    train_model_parser.add_argument("--model-path", default="models/strategy_1/entry_filter_model.joblib", help="모델 저장 경로")
    train_model_parser.set_defaults(func=_run_train_entry_model)

    monitor_parser = sub.add_parser(
        "monitor-signals",
        help="정규장 동안 오늘 top-N 종목을 실시간 감시해 통과 신호를 로그로만 기록 (매수 주문 없음). "
        "--strategy strategy_3은 3분거래대금+수익률 조건만 보는 테스트 모드(텔레그램 알림 포함)",
    )
    monitor_parser.add_argument("--strategy", default="strategy_1", help="strategy_1(기본, 조건1~8+ML), strategy_3(3분 거래대금+수익률만, ML/레짐 없음), strategy_4(거래대금 순위 4→3위/5→4위/6→5위 승격 감시, 정규장 09:00~15:30) — strategy_3/4 모두 텔레그램 알림 포함")
    monitor_parser.add_argument("--model-path", default="models/strategy_1/entry_filter_model.joblib", help="train-entry-model로 저장한 모델 경로 (strategy_1 전용)")
    monitor_parser.add_argument("--top-n", type=int, default=35)
    monitor_parser.add_argument("--proba-threshold", type=float, default=RECOMMENDED_PROBA_THRESHOLD, help="ML 예측 성공확률 임계값 (strategy_1 전용)")
    monitor_parser.add_argument("--interval-seconds", type=float, default=30.0, help="watchlist 한 바퀴 폴링 후 대기 시간(초)")
    monitor_parser.add_argument("--data-dir", default="data", help="일봉 참조용 로컬 데이터 위치 (strategy_1 전용)")
    monitor_parser.add_argument("--output", default="signals.jsonl", help="신호 기록 파일 경로 (strategy_3/4는 미지정 시 각각 state/strategy_3/, state/strategy_4/ 밑 signals.jsonl)")
    monitor_parser.set_defaults(func=_run_monitor_signals)

    trading_parser = sub.add_parser(
        "run-trading",
        help="정규장 동안 전략 1번(조건1~8) 신호에 실제 매수/매도 주문을 실행 (리스크한도+kill switch+텔레그램 알림 포함, monitor-signals와 달리 실주문이 나감)",
    )
    trading_parser.add_argument("--strategy", default="strategy_1", help="전략 식별자 — 미지정 경로 인자들은 이 값으로 state/{strategy}/, models/{strategy}/ 밑에 자동 네임스페이스되어 대시보드가 전략별로 구분/선택할 수 있게 한다")
    trading_parser.add_argument("--model-path", default=None, help="train-entry-model로 저장한 모델 경로 (미지정 시 models/{strategy}/entry_filter_model.joblib)")
    trading_parser.add_argument("--top-n", type=int, default=35)
    trading_parser.add_argument("--proba-threshold", type=float, default=RECOMMENDED_PROBA_THRESHOLD, help="ML 예측 성공확률 임계값")
    trading_parser.add_argument("--max-concurrent-positions", type=int, default=RECOMMENDED_MAX_CONCURRENT_POSITIONS, help="동시보유 슬롯 수")
    trading_parser.add_argument("--total-capital", type=float, default=float(os.environ.get("TOTAL_CAPITAL_KRW", 10_000_000)), help="총 투자금(원), 슬롯 수만큼 균등 배분")
    trading_parser.add_argument("--interval-seconds", type=float, default=30.0, help="진입/청산 감시 폴링 간격(초)")
    trading_parser.add_argument("--data-dir", default="data", help="일봉/코스피 레짐 참조용 로컬 데이터 위치")
    trading_parser.add_argument("--risk-state-path", default=None, help="당일 손익·보유 포지션 상태 저장 경로 (미지정 시 state/{strategy}/risk_state.json)")
    trading_parser.add_argument("--order-log-path", default=None, help="체결 이력 기록 경로(trading-dashboard가 조회) (미지정 시 state/{strategy}/orders.jsonl)")
    trading_parser.add_argument("--pnl-history-path", default=None, help="일별 손익 이력 기록 경로(trading-dashboard가 조회) (미지정 시 state/{strategy}/pnl_history.jsonl)")
    trading_parser.add_argument("--kill-switch-override-path", default=None, help="대시보드 수동 kill switch 요청 상태 파일 경로 (미지정 시 state/{strategy}/kill_switch_override.json)")
    trading_parser.set_defaults(func=_run_trading)

    dashboard_parser = sub.add_parser(
        "dashboard",
        help="state/{strategy}/ 밑 전략별 상태와 signals.jsonl을 읽기 전용으로 서빙하는 로컬 대시보드 서버 실행 (실주문 로직과 완전히 분리, Kiwoom API 호출 없음)",
    )
    dashboard_parser.add_argument("--port", type=int, default=8765)
    dashboard_parser.add_argument(
        "--host", default="127.0.0.1",
        help="바인딩할 인터페이스. 기본 127.0.0.1(이 PC에서만 접속 가능). 휴대폰 등 다른 기기에서 "
        "접속하려면 0.0.0.0으로 지정 — 인증이 없는 서버라 신뢰할 수 있는 사설망(가정용 와이파이, "
        "Tailscale 등 개인 VPN)에서만 쓸 것, 공인 IP에 노출하지 말 것",
    )
    dashboard_parser.add_argument("--state-root", default="state", help="run-trading --strategy가 기록하는 전략별 상태 폴더(state/{strategy}/)의 상위 경로 — 서브폴더를 스캔해 대시보드 전략 선택지로 노출한다")
    dashboard_parser.add_argument("--results-dir", default="results", help="rule/ml/compare가 자동 저장하는 백테스트 결과 위치")
    dashboard_parser.set_defaults(func=_run_dashboard)

    telegram_bot_parser = sub.add_parser(
        "telegram-bot",
        help="텔레그램 /buy, /sell 명령으로 시장가 주문을 내는 봇 실행 (.env의 TELEGRAM_CHAT_ID만 허용, 대시보드/run-trading과 분리된 프로세스)",
    )
    telegram_bot_parser.set_defaults(func=_run_telegram_bot)

    nasdaq_drop_parser = sub.add_parser(
        "monitor-nasdaq-drop",
        help="나스닥100 선물(NQ=F)이 짧은 시간 안에 급락하면 관련 뉴스 헤드라인과 함께 텔레그램 알림 (주문 없음, 시간 제한 없음)",
    )
    nasdaq_drop_parser.add_argument("--interval-seconds", type=float, default=15.0, help="가격 폴링 간격(초)")
    nasdaq_drop_parser.add_argument("--window-seconds", type=float, default=WINDOW_SECONDS, help="급락 판단 기준 시간창(초), 기본 3분")
    nasdaq_drop_parser.add_argument("--threshold-pct", type=float, default=DROP_THRESHOLD_PCT, help="이 값(%%) 이하로 떨어지면 알림, 기본 -1.0")
    nasdaq_drop_parser.set_defaults(func=_run_monitor_nasdaq_drop)

    dashboard_monitor_parser = sub.add_parser(
        "monitor-dashboard",
        help="트레이딩 대시보드가 응답하는지 주기적으로 확인해 응답 없음/복구 시 텔레그램 알림 (대시보드와 분리된 프로세스, Kiwoom API 호출 없음)",
    )
    dashboard_monitor_parser.add_argument("--host", default="127.0.0.1", help="확인할 대시보드 호스트 (dashboard 명령의 --host와 맞출 것)")
    dashboard_monitor_parser.add_argument("--port", type=int, default=8765, help="확인할 대시보드 포트 (dashboard 명령의 --port와 맞출 것)")
    dashboard_monitor_parser.add_argument("--interval-seconds", type=float, default=30.0, help="확인 간격(초)")
    dashboard_monitor_parser.set_defaults(func=_run_monitor_dashboard)

    return parser


def main() -> None:
    # Windows 콘솔의 기본 코드페이지(cp949 등)는 이모지 없는 한글 print는 깨져 보이기만
    # 하지만, em dash(—)처럼 cp949에 아예 없는 문자를 만나면 UnicodeEncodeError로 프로세스가
    # 죽는다(run-trading이 시작 로그 한 줄 때문에 실주문 진입 전에 크래시하는 게 실제로
    # 재현된 사례) — stdout/stderr을 UTF-8로 강제 전환해 원천 차단한다.
    if sys.stdout.encoding is not None and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
