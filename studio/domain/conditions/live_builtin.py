"""내장 지표의 `daily_live` 계산 — (D−1 까지 확정된 일봉) + (오늘 가상 봉) 을 O(1) 점화식으로 합친다. 설계 studio-conditions §3.2.

값은 "오늘 가상 봉을 일봉 끝에 붙여 일반 지표 함수로 다시 계산한 것"과 같아야 한다(`timeframe.check_live_equals_recompute`, C6).
모든 선행 통계(롤링 합·최댓값·EWM)는 일봉을 **종목 자기 거래일** 기준으로(live.own) 계산하고 D−1 행(live.prev)만 읽는다 — 오늘 이후 값 미참조.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from .catalog import LIVE_REGISTRY

if TYPE_CHECKING:  # pragma: no cover
    from .timeframe import LiveBars

Frame = pd.DataFrame


def _cnt(live: "LiveBars", src: str) -> Frame:
    """D−1 까지 자기 거래일 관측 수."""
    return live.prev(live.own(lambda pn: getattr(pn, src).notna().cumsum().astype(float)))


def live_sma(live: "LiveBars", p: dict[str, Any]) -> Frame:
    n, src = p["n"], p["src"]
    x = live.field(src)
    if n == 1:
        return x.copy()
    s = live.prev(live.own(lambda pn: getattr(pn, src).rolling(n - 1).sum()))
    return (s + x) / n


def live_ema(live: "LiveBars", p: dict[str, Any]) -> Frame:
    n, src = p["n"], p["src"]
    a = 2.0 / (n + 1)
    e0 = live.prev(live.own(lambda pn: getattr(pn, src).ewm(span=n, adjust=False, min_periods=1).mean()))
    out = a * live.field(src) + (1 - a) * e0
    return out.where(_cnt(live, src) >= n - 1)  # 일반 EMA 는 min_periods=n — 오늘 값 포함 n 개가 모여야 값이 있다


def _extreme(live: "LiveBars", p: dict[str, Any], fn: str) -> Frame:
    n, src, inc = p["n"], p["src"], bool(p["include_current"])
    roll = (lambda x, k: x.rolling(k).max()) if fn == "max" else (lambda x, k: x.rolling(k).min())
    if not inc:  # 직전 n봉 — 오늘 봉을 안 쓴다(오늘 가상 봉이 바뀌어도 값은 그대로)
        return live.prev(live.own(lambda pn: roll(getattr(pn, src), n)))
    if n == 1:
        return live.field(src).copy()
    past = live.prev(live.own(lambda pn: roll(getattr(pn, src), n - 1)))
    x = live.field(src)
    return past.combine(x, np.fmax if fn == "max" else np.fmin)


def live_highest(live: "LiveBars", p: dict[str, Any]) -> Frame:
    return _extreme(live, p, "max")


def live_lowest(live: "LiveBars", p: dict[str, Any]) -> Frame:
    return _extreme(live, p, "min")


def live_change_pct(live: "LiveBars", p: dict[str, Any]) -> Frame:
    n = p["n"]
    base = live.prev(live.own(lambda pn: pn.close if n == 1 else pn.close.shift(n - 1)))  # D−n 종가(n=1 이면 D−1)
    return (live.c / base - 1) * 100


def live_gap_pct(live: "LiveBars", p: dict[str, Any]) -> Frame:
    prev_close = live.prev(live.daily.close.ffill())  # D−1(자기 마지막 종가) — 일봉 gap_pct 의 전일 종가와 같은 값
    return (live.o / prev_close - 1) * 100


def _rsi_parts(live: "LiveBars"):
    prev_close = live.prev(live.daily.close.ffill())
    d = live.c - prev_close  # 오늘 가상 변화
    return d.clip(lower=0), (-d).clip(lower=0)


def live_rsi(live: "LiveBars", p: dict[str, Any]) -> Frame:
    n = p["n"]
    g_t, l_t = _rsi_parts(live)
    if n == 1:
        ag, al = g_t, l_t
    else:
        g = live.prev(live.own(lambda pn: pn.close.diff().clip(lower=0).rolling(n - 1).sum()))
        lo = live.prev(live.own(lambda pn: (-pn.close.diff().clip(upper=0)).rolling(n - 1).sum()))
        ag, al = (g + g_t) / n, (lo + l_t) / n
    rs = ag / al.where(al != 0)
    out = 100 - 100 / (1 + rs)
    return out.where(al != 0, 100.0).where(ag.notna() & al.notna())


def live_rsi_wilder(live: "LiveBars", p: dict[str, Any]) -> Frame:
    n = p["n"]
    a = 1.0 / n
    g_t, l_t = _rsi_parts(live)
    ag0 = live.prev(live.own(lambda pn: pn.close.diff().clip(lower=0).ewm(alpha=a, adjust=False, min_periods=1).mean()))
    al0 = live.prev(live.own(lambda pn: (-pn.close.diff().clip(upper=0)).ewm(alpha=a, adjust=False, min_periods=1).mean()))
    cnt = live.prev(live.own(lambda pn: pn.close.diff().notna().cumsum().astype(float)))  # 유효 변화 수(D−1 까지)
    ag, al = (1 - a) * ag0 + a * g_t, (1 - a) * al0 + a * l_t
    rs = ag / al.where(al != 0)
    out = 100 - 100 / (1 + rs)
    return out.where(al != 0, 100.0).where(ag.notna() & al.notna() & (cnt >= n - 1))


def _bb(live: "LiveBars", p: dict[str, Any], upper: bool) -> Frame:
    n, k = p["n"], float(p["k"])
    x = live.c
    if n == 1:
        return x.copy()
    s1 = live.prev(live.own(lambda pn: pn.close.rolling(n - 1).sum()))
    s2 = live.prev(live.own(lambda pn: (pn.close ** 2).rolling(n - 1).sum()))
    mean = (s1 + x) / n
    var = ((s2 + x ** 2) / n - mean ** 2).clip(lower=0)
    sd = np.sqrt(var)
    return mean + k * sd if upper else mean - k * sd


def live_bb_upper(live: "LiveBars", p: dict[str, Any]) -> Frame:
    return _bb(live, p, True)


def live_bb_lower(live: "LiveBars", p: dict[str, Any]) -> Frame:
    return _bb(live, p, False)


LIVE_REGISTRY.update({
    "sma": live_sma, "ema": live_ema, "highest": live_highest, "lowest": live_lowest, "change_pct": live_change_pct,
    "gap_pct": live_gap_pct, "rsi": live_rsi, "rsi_wilder": live_rsi_wilder, "bb_upper": live_bb_upper, "bb_lower": live_bb_lower,
})
