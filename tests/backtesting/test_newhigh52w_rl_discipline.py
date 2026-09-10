import numpy as np
import pandas as pd
import pytest

from backtesting.newhigh52w_rl_discipline import (
    _code_arrays,
    _random_trades,
    judge_buried,
    random_control_distribution,
)


def _panel(code: str, n: int = 20) -> pd.DataFrame:
    dates = [f"2025-01-{i:02d}" for i in range(1, n + 1)]
    closes = [100.0 + i for i in range(n)]
    return pd.DataFrame({"code": [code] * n, "date": dates, "open": closes, "high": [c + 1 for c in closes],
                         "low": [c - 1 for c in closes], "close": closes})


def test_code_arrays_sorts_by_date_and_extracts_ohlc():
    panel = pd.concat([_panel("B"), _panel("A")], ignore_index=True)

    arr = _code_arrays(panel, "A")

    assert len(arr["opens"]) == 20
    assert arr["dates"][0] == "2025-01-01"


def test_random_trades_entry_idx_never_the_last_row(monkeypatch):
    # entry_idx는 0..n-2 범위여야(최소 하루는 exit_idx로 남게) - 시드 여러 개로 확인
    panel = _panel("A", n=10)
    arrays = {"A": _code_arrays(panel, "A")}

    for seed in range(30):
        rng = np.random.default_rng(seed)
        out = _random_trades(["A"], arrays, rng, stop_pct=0.08, target_pct=0.24)
        entry_idx = list(arrays["A"]["dates"]).index(out.iloc[0]["entry_date"])
        assert entry_idx <= 8  # n-2


def test_random_trades_preserves_code_multiset():
    panel = pd.concat([_panel("A", 10), _panel("B", 10)], ignore_index=True)
    arrays = {"A": _code_arrays(panel, "A"), "B": _code_arrays(panel, "B")}
    rng = np.random.default_rng(0)

    out = _random_trades(["A", "A", "B"], arrays, rng)

    assert sorted(out["code"]) == ["A", "A", "B"]


def test_random_control_distribution_reproducible_across_calls():
    panel = pd.concat([_panel("A", 15), _panel("B", 15)], ignore_index=True)
    real_trades = pd.DataFrame({"code": ["A", "B"], "entry_date": ["2025-01-05", "2025-01-05"],
                                "exit_date": ["2025-01-10", "2025-01-10"], "net_pct": [0.01, -0.01]})

    r1 = random_control_distribution(panel, real_trades, n_seeds=5)
    r2 = random_control_distribution(panel, real_trades, n_seeds=5)

    assert r1 == r2  # 같은 시드 목록(0..4) -> 같은 결과(결정론)
    assert len(r1) == 5


def test_random_control_distribution_empty_when_no_real_trades():
    out = random_control_distribution(pd.DataFrame(), pd.DataFrame(columns=["code", "entry_date"]))

    assert out == []


def test_judge_buried_true_when_median_at_or_below_50():
    df = pd.DataFrame({"percentile_rank": [10.0, 20.0, 30.0, 40.0]})

    verdict = judge_buried(df)

    assert verdict["buried"] is True
    assert verdict["median_percentile"] == pytest.approx(25.0)


def test_judge_buried_false_when_clearly_beats_random():
    df = pd.DataFrame({"percentile_rank": [80.0, 90.0, 70.0, 95.0]})

    verdict = judge_buried(df)

    assert verdict["buried"] is False
    assert verdict["win_share"] == pytest.approx(1.0)


def test_judge_buried_ignores_nan_rows_from_zero_signal_windows():
    df = pd.DataFrame({"percentile_rank": [90.0, 85.0, float("nan")]})

    verdict = judge_buried(df)

    assert verdict["n_valid_combos"] == 2
    assert verdict["buried"] is False
