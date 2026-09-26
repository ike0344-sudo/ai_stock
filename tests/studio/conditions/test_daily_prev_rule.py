"""daily_prev = "오늘(D) 장 시작 전에 알 수 있는 값"(lead 판정 2026-09-26) — 현재 봉을 빼는 지표(highest/lowest 기본)는 일봉 행 D, 나머지는 행 D−1.

표시한 지표(`catalog.excludes_current`)마다 카나리아: **봉 D 의 일봉 행을 변조해도 그날 daily_prev 값은 불변**(틀린 표시 = 미래참조).
"""
import numpy as np
import pandas as pd
import pytest

from studio.domain.conditions.catalog import _EXCLUDES_CURRENT, excludes_current
from studio.domain.conditions.evaluator import evaluate_group
from studio.domain.models import Panel

from .test_c1_operators_and_timeframes import F, I, cond, grp
from .test_timeframe import BAR, make_data

CASES = [("highest", {"src": "high", "n": 20}), ("lowest", {"src": "low", "n": 10}),
         ("highest", {"src": "close", "n": 5}), ("lowest", {"src": "close", "n": 7})]


def test_flag_only_where_the_current_bar_is_excluded():
    assert excludes_current("highest", {"src": "high", "n": 20}) and excludes_current("lowest", {"src": "low", "n": 5})
    assert not excludes_current("highest", {"src": "high", "n": 20, "include_current": True})
    assert not excludes_current("sma", {"n": 20}) and not excludes_current("rsi", {"n": 14})
    assert set(_EXCLUDES_CURRENT) == {"highest", "lowest"}  # 새로 표시하려면 이 테스트에 카나리아 사례부터 추가


def _frame(daily, minute, name, params, tf="daily_prev"):
    """피연산자 값 표 그대로(비교 없이) — 평가기의 시간 단위 층을 직접 읽는다."""
    from studio.domain.conditions.ast import IndOperand
    from studio.domain.conditions.evaluator import _operand
    from studio.domain.conditions.timeframe import TimeContext
    return _operand(IndOperand.model_validate(I(name, params, tf=tf)), minute, None, [], None, TimeContext(minute, daily, BAR))


@pytest.mark.parametrize("name,params", CASES)
def test_canary_tampering_bar_D_daily_row_never_changes_that_days_daily_prev_value(name, params):
    daily, minute = make_data(n_hist=60, n_min_days=4)
    base = _frame(daily, minute, name, params)
    d_last = minute.close.index[-1].normalize()
    bad = Panel(*(getattr(daily, k).copy() for k in ("open", "high", "low", "close", "volume", "value", "prev_close")))
    for k in ("open", "high", "low", "close", "volume", "value", "prev_close"):
        x = getattr(bad, k)
        x.loc[x.index >= d_last] = x.loc[x.index >= d_last] * 10  # 마지막 날(D) 일봉 행을 통째로 변조
    got = _frame(bad, minute, name, params)
    on_last = base.index.normalize() == d_last
    assert on_last.any() and base[on_last].notna().to_numpy().all()
    pd.testing.assert_frame_equal(got[on_last], base[on_last])  # D 의 값은 그대로
    # 카나리아가 살아 있다: 변조가 D+1 이후 값에 영향을 주는 경우(여기선 마지막 날이 D 라 대신 "D−1 행 변조 → D 값이 바뀐다")
    d_prev = daily.close.index[daily.close.index.get_loc(d_last) - 1]
    changed = False
    for f in (10.0, 0.1):  # 최고가는 키우고 최저가는 줄여야 값이 움직인다
        bad2 = Panel(*(getattr(daily, k).copy() for k in ("open", "high", "low", "close", "volume", "value", "prev_close")))
        for k in ("open", "high", "low", "close", "volume", "value", "prev_close"):
            getattr(bad2, k).loc[d_prev] = getattr(bad2, k).loc[d_prev] * f
        changed |= not _frame(bad2, minute, name, params)[on_last].equals(base[on_last])
    assert changed


@pytest.mark.parametrize("name,src,n", [("highest", "high", 20), ("lowest", "low", 10)])
def test_three_spellings_of_previous_n_day_extreme_are_equal(name, src, n):
    daily, minute = make_data(n_hist=60, n_min_days=4)
    a = _frame(daily, minute, name, {"src": src, "n": n}, "daily_prev")                       # D.HIGHEST(H,n)
    b = _frame(daily, minute, name, {"src": src, "n": n, "include_current": True}, "daily_prev")  # D.HIGHEST(H,n,TRUE) = 행 D−1 의 포함 창
    c = _frame(daily, minute, name, {"src": src, "n": n}, "daily_live")                       # DL.HIGHEST(H,n)
    pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_frame_equal(a, c)
    # 손계산: 마지막 날 값 = 그 전 n 개 일봉의 최대/최소
    d_last = minute.close.index[-1].normalize()
    pos = daily.close.index.get_loc(d_last)
    hand = getattr(daily, src).iloc[pos - n: pos]
    exp = hand.max() if name == "highest" else hand.min()
    last = a[a.index.normalize() == d_last].iloc[0]
    assert np.allclose(last.to_numpy(), exp.reindex(last.index).to_numpy())


def test_missing_daily_row_for_the_day_gives_nan_not_a_stale_value():
    daily, minute = make_data(n_hist=60, n_min_days=4)
    d_last = minute.close.index[-1].normalize()
    # 마지막 날의 일봉 행이 아직 없으면(분봉이 일봉보다 앞선 날) 그 날은 값 없음(NaN) → 신호 없음 — 조용히 낡은 값을 쓰지 않는다
    short = Panel(*(getattr(daily, k).loc[daily.close.index < d_last] for k in ("open", "high", "low", "close", "volume", "value", "prev_close")))
    got = _frame(short, minute, "highest", {"src": "high", "n": 20})
    assert got[got.index.normalize() == d_last].isna().to_numpy().all()
