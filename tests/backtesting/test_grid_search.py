import logging
from datetime import date

import numpy as np
import pandas as pd
import pytest

from backtesting import grid_search
from backtesting.strategies.ma_crossover import MovingAverageCrossover
from backtesting.types import Signal


def _daily_candles(n: int = 40) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=n, freq="B")
    closes = [10.0] * (n // 2) + [20.0] * (n - n // 2)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * n},
        index=index,
    )


def _minute_candles(days: int = 10, per_day: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    frames = []
    for d in range(days):
        day = pd.Timestamp("2026-01-01") + pd.Timedelta(days=d)
        index = pd.date_range(day + pd.Timedelta(hours=9), periods=per_day, freq="1min")
        prices = 100 + np.cumsum(rng.normal(0, 0.15, size=per_day))
        frames.append(
            pd.DataFrame(
                {
                    "open": prices,
                    "high": prices + 0.05,
                    "low": prices - 0.05,
                    "close": prices,
                    "volume": rng.integers(900, 1100, size=per_day),
                },
                index=index,
            )
        )
    return pd.concat(frames)


def test_param_combinations_produces_cartesian_product():
    combos = grid_search._param_combinations({"a": [1, 2], "b": [10]})

    assert combos == [{"a": 1, "b": 10}, {"a": 2, "b": 10}]


def test_run_rule_based_produces_result_per_stock_and_param(monkeypatch):
    candles = _daily_candles()
    monkeypatch.setattr(grid_search, "load_history", lambda *a, **k: candles)

    results = grid_search.run_rule_based(
        client=object(),
        stock_codes=["005930"],
        strategy=MovingAverageCrossover(),
        param_grid={"short_window": [2], "long_window": [5]},
        start=date(2026, 1, 1),
        end=date(2026, 3, 1),
    )

    assert len(results) == 1
    assert results[0].stock_code == "005930"
    assert results[0].params == {"short_window": 2, "long_window": 5}


def test_run_rule_based_computes_benchmark_buy_and_hold_return(monkeypatch):
    """벤치마크(매수 후 보유) 수익률이 OOS 구간 가격으로 정확히 계산되는지 확인.

    실제로 MA 크로스오버 OOS +160%가 벤치마크(매수 후 보유) +285%에 못 미쳐 사실은
    시장을 못 따라간 것으로 드러난 사례를 계기로 추가된 필드."""
    index = pd.date_range("2026-01-01", periods=10, freq="B")
    closes = [10.0] * 7 + [12.0, 14.0, 20.0]  # in_sample_ratio=0.7 -> split_idx=7, OOS=[12,14,20]
    candles = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * 10},
        index=index,
    )
    monkeypatch.setattr(grid_search, "load_history", lambda *a, **k: candles)

    results = grid_search.run_rule_based(
        client=object(), stock_codes=["005930"], strategy=MovingAverageCrossover(),
        param_grid={"short_window": [2], "long_window": [3]},
        start=date(2026, 1, 1), end=date(2026, 1, 20),
    )

    assert len(results) == 1
    expected_benchmark = (20.0 / 12.0 - 1) * 100
    assert results[0].benchmark_oos_return_pct == pytest.approx(expected_benchmark)


def test_run_rule_based_logs_and_skips_failed_stock_load(monkeypatch, caplog):
    """조회 실패 종목(예: API 오류)이 "데이터 원래 없음"과 구분 없이 조용히 사라지던
    문제 - universe.py build_liquid_universe와 같은 패턴으로 로그를 남기고, 결과에서는
    빠지되 나머지 종목은 그대로 계산돼야 한다."""
    candles = _daily_candles()

    def _load_or_fail(client, stock_code, *a, **k):
        if stock_code == "000660":
            raise RuntimeError("API 오류")
        return candles

    monkeypatch.setattr(grid_search, "load_history", _load_or_fail)

    with caplog.at_level(logging.WARNING, logger="backtesting.grid_search"):
        results = grid_search.run_rule_based(
            client=object(),
            stock_codes=["005930", "000660"],
            strategy=MovingAverageCrossover(),
            param_grid={"short_window": [2], "long_window": [5]},
            start=date(2026, 1, 1),
            end=date(2026, 3, 1),
        )

    assert [r.stock_code for r in results] == ["005930"]
    assert "000660" in caplog.text
    assert "1" in caplog.text  # 요약 로그에 실패 건수 1이 찍혀야 함


def test_run_rule_based_skips_invalid_param_combo(monkeypatch):
    candles = _daily_candles()
    monkeypatch.setattr(grid_search, "load_history", lambda *a, **k: candles)

    results = grid_search.run_rule_based(
        client=object(),
        stock_codes=["005930"],
        strategy=MovingAverageCrossover(),
        param_grid={"short_window": [10], "long_window": [5]},
        start=date(2026, 1, 1),
        end=date(2026, 3, 1),
    )

    assert results == []


