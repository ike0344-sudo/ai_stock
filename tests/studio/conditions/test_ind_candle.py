"""분류 "캔들" — 봉 하나(또는 직전 봉과의 관계)의 모양을 손계산으로."""
import numpy as np

from tests.studio.conditions.ind_helpers import mk, nan_eq, val

nan = np.nan


def test_body_and_range_pct():
    nan_eq(val(mk([105, 95], o=[100, 100]), "body_pct"), [5, -5])
    nan_eq(val(mk([105], o=[100], h=[110], l=[100], prev=[100]), "range_pct"), [10])


def test_wick_ratios_same_for_bull_and_bear_and_nan_when_no_range():
    bull = mk([12], o=[10], h=[15], l=[8])
    bear = mk([10], o=[12], h=[15], l=[8])
    for p in (bull, bear):
        nan_eq(val(p, "upper_wick_ratio"), [3 / 7])                  # (15 − 12) ÷ 7
        nan_eq(val(p, "lower_wick_ratio"), [2 / 7])                  # (10 − 8) ÷ 7
    flat = mk([10], o=[10], h=[10], l=[10])
    nan_eq(val(flat, "upper_wick_ratio"), [nan])


def test_long_bull_and_long_bear_use_min_body_pct():
    p = mk([106, 104, 94, 100], o=[100, 100, 100, 100])
    nan_eq(val(p, "long_bull", min_body_pct=5.0), [1, 0, 0, 0])
    nan_eq(val(p, "long_bear", min_body_pct=5.0), [0, 0, 1, 0])
    nan_eq(val(p, "long_bull", min_body_pct=3.0), [1, 1, 0, 0])


def test_doji_needs_a_range():
    p = mk([100.5, 103, 100], o=[100, 100, 100], h=[105, 105, 100], l=[95, 95, 100])
    nan_eq(val(p, "doji", max_body_ratio=0.1), [1, 0, 0])            # 0.05 ≤ 0.1 / 0.3 / 봉 길이 0 이면 0


def test_hammer_and_inverted_hammer():
    p = mk([11, 11, 9], o=[10, 10, 10], h=[11, 13, 15], l=[6, 6, 9])
    nan_eq(val(p, "hammer"), [1, 0, 0])                               # 아랫꼬리 4 ≥ 2×몸통 1, 윗꼬리 0 / 윗꼬리 2 가 커서 탈락 / 아랫꼬리 0
    nan_eq(val(p, "inverted_hammer"), [0, 0, 1])                      # 세 번째: 윗꼬리 5 ≥ 2×1, 아랫꼬리 0


def test_engulfing_patterns():
    bull = mk([8, 10.5], o=[10, 7.5])                                 # 음봉 뒤 그것을 감싼 양봉
    nan_eq(val(bull, "bull_engulfing"), [nan, 1])
    nan_eq(val(mk([8, 9.5], o=[10, 7.5]), "bull_engulfing"), [nan, 0])  # 종가가 직전 시가(10)에 못 미침
    bear = mk([10, 7.5], o=[8, 10.5])
    nan_eq(val(bear, "bear_engulfing"), [nan, 1])
    nan_eq(val(bear, "bull_engulfing"), [nan, 0])


def test_inside_and_outside_bar():
    p = mk([1, 1, 1], h=[10, 9, 12], l=[5, 6, 4])
    nan_eq(val(p, "inside_bar"), [nan, 1, 0])
    nan_eq(val(p, "outside_bar"), [nan, 0, 1])


def test_gap_held_and_filled():
    p = mk([102, 102, 100.2, 102], o=[102, 102, 100.2, 102], l=[101, 99, 100, 101], prev=[100] * 4)
    nan_eq(val(p, "gap_held", min_gap_pct=0.5), [1, 0, 0, 1])
    nan_eq(val(p, "gap_filled", min_gap_pct=0.5), [0, 1, 0, 0])       # 세 번째는 갭이 0.2% 라 둘 다 0
