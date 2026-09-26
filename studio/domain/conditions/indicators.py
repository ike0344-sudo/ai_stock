"""지표 계산 — 넓은 표(index=날짜, columns=종목코드) 벡터 연산. 설계서 §3.7.

Panel 은 덕 타이핑: open/high/low/close/volume/value/prev_close 속성만 쓴다.
모든 지표는 t 까지의 값만 쓴다(미래 참조 없음). `highest/lowest`·`vol_ratio` 의 기준선은 t 제외.

**거래정지 빈칸**: 종목 활동 구간 안에 행 자체가 없는 날(close NaN)이 있으면 넓은 표에서 rolling 이
그 뒤 n봉을 NaN 으로 만든다. 기존 전략은 종목 자기 행만 봤으므로(2026-09-25 lead 판정) 롤링·시프트는
**종목 자기 거래일만 이어서** 계산한다 — 빈칸 없는 열은 그대로 벡터, 빈칸 있는 열만 따로. 빈칸 날 자체 값은 NaN.
(거래량 0 인 날은 행이 있으므로 정상 봉.)
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

import numpy as np
import pandas as pd

from .catalog import INDICATORS, resolve_params
from .intraday import INTRADAY_ONLY, compute_intraday, is_intraday

Frame = pd.DataFrame
_PANEL_FIELDS = ("open", "high", "low", "close", "volume", "value", "prev_close")


# ------------------------------------------------------------------ 거래정지 빈칸 경로
def gap_columns(close: Frame) -> list:
    """활동 구간(첫 종가~마지막 종가) 안에 종가 없는 날이 있는 종목 열."""
    valid = close.notna().astype(int)
    inside = valid.cummax().astype(bool) & valid.iloc[::-1].cummax().iloc[::-1].astype(bool)
    return list(close.columns[(inside & ~close.notna()).any().to_numpy()])


def _own_panel(panel: Any, code: str) -> SimpleNamespace:
    """한 종목의 자기 거래일(종가 있는 행)만 남긴 1열 Panel 대역. 전일 종가 빈칸은 자기 직전 종가로."""
    keep = panel.close[code].notna()
    d = {f: getattr(panel, f).loc[keep, [code]] for f in _PANEL_FIELDS}
    d["prev_close"] = d["prev_close"].where(d["prev_close"].notna(), d["close"].shift(1))
    return SimpleNamespace(**d)


def own_days(panel: Any, fn: Callable[[Any], Frame], gaps: list | None = None) -> Frame:
    """fn(panel) 의 결과. 빈칸 있는 열만 종목 자기 거래일 기준으로 다시 계산해 덮는다."""
    out = fn(panel)
    gaps = gap_columns(panel.close) if gaps is None else gaps
    if not gaps:
        return out
    out = out.copy()
    for c in gaps:
        out[c] = fn(_own_panel(panel, c))[c].reindex(panel.close.index)
    return out


def own_shift(panel: Any, x: Frame, n: int, gaps: list | None = None) -> Frame:
    """n 거래일 전 값 — 빈칸 있는 종목은 자기 거래일 기준."""
    out = x.shift(n)
    gaps = gap_columns(panel.close) if gaps is None else gaps
    for c in gaps:
        keep = panel.close[c].notna()
        out[c] = x.loc[keep, c].shift(n).reindex(x.index)
    return out


# ------------------------------------------------------------------ 지표 (넓은 표 벡터)
def sma(x: Frame, n: int) -> Frame:
    return x.rolling(n).mean()


def ema(x: Frame, n: int) -> Frame:
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: Frame, n: int) -> Frame:
    """기존 `backtesting.indicators.compute_rsi` 와 같은 단순평균 RSI. 손실 0 이면 100."""
    delta = close.diff()
    avg_gain = delta.clip(lower=0).rolling(n).mean()
    avg_loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = avg_gain / avg_loss.where(avg_loss != 0)
    return (100 - 100 / (1 + rs)).where(avg_loss != 0, 100.0)


def rsi_wilder(close: Frame, n: int) -> Frame:
    delta = close.diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.where(avg_loss != 0)
    return (100 - 100 / (1 + rs)).where(avg_loss != 0, 100.0)


def highest(x: Frame, n: int, include_current: bool = False) -> Frame:
    # 기존 전략과 같은 x.shift(1).rolling(n).max() — 오늘은 기본 제외
    return (x if include_current else x.shift(1)).rolling(n).max()


def lowest(x: Frame, n: int, include_current: bool = False) -> Frame:
    return (x if include_current else x.shift(1)).rolling(n).min()


def change_pct(close: Frame, n: int) -> Frame:
    return (close / close.shift(n) - 1) * 100


def gap_pct(open_: Frame, prev_close: Frame) -> Frame:
    return (open_ / prev_close - 1) * 100


def atr(high: Frame, low: Frame, close: Frame, n: int) -> Frame:
    pc = close.shift(1)
    tr = np.fmax(np.fmax(high - low, (high - pc).abs()), (low - pc).abs())  # fmax: 첫 봉은 고−저
    return tr.rolling(n).mean()


def bollinger(close: Frame, n: int, k: float, upper: bool) -> Frame:
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    return mid + k * sd if upper else mid - k * sd


def vol_ratio(volume: Frame, n: int) -> Frame:
    return volume / volume.shift(1).rolling(n).mean()


def value_rank(value: Frame, lookback: int = 1) -> Frame:
    """그날 종목 간 거래대금 순위(1=최대). lookback>1 이면 t 포함 최근 lookback일 평균 기준."""
    base = value if lookback == 1 else value.rolling(lookback).mean()
    return base.rank(axis=1, ascending=False, method="min")


def _wide(panel: Any, name: str, p: dict[str, Any]) -> Frame:
    """빈칸 처리 없는 순수 벡터 계산(value_rank 제외)."""
    if name == "sma":
        return sma(getattr(panel, p["src"]), p["n"])
    if name == "ema":
        return ema(getattr(panel, p["src"]), p["n"])
    if name == "rsi":
        return rsi(panel.close, p["n"])
    if name == "rsi_wilder":
        return rsi_wilder(panel.close, p["n"])
    if name == "highest":
        return highest(getattr(panel, p["src"]), p["n"], p["include_current"])
    if name == "lowest":
        return lowest(getattr(panel, p["src"]), p["n"], p["include_current"])
    if name == "change_pct":
        return change_pct(panel.close, p["n"])
    if name == "gap_pct":
        return gap_pct(panel.open, panel.prev_close)
    if name == "atr":
        return atr(panel.high, panel.low, panel.close, p["n"])
    if name in ("bb_upper", "bb_lower"):
        return bollinger(panel.close, p["n"], float(p["k"]), name == "bb_upper")
    if name == "vol_ratio":
        return vol_ratio(panel.volume, p["n"])
    raise NotImplementedError(name)  # 카탈로그엔 있고 여기 없으면 버그 — 테스트가 잡는다


MEMO_MAX = 64  # memo 에 담는 지표 표 최대 개수 — 넘으면 비우고 다시 쌓는다(표 하나 = 종목×거래일 float 표)


def _bind_memo(memo: dict, panel: Any) -> dict:
    """memo 는 **한 Panel 전용**이다. 다른 Panel 객체가 오면(id 재사용 오인 방지 위해 객체 자체를 들고 비교) 비우고 새로 시작."""
    if memo.get("__panel__") is not panel:
        memo.clear()
        memo["__panel__"] = panel
    return memo


def panel_gaps(panel: Any, memo: dict | None = None) -> list:
    """gap_columns(panel.close) — memo 가 있으면 Panel 당 한 번만 계산."""
    if memo is None:
        return gap_columns(panel.close)
    _bind_memo(memo, panel)
    if "__gaps__" not in memo:
        memo["__gaps__"] = gap_columns(panel.close)
    return memo["__gaps__"]


def compute(panel: Any, name: str, params: dict[str, Any] | None = None, gaps: list | None = None,
            memo: dict | None = None) -> Frame:
    """카탈로그 지표 이름 → 넓은 표. 파라미터는 기본값을 채워 정규화(정수형 실수 → int).

    `gaps` 는 gap_columns(panel.close) — 여러 지표를 부를 때 한 번만 계산해 넘기면 빠르다.
    `memo`(선택) — 같은 Panel 로 조합만 바꿔 여러 번 부를 때(그리드) 같은 (지표, 파라미터) 결과를 재사용한다.
    **돌려주는 표는 공유되니 읽기 전용으로 다룰 것.** memo=None 이면 종전과 똑같다(값 불변).
    """
    d = INDICATORS[name]
    if not d.compute:
        raise NotImplementedError(f"'{name}' 은 분봉·틱 전용 — 계산은 module-6")
    p = resolve_params(name, params or {})
    for spec in d.params:
        if spec.kind == "int":
            p[spec.name] = int(p[spec.name])
    if name in INTRADAY_ONLY or (name == "gap_pct" and is_intraday(panel)):
        return compute_intraday(panel, name)  # 행마다·날짜별 누적이라 빈 봉(NaN) 재계산 경로 불필요
    key = (name, tuple(sorted(p.items())))
    if memo is not None:
        _bind_memo(memo, panel)
        if key in memo:
            return memo[key]
    gaps = panel_gaps(panel, memo) if gaps is None else gaps
    if name == "value_rank":
        lb = p["lookback"]  # 순위는 종목 간 비교라 열별 재계산 불가 — 평균만 자기 거래일로 낸 뒤 순위
        base = panel.value if lb == 1 else own_days(panel, lambda pn: pn.value.rolling(lb).mean(), gaps)
        out = value_rank(base, 1)
    else:
        out = own_days(panel, lambda pn: _wide(pn, name, p), gaps)
    if memo is not None:
        if len(memo) >= MEMO_MAX:  # 메모리 상한 — 비우고 이 Panel 로 다시 시작(gaps 는 다음 호출에 재계산)
            memo.clear()
            memo["__panel__"] = panel
        memo[key] = out
    return out
