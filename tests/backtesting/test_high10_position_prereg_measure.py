import numpy as np
import pandas as pd
import pytest

from backtesting.high10_position_prereg_measure import (
    _assign_bin,
    _concentration_flag,
    _direction_ok,
    add_derived,
    add_features,
)


def test_add_features_breakout_when_close_exceeds_prior_10d_high():
    # 앞 10일 high=110 고정, 11번째날 close=115 -> ratio>1.0 -> breakout
    highs = [110] * 10 + [110]
    closes = [100] * 10 + [115]
    df = pd.DataFrame({
        "code": ["A"] * 11,
        "date": [f"2026-01-{i:02d}" for i in range(1, 12)],
        "open": closes, "high": highs, "low": [90] * 11, "close": closes,
    })

    out = add_features(df)

    assert out.loc[10, "high10"] == pytest.approx(110)
    assert out.loc[10, "ratio"] == pytest.approx(115 / 110)
    assert out.loc[10, "bin"] == "breakout"
    # 10일 미만 이력은 신호 없음(NaN)
    assert pd.isna(out.loc[5, "bin"])


def test_assign_bin_boundaries_are_inclusive_lower_bound():
    ratio = pd.Series([1.0, 0.999, 0.95, 0.9499, 0.5, np.nan])

    out = _assign_bin(ratio, near_band=0.95)

    assert list(out)[:5] == ["breakout", "near", "near", "far", "far"]
    assert pd.isna(out.iloc[5])


def test_add_derived_gap_total_intraday_identity():
    df = pd.DataFrame({
        "date": ["2026-01-01"],
        "breakout_total": [0.10], "breakout_intraday": [0.05],
        "universe_total": [0.02], "universe_intraday": [0.01],
    })

    out = add_derived(df, bins=("breakout",))

    # 텔레스코핑 항등식: (1+total) == (1+intraday)*(1+gap)
    assert (1 + out.loc[0, "breakout_total"]) == pytest.approx(
        (1 + out.loc[0, "breakout_intraday"]) * (1 + out.loc[0, "breakout_gap"])
    )
    assert out.loc[0, "breakout_total_net"] == pytest.approx(0.10 - 0.0052)
    assert out.loc[0, "breakout_excess_total"] == pytest.approx(0.10 - 0.02)


def test_direction_ok_positive_and_negative():
    assert _direction_ok(0.01, 2.0, "positive") is True
    assert _direction_ok(0.01, 1.0, "positive") is False  # t 미달
    assert _direction_ok(-0.01, 1.0, "positive") is False  # 부호 다름
    assert _direction_ok(-0.01, -2.0, "negative") is True
    assert _direction_ok(np.nan, np.nan, "positive") is False


def test_concentration_flag_detects_top5_dominance():
    # 상위 5개(값 10짜리)가 합계의 대부분을 차지하는 극단 사례
    values = np.array([10.0] * 5 + [0.01] * 20)

    flagged, desc = _concentration_flag(values, "positive")

    assert bool(flagged) is True
    assert "%" in desc


def test_concentration_flag_not_applicable_when_sign_mismatches_direction():
    values = np.array([-1.0, -1.0, -1.0])  # 전체합 음수인데 방향은 positive

    flagged, desc = _concentration_flag(values, "positive")

    assert flagged is False
    assert "부호불일치" in desc
