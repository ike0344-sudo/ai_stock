"""분류별 지표 모듈(`ind_trend`·`ind_oscillator`·`ind_candle`)이 같이 쓰는 작은 벡터 도구 — numpy·pandas 만.

catalog·indicators 를 import 하지 않는다(순환 방지). 전부 넓은 표(index=시각, columns=종목) 연산이고
**t 까지의 값만** 쓴다. 롤링 창은 현재 봉 포함이 기본(`hh`/`ll`) — 돌파용(t 제외)은 호출하는 쪽이 shift(1).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

Frame = pd.DataFrame


def sma(x: Frame, n: int) -> Frame:
    return x.rolling(n).mean()


def ema(x: Frame, n: int) -> Frame:
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def rma(x: Frame, n: int) -> Frame:
    """와일더 평활(α=1/n, 초기값=첫 유효값) — 기존 `rsi_wilder` 와 같은 방식."""
    return x.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def hh(x: Frame, n: int) -> Frame:
    """최근 n봉 최고값(현재 봉 포함)."""
    return x.rolling(n).max()


def ll(x: Frame, n: int) -> Frame:
    return x.rolling(n).min()


def flag(cond: Frame, *inputs: Frame) -> Frame:
    """bool 표 → 1.0/0.0, 입력 중 하나라도 NaN 인 칸은 NaN(그 봉엔 판정할 자료가 없음)."""
    valid = inputs[0].notna()
    for x in inputs[1:]:
        valid = valid & x.notna()
    return cond.astype(float).where(valid)


def true_range(panel: Any) -> Frame:
    """진폭(TR) — 첫 봉은 고−저(기존 `atr` 과 같음)."""
    h, l, pc = panel.high, panel.low, panel.close.shift(1)
    return np.fmax(np.fmax(h - l, (h - pc).abs()), (l - pc).abs())


def typical_price(panel: Any) -> Frame:
    return (panel.high + panel.low + panel.close) / 3


def safe_div(a: Frame, b: Frame) -> Frame:
    """b 가 0 이면 NaN."""
    return a / b.where(b != 0)


# ------------------------------------------------------------------ daily_live 도우미 (live = timeframe.LiveBars 덕 타이핑)
def live_zeros(live: Any) -> Frame:
    return pd.DataFrame(0.0, index=live.index, columns=live.codes)


def past_roll(live: Any, fn: Any, m: int, how: str) -> Frame:
    """D−1 까지 일봉(종목 자기 거래일 기준)에서 `fn(일봉Panel)` 표의 최근 m봉 집계(how: sum·max·min)를 D−1 행 값으로 봉마다 붙인 것.

    daily_live 값 = 이 "과거 m−1 봉 집계" + 오늘 가상 봉 항 (점화식 O(1)). m=0 이면 빈 합 0(sum 만)."""
    if m <= 0:
        if how == "sum":
            return live_zeros(live)
        raise ValueError("빈 창의 max/min 은 없다 — 호출하는 쪽에서 n==1 을 따로 처리할 것")
    return live.prev(live.own(lambda pn: getattr(fn(pn).rolling(m), how)()))


def prev_ffill(live: Any, field: str) -> Frame:
    """일봉 field 의 D−1(자기 마지막 유효값) — 일봉 함수들의 '직전 봉 값'(shift(1), 종목 자기 거래일)과 같다."""
    return live.prev(getattr(live.daily, field).ffill())
