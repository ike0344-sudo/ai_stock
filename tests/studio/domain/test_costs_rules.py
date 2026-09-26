"""P4 — CostModel.round_trip_pct vs t0_forward_return.round_trip_cost_pct, 그리고 시장 규칙 대조."""
import numpy as np
import pandas as pd
import pytest

from backtesting import types as legacy_types
from backtesting.t0_forward_return import krx_tick_size as legacy_tick
from backtesting.t0_forward_return import round_trip_cost_pct
from studio.domain import market_rules as mr
from studio.domain.costs import CostModel


def test_p4_round_trip_matches_legacy_over_price_grid():
    prices = np.unique(np.concatenate([
        np.arange(1_000, 1_000_001, 137.0),
        [1_999, 2_000, 4_999, 5_000, 19_999, 20_000, 49_999, 50_000, 199_999, 200_000, 499_999, 500_000, 1_000_000],
    ]))
    got = CostModel().round_trip_pct(prices)
    assert np.max(np.abs(got - round_trip_cost_pct(prices))) < 1e-12


def test_tick_size_scalar_and_array_match_legacy():
    prices = np.array([1, 1_999, 2_000, 4_999.5, 5_000, 19_999, 20_000, 49_999, 50_000,
                       199_999, 200_000, 499_999, 500_000, 2_000_000], dtype=float)
    assert [mr.krx_tick_size(p) for p in prices] == [legacy_tick(p) for p in prices]
    assert list(mr.tick_size_array(prices)) == [legacy_tick(p) for p in prices]


@pytest.mark.parametrize("price", [130, 100, 70, 69.7, 69.65, 130.5, 129.5, 100.0])
def test_limit_lock_matches_legacy(price):
    for prev in (100.0, float("nan")):
        assert mr.is_price_limit_locked(price, prev) == legacy_types.is_price_limit_locked(price, prev)


def test_slippage_modes():
    assert CostModel(slippage_mode="rate").slippage_frac(1_000_000) == 0.001
    assert CostModel(slippage_mode="ticks").slippage_frac(1_000) == pytest.approx(1 / 1000)
    # 저가주: 1틱(1원/1000원=0.1%) < 0.1% 가 같은 경우 / 5,000원대는 10원=0.2% > 0.1%
    assert CostModel().slippage_frac(5_000) == pytest.approx(0.002)
    assert CostModel().buy_price(5_000) == pytest.approx(5_010)
    assert CostModel().sell_price(5_000) == pytest.approx(4_990)


def test_regular_session():
    assert mr.is_regular_session(pd.Timestamp("2026-01-05 09:00"))
    assert not mr.is_regular_session(pd.Timestamp("2026-01-05 15:35"))
