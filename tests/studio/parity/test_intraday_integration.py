"""통합 스모크 — data-agent 로더(`intraday_data`) 산출물을 조건식(분봉 지표·틱 조건)이 실제로 받아 먹는다.

로더의 계약 모양(분봉 Panel: index=봉 끝 시각, prev_close=D−1, value=종가×거래량 / TickDay)을 조건식 쪽에서 다시 확인.
실데이터(분봉 보관소·체결 파일)가 없거나 기간을 못 덮으면 skip — `@pytest.mark.parity`.
"""
import datetime as dt

import numpy as np
import pytest

from studio.domain.conditions.ast import Group
from studio.domain.conditions.evaluator import evaluate_group
from studio.domain.conditions.indicators import compute
from studio.domain.conditions.intraday import is_intraday
from studio.domain.conditions.tick import detect_signals
from studio.infrastructure import intraday_data as I
from tests.studio.conditions.helpers import cond, const, field, group, ind

D = dt.date


@pytest.fixture(scope="module")
def panel():
    try:
        p = I.load_minute_panel_wide(["005930", "000660"], D(2026, 9, 22), D(2026, 9, 23), 5)
    except Exception as e:  # 보관소 없음·범위 밖
        pytest.skip(f"분봉 보관소를 못 읽음: {e}")
    if len(p.close) == 0:
        pytest.skip("요청 기간 분봉 없음")
    return p


@pytest.mark.parity
def test_loader_panel_is_recognised_as_intraday_and_time_is_bar_end(panel):
    assert is_intraday(panel)
    t = compute(panel, "time")
    first = t.iloc[0].dropna()
    assert len(first) and (first == 905.0).all()  # 09:00 시작 봉의 끝 = 09:05 (로더가 시작+bar_minutes 로 라벨)
    assert not hasattr(panel, "bar_end_offset_minutes")  # 로더가 이미 봉 끝으로 옮겼으니 보정 불필요


@pytest.mark.parity
def test_cum_value_and_vwap_reset_on_new_day_and_stay_inside_close_range(panel):
    cv, vw = compute(panel, "cum_value"), compute(panel, "vwap")
    days = panel.close.index.normalize()
    d2 = days.unique()[-1]
    first2 = np.flatnonzero(days == d2)[0]
    code = panel.close.columns[0]
    assert cv.iloc[first2][code] == np.nan_to_num(panel.value.iloc[first2][code])   # 날이 바뀌면 그 봉 값부터
    day2 = panel.close[days == d2][code].dropna()
    assert day2.min() - 1e-9 <= vw[days == d2][code].dropna().iloc[-1] <= day2.max() + 1e-9  # 종가 가중평균이라 범위 안


@pytest.mark.parity
def test_evaluator_runs_on_loader_panel_and_masks_empty_bars(panel):
    g = Group.model_validate(group("all", cond(ind("time"), "gte", const(910)), cond(field("close"), "gt", ind("vwap")),
                                   cond(ind("gap_pct"), "gt", const(-100))))
    r = evaluate_group(g, panel)
    assert r.shape == panel.close.shape and r.dtypes.eq(bool).all()
    assert not (r & panel.close.isna()).to_numpy().any()  # 체결 없는 봉은 신호 없음


@pytest.mark.parity
def test_tick_loader_day_feeds_detect_signals_with_strict_entry():
    try:
        td = I.load_tick_day("001380", D(2026, 9, 23))
    except Exception as e:
        pytest.skip(f"체결 파일을 못 읽음: {e}")
    if td is None:
        pytest.skip("정규장 체결 없음")
    ev = detect_signals(td, breakout_min=1, cooldown_sec=60)
    assert (ev.entry_sec > ev.signal_sec).all()
    assert np.array_equal(ev.entry_price, td.prc.astype(float)[ev.entry_idx])
