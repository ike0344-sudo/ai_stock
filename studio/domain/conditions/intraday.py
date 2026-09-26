"""분봉 전용 지표 — 설계서 §3.7 (`day_change_pct`·`time`·`cum_value`·`vwap`, 분봉의 `gap_pct`).

입력은 일봉 때와 같은 Panel 덕 타이핑이지만 **index = 봉 시각(여러 날), columns = 종목코드**.
- 봉 시각은 **봉 끝** 이 규약이다. 로더가 봉 시작 시각으로 라벨을 붙였다면 Panel 에
  `bar_end_offset_minutes`(봉 길이)를 달아 준다 — `time` 이 그만큼 더해 읽는다.
- `prev_close` = 그 날의 **전일 종가**(하루 안에서 상수).
- 당일 누적 지표는 **날이 바뀌면 0부터**(날짜별 groupby). t 까지의 봉만 쓴다.
- 일봉을 분봉에 쓸 때는 D−1 값만(`prefilter.py`) — 당일 일봉은 장중에 모르는 값이다.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

Frame = pd.DataFrame
INTRADAY_ONLY = ("day_change_pct", "time", "cum_value", "vwap")


def day_keys(panel: Any) -> pd.DatetimeIndex:
    return panel.close.index.normalize()


def is_intraday(panel: Any) -> bool:
    """같은 날짜가 여러 행이면 분봉 표(일봉은 하루 한 행)."""
    return not day_keys(panel).is_unique


def _broadcast(v: np.ndarray, panel: Any) -> Frame:
    idx, cols = panel.close.index, panel.close.columns
    return pd.DataFrame(np.repeat(v[:, None], len(cols), axis=1), index=idx, columns=cols)


def hhmm(panel: Any) -> Frame:
    off = int(getattr(panel, "bar_end_offset_minutes", 0))
    ts = panel.close.index + pd.Timedelta(minutes=off)
    return _broadcast((ts.hour * 100 + ts.minute).to_numpy(dtype=float), panel)


def cum_value(panel: Any) -> Frame:
    """당일 누적 거래대금. 빠진 봉은 0 으로 더한다(그 봉 자체의 신호는 evaluator 가 close NaN 으로 막음)."""
    return panel.value.fillna(0).groupby(day_keys(panel)).cumsum()


def vwap(panel: Any) -> Frame:
    days = day_keys(panel)
    cv = panel.value.fillna(0).groupby(days).cumsum()
    cvol = panel.volume.fillna(0).groupby(days).cumsum()
    return cv / cvol.where(cvol > 0)


def day_change_pct(panel: Any) -> Frame:
    return (panel.close / panel.prev_close - 1) * 100


def gap_pct(panel: Any) -> Frame:
    """(당일 첫 봉 시가 ÷ 전일 종가 − 1)×100 — 첫 봉 이후엔 그 날 내내 같은 값(t 시점에 이미 아는 값)."""
    day_open = panel.open.groupby(day_keys(panel)).transform("first")  # 그 날 첫 non-null 시가
    return (day_open / panel.prev_close - 1) * 100


def _prev_rows(daily_index: pd.DatetimeIndex, bar_index: pd.DatetimeIndex) -> np.ndarray:
    """각 봉의 날짜 D 에 대해 daily_index 안 D **미만** 마지막 위치(없으면 −1)."""
    return daily_index.searchsorted(bar_index.normalize().to_numpy(), side="left") - 1


def previous_day_flags(daily_flags: Frame, bar_index: pd.DatetimeIndex, codes: Any) -> Frame:
    """일봉 bool 표 → 분봉 표(index=봉 시각, columns=codes). D−1 값을 그 날 전 봉에 붙임. 없는 종목·날은 False."""
    codes = list(codes)
    arr = daily_flags.reindex(columns=codes, fill_value=False).to_numpy(dtype=bool)
    pos = _prev_rows(daily_flags.index, bar_index)
    out = np.zeros((len(bar_index), len(codes)), dtype=bool)
    ok = pos >= 0
    out[ok] = arr[pos[ok]]
    return pd.DataFrame(out, index=bar_index, columns=codes)


def previous_day_values(daily_values: Frame, bar_index: pd.DatetimeIndex, codes: Any) -> Frame:
    """일봉 수치 표 → 분봉 표. D−1 값, 없으면 NaN."""
    codes = list(codes)
    arr = daily_values.reindex(columns=codes).to_numpy(dtype=float)
    pos = _prev_rows(daily_values.index, bar_index)
    out = np.full((len(bar_index), len(codes)), np.nan)
    ok = pos >= 0
    out[ok] = arr[pos[ok]]
    return pd.DataFrame(out, index=bar_index, columns=codes)


def compute_intraday(panel: Any, name: str) -> Frame:
    if not is_intraday(panel):
        raise ValueError(f"'{name}' 은 분봉 전용 — 날짜가 여러 개인 봉 표에서만 계산됨(일봉 표엔 쓸 수 없음)")
    if name == "time":
        return hhmm(panel)
    if name == "cum_value":
        return cum_value(panel)
    if name == "vwap":
        return vwap(panel)
    if name == "day_change_pct":
        return day_change_pct(panel)
    if name == "gap_pct":
        return gap_pct(panel)
    raise NotImplementedError(name)