class _FixedSignalStrategy:
    """가격과 무관하게 정해진 날짜에만 BUY/SELL — IS/OOS 경계 시나리오를 정확히
    구성하기 위한 테스트 전용 더미(daily_walk_forward.py 회귀 테스트와 같은 패턴)."""

    name = "fixed_signal_for_test"

    def __init__(self, buy_dates, sell_dates):
        self.buy_dates = set(buy_dates)
        self.sell_dates = set(sell_dates)

    def evaluate(self, candles: pd.DataFrame, params: dict) -> pd.Series:
        def sig(ts):
            d = ts.date()
            if d in self.buy_dates:
                return Signal.BUY
            if d in self.sell_dates:
                return Signal.SELL
            return Signal.HOLD

        return pd.Series([sig(ts) for ts in candles.index], index=candles.index)


def test_run_rule_based_position_spanning_is_oos_boundary_is_not_double_entered(monkeypatch):
    """회귀 테스트: IS 막바지에 진입해 OOS까지 안 닫힌 포지션을, IS/OOS를 독립적으로
    evaluate+simulate하던 예전 구현은 못 봤다 — IS의 시뮬레이션이 자기 구간 끝에서
    끊겨 그 포지션은 미청산으로 사라지고(in_sample.num_trades==0), 대신 OOS가 새로
    fresh 상태로 시작하며 OOS 안의 신호를 자기 것인 양 진입으로 잡는다
    (out_of_sample.num_trades==1) — 총 거래수는 우연히 같아 보여도 "어느 쪽 거래인지"가
    틀린다(daily_walk_forward.py에서 실측으로 확인한 것과 같은 계열의 버그). 지금은
    전체 캔들을 한 번만 시뮬레이션하고 거래를 entry_date로 나눠, 진짜 거래가 IS에
    올바르게 잡힌다."""
    candles = _daily_candles(n=20)  # in_sample_ratio=0.7 -> split_idx=14
    split_idx = int(len(candles) * 0.7)
    split_date = candles.index[split_idx].date()

    # IS 마지막 거래일에 체결되도록 신호는 그 하루 전에 둔다(다음 봉 시가 체결).
    buy_signal_date = candles.index[split_idx - 2].date()
    exit_date = candles.index[split_idx + 3].date()
    # OOS 초입에도 "새 진입처럼 보이는" BUY를 하나 더 심는다.
    phantom_buy_date = candles.index[split_idx].date()

    strategy = _FixedSignalStrategy(buy_dates=[buy_signal_date, phantom_buy_date], sell_dates=[exit_date])
    monkeypatch.setattr(grid_search, "load_history", lambda *a, **k: candles)

    results = grid_search.run_rule_based(
        client=object(), stock_codes=["005930"], strategy=strategy, param_grid={},
        start=date(2026, 1, 1), end=date(2026, 3, 1),
    )

    assert len(results) == 1
    # 총 거래수(1건)만 보면 예전 버그도 우연히 통과한다 — "어느 쪽 거래인지"가 핵심.
    assert results[0].in_sample.num_trades == 1, (
        "IS 막바지에 진입한 진짜 거래가 안 잡혔다 — IS/OOS를 독립적으로 "
        "시뮬레이션하도록 되돌아갔는지 확인할 것(그러면 이 거래가 미청산으로 사라진다)"
    )
    assert results[0].out_of_sample.num_trades == 0, (
        "OOS 쪽이 IS의 미청산 포지션을 모르고 자기 구간의 신호를 새 진입으로 또 잡았다"
    )


def test_run_ml_walk_forward_produces_valid_result_structure(monkeypatch):
    candles = _minute_candles()
    monkeypatch.setattr(grid_search, "load_history", lambda *a, **k: candles)

    results = grid_search.run_ml_walk_forward(
        client=object(),
        stock_codes=["005930"],
        param_grid={"buy_threshold": [0.5]},
        start=date(2026, 1, 1),
        end=date(2026, 1, 10),
        train_days=5,
        test_days=2,
        step_days=2,
        label_horizon_minutes=5,
        label_return_threshold=0.0005,
    )

    for result in results:
        assert result.strategy_name == "ml_day_trading"
        assert result.out_of_sample.num_trades >= 0
        assert result.in_sample.num_trades >= 0


def test_run_ml_walk_forward_logs_and_skips_failed_stock_load(monkeypatch, caplog):
    candles = _minute_candles()

    def _load_or_fail(client, stock_code, *a, **k):
        if stock_code == "000660":
            raise RuntimeError("API 오류")
        return candles

    monkeypatch.setattr(grid_search, "load_history", _load_or_fail)

    with caplog.at_level(logging.WARNING, logger="backtesting.grid_search"):
        results = grid_search.run_ml_walk_forward(
            client=object(),
            stock_codes=["005930", "000660"],
            param_grid={"buy_threshold": [0.5]},
            start=date(2026, 1, 1),
            end=date(2026, 1, 10),
            train_days=5,
            test_days=2,
            step_days=2,
            label_horizon_minutes=5,
            label_return_threshold=0.0005,
        )

    assert all(r.stock_code == "005930" for r in results)
    assert "000660" in caplog.text
    assert "1" in caplog.text
