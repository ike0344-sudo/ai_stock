import os
from argparse import Namespace

import pandas as pd
import pytest

from backtesting import cli
from backtesting.types import GridSearchResult, PerformanceMetrics


def _result(stock_code: str, strategy_name: str, oos_return: float, num_trades: int = 3) -> GridSearchResult:
    metrics = PerformanceMetrics(
        total_return_pct=oos_return, cagr_pct=oos_return, win_rate_pct=50.0,
        max_drawdown_pct=5.0, sharpe_ratio=1.0, num_trades=num_trades,
    )
    return GridSearchResult(
        stock_code=stock_code, strategy_name=strategy_name, params={},
        in_sample=metrics, out_of_sample=metrics,
    )


def test_report_calls_plot_best_for_best_result_when_plot_arg_set(monkeypatch, tmp_path):
    candles = pd.DataFrame(
        {"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]},
        index=pd.date_range("2026-01-01", periods=1),
    )
    monkeypatch.setattr(cli, "load_history", lambda *a, **k: candles)

    plot_calls = []
    monkeypatch.setattr(cli.report, "plot_best", lambda *a, **k: plot_calls.append((a, k)))

    args = Namespace(
        csv=None, plot="out.png", start="2026-01-01", end="2026-01-02", no_local_data=True, data_dir="data",
        results_dir=str(tmp_path / "results"),
    )
    results = [_result("005930", "ma_crossover", 5.0), _result("000660", "rsi", 1.0)]

    cli._report(results, args, client=object())

    assert len(plot_calls) == 1
    _, kwargs = plot_calls[0]
    assert kwargs["save_path"] == "out.png"


def test_report_prefers_traded_result_over_untraded_tie(monkeypatch, tmp_path):
    """실제 API 실행에서, 거래 0건인 조합들이 수익률 0%로 동률이라 '최고'로 잘못 뽑혀
    mplfinance가 크래시했던 문제의 회귀 테스트. 거래가 있는 조합을 우선해야 한다."""
    candles = pd.DataFrame(
        {"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]},
        index=pd.date_range("2026-01-01", periods=1),
    )
    monkeypatch.setattr(cli, "load_history", lambda *a, **k: candles)

    plot_calls = []
    monkeypatch.setattr(cli.report, "plot_best", lambda *a, **k: plot_calls.append((a, k)))

    args = Namespace(
        csv=None, plot="out.png", start="2026-01-01", end="2026-01-02", no_local_data=True, data_dir="data",
        results_dir=str(tmp_path / "results"),
    )
    untraded = _result("005930", "ma_crossover", 0.0, num_trades=0)
    traded = _result("000660", "rsi", -1.0, num_trades=2)  # 수익률은 낮지만 실제 거래가 있음

    cli._report([untraded, traded], args, client=object())

    assert len(plot_calls) == 1
    positional_args, _ = plot_calls[0]
    title = positional_args[2]
    assert "000660" in title and "rsi" in title


def test_report_skips_plot_when_no_results(monkeypatch):
    plot_calls = []
    monkeypatch.setattr(cli.report, "plot_best", lambda *a, **k: plot_calls.append(1))

    args = Namespace(csv=None, plot="out.png", start="2026-01-01", end="2026-01-02")

    cli._report([], args, client=object())

    assert plot_calls == []


def test_report_auto_saves_to_results_dir_with_label(tmp_path):
    """backtest-dashboard가 조회하는 results/{label}_{timestamp}.csv 규칙으로 자동 저장돼야 함
    (Design §3.1) — --csv를 지정하지 않아도 저장된다."""
    results_dir = tmp_path / "results"
    args = Namespace(
        csv=None, plot=None, start="2026-01-01", end="2026-01-02", results_dir=str(results_dir),
    )
    results = [_result("005930", "ma_crossover", 5.0)]

    cli._report(results, args, client=object(), results_label="ma_crossover")

    saved = list(results_dir.glob("ma_crossover_*.csv"))
    assert len(saved) == 1


def test_report_skips_results_dir_save_when_results_empty(tmp_path):
    results_dir = tmp_path / "results"
    args = Namespace(csv=None, plot=None, start="2026-01-01", end="2026-01-02", results_dir=str(results_dir))

    cli._report([], args, client=object())

    assert not results_dir.exists()


def test_report_defaults_to_results_dir_named_results_when_arg_missing(monkeypatch, tmp_path):
    """args에 results_dir이 없는 (구버전 Namespace) 호출부도 깨지지 않아야 함 — getattr 기본값 확인."""
    monkeypatch.chdir(tmp_path)
    args = Namespace(csv=None, plot=None, start="2026-01-01", end="2026-01-02")
    results = [_result("005930", "ma_crossover", 5.0)]

    cli._report(results, args, client=object(), results_label="ma_crossover")

    assert (tmp_path / "results").exists()


def test_run_compare_merges_rule_and_ml_results(monkeypatch):
    ma_result = _result("005930", "ma_crossover", 1.0)
    rsi_result = _result("005930", "rsi", 2.0)
    ml_result = _result("005930", "ml_day_trading", 3.0)
    call_log = []

    def fake_run_rule_based(client, stock_codes, strategy, param_grid, **kwargs):
        call_log.append(strategy.name)
        return [ma_result] if strategy.name == "ma_crossover" else [rsi_result]

    def fake_run_ml_walk_forward(client, stock_codes, param_grid, **kwargs):
        call_log.append("ml")
        return [ml_result]

    monkeypatch.setattr(cli.grid_search, "run_rule_based", fake_run_rule_based)
    monkeypatch.setattr(cli.grid_search, "run_ml_walk_forward", fake_run_ml_walk_forward)
    monkeypatch.setattr(cli, "_build_client", lambda: object())

    reported = {}
    monkeypatch.setattr(
        cli, "_report",
        lambda results, args, client, plot_interval="day", results_label="backtest": reported.setdefault("results", results),
    )

    args = Namespace(
        stocks="005930", start="2026-01-01", end="2026-03-01", capital=10_000_000,
        commission_rate=0.0001, slippage_rate=0.0001, tax_rate=0.0023, csv=None, plot=None,
        short_window="5,10", long_window="20,60",
        rsi_period="14", rsi_buy_below="30", rsi_sell_above="70",
        train_days=30, test_days=5, step_days=5, label_horizon_minutes=30,
        label_return_threshold=0.005, model_type="random_forest", buy_threshold="0.5",
        rule_interval="day", ml_interval="5", in_sample_ratio=0.7,
        no_local_data=True, data_dir="data",
    )

    cli._run_compare(args)

    assert set(call_log) == {"ma_crossover", "rsi", "ml"}
    assert reported["results"] == [ma_result, rsi_result, ml_result]


def test_run_rule_forwards_local_data_flags_to_grid_search(monkeypatch):
    captured = {}

    def fake_run_rule_based(client, stock_codes, strategy, param_grid, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(cli.grid_search, "run_rule_based", fake_run_rule_based)
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "_report", lambda *a, **k: None)

    args = Namespace(
        stocks="005930", start="2026-01-01", end="2026-03-01", capital=10_000_000,
        commission_rate=0.0001, slippage_rate=0.0001, tax_rate=0.0023, csv=None, plot=None,
        strategy="ma_crossover", interval="day", in_sample_ratio=0.7,
        short_window="5,10", long_window="20,60",
        no_local_data=False, data_dir="my_data",
    )

    cli._run_rule(args)

    assert captured["use_local_data"] is True
    assert captured["data_dir"] == "my_data"


def test_run_rule_disables_local_data_when_no_local_data_flag_set(monkeypatch):
    captured = {}

    def fake_run_rule_based(client, stock_codes, strategy, param_grid, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(cli.grid_search, "run_rule_based", fake_run_rule_based)
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "_report", lambda *a, **k: None)

    args = Namespace(
        stocks="005930", start="2026-01-01", end="2026-03-01", capital=10_000_000,
        commission_rate=0.0001, slippage_rate=0.0001, tax_rate=0.0023, csv=None, plot=None,
        strategy="ma_crossover", interval="day", in_sample_ratio=0.7,
        short_window="5,10", long_window="20,60",
        no_local_data=True, data_dir="data",
    )

    cli._run_rule(args)

    assert captured["use_local_data"] is False


def _minute_candles_for_day(day: str, closes: list[float]) -> pd.DataFrame:
    index = pd.date_range(f"{day} 09:00", periods=len(closes), freq="1min")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * len(closes)},
        index=index,
    )


