import numpy as np
import pytest

from backtesting.slippage_measurement import _jumps_from_ticks, summarize
import pandas as pd


def test_jumps_from_ticks_skips_zero_diffs_and_computes_pct_and_ticks():
    # 가격 10000원대는 krx_tick_size=10원(t0_forward_return.krx_tick_size 확인).
    prc = np.array([10000, 10000, 10020, 10020, 10010])
    qty = np.array([1, 2, 3, 4, 5])
    sec = np.array([0, 1, 2, 3, 4])

    out = _jumps_from_ticks(prc, qty, sec)

    # 0->1(diff 0, 스킵), 1->2(diff+20), 2->3(diff 0, 스킵), 3->4(diff-10) = 2건.
    assert len(out) == 2
    assert out.iloc[0]["jump_pct"] == pytest.approx(20 / 10000)
    assert out.iloc[0]["jump_ticks"] == pytest.approx(2.0)  # 20원 / 10원틱
    assert out.iloc[0]["qty"] == 2  # 점프 직전(인덱스1) 체결수량


def test_jumps_from_ticks_returns_none_when_all_flat_or_too_short():
    assert _jumps_from_ticks(np.array([100]), np.array([1]), np.array([0])) is None
    assert _jumps_from_ticks(np.array([100, 100, 100]), np.array([1, 1, 1]), np.array([0, 1, 2])) is None


def test_summarize_empty_series_returns_zero_n():
    assert summarize(pd.Series([], dtype=float)) == {"n": 0}


def test_summarize_computes_percentiles():
    s = pd.Series([1.0, 2.0, 3.0, 4.0])
    out = summarize(s)
    assert out["n"] == 4
    assert out["p50"] == pytest.approx(2.5)
