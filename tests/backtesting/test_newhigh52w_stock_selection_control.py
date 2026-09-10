import numpy as np
import pandas as pd
import pytest

from backtesting.newhigh52w_stock_selection_control import (
    _random_stock_trades,
    population_b_codes,
    random_population_distribution,
)


def _panel(code: str, n: int = 20, newhigh_days: set[int] | None = None) -> pd.DataFrame:
    dates = [f"2025-01-{i:02d}" for i in range(1, n + 1)]
    closes = [100.0 + i for i in range(n)]
    newhigh = [(i in newhigh_days) if newhigh_days else False for i in range(n)]
    return pd.DataFrame({"code": [code] * n, "date": dates, "open": closes, "high": [c + 1 for c in closes],
                         "low": [c - 1 for c in closes], "close": closes, "newhigh": newhigh})


def test_population_b_is_subset_of_a_that_hit_newhigh():
    panel = pd.concat([_panel("A", newhigh_days={5}), _panel("B"), _panel("C", newhigh_days={2, 7})],
                       ignore_index=True)

    out = population_b_codes(panel, population_a=["A", "B", "C"])

    assert out == ["A", "C"]  # B는 한 번도 newhigh 아니었음


def test_population_b_excludes_codes_outside_population_a():
    # D 는 newhigh 지만 population_a(시총필터)에 없으니 제외돼야 함
    panel = pd.concat([_panel("A", newhigh_days={1}), _panel("D", newhigh_days={1})], ignore_index=True)

    out = population_b_codes(panel, population_a=["A"])

    assert out == ["A"]


def test_random_stock_trades_uses_entry_date_or_next_available_day():
    panel = _panel("A", n=10)  # 2025-01-01 ~ 2025-01-10
    rng = np.random.default_rng(0)

    out, dropped = _random_stock_trades(["2025-01-03"], ["A"], panel, rng, code_cache={})

    assert dropped == 0
    assert len(out) == 1
    assert out.iloc[0]["entry_date"] == "2025-01-03"  # 정확히 그 날짜에 데이터 있음


def test_random_stock_trades_drops_when_entry_date_beyond_available_data():
    panel = _panel("A", n=5)  # 2025-01-01 ~ 2025-01-05
    rng = np.random.default_rng(0)

    out, dropped = _random_stock_trades(["2025-06-01"], ["A"], panel, rng, code_cache={})

    assert dropped == 1
    assert out.empty


def test_random_population_distribution_empty_when_population_or_dates_empty():
    panel = _panel("A")

    r1, d1 = random_population_distribution(panel, ["2025-01-03"], population=[])
    r2, d2 = random_population_distribution(panel, [], population=["A"])

    assert r1 == [] and d1 == 0
    assert r2 == [] and d2 == 0


def test_random_population_distribution_reproducible():
    panel = pd.concat([_panel("A", 15), _panel("B", 15)], ignore_index=True)

    r1, _ = random_population_distribution(panel, ["2025-01-03", "2025-01-05"], ["A", "B"], n_seeds=5)
    r2, _ = random_population_distribution(panel, ["2025-01-03", "2025-01-05"], ["A", "B"], n_seeds=5)

    assert r1 == r2
    assert len(r1) == 5