def test_build_parser_help_strings_are_valid_for_every_subcommand():
    """argparse는 help 문자열을 %-포맷으로 해석해, 설명에 리터럴 '%'가 있으면
    --help 실행 자체가 크래시한다 (scan-brackets의 '2%' 같은 표현에서 실제로 발생했던 버그).
    모든 서브커맨드의 --help가 예외 없이 종료되는지로 회귀 방지한다."""
    parser = cli.build_parser()
    for action in parser._subparsers._group_actions[0].choices.values():
        with pytest.raises(SystemExit) as exc_info:
            action.parse_args(["--help"])
        assert exc_info.value.code == 0


def test_run_scan_brackets_screens_then_scans_each_stock(monkeypatch, capsys):
    screened = pd.DataFrame(
        [
            {"stock_code": "000660", "name": "SK하이닉스", "rank": 1, "trading_value": 100},
            {"stock_code": "005930", "name": "삼성전자", "rank": 2, "trading_value": 90},
        ]
    )
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "top_by_trading_value", lambda client, top_n, market: screened)

    candles_by_code = {
        "000660": _minute_candles_for_day("2026-07-17", [100, 100, 103]),  # +3% -> win
        "005930": _minute_candles_for_day("2026-07-17", [100, 100, 98]),  # -2% -> loss
    }
    monkeypatch.setattr(cli, "load_history", lambda client, code, start, end, interval, use_cache, **k: candles_by_code[code])

    args = Namespace(
        date="2026-07-17", top_n=35, market="000", stop_loss=0.02, take_profit=0.03,
        bucket_minutes=30, use_cache=False, csv=None, no_local_data=True, data_dir="data",
    )

    cli._run_scan_brackets(args)

    out = capsys.readouterr().out
    assert "000660" in out and "005930" in out
    assert "종목별 요약" in out and "시간대별 요약" in out


