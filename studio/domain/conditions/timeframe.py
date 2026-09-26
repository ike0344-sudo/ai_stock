"""시간 단위 해석 — 설계 studio-conditions §3.2. **미래참조 차단의 핵심.**

분봉 실행(봉 끝 시각 t, 날짜 D)에서 피연산자마다 값을 어느 시간 단위로 볼지(`tf`):

  bar         실행 봉 그대로(기존 동작).
  m1..m60     N분봉으로 다시 묶은 뒤 그 위에서 지표를 계산하고, 봉 t 에는 **끝 시각 ≤ t 인 마지막 N분봉** 값(마감된 봉만)을 붙인다.
              묶기는 하루 단위(09:00 기준점의 N분 격자 — 차트와 같은 정의)이고 롤링 지표는 날을 넘어 이어진다(lead 결정 2026-09-26).
              N 은 실행 봉 길이의 배수이면서 더 긴 것만(검증 오류 문구는 validation.py).
  daily_prev  **오늘(D) 장 시작 전에 알 수 있는 일봉 값**(lead 판정 2026-09-26): 지표의 행 D 값이 봉 D 자료에 의존하지 않으면(현재 봉을 빼는 highest/lowest —
              카탈로그 `excludes_current`) **일봉 행 D**, 의존하면 **행 D−1**(날짜 < D 인 마지막 일봉 행 — `previous_day_values` 와 같은 규칙).
              그래서 `highest(n)`(기본 오늘 제외) = D−n..D−1 = "전일까지 n일 신고가". 행 D 가 일봉에 없으면(아직 일봉이 안 만들어진 날) NaN → 신호 없음.
  daily_live  키움 조건검색처럼 **오늘 일봉을 장중 값으로**: 과거 일봉(D−1까지) + 오늘 가상 봉(O=당일 첫 시가, H/L=t 까지 최고/최저, C=봉 t 종가,
              V·거래대금=t 까지 누적)으로 계산한 값. **카탈로그 `live=True` 지표만**(점화식이 O(1) — `LIVE_REGISTRY`).

`offset`(며칠·몇 봉 전)은 **그 피연산자 자신의 시간 단위**로 센다: `daily_prev` offset 1 = D−2 값, `m5` offset 1 = 직전 마감 5분봉 값,
`daily_live` offset k(≥1) = D−k 값(= daily_prev offset k−1).
모든 함수는 t 이후 입력을 보지 않는다 — 카나리아 C5(mN)·C6(daily_live)·C3 확장(daily_prev)이 검증한다.

## `daily_live` 계산 함수 작성법 (새 지표의 `ind_*.py` 가 `LIVE` dict 로 등록)
    def live_myind(live: LiveBars, params: dict) -> DataFrame     # index = live.index(봉 끝 시각), columns = live.codes
`live.o/h/l/c/v/val` 은 봉마다의 **오늘 가상 봉**, `live.prev(frame)` 은 일봉 표 frame 의 D−1 행을 봉마다 붙인 것(D−1 이 없으면 NaN),
`live.own(fn)` 은 거래정지 빈칸이 있는 종목을 자기 거래일 기준으로 계산하는 래퍼(indicators.own_days 와 같음). 예 SMA:
    S = live.own(lambda pn: getattr(pn, src).rolling(n - 1).sum())  →  (live.prev(S) + live.<src>) / n
검증 도구: `check_live_equals_recompute(name, params, daily, panel)` — 오늘 가상 봉을 일봉 끝에 붙여 일반 함수로 다시 계산한 값과 대조(C6).
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np
import pandas as pd

from .catalog import LIVE_REGISTRY, MINUTE_TIMEFRAMES, TIMEFRAMES
from .indicators import compute, own_days, own_shift

Frame = pd.DataFrame
TF_ALL = TIMEFRAMES
TF_MINUTES = MINUTE_TIMEFRAMES
_FIELDS = ("open", "high", "low", "close", "volume", "value")
SESSION_OPEN = pd.Timedelta(hours=9)


def tf_minutes(tf: str) -> int | None:
    return TF_MINUTES.get(tf)


# ----------------------------------------------------------------------------- 일봉 D−1 정렬
def prev_day_positions(daily_index: pd.DatetimeIndex, bar_index: pd.DatetimeIndex) -> np.ndarray:
    """각 봉의 날짜 D 에 대해 daily_index 안 D **미만** 마지막 위치(없으면 −1) — D 행은 있어도 절대 안 본다."""
    return daily_index.searchsorted(bar_index.normalize().to_numpy(), side="left") - 1


def take_rows(frame: Frame, pos: np.ndarray, index: pd.DatetimeIndex, columns) -> Frame:
    """frame(일봉 표)의 pos 행을 봉마다 붙인다. pos<0 이면 NaN. 없는 종목 열은 NaN."""
    cols = list(columns)
    arr = frame.reindex(columns=cols).to_numpy(dtype=float)
    out = np.full((len(index), len(cols)), np.nan)
    ok = pos >= 0
    out[ok] = arr[pos[ok]]
    return pd.DataFrame(out, index=index, columns=cols)


# ----------------------------------------------------------------------------- daily_live
@dataclass(frozen=True, eq=False)
class LiveBars:
    """분봉 t 마다의 '오늘 가상 일봉' — daily_live 계산 함수의 입력."""

    index: pd.DatetimeIndex  # 봉 끝 시각(실행 봉)
    codes: list
    daily: Any  # 실제 일봉 Panel(덕 타이핑 open..prev_close) — D−1 까지만 쓴다(D 행이 있어도 위치 계산이 D 미만만 고른다)
    prev_pos: np.ndarray  # 봉마다 D−1 의 daily 행 위치(없으면 −1)
    o: Frame  # 당일 첫 봉 시가(첫 봉이 정해진 뒤에만 값)
    h: Frame  # t 까지 당일 최고가
    l: Frame  # t 까지 당일 최저가
    c: Frame  # 봉 t 종가
    v: Frame  # t 까지 당일 누적 거래량
    val: Frame  # t 까지 당일 누적 거래대금(봉별 value 의 합 — 분봉 value 근사와 같은 정의)

    def prev(self, frame: Frame) -> Frame:
        return take_rows(frame, self.prev_pos, self.index, self.codes)

    def own(self, fn: Callable[[Any], Frame]) -> Frame:
        return own_days(self.daily, fn)

    def field(self, name: str) -> Frame:
        return getattr(self, LIVE_FIELD[name])


LIVE_FIELD = {"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v", "value": "val"}


def make_live_bars(panel: Any, daily: Any) -> LiveBars:
    """분봉 Panel + 일봉 Panel → LiveBars. 당일 값은 **t 까지의 봉만**으로 만든다(날짜별 누적 — 미래 봉 미참조)."""
    days = panel.close.index.normalize()
    codes = list(panel.close.columns)
    seen = panel.open.notna().groupby(days).cummax().astype(bool)  # 그 날 첫 non-NaN 시가가 나온 뒤
    first_open = panel.open.groupby(days).transform("first").where(seen)  # 그 날 첫 non-NaN 시가(이후 봉에서만 노출)
    h = panel.high.groupby(days).cummax()
    lo = panel.low.groupby(days).cummin()
    return LiveBars(
        index=panel.close.index, codes=codes, daily=daily,
        prev_pos=prev_day_positions(daily.close.index, panel.close.index),
        o=first_open, h=h, l=lo, c=panel.close,
        v=panel.volume.fillna(0).groupby(days).cumsum().where(seen),
        val=panel.value.fillna(0).groupby(days).cumsum().where(seen),
    )


# ----------------------------------------------------------------------------- N분봉 묶기 (mN)
@dataclass(frozen=True, eq=False)
class Resampled:
    """실행 분봉을 N분봉으로 묶은 결과 — 봉 끝 라벨 기준."""

    panel: Any  # 덕 타이핑 Panel(open..value, prev_close): index = N분봉 끝 시각
    ends: pd.DatetimeIndex  # 묶음 끝 시각(= panel.close.index, 시간순)


def resample_bars(panel: Any, n_minutes: int, bar_minutes: int) -> Resampled:
    """하루 단위로 09:00 기준 N분 격자에 묶는다 — open 첫값·high 최대·low 최소·close 끝값·volume/value 합(체결 없는 봉은 건너뜀).
    묶음의 끝 라벨 = 격자 시작 + N분. 그 묶음은 **끝 라벨 시각의 실행 봉이 끝나야 마감**된다 — `asof_positions` 가 마감된 것만 고른다."""
    if n_minutes % bar_minutes or n_minutes <= bar_minutes:
        raise ValueError(f"{n_minutes}분봉은 실행 봉({bar_minutes}분)의 배수이면서 더 긴 것만 쓸 수 있다")
    idx = panel.close.index
    start = idx - pd.Timedelta(minutes=bar_minutes)
    days = idx.normalize()
    bucket = ((start - days - SESSION_OPEN) // pd.Timedelta(minutes=n_minutes)).to_numpy()
    keys = [days.to_numpy(), bucket]

    def agg(frame: Frame, how: str) -> Frame:
        g = frame.groupby(keys, sort=True)
        return {"first": g.first, "max": g.max, "min": g.min, "last": g.last}[how]() if how != "sum" else g.sum(min_count=1)

    o, h, lo, c = agg(panel.open, "first"), agg(panel.high, "max"), agg(panel.low, "min"), agg(panel.close, "last")
    v, val = agg(panel.volume, "sum"), agg(panel.value, "sum")
    prev = panel.prev_close.groupby(keys, sort=True).last()
    lv = o.index.get_level_values
    ends = pd.DatetimeIndex(pd.to_datetime(lv(0)) + SESSION_OPEN + (np.asarray(lv(1)) + 1) * pd.Timedelta(minutes=n_minutes))
    for f in (o, h, lo, c, v, val, prev):
        f.index = ends
    ns = SimpleNamespace(open=o, high=h, low=lo, close=c, volume=v, value=val, prev_close=prev)
    return Resampled(ns, ends)


def asof_positions(bucket_ends: pd.DatetimeIndex, bar_index: pd.DatetimeIndex) -> np.ndarray:
    """각 실행 봉 t 에 대해 **끝 시각 ≤ t 인 마지막 묶음**의 위치(없으면 −1)."""
    return bucket_ends.searchsorted(bar_index.to_numpy(), side="right") - 1


def map_asof(frame: Frame, ends: pd.DatetimeIndex, bar_index: pd.DatetimeIndex, columns) -> Frame:
    return take_rows(frame, asof_positions(ends, bar_index), bar_index, columns)


# ----------------------------------------------------------------------------- 평가기가 쓰는 맥락
class TimeContext:
    """한 번의 평가에서 시간 단위별 준비물(묶은 분봉·가상 오늘 봉)과 지표 memo 를 한 번씩만 만든다."""

    def __init__(self, panel: Any, daily: Any | None, bar_minutes: int | None) -> None:
        self.panel, self.daily, self.bar_minutes = panel, daily, bar_minutes
        self._resampled: dict[int, Resampled] = {}
        self._live: LiveBars | None = None
        self._memos: dict[str, dict] = {}
        self._prev: np.ndarray | None = None
        self._same: np.ndarray | None = None

    def need_daily(self, tf: str) -> Any:
        if self.daily is None:
            raise ValueError(f"시간 단위 '{tf}' 는 일봉 자료가 필요하다 — 이 실행 모드에선 쓸 수 없다(분봉 모드에서만)")
        return self.daily

    def memo(self, tf: str) -> dict:
        return self._memos.setdefault(tf, {})

    def resampled(self, tf: str) -> Resampled:
        n = TF_MINUTES[tf]
        if self.bar_minutes is None:
            raise ValueError(f"시간 단위 '{tf}' 는 분봉 실행에서만 쓸 수 있다")
        if n not in self._resampled:
            self._resampled[n] = resample_bars(self.panel, n, self.bar_minutes)
        return self._resampled[n]

    def live(self) -> LiveBars:
        if self._live is None:
            self._live = make_live_bars(self.panel, self.need_daily("daily_live"))
        return self._live

    def same_pos(self) -> np.ndarray:
        """봉의 날짜 D 와 같은 날짜의 일봉 행 위치(없으면 −1) — `excludes_current` 지표 전용(그 행 값은 봉 D 자료를 안 쓴다)."""
        if self._same is None:
            di = self.need_daily("daily_prev").close.index
            days = self.panel.close.index.normalize().to_numpy()
            p = di.searchsorted(days, side="left")
            ok = (p < len(di)) & (di.to_numpy()[np.minimum(p, len(di) - 1)] == days)
            self._same = np.where(ok, p, -1)
        return self._same

    def prev_pos(self) -> np.ndarray:
        if self._prev is None:
            self._prev = prev_day_positions(self.need_daily("daily_prev").close.index, self.panel.close.index)
        return self._prev


# ----------------------------------------------------------------------------- 검증 도구 (C6 / 지표 단위 테스트용)
def check_live_equals_recompute(name: str, params: dict[str, Any], daily: Any, panel: Any, *, sample: int = 40,
                                seed: int = 0) -> float:
    """`LIVE_REGISTRY[name]` 값 vs "오늘 가상 봉을 일봉 끝에 붙여 일반 함수로 다시 계산한 값" — 표본 (봉, 종목) 의 최대 절대 오차.
    가상 봉 = `make_live_bars` 의 o/h/l/c/v/val (미래 봉 미참조), 붙이는 행 날짜 = 그 봉의 날짜 D, 일봉은 D 미만 행만 사용."""
    from .catalog import resolve_params
    p = resolve_params(name, params)
    live = make_live_bars(panel, daily)
    val = LIVE_REGISTRY[name](live, p)
    rng = np.random.default_rng(seed)
    n_bars = len(live.index)
    worst = 0.0
    checked = 0
    for i in rng.permutation(n_bars):
        if checked >= sample:
            break
        pos = int(live.prev_pos[i])
        if pos < 0:
            continue
        day = live.index[i].normalize()
        for code in live.codes:
            v = val.iloc[i][code]
            if code not in daily.close.columns:
                continue
            row = {f: float(getattr(live, LIVE_FIELD[f]).iloc[i][code]) for f in _FIELDS}
            if any(np.isnan(x) for x in row.values()):
                continue
            hist = {f: getattr(daily, f).iloc[: pos + 1][[code]] for f in ("open", "high", "low", "close", "volume", "value", "prev_close")}
            virt = SimpleNamespace(**{
                f: pd.concat([hist[f], pd.DataFrame({code: [row[f] if f in row else hist["close"][code].iloc[-1]]}, index=[day])])
                for f in hist
            })
            virt.prev_close = pd.concat([hist["prev_close"], pd.DataFrame({code: [hist["close"][code].iloc[-1]]}, index=[day])])
            ref = compute(virt, name, p)[code].iloc[-1]
            if np.isnan(ref) and np.isnan(v):
                checked += 1
                continue
            worst = max(worst, abs(float(ref) - float(v))) if not (np.isnan(ref) or np.isnan(v)) else float("inf")
            checked += 1
            break
    return worst


# 내장 지표의 daily_live 계산 함수 등록(catalog._META 에서 live=True 인 것과 1:1)
from . import live_builtin  # noqa: E402,F401  (import 시 LIVE_REGISTRY 를 채운다)
