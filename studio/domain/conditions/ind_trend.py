"""분류 "가격·이평·신고가" 지표 — 설계 studio-conditions §3.3 `ind_trend.py` 표(새 것만; sma·ema·highest·lowest·change_pct·gap_pct 는 기존).

계산 함수는 `fn(panel, p) -> 넓은 표`(catalog.COMPUTE_REGISTRY 규약). 전부 **t 까지의 값만** 쓴다.
`daily_live`: 설계표 live ✔ 인 지표는 `LIVE` 에 점화식 함수(D−1 까지 일봉 과거 집계 + 오늘 가상 봉 항)를 등록했다 —
값 = "오늘 가상 봉을 일봉 끝에 붙여 일반 함수로 다시 계산한 값"(tests/studio/conditions/test_ind_live.py). 창은 "봉" 단위이고, 거래정지 빈칸 종목은
`indicators.own_days` 가 자기 거래일로 이어 계산한다(이 모듈은 열마다 같은 식만 쓰면 된다).

결정(설계가 모호한 곳):
- `high52_pct`·`low52_pct`·`box_pct` 의 최고/최저는 **현재 봉 포함**(52주 고가 대비 값이 ≤ 0 이 되도록 — 신고가 종가면 0).
  `highest` 기본(t 제외)과 다르다.
- `limit_up_*`: 설계는 "호가 반올림" 이라 썼지만 실제 KRX 규칙은 **상한가 = 전일 종가×1.3 을 호가단위 미만 절사**(내림)다
  (반올림하면 130% 를 넘는 가격이 나올 수 있다). 절사로 구현.
- `prev_high_break` 분봉: 패널 안 **직전 날짜의 봉들 최고가**(D−1, 통합 분봉 기준) 대비 — 일봉 고가와 정확히 같진 않다.
- `rel_strength`(상대강도)는 지수 자료가 필요해 `compute(panel, …)` 서명으로는 못 만든다 → c1(시간 단위·market 연결) 뒤로 미룸.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..market_rules import PRICE_LIMIT_PCT, tick_size_array
from .catalog import ParamDef, IndicatorDef, _DAILY_INTRA, _n, _src, register_indicators
from .ind_common import flag, hh, ll, sma, ema, past_roll, prev_ffill
from .intraday import day_keys, is_intraday
from .live_builtin import live_ema, live_sma  # daily_live 의 이평 점화식(내장) 재사용

Frame = pd.DataFrame


# ------------------------------------------------------------------ 계산
def _wnum(x: Frame, m: int) -> Frame:
    """Σ_{i=0}^{m−1} (m−i)·x_{t−i} — 가중이평의 분자(최근 봉이 가장 큰 가중)."""
    num = None
    for i in range(m):  # ponytail: 창 m 만큼 표 연산 — n≤500 에서 수 초, 더 필요하면 누적합 식으로 교체
        term = (m - i) * x.shift(i)
        num = term if num is None else num + term
    return num


def wma(panel: Any, p: dict) -> Frame:
    n = p["n"]
    return _wnum(getattr(panel, p["src"]), n) / (n * (n + 1) / 2)


def vwma(panel: Any, p: dict) -> Frame:
    n = p["n"]
    den = panel.volume.rolling(n).sum()
    return (panel.close * panel.volume).rolling(n).sum() / den.where(den > 0)


def _ma(x: Frame, n: int, kind: str) -> Frame:
    return sma(x, n) if kind == "sma" else ema(x, n)


def ma_disparity(panel: Any, p: dict) -> Frame:
    x = getattr(panel, p["src"])
    return x / _ma(x, p["n"], p["ma"]) * 100


def ma_slope(panel: Any, p: dict) -> Frame:
    m = sma(panel.close, p["n"])
    return (m / m.shift(p["k"]) - 1) * 100


def _aligned_ns(p: dict) -> list[int]:
    ns = [int(p["n1"]), int(p["n2"]), int(p["n3"])] + ([int(p["n4"])] if p["n4"] > 0 else [])
    if any(a >= b for a, b in zip(ns, ns[1:])):
        raise ValueError(f"이평 기간은 n1 < n2 < n3 < n4 순으로 커야 함 (받은 값 {ns})")
    return ns


def _aligned_mas(panel: Any, p: dict) -> list[Frame]:
    return [sma(panel.close, n) for n in _aligned_ns(p)]


def ma_aligned(panel: Any, p: dict) -> Frame:
    mas = _aligned_mas(panel, p)
    cond = mas[0] > mas[1]
    for a, b in zip(mas[1:], mas[2:]):
        cond = cond & (a > b)
    return flag(cond, *mas)


def ma_reversed(panel: Any, p: dict) -> Frame:
    mas = _aligned_mas(panel, p)
    cond = mas[0] < mas[1]
    for a, b in zip(mas[1:], mas[2:]):
        cond = cond & (a < b)
    return flag(cond, *mas)


def new_high(panel: Any, p: dict) -> Frame:
    base = panel.high.shift(1).rolling(p["n"]).max()  # 직전 n봉 고가(t 제외)
    x = getattr(panel, p["src"])
    return flag(x > base, x, base)


def new_low(panel: Any, p: dict) -> Frame:
    base = panel.low.shift(1).rolling(p["n"]).min()
    return flag(panel.low < base, panel.low, base)


def high52_pct(panel: Any, p: dict) -> Frame:
    return (panel.close / hh(panel.high, p["n"]) - 1) * 100


def low52_pct(panel: Any, p: dict) -> Frame:
    return (panel.close / ll(panel.low, p["n"]) - 1) * 100


def bars_since_high(panel: Any, p: dict) -> Frame:
    """최근 n봉(현재 포함) 고가 최댓값이 난 뒤 지난 봉 수 — 오늘이 최고면 0, 같은 값이 여럿이면 가장 최근 것 기준."""
    return _bsh(panel.high, p["n"])


def _bsh(h: Frame, n: int) -> Frame:
    m = hh(h, n)
    out = pd.DataFrame(np.nan, index=h.index, columns=h.columns)
    unset = m.notna()
    for i in range(n):
        hit = unset & (h.shift(i) == m)
        out = out.mask(hit, float(i))
        unset = unset & ~hit
    return out


def box_pct(panel: Any, p: dict) -> Frame:
    lo = ll(panel.low, p["n"])
    return (hh(panel.high, p["n"]) - lo) / lo * 100


def _streak(cond: Frame, valid: Frame) -> Frame:
    grp = cond.astype(int).cumsum()
    base = grp.where(~cond).ffill().fillna(0)
    return (grp - base).astype(float).where(valid)


def up_streak(panel: Any, p: dict) -> Frame:
    c, pc = panel.close, panel.close.shift(1)
    return _streak(c > pc, c.notna() & pc.notna())


def down_streak(panel: Any, p: dict) -> Frame:
    c, pc = panel.close, panel.close.shift(1)
    return _streak(c < pc, c.notna() & pc.notna())


def limit_up_price(prev_close: Frame) -> Frame:
    """상한가 = 전일 종가×1.3 을 호가단위 미만 절사(내림). 호가단위는 그 가격대 기준."""
    raw = prev_close.to_numpy(dtype=float) * (1 + PRICE_LIMIT_PCT)
    tick = tick_size_array(raw)
    lim = np.floor(raw / tick + 1e-9) * tick  # 1e-9: 1.3 이진 표현 오차로 정확히 떨어지는 값이 한 호가 낮아지지 않게
    return pd.DataFrame(lim, index=prev_close.index, columns=prev_close.columns)


def limit_up_pct(panel: Any, p: dict) -> Frame:
    lim = limit_up_price(panel.prev_close)
    return (lim - panel.close) / panel.close * 100


def limit_up_hit(panel: Any, p: dict) -> Frame:
    lim = limit_up_price(panel.prev_close)
    return flag(panel.high >= lim, panel.high, lim)


def prev_high_break(panel: Any, p: dict) -> Frame:
    c, h = panel.close, panel.high
    if is_intraday(panel):
        days = day_keys(panel)
        prev = h.groupby(days).max().shift(1).reindex(days).set_axis(h.index)  # 패널 안 직전 날짜의 최고가(D−1)
    else:
        prev = h.shift(1)
    return flag(c > prev, c, prev)


# ------------------------------------------------------------------ daily_live (D−1 까지 일봉의 과거 집계 + 오늘 가상 봉 항 — 점화식 O(1))
# 값은 "오늘 가상 봉을 일봉 끝에 붙여 위 일반 함수로 다시 계산한 값"과 같아야 한다(`timeframe.check_live_equals_recompute`).
def live_wma(live: Any, p: dict) -> Frame:
    n, src = int(p["n"]), p["src"]
    x = live.field(src)
    if n == 1:
        return x.copy()
    past = live.prev(live.own(lambda pn: _wnum(getattr(pn, src), n - 1)))  # 오늘 이전 n−1 봉의 가중합(가중 n−1..1)
    return (n * x + past) / (n * (n + 1) / 2)


def live_vwma(live: Any, p: dict) -> Frame:
    n = int(p["n"])
    num = past_roll(live, lambda pn: pn.close * pn.volume, n - 1, "sum") + live.c * live.v
    den = past_roll(live, lambda pn: pn.volume, n - 1, "sum") + live.v
    return num / den.where(den > 0)


def live_ma_disparity(live: Any, p: dict) -> Frame:
    n, src = int(p["n"]), p["src"]
    ma = (live_sma if p["ma"] == "sma" else live_ema)(live, {"src": src, "n": n})
    return live.field(src) / ma * 100


def live_ma_slope(live: Any, p: dict) -> Frame:
    n, k = int(p["n"]), int(p["k"])
    ma = live_sma(live, {"src": "close", "n": n})
    base = live.prev(live.own(lambda pn: sma(pn.close, n).shift(k - 1)))  # t−k 의 이평 = 일봉 D−1 행에서 k−1 봉 전
    return (ma / base - 1) * 100


def _live_mas(live: Any, p: dict) -> list[Frame]:
    return [live_sma(live, {"src": "close", "n": n}) for n in _aligned_ns(p)]


def live_ma_aligned(live: Any, p: dict) -> Frame:
    mas = _live_mas(live, p)
    cond = mas[0] > mas[1]
    for a, b in zip(mas[1:], mas[2:]):
        cond = cond & (a > b)
    return flag(cond, *mas)


def live_ma_reversed(live: Any, p: dict) -> Frame:
    mas = _live_mas(live, p)
    cond = mas[0] < mas[1]
    for a, b in zip(mas[1:], mas[2:]):
        cond = cond & (a < b)
    return flag(cond, *mas)


def _past_high(live: Any, n: int) -> Frame:
    """오늘 제외 직전 n봉 고가 최댓값(D−1 행의 rolling(n).max())."""
    return live.prev(live.own(lambda pn: pn.high.rolling(n).max()))


def _past_low(live: Any, n: int) -> Frame:
    return live.prev(live.own(lambda pn: pn.low.rolling(n).min()))


def live_new_high(live: Any, p: dict) -> Frame:
    base = _past_high(live, int(p["n"]))
    x = live.field(p["src"])
    return flag(x > base, x, base)


def live_new_low(live: Any, p: dict) -> Frame:
    base = _past_low(live, int(p["n"]))
    return flag(live.l < base, live.l, base)


def _live_hh_ll(live: Any, n: int) -> tuple[Frame, Frame]:
    """오늘 포함 최근 n봉 최고가·최저가 = max(과거 n−1 봉, 오늘 가상 봉). 창이 덜 차면 NaN."""
    if n == 1:
        return live.h.copy(), live.l.copy()
    top = np.maximum(past_roll(live, lambda pn: pn.high, n - 1, "max"), live.h)
    bot = np.minimum(past_roll(live, lambda pn: pn.low, n - 1, "min"), live.l)
    return top, bot


def live_high52_pct(live: Any, p: dict) -> Frame:
    top, _ = _live_hh_ll(live, int(p["n"]))
    return (live.c / top - 1) * 100


def live_low52_pct(live: Any, p: dict) -> Frame:
    _, bot = _live_hh_ll(live, int(p["n"]))
    return (live.c / bot - 1) * 100


def live_bars_since_high(live: Any, p: dict) -> Frame:
    n = int(p["n"])
    if n == 1:
        return (live.h * 0.0)
    past_max = past_roll(live, lambda pn: pn.high, n - 1, "max")
    b_past = live.prev(live.own(lambda pn: _bsh(pn.high, n - 1)))         # 과거 창에서 최근 최고가까지의 거리
    out = (b_past + 1).mask(live.h >= past_max, 0.0)                       # 오늘이 (동률 포함) 최고면 0, 아니면 하루 더 멀다
    return out.where(past_max.notna() & live.h.notna())


def live_box_pct(live: Any, p: dict) -> Frame:
    top, bot = _live_hh_ll(live, int(p["n"]))
    return (top - bot) / bot * 100


def _live_streak(live: Any, up: bool) -> Frame:
    pc, c = prev_ffill(live, "close"), live.c
    cmp = (lambda a, b: a > b) if up else (lambda a, b: a < b)
    prev = live.prev(live.own(lambda pn: _streak(cmp(pn.close, pn.close.shift(1)), pn.close.notna() & pn.close.shift(1).notna())))
    return (prev.fillna(0) + 1).where(cmp(c, pc), 0.0).where(c.notna() & pc.notna())


def live_up_streak(live: Any, p: dict) -> Frame:
    return _live_streak(live, True)


def live_down_streak(live: Any, p: dict) -> Frame:
    return _live_streak(live, False)


def live_limit_up_pct(live: Any, p: dict) -> Frame:
    lim = limit_up_price(prev_ffill(live, "close"))
    return (lim - live.c) / live.c * 100


def live_limit_up_hit(live: Any, p: dict) -> Frame:
    lim = limit_up_price(prev_ffill(live, "close"))
    return flag(live.h >= lim, live.h, lim)


LIVE = {
    "wma": live_wma, "vwma": live_vwma, "ma_disparity": live_ma_disparity, "ma_slope": live_ma_slope,
    "ma_aligned": live_ma_aligned, "ma_reversed": live_ma_reversed, "new_high": live_new_high, "new_low": live_new_low,
    "high52_pct": live_high52_pct, "low52_pct": live_low52_pct, "bars_since_high": live_bars_since_high,
    "box_pct": live_box_pct, "up_streak": live_up_streak, "down_streak": live_down_streak,
    "limit_up_pct": live_limit_up_pct, "limit_up_hit": live_limit_up_hit,
}


# ------------------------------------------------------------------ 카탈로그
def _d(name: str, label: str, definition: str, params: tuple, example: str, *, timing: str = "t 포함",
       desc: str | None = None, vol: bool = False) -> IndicatorDef:
    return IndicatorDef(name, label, desc or definition, params, _DAILY_INTRA, timing, category="trend",
                        definition=definition, example=example, live=name in LIVE, volume_based=vol)


_NP = lambda default=20, name="n": _n(default, name)  # noqa: E731
_MA = ParamDef("ma", "enum", "sma", choices=("sma", "ema"), label_ko="이평 종류")

DEFS: tuple[IndicatorDef, ...] = (
    _d("wma", "가중이평", "WMA_n = Σ(i·X_{t−n+i}) ÷ Σi (i=1..n, 최근 봉이 가장 큰 가중)", (_src(), _NP()), "종가가 20일 가중이평 위"),
    _d("vwma", "거래량가중이평", "VWMA_n = Σ(C·V) ÷ ΣV (최근 n봉)", (_NP(),), "종가가 20일 거래량가중이평 위", vol=True),
    _d("ma_disparity", "이격도(%)", "X ÷ MA_n × 100 (MA 는 단순 또는 지수)", (_src(), _NP(), _MA), "20일선 이격도 ≥ 110"),
    _d("ma_slope", "이평 기울기(%)", "(SMA_n(C)_t ÷ SMA_n(C)_{t−k} − 1) × 100",
       (_NP(), _n(5, "k")), "20일선 5봉 기울기 > 0"),
    _d("ma_aligned", "정배열(1/0)", "SMA_n1 > SMA_n2 > SMA_n3 [> SMA_n4] 이면 1 (n4=0 이면 3개만)",
       (_NP(5, "n1"), _NP(20, "n2"), _NP(60, "n3"), ParamDef("n4", "int", 0, 0, 500, label_ko="네 번째 이평(0=안 씀)")),
       "5·20·60일선 정배열"),
    _d("ma_reversed", "역배열(1/0)", "SMA_n1 < SMA_n2 < SMA_n3 [< SMA_n4] 이면 1",
       (_NP(5, "n1"), _NP(20, "n2"), _NP(60, "n3"), ParamDef("n4", "int", 0, 0, 500, label_ko="네 번째 이평(0=안 씀)")),
       "5·20·60일선 역배열"),
    _d("new_high", "N봉 신고가 돌파(1/0)", "X_t > max(H_{t−n}..H_{t−1}) 이면 1 (직전 n봉 고가, 오늘 제외)",
       (_NP(), ParamDef("src", "enum", "high", choices=("high", "close"), label_ko="비교 값")), "20일 신고가 돌파",
       timing="기준선 t 제외"),
    _d("new_low", "N봉 신저가 이탈(1/0)", "L_t < min(L_{t−n}..L_{t−1}) 이면 1 (직전 n봉 저가, 오늘 제외)", (_NP(),),
       "20일 신저가 이탈", timing="기준선 t 제외"),
    _d("high52_pct", "52주 고가 대비(%)", "(C_t ÷ max(H_{t−n+1}..H_t) − 1) × 100 — 오늘 포함, 신고가 종가면 0",
       (_NP(250),), "52주 고가 대비 −5% 이내"),
    _d("low52_pct", "52주 저가 대비(%)", "(C_t ÷ min(L_{t−n+1}..L_t) − 1) × 100 — 오늘 포함", (_NP(250),),
       "52주 저가 대비 +30% 이상"),
    _d("bars_since_high", "신고가 뒤 경과 봉", "최근 n봉(오늘 포함) 고가 최댓값이 난 뒤 지난 봉 수(오늘이 최고면 0)", (_NP(),),
       "20일 최고가 후 3봉 이내"),
    _d("box_pct", "박스 폭(%)", "(max(H)−min(L)) ÷ min(L) × 100 (최근 n봉, 오늘 포함)", (_NP(),), "20일 박스 폭 10% 이하"),
    _d("up_streak", "연속 상승 봉", "종가가 직전 봉보다 오른 연속 봉 수(같거나 내리면 0)", (), "3봉 연속 상승"),
    _d("down_streak", "연속 하락 봉", "종가가 직전 봉보다 내린 연속 봉 수(같거나 오르면 0)", (), "3봉 연속 하락"),
    _d("limit_up_pct", "상한가까지 남은(%)", "(상한가 − C) ÷ C × 100, 상한가 = 전일 종가×1.3 을 호가단위 미만 절사", (),
       "상한가까지 5% 이내", timing="전일 종가"),
    _d("limit_up_hit", "상한가 도달(1/0)", "H ≥ 상한가 이면 1", (), "오늘 상한가 도달", timing="전일 종가"),
    _d("prev_high_break", "전일 고가 돌파(1/0)", "일봉: C_t > H_{t−1} / 분봉: C_t > 직전 날짜 봉들의 최고가", (),
       "종가가 전일 고가 위", timing="전일 고가 D−1"),
)

COMPUTE = {
    "wma": wma, "vwma": vwma, "ma_disparity": ma_disparity, "ma_slope": ma_slope, "ma_aligned": ma_aligned,
    "ma_reversed": ma_reversed, "new_high": new_high, "new_low": new_low, "high52_pct": high52_pct,
    "low52_pct": low52_pct, "bars_since_high": bars_since_high, "box_pct": box_pct, "up_streak": up_streak,
    "down_streak": down_streak, "limit_up_pct": limit_up_pct, "limit_up_hit": limit_up_hit,
    "prev_high_break": prev_high_break,
}

# 설계표에서 live ✔ 인 것(점화식 O(1)) 전부 + vwma("krx" — 거래량 계열이라 volume_based=True: 통합 분봉에선 daily_live 검증 오류).
LIVE_CANDIDATES = frozenset(LIVE)

register_indicators(DEFS, COMPUTE, LIVE)