def test_run_scan_brackets_skips_stock_on_load_failure(monkeypatch, capsys):
    screened = pd.DataFrame(
        [
            {"stock_code": "000660", "name": "SK하이닉스", "rank": 1, "trading_value": 100},
            {"stock_code": "005930", "name": "삼성전자", "rank": 2, "trading_value": 90},
        ]
    )
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "top_by_trading_value", lambda client, top_n, market: screened)

    good_candles = _minute_candles_for_day("2026-07-17", [100, 100, 103])

    def fake_load_history(client, code, start, end, interval, use_cache, **k):
        if code == "000660":
            raise RuntimeError("API error")
        return good_candles

    monkeypatch.setattr(cli, "load_history", fake_load_history)

    args = Namespace(
        date="2026-07-17", top_n=35, market="000", stop_loss=0.02, take_profit=0.03,
        bucket_minutes=30, use_cache=False, csv=None, no_local_data=True, data_dir="data",
    )

    cli._run_scan_brackets(args)

    out = capsys.readouterr().out
    assert "000660" in out and "스킵" in out
    assert "005930" in out


def test_run_scan_brackets_handles_empty_screen_result(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "top_by_trading_value", lambda client, top_n, market: pd.DataFrame())

    args = Namespace(
        date="2026-07-17", top_n=35, market="000", stop_loss=0.02, take_profit=0.03,
        bucket_minutes=30, use_cache=False, csv=None,
    )

    cli._run_scan_brackets(args)

    assert "스크리닝된 종목이 없습니다" in capsys.readouterr().out


def test_run_scan_brackets_saves_derived_csv_files(monkeypatch, tmp_path):
    screened = pd.DataFrame([{"stock_code": "000660", "name": "SK하이닉스", "rank": 1, "trading_value": 100}])
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "top_by_trading_value", lambda client, top_n, market: screened)
    monkeypatch.setattr(
        cli, "load_history",
        lambda client, code, start, end, interval, use_cache, **k: _minute_candles_for_day("2026-07-17", [100, 100, 103]),
    )

    csv_path = tmp_path / "scan.csv"
    args = Namespace(
        date="2026-07-17", top_n=35, market="000", stop_loss=0.02, take_profit=0.03,
        bucket_minutes=30, use_cache=False, csv=str(csv_path), no_local_data=True, data_dir="data",
    )

    cli._run_scan_brackets(args)

    assert csv_path.exists()
    assert (tmp_path / "scan_by_stock.csv").exists()
    assert (tmp_path / "scan_by_time.csv").exists()


def _make_download_args(tmp_path, **overrides):
    defaults = dict(
        criterion="avg-value",
        min_avg_trading_value_eok=1000, liquidity_lookback_days=5, candidate_pool_size=150,
        topn=35, topn_lookback_days=252,
        market="000", daily_years=5, minute_tic_scope="1", data_dir=str(tmp_path / "data"),
    )
    defaults.update(overrides)
    return Namespace(**defaults)


