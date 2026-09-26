"""분류 "캔들" — 설계 studio-conditions §3.3 `ind_candle.py` 표(전부 신규). 한 봉(또는 직전 봉과의 관계)만 본다 — 미래 참조 없음.

계산 함수는 `fn(panel, p) -> 넓은 표`. 1/0 지표는 입력에 NaN 이 있으면 NaN.
`daily_live`: 설계표에서 캔들 계열은 전부 live ✔ — 오늘 가상 봉의 O·H·L·C(+전일 봉)로 바로 계산해 `LIVE` 에 등록했다.

정의 결정(설계가 모호한 곳 — 패턴은 추세 맥락 없이 모양만 본다):
- 꼬리 비율은 (고−저)가 0 인 봉(상하한가 잠김·무거래)이면 값 없음(NaN), `doji`·`hammer`·`inverted_hammer` 는 0.
- `doji`: |C−O| ÷ (H−L) ≤ max_body_ratio. `hammer`: 아랫꼬리 ≥ wick_mult × 몸통 이고 윗꼬리 ≤ max_other_wick × (H−L) 이며 아랫꼬리 > 0.
  `inverted_hammer` 는 위아래를 바꾼 것.
- `bull_engulfing`: 직전 음봉 뒤 양봉이 O_t ≤ C_{t−1} 이고 C_t ≥ O_{t−1}(직전 몸통을 감쌈, 같으면 포함). `bear_engulfing` 은 대칭.
- `inside_bar`: H_t < H_{t−1} 이고 L_t > L_{t−1}(엄격). `outside_bar`: H_t > H_{t−1} 이고 L_t < L_{t−1}.
- `gap_held`: 시가가 전일 종가보다 min_gap_pct% 이상 높게 시작하고 저가가 전일 종가 위(갭 유지). `gap_filled`: 같은 갭 상승인데 저가가 전일 종가 이하(갭 메움).
  분봉 표에서는 "그 봉" 기준이라 하루 단위 캔들이 필요하면 `daily_live`/`daily_prev`(c1)로 쓸 것.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from .catalog import ParamDef, IndicatorDef, _DAILY_INTRA, register_indicators
from .ind_common import flag, prev_ffill, safe_div

Frame = pd.DataFrame


# ------------------------------------------------------------------ 계산
def body_pct(panel: Any, p: dict) -> Frame:
    return (panel.close - panel.open) / panel.open * 100


def upper_wick_ratio(panel: Any, p: dict) -> Frame:
    return safe_div(panel.high - np.maximum(panel.open, panel.close), panel.high - panel.low)


def lower_wick_ratio(panel: Any, p: dict) -> Frame:
    return safe_div(np.minimum(panel.open, panel.close) - panel.low, panel.high - panel.low)


def range_pct(panel: Any, p: dict) -> Frame:
    return (panel.high - panel.low) / panel.prev_close * 100


def long_bull(panel: Any, p: dict) -> Frame:
    o, c = panel.open, panel.close
    return flag((c > o) & ((c - o) / o * 100 >= p["min_body_pct"]), o, c)


def long_bear(panel: Any, p: dict) -> Frame:
    o, c = panel.open, panel.close
    return flag((c < o) & ((o - c) / o * 100 >= p["min_body_pct"]), o, c)


def doji(panel: Any, p: dict) -> Frame:
    o, h, l, c = panel.open, panel.high, panel.low, panel.close
    rng = h - l
    return flag((rng > 0) & ((c - o).abs() <= p["max_body_ratio"] * rng), o, h, l, c)


def _hammer_parts(panel: Any):
    o, h, l, c = panel.open, panel.high, panel.low, panel.close
    return o, h, l, c, (c - o).abs(), np.minimum(o, c) - l, h - np.maximum(o, c), h - l


def hammer(panel: Any, p: dict) -> Frame:
    o, h, l, c, body, lower, upper, rng = _hammer_parts(panel)
    cond = (rng > 0) & (lower > 0) & (lower >= p["wick_mult"] * body) & (upper <= p["max_other_wick"] * rng)
    return flag(cond, o, h, l, c)


def inverted_hammer(panel: Any, p: dict) -> Frame:
    o, h, l, c, body, lower, upper, rng = _hammer_parts(panel)
    cond = (rng > 0) & (upper > 0) & (upper >= p["wick_mult"] * body) & (lower <= p["max_other_wick"] * rng)
    return flag(cond, o, h, l, c)


def bull_engulfing(panel: Any, p: dict) -> Frame:
    o, c, po, pc = panel.open, panel.close, panel.open.shift(1), panel.close.shift(1)
    return flag((pc < po) & (c > o) & (o <= pc) & (c >= po), o, c, po, pc)


def bear_engulfing(panel: Any, p: dict) -> Frame:
    o, c, po, pc = panel.open, panel.close, panel.open.shift(1), panel.close.shift(1)
    return flag((pc > po) & (c < o) & (o >= pc) & (c <= po), o, c, po, pc)


def inside_bar(panel: Any, p: dict) -> Frame:
    h, l, ph, pl = panel.high, panel.low, panel.high.shift(1), panel.low.shift(1)
    return flag((h < ph) & (l > pl), h, l, ph, pl)


def outside_bar(panel: Any, p: dict) -> Frame:
    h, l, ph, pl = panel.high, panel.low, panel.high.shift(1), panel.low.shift(1)
    return flag((h > ph) & (l < pl), h, l, ph, pl)


def _gap_up(panel: Any, min_gap_pct: float) -> Frame:
    return (panel.open / panel.prev_close - 1) * 100 >= min_gap_pct


def gap_held(panel: Any, p: dict) -> Frame:
    pc = panel.prev_close
    return flag(_gap_up(panel, p["min_gap_pct"]) & (panel.low > pc), panel.open, panel.low, pc)


def gap_filled(panel: Any, p: dict) -> Frame:
    pc = panel.prev_close
    return flag(_gap_up(panel, p["min_gap_pct"]) & (panel.low <= pc), panel.open, panel.low, pc)


# ------------------------------------------------------------------ daily_live — 오늘 가상 봉(O=당일 첫 시가, H/L=t 까지 최고/최저, C=봉 t 종가)의 모양
def _today(live: Any) -> SimpleNamespace:
    """한 봉짜리 함수는 오늘 가상 봉을 Panel 처럼 넘기면 그대로 된다(전일 종가 = 일봉 D−1 의 자기 마지막 종가)."""
    return SimpleNamespace(open=live.o, high=live.h, low=live.l, close=live.c, volume=live.v, value=live.val,
                           prev_close=prev_ffill(live, "close"))


def _single(fn: Any) -> Any:
    return lambda live, p: fn(_today(live), p)


def live_bull_engulfing(live: Any, p: dict) -> Frame:
    o, c, po, pc = live.o, live.c, prev_ffill(live, "open"), prev_ffill(live, "close")
    return flag((pc < po) & (c > o) & (o <= pc) & (c >= po), o, c, po, pc)


def live_bear_engulfing(live: Any, p: dict) -> Frame:
    o, c, po, pc = live.o, live.c, prev_ffill(live, "open"), prev_ffill(live, "close")
    return flag((pc > po) & (c < o) & (o >= pc) & (c <= po), o, c, po, pc)


def live_inside_bar(live: Any, p: dict) -> Frame:
    h, l, ph, pl = live.h, live.l, prev_ffill(live, "high"), prev_ffill(live, "low")
    return flag((h < ph) & (l > pl), h, l, ph, pl)


def live_outside_bar(live: Any, p: dict) -> Frame:
    h, l, ph, pl = live.h, live.l, prev_ffill(live, "high"), prev_ffill(live, "low")
    return flag((h > ph) & (l < pl), h, l, ph, pl)


LIVE = {
    "body_pct": _single(body_pct), "upper_wick_ratio": _single(upper_wick_ratio),
    "lower_wick_ratio": _single(lower_wick_ratio), "range_pct": _single(range_pct), "long_bull": _single(long_bull),
    "long_bear": _single(long_bear), "doji": _single(doji), "hammer": _single(hammer),
    "inverted_hammer": _single(inverted_hammer), "gap_held": _single(gap_held), "gap_filled": _single(gap_filled),
    "bull_engulfing": live_bull_engulfing, "bear_engulfing": live_bear_engulfing,
    "inside_bar": live_inside_bar, "outside_bar": live_outside_bar,
}


# ------------------------------------------------------------------ 카탈로그
def _d(name: str, label: str, definition: str, params: tuple, example: str) -> IndicatorDef:
    return IndicatorDef(name, label, definition, params, _DAILY_INTRA, "그 봉 종가까지", category="candle",
                        definition=definition, example=example, live=name in LIVE)


def _f(name: str, default: float, lo: float, hi: float, label: str) -> ParamDef:
    return ParamDef(name, "float", default, lo, hi, label_ko=label)


_MIN_GAP = (_f("min_gap_pct", 0.5, 0.0, 30.0, "최소 갭(%)"),)
_HAMMER_P = (_f("wick_mult", 2.0, 0.5, 10.0, "꼬리÷몸통 최소 배수"), _f("max_other_wick", 0.1, 0.0, 0.5, "반대 꼬리 최대 비율(봉 길이 대비)"))

DEFS: tuple[IndicatorDef, ...] = (
    _d("body_pct", "몸통(%)", "(C − O) ÷ O × 100 (양봉 +, 음봉 −)", (), "몸통 +5% 이상 양봉"),
    _d("upper_wick_ratio", "윗꼬리 비율", "(H − max(O,C)) ÷ (H − L) — 봉 길이가 0 이면 값 없음", (), "윗꼬리가 봉의 50% 이상"),
    _d("lower_wick_ratio", "아랫꼬리 비율", "(min(O,C) − L) ÷ (H − L) — 봉 길이가 0 이면 값 없음", (), "아랫꼬리가 봉의 50% 이상"),
    _d("range_pct", "봉 길이(%)", "(H − L) ÷ 전일 종가 × 100", (), "일 변동폭 10% 이상"),
    _d("long_bull", "장대양봉(1/0)", "C > O 이고 (C−O)÷O×100 ≥ min_body_pct", (_f("min_body_pct", 5.0, 0.1, 30.0, "최소 몸통(%)"),), "장대양봉"),
    _d("long_bear", "장대음봉(1/0)", "C < O 이고 (O−C)÷O×100 ≥ min_body_pct", (_f("min_body_pct", 5.0, 0.1, 30.0, "최소 몸통(%)"),), "장대음봉"),
    _d("doji", "도지(1/0)", "|C−O| ÷ (H−L) ≤ max_body_ratio (봉 길이 0 이면 0)", (_f("max_body_ratio", 0.1, 0.0, 0.5, "몸통÷봉 길이 최대"),), "도지 출현"),
    _d("hammer", "망치형(1/0)", "아랫꼬리 ≥ wick_mult×몸통, 윗꼬리 ≤ max_other_wick×(H−L), 아랫꼬리 > 0", _HAMMER_P, "망치형 캔들"),
    _d("inverted_hammer", "역망치형(1/0)", "윗꼬리 ≥ wick_mult×몸통, 아랫꼬리 ≤ max_other_wick×(H−L), 윗꼬리 > 0", _HAMMER_P, "역망치형 캔들"),
    _d("bull_engulfing", "상승 장악형(1/0)", "직전 음봉 뒤 양봉이 O ≤ 직전 C 이고 C ≥ 직전 O", (), "상승 장악형"),
    _d("bear_engulfing", "하락 장악형(1/0)", "직전 양봉 뒤 음봉이 O ≥ 직전 C 이고 C ≤ 직전 O", (), "하락 장악형"),
    _d("inside_bar", "인사이드바(1/0)", "H_t < H_{t−1} 이고 L_t > L_{t−1}", (), "직전 봉 안에 갇힘"),
    _d("outside_bar", "아웃사이드바(1/0)", "H_t > H_{t−1} 이고 L_t < L_{t−1}", (), "직전 봉을 감쌈"),
    _d("gap_held", "갭 유지(1/0)", "시가가 전일 종가보다 min_gap_pct% 이상 위 & 저가 > 전일 종가", _MIN_GAP, "갭 상승 후 갭 유지"),
    _d("gap_filled", "갭 메움(1/0)", "시가가 전일 종가보다 min_gap_pct% 이상 위 & 저가 ≤ 전일 종가", _MIN_GAP, "갭 상승 후 메움"),
)

COMPUTE = {d.name: globals()[d.name] for d in DEFS}

# 설계표: 캔들 계열 전부 live ✔ (오늘 가상 봉의 O·H·L·C 로 바로 계산).
LIVE_CANDIDATES = frozenset(LIVE)

register_indicators(DEFS, COMPUTE, LIVE)
