import pandas as pd

from backtesting import report
from backtesting.types import GridSearchResult, PerformanceMetrics


def _result(stock_code: str, oos_return: float, benchmark_oos_return: float = 0.0) -> GridSearchResult:
    metrics = PerformanceMetrics(
        total_return_pct=oos_return,
        cagr_pct=oos_return,
        win_rate_pct=50.0,
        max_drawdown_pct=5.0,
        sharpe_ratio=1.0,
        num_trades=3,
    )
    return GridSearchResult(
        stock_code=stock_code,
        strategy_name="ma_crossover",
        params={"short_window": 5, "long_window": 20},
        in_sample=metrics,
        out_of_sample=metrics,
        benchmark_oos_return_pct=benchmark_oos_return,
    )


def test_summarize_sorts_by_out_of_sample_return_descending():
    results = [_result("A", 1.0), _result("B", 5.0), _result("C", -2.0)]

    df = report.summarize(results)

    assert list(df["stock_code"]) == ["B", "A", "C"]


def test_summarize_includes_alpha_column():
    results = [_result("A", 10.0, benchmark_oos_return=4.0)]

    df = report.summarize(results)

    assert df.iloc[0]["alpha_oos_pct"] == 6.0
    assert df.iloc[0]["benchmark_oos_return_pct"] == 4.0


def test_rank_results_prefers_higher_alpha_over_higher_raw_return():
    """실제 사례 재현: MA 크로스오버가 OOS +160%였지만 벤치마크(매수후보유)가 +285%라
    사실은 시장을 못 따라간 것으로 드러난 문제. 랭킹은 raw 수익률이 아니라 alpha 기준."""
    high_return_low_alpha = _result("underperformed", oos_return=160.0, benchmark_oos_return=285.0)
    lower_return_high_alpha = _result("beat_market", oos_return=50.0, benchmark_oos_return=10.0)

    ranked = report.rank_results([high_return_low_alpha, lower_return_high_alpha])

    assert ranked[0].stock_code == "beat_market"


def test_save_csv_round_trip(tmp_path):
    results = [_result("A", 1.0)]
    df = report.summarize(results)
    csv_path = tmp_path / "results.csv"

    report.save_csv(df, str(csv_path))

    assert csv_path.exists()
    assert "oos_return_pct" in csv_path.read_text(encoding="utf-8")


def _candles(n: int = 5) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=n, freq="D")
    closes = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * n},
        index=index,
    )


def test_plot_best_does_not_crash_with_no_trades(monkeypatch):
    """실제 API로 거래 0건인 조합을 그리려다 mplfinance가 크래시했던 버그의 회귀 테스트."""
    plot_calls = []
    monkeypatch.setattr(report.mpf, "plot", lambda *a, **k: plot_calls.append(k))

    report.plot_best(_candles(), trades=[], title="no trades")

    assert len(plot_calls) == 1
    assert "addplot" not in plot_calls[0]


def test_plot_best_includes_addplot_when_trades_exist(monkeypatch):
    from datetime import date as date_type

    from backtesting.types import Trade

    plot_calls = []
    monkeypatch.setattr(report.mpf, "plot", lambda *a, **k: plot_calls.append(k))

    trade = Trade(
        stock_code="005930", entry_date=date_type(2026, 1, 1), entry_price=100,
        quantity=10, commission=0, slippage=0, exit_date=date_type(2026, 1, 3),
        exit_price=102, pnl=20, pnl_pct=0.02,
    )

    report.plot_best(_candles(), trades=[trade], title="with trades")

    assert "addplot" in plot_calls[0]
    assert len(plot_calls[0]["addplot"]) == 2