def _candles(n: int = 3) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"open": [100] * n, "high": [101] * n, "low": [99] * n, "close": [100] * n, "volume": [1000] * n},
        index=index,
    )


def test_run_download_universe_saves_stock_and_index_files(monkeypatch, tmp_path):
    universe = pd.DataFrame([{"stock_code": "000660", "name": "SK하이닉스", "avg_trading_value_eok": 1200.0}])
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "build_liquid_universe", lambda client, **kwargs: universe)
    monkeypatch.setattr(cli, "load_history", lambda client, code, start, end, interval, use_cache: _candles())
    monkeypatch.setattr(cli, "load_full_minute_history", lambda client, code, tic_scope, use_cache: _candles())
    monkeypatch.setattr(cli, "load_index_history", lambda client, code, start, end, interval, use_cache: _candles())
    monkeypatch.setattr(cli, "load_full_index_minute_history", lambda client, code, tic_scope, use_cache: _candles())

    args = _make_download_args(tmp_path)
    cli._run_download_universe(args)

    data_dir = tmp_path / "data"
    assert (data_dir / "universe.csv").exists()
    assert (data_dir / "stocks" / "daily" / "000660.csv").exists()
    assert (data_dir / "stocks" / "minute" / "000660.csv").exists()
    assert (data_dir / "index" / "daily" / "001.csv").exists()
    assert (data_dir / "index" / "minute" / "001.csv").exists()
    assert (data_dir / "index" / "daily" / "101.csv").exists()
    assert (data_dir / "index" / "minute" / "101.csv").exists()


def test_run_download_universe_uses_topn_union_when_criterion_selected(monkeypatch, tmp_path):
    universe = pd.DataFrame([{"stock_code": "000660", "name": "SK하이닉스"}])
    calls = []
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "build_liquid_universe", lambda client, **kwargs: calls.append("avg-value") or universe)
    monkeypatch.setattr(cli, "build_topn_union_universe", lambda client, **kwargs: calls.append("topn-union") or universe)
    monkeypatch.setattr(cli, "load_history", lambda client, code, start, end, interval, use_cache: _candles())
    monkeypatch.setattr(cli, "load_full_minute_history", lambda client, code, tic_scope, use_cache: _candles())
    monkeypatch.setattr(cli, "load_index_history", lambda client, code, start, end, interval, use_cache: _candles())
    monkeypatch.setattr(cli, "load_full_index_minute_history", lambda client, code, tic_scope, use_cache: _candles())

    args = _make_download_args(tmp_path, criterion="topn-union")
    cli._run_download_universe(args)

    assert calls == ["topn-union"]


def test_run_download_universe_handles_empty_universe(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "build_liquid_universe", lambda client, **kwargs: pd.DataFrame())

    args = _make_download_args(tmp_path)
    cli._run_download_universe(args)

    assert "조건을 만족하는 종목이 없습니다" in capsys.readouterr().out


def test_run_download_universe_continues_after_per_stock_failure(monkeypatch, tmp_path, capsys):
    universe = pd.DataFrame(
        [
            {"stock_code": "000660", "name": "SK하이닉스", "avg_trading_value_eok": 1200.0},
            {"stock_code": "005930", "name": "삼성전자", "avg_trading_value_eok": 1100.0},
        ]
    )
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "build_liquid_universe", lambda client, **kwargs: universe)

    def flaky_load_history(client, code, start, end, interval, use_cache):
        if code == "000660":
            raise RuntimeError("API error")
        return _candles()

    monkeypatch.setattr(cli, "load_history", flaky_load_history)
    monkeypatch.setattr(cli, "load_full_minute_history", lambda client, code, tic_scope, use_cache: _candles())
    monkeypatch.setattr(cli, "load_index_history", lambda client, code, start, end, interval, use_cache: _candles())
    monkeypatch.setattr(cli, "load_full_index_minute_history", lambda client, code, tic_scope, use_cache: _candles())

    args = _make_download_args(tmp_path)
    cli._run_download_universe(args)

    out = capsys.readouterr().out
    assert "실패" in out
    assert "성공 1종목, 실패 1종목" in out
    assert (tmp_path / "data" / "stocks" / "daily" / "005930.csv").exists()
    assert not (tmp_path / "data" / "stocks" / "daily" / "000660.csv").exists()


