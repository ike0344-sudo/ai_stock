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
INTRADAY_ONLY = (
    "day_change_pct", "time", "cum_value", "vwap",
    "open_change_pct", "day_high_break", "day_low_break", "minutes_since_open", "first_n_value", "vwap_disparity",
    "cum_value_rank",
)
SESSION_OPEN_MIN = 9 * 60  # 정규장 시작(분) — minutes_since_open·first_n_value 의 0 점


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


def _end_minutes(panel: Any) -> np.ndarray:
    """봉 끝 시각의 하루 중 분(09:05 → 545). `time` 과 같은 규약(bar_end_offset_minutes)."""
    off = int(getattr(panel, "bar_end_offset_minutes", 0))
    ts = panel.close.index + pd.Timedelta(minutes=off)
    return (ts.hour * 60 + ts.minute).to_numpy(dtype=float)


def _bar_minutes(panel: Any) -> int:
    """봉 길이(분) — 같은 날 안 인접 봉 끝 시각 차이의 최빈값(봉이 한 개뿐이면 1)."""
    m = _end_minutes(panel)
    same = day_keys(panel)[1:] == day_keys(panel)[:-1]
    d = np.diff(m)[same]
    d = d[d > 0]
    return int(pd.Series(d).mode().iloc[0]) if len(d) else 1


def open_change_pct(panel: Any) -> Frame:
    """(C_t ÷ 당일 시가 − 1)×100. 당일 시가 = 그 날 첫 봉 시가 — 그 봉 이전엔 값 없음(t 까지만 씀)."""
    days = day_keys(panel)
    day_open = panel.open.groupby(days).transform("first")
    seen = panel.open.notna().groupby(days).cummax().astype(bool)  # 첫 봉 이전 행에 미래 시가가 새지 않게
    return ((panel.close / day_open - 1) * 100).where(seen)


def _prior_extreme(x: Frame, days: pd.DatetimeIndex, high: bool) -> Frame:
    """t 봉 **앞** 봉들의 당일 최고/최저 — 첫 봉은 값 없음. 빠진 봉은 건너뛰고 이어 붙인다."""
    g = x.groupby(days)
    run = (g.cummax() if high else g.cummin()).groupby(days).ffill()
    return run.groupby(days).shift(1)


def day_break(panel: Any, src: str, high: bool) -> Frame:
    """t 봉의 src(high/close 또는 low/close)가 당일 앞 봉들의 최고(최저)를 넘으면 1, 아니면 0. 첫 봉·빈 봉은 값 없음."""
    days = day_keys(panel)
    if src == "close":
        x = panel.close
    else:
        x = panel.high if high else panel.low
    ref = _prior_extreme(panel.high if high else panel.low, days, high)
    hit = (x > ref) if high else (x < ref)
    return hit.astype(float).where(ref.notna() & x.notna())


def minutes_since_open(panel: Any) -> Frame:
    """09:00 부터 봉 끝까지 경과 분(장 전 봉은 음수)."""
    return _broadcast(_end_minutes(panel) - SESSION_OPEN_MIN, panel)


def first_n_value(panel: Any, n: int) -> Frame:
    """장 시작 후 n분(09:00 < 봉 끝 ≤ 09:00+n) 누적 거래대금 — n분이 지난 봉부터 값이 있고 그 날은 계속 같은 값.
    봉 길이가 n 을 나누지 못하면(예: 5분봉에 n=3) 창이 봉 경계에 안 맞아 오류."""
    bm = _bar_minutes(panel)
    if n % bm:
        raise ValueError(f"first_n_value: n={n}분이 봉 길이 {bm}분의 배수가 아님")
    end = _end_minutes(panel)
    inside = _broadcast(((end > SESSION_OPEN_MIN) & (end <= SESSION_OPEN_MIN + n)).astype(float), panel).astype(bool)
    done = _broadcast((end >= SESSION_OPEN_MIN + n).astype(float), panel).astype(bool)
    v = panel.value.fillna(0).where(inside, 0.0)
    return v.groupby(day_keys(panel)).cumsum().where(done)


def vwap_disparity(panel: Any) -> Frame:
    return (panel.close / vwap(panel) - 1) * 100


def cum_value_rank(panel: Any) -> Frame:
    """t 시점 유니버스(표의 열) 안 당일 누적 거래대금 순위(1=최대). 같은 시각 다른 종목 값만 쓴다 — 미래 봉 안 봄."""
    return cum_value(panel).rank(axis=1, ascending=False, method="min")


def compute_intraday(panel: Any, name: str, params: dict[str, Any] | None = None) -> Frame:
    p = params or {}
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
    if name == "open_change_pct":
        return open_change_pct(panel)
    if name in ("day_high_break", "day_low_break"):
        return day_break(panel, p.get("src", "close"), name == "day_high_break")
    if name == "minutes_since_open":
        return minutes_since_open(panel)
    if name == "first_n_value":
        return first_n_value(panel, int(p.get("n", 5)))
    if name == "vwap_disparity":
        return vwap_disparity(panel)
    if name == "cum_value_rank":
        return cum_value_rank(panel)
    raise NotImplementedError(name)
