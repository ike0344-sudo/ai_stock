"""SC-4 — 서비스(run_backtest) 호환 모드 결과 == 기존 simulator.run + metrics.compute (거래·지표 1e-9).

프리셋 golden_cross_5_20 을 daily_single + compat.legacy 로 돌린다. 실제 3종목, 고정 구간.
기존 CLI 는 워밍업 없이 기간 캔들만으로 신호를 계산하므로 호환 모드도 그렇게 한다(서비스 docstring).
"""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from backtesting import metrics as legacy_metrics_mod
from backtesting import simulator
from backtesting.strategies.ma_crossover import MovingAverageCrossover
from backtesting.strategies.rsi_strategy import RsiStrategy
from studio.application.backtest_service import run_backtest
from studio.domain.spec import Spec
from studio.infrastructure.legacy_adapter import LegacyAdapter
from studio.infrastructure.market_data import LocalMarketData

PARQUET = os.path.join("data", "cache", "daily_all.parquet")
PRESET = Path(__file__).resolve().parents[3] / "presets" / "studio" / "golden_cross_5_20.json"
CODES = ["000020", "000050", "000070"]
START, END = "2023-01-02", "2026-08-31"
TOL = 1e-9
COMM, SLIP, CAP = 0.00015, 0.001, 10_000_000


@pytest.fixture(scope="module")
def md():
    if not os.path.exists(PARQUET):
        pytest.skip("daily_all.parquet 없음")
    return LocalMarketData()


def _candles(code):
    d = pd.read_parquet(PARQUET)
    d = d[(d["code"] == code) & (d["date"] >= START) & (d["date"] <= END)]
    return d.assign(date=pd.to_datetime(d["date"])).set_index("date")[["open", "high", "low", "close", "volume"]].astype(float)


def _compare(rec, old, candles):
    assert len(rec.trades) == len(old) > 0
    for (_, n), o in zip(rec.trades.iterrows(), old):
        assert o.entry_date == n["entry_ts"].date()
        assert o.entry_price == pytest.approx(n["entry_price"], abs=TOL, rel=TOL)
        assert o.quantity == n["qty"] and o.commission == pytest.approx(n["commission"], abs=TOL, rel=TOL)
        if o.exit_date is None:
            assert pd.isna(n["exit_ts"])
        else:
            assert o.exit_date == n["exit_ts"].date()
            assert o.exit_price == pytest.approx(n["exit_price"], abs=TOL, rel=TOL)
            assert o.pnl == pytest.approx(n["net_pnl"], abs=TOL, rel=TOL)
            assert o.pnl_pct == pytest.approx(n["net_pct"], abs=TOL, rel=TOL)
    m = legacy_metrics_mod.compute(old, candles, CAP)
    got = rec.summary["legacy_metrics"]
    for k in ("total_return_pct", "cagr_pct", "win_rate_pct", "max_drawdown_pct", "sharpe_ratio", "num_trades"):
        assert getattr(m, k) == pytest.approx(got[k], abs=TOL, rel=TOL), k


def _spec(code, strategy=None):
    d = json.loads(PRESET.read_text(encoding="utf-8"))
    d.update(mode="daily_single", period={"start": START, "end": END}, compat={"legacy": True},
             universe={"type": "codes", "codes": [code]})
    if strategy is not None:
        d["strategy"], d["params"] = strategy, {}
    return Spec.model_validate(d)


@pytest.mark.parity
@pytest.mark.parametrize("code", CODES)
def test_sc4_preset_golden_cross_compat_equals_legacy(md, code):
    rec = run_backtest(_spec(code), md)
    c = _candles(code)
    old = simulator.run(c, MovingAverageCrossover().evaluate(c, {"short_window": 5, "long_window": 20}),
                        COMM, SLIP, CAP, code)
    _compare(rec, old, c)
    assert rec.meta["compat"] and rec.meta["warmup_bars"] == 0


@pytest.mark.parity
@pytest.mark.parametrize("code", CODES)
def test_sc4b_legacy_source_strategies_via_service(md, code):
    """strategy.source='legacy' 경로(어댑터)도 같은 숫자."""
    c = _candles(code)
    for name, params, strat in (
        ("ma_crossover", {"short_window": 5, "long_window": 20}, MovingAverageCrossover()),
        ("rsi", {"period": 14, "buy_below": 30, "sell_above": 70}, RsiStrategy()),
    ):
        rec = run_backtest(_spec(code, {"source": "legacy", "name": name, "params": params}), md,
                           legacy=LegacyAdapter())
        old = simulator.run(c, strat.evaluate(c, params), COMM, SLIP, CAP, code)
        if not old:
            continue
        _compare(rec, old, c)


@pytest.mark.parity
def test_real_data_general_mode_runs_and_is_reasonable(md):
    """실데이터 일반 모드 스모크 — 프리셋 그대로(top100·5슬롯). 숫자 검증이 아니라 끝까지 도는지."""
    d = json.loads(PRESET.read_text(encoding="utf-8"))
    d["period"] = {"start": "2024-01-02", "end": "2026-08-31"}
    rec = run_backtest(Spec.model_validate(d), md)
    assert rec.summary["n_trades"] > 30 and rec.summary["n_codes"] > 1000
    assert (rec.equity["n_positions"] <= 5).all() and rec.equity["cash"].min() >= -1e-6
    assert rec.equity["n_positions"].iloc[-1] == 0  # 데이터 끝에서 전부 청산(end_of_data)
    assert rec.equity["equity"].iloc[-1] == pytest.approx(10_000_000 + rec.trades["net_pnl"].sum(), rel=1e-9)