def test_run_update_top35_prints_summary(monkeypatch, tmp_path, capsys):
    summary = pd.DataFrame(
        [
            {"stock_code": "000660", "name": "SK하이닉스", "daily_rows": 1222, "minute_rows": 97500, "status": "ok"},
            {"stock_code": "005930", "name": "삼성전자", "daily_rows": None, "minute_rows": None, "status": "실패: API error"},
        ]
    )
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "update_top35", lambda client, **kwargs: summary)

    args = Namespace(
        market="000", daily_years=5, minute_tic_scope="1", overlap_days=5, data_dir=str(tmp_path / "data"),
    )
    cli._run_update_top35(args)

    out = capsys.readouterr().out
    assert "000660" in out and "97500" in out
    assert "실패: API error" in out
    assert "성공 1종목, 실패 1종목" in out


def test_run_collect_orderbook_skips_when_market_closed(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "is_market_open", lambda now: False)
    calls = []
    monkeypatch.setattr(cli, "run_collection_loop", lambda *a, **k: calls.append((a, k)))

    args = Namespace(top_n=35, market="000", interval_seconds=3.0, data_dir="data")
    cli._run_collect_orderbook(args)

    assert calls == []
    assert "정규장 시간이 아닙니다" in capsys.readouterr().out


def test_run_collect_orderbook_polls_todays_top_n_when_market_open(monkeypatch, capsys):
    watchlist = pd.DataFrame([{"stock_code": "005930", "name": "삼성전자"}, {"stock_code": "000660", "name": "SK하이닉스"}])
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "is_market_open", lambda now: True)
    monkeypatch.setattr(cli, "top_by_trading_value", lambda client, top_n, market: watchlist)
    calls = []
    monkeypatch.setattr(cli, "run_collection_loop", lambda client, codes, output_dir, interval_seconds: calls.append((codes, output_dir, interval_seconds)))

    args = Namespace(top_n=35, market="000", interval_seconds=2.5, data_dir="data")
    cli._run_collect_orderbook(args)

    assert len(calls) == 1
    codes, output_dir, interval_seconds = calls[0]
    assert codes == ["005930", "000660"]
    assert output_dir == os.path.join("data", "orderbook")
    assert interval_seconds == 2.5


def test_run_monitor_signals_skips_when_market_closed(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "wait_until_extended_market_open", lambda: False)
    calls = []
    monkeypatch.setattr(cli, "load_model", lambda path: calls.append(("load", path)))
    monkeypatch.setattr(cli, "run_monitor_loop", lambda *a, **k: calls.append(("run", a, k)))

    args = Namespace(
        model_path="models/entry_filter_model.joblib", top_n=35, proba_threshold=0.6,
        interval_seconds=30.0, data_dir="data", output="signals.jsonl",
    )
    cli._run_monitor_signals(args)

    assert calls == []
    assert "통합장 시간이 아닙니다" in capsys.readouterr().out


def test_run_monitor_signals_routes_strategy_3_to_scalp_loop_without_loading_model(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_build_client", lambda: "client-obj")
    monkeypatch.setattr(cli, "wait_until_extended_market_open", lambda: True)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "CHAT")

    model_loads = []
    monkeypatch.setattr(cli, "load_model", lambda path: model_loads.append(path))
    scalp_calls = []
    monkeypatch.setattr(
        cli, "run_scalp_monitor_loop",
        lambda client, bot_token, chat_id, output_path, top_n, poll_interval_seconds: scalp_calls.append(
            (client, bot_token, chat_id, output_path, top_n, poll_interval_seconds)
        ),
    )

    args = Namespace(
        strategy="strategy_3", model_path="models/strategy_1/entry_filter_model.joblib", top_n=35,
        proba_threshold=0.6, interval_seconds=30.0, data_dir="data", output="signals.jsonl",
    )
    cli._run_monitor_signals(args)

    assert model_loads == []  # strategy_3은 ML 모델을 아예 로드하지 않음
    assert len(scalp_calls) == 1
    client, bot_token, chat_id, output_path, top_n, poll_interval_seconds = scalp_calls[0]
    assert client == "client-obj"
    assert bot_token == "TOKEN"
    assert chat_id == "CHAT"
    assert output_path == "state/strategy_3/signals.jsonl"  # --output 미지정 시 전략3 전용 경로로 대체
    assert top_n == 35
    assert poll_interval_seconds == 30.0


