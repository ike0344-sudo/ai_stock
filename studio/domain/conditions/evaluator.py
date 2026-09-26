"""조건식 평가기 — Group → bool 넓은 표. 설계서 §3.2·§3.7.

Panel 은 덕 타이핑(open/high/low/close/volume/value/prev_close). 출력은 같은 모양의 bool 표.
- `cross_above(a,b) = a_t > b_t AND a_{t-1} <= b_{t-1}` (NaN 비교는 False) — 기존 MovingAverageCrossover 와 같은 정의.
- 신호 시점: 이 표의 t 행은 "t 종가까지 알 수 있는 조건". 체결은 엔진이 t+1 시가에 한다(여기선 안 함).
- market 피연산자: 지수 csv 는 값이 ×100(326599 = 3265.99) — `INDEX_SCALE` 로 나눠 실제 포인트로 쓴다.
  **분봉 표에서는 D−1(직전 거래일) 지수 값**을 그 날 전 봉에 붙인다(당일 지수는 장중에 모르는 값).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .ast import (
    Condition, ConstOperand, FieldOperand, Group, IndOperand, MarketOperand, ParamRef, bind_group,
)
from .indicators import compute, own_shift, panel_gaps
from .intraday import is_intraday, previous_day_values

INDEX_SCALE = 100.0  # data/index/daily/{001,101}.csv 는 지수 × 100 으로 저장돼 있다
BUY, SELL, HOLD = "buy", "sell", "hold"  # backtesting.types.Signal 의 .value 와 같은 문자열

Frame = pd.DataFrame


@dataclass(frozen=True)
class Evaluation:
    entry: Frame
    exit: Frame


def _num(v: Any) -> float:
    if isinstance(v, ParamRef):
        raise ValueError(f"변수 '{v.param}' 가 채워지지 않음 — values 를 주거나 bind 하세요")
    return float(v)


def _market_frame(op: MarketOperand, panel: Any, market: Mapping[str, pd.DataFrame] | None) -> Frame:
    if market is None or op.index not in market:
        raise ValueError(f"시장 지수 '{op.index}' 데이터가 없음 (market 인자로 전달)")
    close = market[op.index]["close"].astype(float) / INDEX_SCALE
    if op.name == "sma":  # 지수 자신의 거래일 기준으로 계산한 뒤 종목 날짜에 맞춘다
        s = close.rolling(int(_num(op.params.get("n", 20)))).mean()
    elif op.name == "change_pct":
        n = int(_num(op.params.get("n", 1)))
        s = (close / close.shift(n) - 1) * 100
    else:
        s = close
    idx, cols = panel.close.index, panel.close.columns
    if is_intraday(panel):
        # 분봉: 지수는 일봉 자료라 당일 값은 장중에 모른다 → 봉 날짜 D 보다 앞선 마지막 지수 행(D−1)의 값을 그 날 전 봉에 붙인다
        # (설계 §3.7 "분봉 = 일봉 지표는 D−1"). 지수 자료가 D−1 이후로 없으면 마지막 값이 이어지니 validate_against 로 기간을 확인할 것.
        v = previous_day_values(s.sort_index().to_frame("m"), idx, ["m"])["m"].to_numpy()
    else:
        v = s.reindex(idx).to_numpy()  # 지수에 없는 날은 NaN → 조건 False
    return pd.DataFrame(np.repeat(v[:, None], len(cols), axis=1), index=idx, columns=cols)


def _operand(op: Any, panel: Any, market: Mapping[str, pd.DataFrame] | None, gaps: list,
             memo: dict | None = None) -> Frame | float:
    if isinstance(op, ConstOperand):
        return _num(op.value)
    if isinstance(op, MarketOperand):
        return _market_frame(op, panel, market)
    if isinstance(op, FieldOperand):
        x = getattr(panel, op.name)
    elif isinstance(op, IndOperand):
        params = {k: (_num(v) if isinstance(v, ParamRef) else v) for k, v in op.params.items()}
        x = compute(panel, op.name, params, gaps, memo)
    else:  # pragma: no cover
        raise TypeError(op)
    if op.offset:
        x = own_shift(panel, x, op.offset, gaps)  # "며칠 전" — 과거만, 거래정지 종목은 자기 거래일 기준
    mul = _num(op.mul)
    return x if mul == 1.0 else x * mul


def _prev(x: Frame | float, panel: Any, gaps: list) -> Frame | float:
    return own_shift(panel, x, 1, gaps) if isinstance(x, pd.DataFrame) else x


def _condition(c: Condition, panel: Any, market: Mapping[str, pd.DataFrame] | None, gaps: list,
               memo: dict | None = None) -> Frame:
    a, b = _operand(c.left, panel, market, gaps, memo), _operand(c.right, panel, market, gaps, memo)
    if c.op == "gt":
        r = a > b
    elif c.op == "gte":
        r = a >= b
    elif c.op == "lt":
        r = a < b
    elif c.op == "lte":
        r = a <= b
    elif c.op == "cross_above":
        r = (a > b) & (_prev(a, panel, gaps) <= _prev(b, panel, gaps))
    else:  # cross_below
        r = (a < b) & (_prev(a, panel, gaps) >= _prev(b, panel, gaps))
    return r  # NaN 비교는 pandas 가 False 로 준다


def _group(g: Group, panel: Any, market: Mapping[str, pd.DataFrame] | None, gaps: list,
           memo: dict | None = None) -> Frame:
    parts = [
        _group(i, panel, market, gaps, memo) if isinstance(i, Group) else _condition(i, panel, market, gaps, memo)
        for i in g.items
    ]
    out = parts[0]
    for p in parts[1:]:
        out = (out & p) if g.logic == "all" else (out | p)
    return out


def evaluate_group(
    g: Group, panel: Any, *, values: Mapping[str, float] | None = None,
    market: Mapping[str, pd.DataFrame] | None = None, memo: dict | None = None,
) -> Frame:
    """Group → bool 표. `values` 가 있으면 {"param":..} 를 먼저 채운다. 빈 그룹은 전부 False.

    `memo`(선택, 그리드용): 같은 Panel 로 조합만 바꿔 부를 때 같은 (지표, 파라미터) 계산을 재사용하는 dict.
    **한 Panel 전용**(다른 Panel 이 오면 비우고 새로 시작), 결과 숫자는 memo 없을 때와 같다.

    거래정지 빈칸이 있는 종목은 자기 거래일 기준으로 계산하고, 봉이 없는 날(종가 NaN)은 신호도 없다.
    """
    if values is not None:
        g = bind_group(g, values)
    if not g.items:
        return pd.DataFrame(False, index=panel.close.index, columns=panel.close.columns)
    return _group(g, panel, market, panel_gaps(panel, memo), memo) & panel.close.notna()


def evaluate(
    entry: Group, exit_: Group, panel: Any, *, values: Mapping[str, float] | None = None,
    market: Mapping[str, pd.DataFrame] | None = None, market_filter: Group | None = None,
    memo: dict | None = None,
) -> Evaluation:
    """진입·청산 bool 표. market_filter 는 진입에만 AND 로 얹는다(청산은 막지 않음). memo: evaluate_group 참고."""
    e = evaluate_group(entry, panel, values=values, market=market, memo=memo)
    if market_filter is not None:
        e = e & evaluate_group(market_filter, panel, values=values, market=market, memo=memo)
    return Evaluation(entry=e, exit=evaluate_group(exit_, panel, values=values, market=market, memo=memo))


def to_signals(ev: Evaluation) -> Frame:
    """호환 모드용 신호 표: 기본 hold, 진입 → buy, 청산 → sell(둘 다면 sell — 기존 전략 대입 순서와 같음)."""
    arr = np.where(ev.exit.to_numpy(), SELL, np.where(ev.entry.to_numpy(), BUY, HOLD))
    return pd.DataFrame(arr, index=ev.entry.index, columns=ev.entry.columns)


__all__ = ["Evaluation", "evaluate", "evaluate_group", "to_signals", "INDEX_SCALE", "BUY", "SELL", "HOLD"]