def test_run_monitor_signals_loads_model_and_runs_loop_when_market_open(monkeypatch):
    monkeypatch.setattr(cli, "_build_client", lambda: "client-obj")
    monkeypatch.setattr(cli, "wait_until_extended_market_open", lambda: True)
    monkeypatch.setattr(cli, "load_model", lambda path: f"trained:{path}")
    calls = []
    monkeypatch.setattr(
        cli, "run_monitor_loop",
        lambda client, trained, output_path, data_dir, top_n, proba_threshold, poll_interval_seconds: calls.append(
            (client, trained, output_path, data_dir, top_n, proba_threshold, poll_interval_seconds)
        ),
    )

    args = Namespace(
        model_path="models/entry_filter_model.joblib", top_n=35, proba_threshold=0.6,
        interval_seconds=30.0, data_dir="data", output="signals.jsonl",
    )
    cli._run_monitor_signals(args)

    assert len(calls) == 1
    client, trained, output_path, data_dir, top_n, proba_threshold, poll_interval_seconds = calls[0]
    assert client == "client-obj"
    assert trained == "trained:models/entry_filter_model.joblib"
    assert output_path == "signals.jsonl"
    assert top_n == 35
    assert proba_threshold == 0.6
    assert poll_interval_seconds == 30.0


def _trading_args(**overrides):
    defaults = dict(
        strategy="strategy_1",
        model_path="models/strategy_1/entry_filter_model.joblib", top_n=35, proba_threshold=0.5,
        max_concurrent_positions=5, total_capital=10_000_000, interval_seconds=30.0,
        data_dir="data", risk_state_path="state/risk_state.json",
        order_log_path="state/orders.jsonl", pnl_history_path="state/pnl_history.jsonl",
        kill_switch_override_path="state/kill_switch_override.json",
    )
    defaults.update(overrides)
    return Namespace(**defaults)


def test_run_trading_refuses_when_max_daily_loss_not_set(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.delenv("MAX_DAILY_LOSS_KRW", raising=False)
    calls = []
    monkeypatch.setattr(cli, "_build_client", lambda: calls.append("client") or object())

    cli._run_trading(_trading_args())

    assert calls == []  # 클라이언트 생성 전에 즉시 중단
    assert "MAX_DAILY_LOSS_KRW" in capsys.readouterr().out


def test_run_trading_refuses_when_telegram_credentials_missing(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("MAX_DAILY_LOSS_KRW", "300000")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    calls = []
    monkeypatch.setattr(cli, "_build_client", lambda: calls.append("client") or object())

    cli._run_trading(_trading_args())

    assert calls == []
    assert "TELEGRAM" in capsys.readouterr().out


def test_run_trading_skips_when_market_closed(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("MAX_DAILY_LOSS_KRW", "300000")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(cli, "_build_client", lambda: object())
    monkeypatch.setattr(cli, "wait_until_extended_market_open", lambda **kwargs: False)
    calls = []
    monkeypatch.setattr(cli, "run_trading_loop", lambda *a, **k: calls.append((a, k)))

    cli._run_trading(_trading_args())

    assert calls == []
    assert "통합장 시간이 아닙니다" in capsys.readouterr().out


def test_run_trading_starts_loop_with_env_values_when_market_open(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("MAX_DAILY_LOSS_KRW", "300000")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    monkeypatch.setenv("KIWOOM_IS_MOCK", "true")
    monkeypatch.setattr(cli, "_build_client", lambda: "client-obj")
    monkeypatch.setattr(cli, "wait_until_extended_market_open", lambda **kwargs: True)
    monkeypatch.setattr(cli, "load_model", lambda path: f"trained:{path}")
    monkeypatch.setattr(cli, "_write_strategy_config", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(cli, "run_trading_loop", lambda *a, **k: calls.append((a, k)))

    cli._run_trading(_trading_args())

    assert len(calls) == 1
    args, kwargs = calls[0]
    client, trained, bot_token, chat_id, max_daily_loss_krw = args
    assert client == "client-obj"
    assert trained == "trained:models/strategy_1/entry_filter_model.joblib"
    assert bot_token == "token123"
    assert chat_id == "chat456"
    assert max_daily_loss_krw == 300000.0
    assert kwargs["risk_state_path"] == "state/risk_state.json"
    assert kwargs["max_concurrent_positions"] == 5
    assert kwargs["total_capital_krw"] == 10_000_000
    assert "모의투자" in capsys.readouterr().out


def test_run_trading_warns_real_account_when_not_mock(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("MAX_DAILY_LOSS_KRW", "300000")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    monkeypatch.setenv("KIWOOM_IS_MOCK", "false")
    monkeypatch.setattr(cli, "_build_client", lambda: "client-obj")
    monkeypatch.setattr(cli, "wait_until_extended_market_open", lambda **kwargs: True)
    monkeypatch.setattr(cli, "load_model", lambda path: "trained")
    monkeypatch.setattr(cli, "_write_strategy_config", lambda *a, **k: None)
    monkeypatch.setattr(cli, "run_trading_loop", lambda *a, **k: None)

    cli._run_trading(_trading_args())

    assert "실계좌" in capsys.readouterr().out


def test_run_trading_derives_paths_from_strategy_when_not_explicit(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("MAX_DAILY_LOSS_KRW", "300000")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    monkeypatch.setattr(cli, "_build_client", lambda: "client-obj")
    monkeypatch.setattr(cli, "wait_until_extended_market_open", lambda **kwargs: True)
    monkeypatch.setattr(cli, "load_model", lambda path: f"trained:{path}")
    monkeypatch.setattr(cli, "_write_strategy_config", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(cli, "run_trading_loop", lambda *a, **k: calls.append((a, k)))

    # strategy_2는 오버솔드 전용 경로로 분기되므로(아래 test_run_trading_dispatches_*),
    # 여기서는 일반적인(ML 기반) 향후 전략을 흉내내는 다른 이름으로 경로 유도 규칙만 검증한다.
    args = _trading_args(
        strategy="strategy_3", model_path=None, risk_state_path=None,
        order_log_path=None, pnl_history_path=None, kill_switch_override_path=None,
    )
    cli._run_trading(args)

    assert len(calls) == 1
    trained_args, kwargs = calls[0]
    assert trained_args[1] == "trained:models/strategy_3/entry_filter_model.joblib"
    assert kwargs["risk_state_path"] == "state/strategy_3/risk_state.json"
    assert kwargs["order_log_path"] == "state/strategy_3/orders.jsonl"
    assert kwargs["pnl_history_path"] == "state/strategy_3/pnl_history.jsonl"
    assert kwargs["kill_switch_override_path"] == "state/strategy_3/kill_switch_override.json"


def test_run_trading_writes_strategy_config_snapshot(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("MAX_DAILY_LOSS_KRW", "300000")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    monkeypatch.setenv("KIWOOM_IS_MOCK", "true")
    monkeypatch.setattr(cli, "_build_client", lambda: "client-obj")
    monkeypatch.setattr(cli, "wait_until_extended_market_open", lambda **kwargs: True)
    monkeypatch.setattr(cli, "load_model", lambda path: "trained")
    monkeypatch.setattr(cli, "run_trading_loop", lambda *a, **k: None)
    config_calls = []
    monkeypatch.setattr(cli, "_write_strategy_config", lambda risk_state_path, config: config_calls.append((risk_state_path, config)))

    cli._run_trading(_trading_args(strategy="strategy_1"))

    assert len(config_calls) == 1
    risk_state_path, config = config_calls[0]
    assert risk_state_path == "state/risk_state.json"
    assert config["strategy"] == "strategy_1"
    assert config["model_path"] == "models/strategy_1/entry_filter_model.joblib"
    assert config["top_n"] == 35
    assert config["proba_threshold"] == 0.5
    assert config["max_concurrent_positions"] == 5
    assert config["total_capital_krw"] == 10_000_000
    assert config["max_daily_loss_krw"] == 300000.0


def test_run_trading_dispatches_strategy_2_to_oversold_loop_without_loading_model(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("MAX_DAILY_LOSS_KRW", "300000")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    monkeypatch.setenv("KIWOOM_IS_MOCK", "true")
    monkeypatch.setattr(cli, "_build_client", lambda: "client-obj")
    monkeypatch.setattr(cli, "wait_until_extended_market_open", lambda **kwargs: True)
    monkeypatch.setattr(cli, "_write_strategy_config", lambda *a, **k: None)
    model_calls = []
    monkeypatch.setattr(cli, "load_model", lambda path: model_calls.append(path) or "trained")
    ml_calls = []
    monkeypatch.setattr(cli, "run_trading_loop", lambda *a, **k: ml_calls.append((a, k)))
    oversold_calls = []
    monkeypatch.setattr(cli, "run_oversold_trading_loop", lambda *a, **k: oversold_calls.append((a, k)))

    cli._run_trading(_trading_args(strategy="strategy_2"))

    assert model_calls == []  # 전략2는 ML 모델을 쓰지 않음
    assert ml_calls == []  # strategy_1용 루프는 호출되지 않음
    assert len(oversold_calls) == 1
    args, kwargs = oversold_calls[0]
    client, bot_token, chat_id, max_daily_loss_krw = args
    assert client == "client-obj"
    assert bot_token == "token123"
    assert chat_id == "chat456"
    assert max_daily_loss_krw == 300000.0
    assert kwargs["total_capital_krw"] == 10_000_000
    assert kwargs["risk_state_path"] == "state/risk_state.json"
    assert kwargs["poll_interval_seconds"] == 30.0


def test_run_trading_strategy_2_config_snapshot_has_no_ml_fields(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("MAX_DAILY_LOSS_KRW", "300000")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    monkeypatch.setenv("KIWOOM_IS_MOCK", "true")
    monkeypatch.setattr(cli, "_build_client", lambda: "client-obj")
    monkeypatch.setattr(cli, "wait_until_extended_market_open", lambda **kwargs: True)
    monkeypatch.setattr(cli, "run_oversold_trading_loop", lambda *a, **k: None)
    config_calls = []
    monkeypatch.setattr(cli, "_write_strategy_config", lambda risk_state_path, config: config_calls.append((risk_state_path, config)))

    cli._run_trading(_trading_args(strategy="strategy_2"))

    assert len(config_calls) == 1
    _, config = config_calls[0]
    assert config["strategy"] == "strategy_2"
    assert config["stock_code"] == "000660"
    assert config["total_capital_krw"] == 10_000_000
    assert config["max_daily_loss_krw"] == 300000.0
    assert "model_path" not in config
    assert "top_n" not in config
    assert "proba_threshold" not in config
    assert config["is_mock"] is True
    assert "started_at" in config


def test_write_strategy_config_writes_json_next_to_risk_state(tmp_path):
    risk_state_path = str(tmp_path / "state" / "strategy_1" / "risk_state.json")

    cli._write_strategy_config(risk_state_path, {"strategy": "strategy_1", "top_n": 35})

    import json
    config_path = tmp_path / "state" / "strategy_1" / "config.json"
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"strategy": "strategy_1", "top_n": 35}


def test_run_dashboard_forwards_args_to_server(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("KIWOOM_APPKEY", "appkey123")
    monkeypatch.setenv("KIWOOM_SECRETKEY", "secret456")
    monkeypatch.setenv("KIWOOM_IS_MOCK", "true")
    calls = []
    monkeypatch.setattr(cli, "run_dashboard_server", lambda **kwargs: calls.append(kwargs))

    args = Namespace(port=9999, host="127.0.0.1", state_root="custom/state", results_dir="custom/results")
    cli._run_dashboard(args)

    assert calls == [{
        "state_root": "custom/state",
        "results_dir": "custom/results",
        "kiwoom_appkey": "appkey123",
        "kiwoom_secretkey": "secret456",
        "kiwoom_is_mock": True,
        "port": 9999,
        "host": "127.0.0.1",
    }]


def test_dashboard_parser_defaults_host_to_localhost():
    # 기본값은 127.0.0.1(로컬 전용)이어야 한다 — 모바일 등 외부 접속을 원하면
    # --host 0.0.0.0을 명시적으로 넘겨야 하고, 실수로 열려있으면 안 된다.
    parser = cli.build_parser()
    args = parser.parse_args(["dashboard"])
    assert args.host == "127.0.0.1"


def test_dashboard_parser_accepts_custom_host():
    parser = cli.build_parser()
    args = parser.parse_args(["dashboard", "--host", "0.0.0.0"])
    assert args.host == "0.0.0.0"


def test_run_dashboard_defaults_is_mock_true_when_env_unset(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.delenv("KIWOOM_APPKEY", raising=False)
    monkeypatch.delenv("KIWOOM_SECRETKEY", raising=False)
    monkeypatch.delenv("KIWOOM_IS_MOCK", raising=False)
    calls = []
    monkeypatch.setattr(cli, "run_dashboard_server", lambda **kwargs: calls.append(kwargs))

    args = Namespace(port=8765, host="127.0.0.1", state_root="state", results_dir="results")
    cli._run_dashboard(args)

    assert calls[0]["kiwoom_appkey"] == ""
    assert calls[0]["kiwoom_secretkey"] == ""
    assert calls[0]["kiwoom_is_mock"] is True
