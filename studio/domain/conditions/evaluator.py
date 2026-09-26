"""조건식 평가기 — Group → bool 넓은 표. 설계서 §3.2·§3.7 + studio-conditions c1.

Panel 은 덕 타이핑(open/high/low/close/volume/value/prev_close). 출력은 같은 모양의 bool 표.
- `cross_above(a,b) = a_t > b_t AND a_{t-1} <= b_{t-1}` (NaN 비교는 False) — 기존 MovingAverageCrossover 와 같은 정의.
  `cross_*_within(k)` = 최근 k봉(t 포함) 안에 크로스가 있었다. `is_true`/`is_false` = 왼쪽 값이 0 이 아니다/0 이다(NaN 은 둘 다 거짓).
  `hold=k` = 그 조건이 연속 k봉 만족(봉 t 포함, NaN 봉은 끊김).
- 신호 시점: 이 표의 t 행은 "t 종가까지 알 수 있는 조건". 체결은 엔진이 t+1 시가에 한다(여기선 안 함).
- market 피연산자: 지수 csv 는 값이 ×100(326599 = 3265.99) — `INDEX_SCALE` 로 나눠 실제 포인트로 쓴다.
  **분봉 표에서는 D−1(직전 거래일) 지수 값**을 그 날 전 봉에 붙인다(당일 지수는 장중에 모르는 값).
- **시간 단위(`tf`)**: bar(실행 봉) · mN(N분봉으로 묶은 뒤 마감된 마지막 값) · daily_prev(일봉 D−1 값) · daily_live(D−1 까지 일봉 + 오늘 가상 봉).
  분봉 실행에서만 bar 이외를 쓸 수 있고, 일봉 Panel·봉 길이는 `daily`·`bar_minutes` 로 받는다 — 규칙은 `timeframe.py`.
- Group `negate`(NOT): 결과를 뒤집되 **피연산자가 하나라도 값 없음(NaN)이면 참이 되지 않는다** — 워밍업 구간에서 NOT 이 참이 되는 사고를 막는다.
- `pos`(포지션) 피연산자는 보유 종목마다 엔진이 평가한다(청산 확장, c2) — `evaluate_group` 은 지원하지 않고, `evaluate` 가 pos 가 든 청산 그룹을
  `position.PosExitPlan` 으로 컴파일해 `Evaluation.pos_exit` 에 담는다(exit 표는 전부 False).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .ast import (
    Condition, ConstOperand, ExprOperand, FieldOperand, Group, IndOperand, MarketOperand, ParamRef, PosOperand, bind_group,
)
from .catalog import LIVE_REGISTRY, excludes_current, resolve_params
from .indicators import compute, own_shift, panel_gaps
from .intraday import is_intraday, previous_day_values
from .timeframe import TimeContext, map_asof, take_rows

INDEX_SCALE = 100.0  # data/index/daily/{001,101}.csv 는 지수 × 100 으로 저장돼 있다
BUY, SELL, HOLD = "buy", "sell", "hold"  # backtesting.types.Signal 의 .value 와 같은 문자열

Frame = pd.DataFrame


@dataclass(frozen=True)
class Evaluation:
    entry: Frame
    exit: Frame
    pos_exit: Any = None  # 청산 그룹에 pos(포지션) 피연산자가 있으면 그 컴파일 결과(position.PosExitPlan) — 이때 exit 표는 전부 False


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


# ----------------------------------------------------------------------------- 피연산자 (시간 단위 포함)
def _params(op: IndOperand) -> dict[str, Any]:
    return {k: (_num(v) if isinstance(v, ParamRef) else v) for k, v in op.params.items()}


def _tf_frame(op: FieldOperand | IndOperand, tctx: TimeContext) -> Frame:
    """bar 이외 시간 단위의 값 표(실행 봉 index·종목 열). offset 은 그 시간 단위 자신의 단위로 센다."""
    panel = tctx.panel
    tf = op.tf
    cols = list(panel.close.columns)
    idx = panel.close.index
    is_ind = isinstance(op, IndOperand)

    if tf.startswith("m"):  # mN — 묶은 분봉 위에서 계산 → 마감된 마지막 묶음 값
        rs = tctx.resampled(tf)
        x = compute(rs.panel, op.name, _params(op), memo=tctx.memo(tf)) if is_ind else getattr(rs.panel, op.name)
        if op.offset:
            x = own_shift(rs.panel, x, op.offset)
        return map_asof(x, rs.ends, idx, cols)

    daily = tctx.need_daily(tf)
    if tf == "daily_prev":
        x = compute(daily, op.name, _params(op), memo=tctx.memo(tf)) if is_ind else getattr(daily, op.name)
        if op.offset:
            x = own_shift(daily, x, op.offset)
        pos = tctx.same_pos() if (is_ind and excludes_current(op.name, _params(op))) else tctx.prev_pos()  # 오늘 장 시작 전에 아는 값(행 D 또는 D−1)
        return take_rows(x, pos, idx, cols)

    # daily_live: offset 0 = 오늘 가상 봉 값, offset k>=1 = D−k 값(= daily_prev 의 offset k−1)
    if op.offset:
        x = compute(daily, op.name, _params(op), memo=tctx.memo("daily_prev")) if is_ind else getattr(daily, op.name)
        if op.offset > 1:
            x = own_shift(daily, x, op.offset - 1)
        return take_rows(x, tctx.prev_pos(), idx, cols)
    live = tctx.live()
    if is_ind:
        fn = LIVE_REGISTRY.get(op.name)
        if fn is None:  # AST 검증이 막지만 카탈로그가 바뀐 경우를 위해
            raise ValueError(f"지표 '{op.name}' 는 일봉 장중(daily_live)을 지원하지 않는다")
        return fn(live, resolve_params(op.name, _params(op)))
    return live.field(op.name)


def _operand(op: Any, panel: Any, market: Mapping[str, pd.DataFrame] | None, gaps: list,
             memo: dict | None = None, tctx: TimeContext | None = None) -> Frame | float:
    if isinstance(op, ConstOperand):
        return _num(op.value)
    if isinstance(op, MarketOperand):
        return _market_frame(op, panel, market)
    if isinstance(op, PosOperand):
        raise ValueError(f"포지션 피연산자 'pos.{op.name}' 는 보유 종목마다 엔진이 평가한다 — 평가기 단독으로는 계산할 수 없다(청산 조건, c2)")
    if isinstance(op, ExprOperand):
        a = _operand(op.left, panel, market, gaps, memo, tctx)
        b = _operand(op.right, panel, market, gaps, memo, tctx)
        if op.op == "+":
            return a + b
        if op.op == "-":
            return a - b
        if op.op == "*":
            return a * b
        if isinstance(b, pd.DataFrame):
            return a / b.where(b != 0)  # 0 으로 나누면 NaN → 조건 거짓
        return a / b if b != 0 else float("nan")
    tf = getattr(op, "tf", "bar")
    if tf != "bar":
        if tctx is None:
            raise ValueError(f"시간 단위 '{tf}' 는 분봉 실행에서만 쓸 수 있다(평가기에 일봉·봉 길이 정보가 없음)")
        x = _tf_frame(op, tctx)
    else:
        if isinstance(op, FieldOperand):
            x = getattr(panel, op.name)
        elif isinstance(op, IndOperand):
            x = compute(panel, op.name, _params(op), gaps, memo)
        else:  # pragma: no cover
            raise TypeError(op)
        if op.offset:
            x = own_shift(panel, x, op.offset, gaps)  # "며칠 전" — 과거만, 거래정지 종목은 자기 거래일 기준
    mul = _num(op.mul)
    return x if mul == 1.0 else x * mul


def _prev(x: Frame | float, panel: Any, gaps: list) -> Frame | float:
    return own_shift(panel, x, 1, gaps) if isinstance(x, pd.DataFrame) else x


def _frame(x: Any, like: Frame) -> Frame:
    return x if isinstance(x, pd.DataFrame) else pd.DataFrame(bool(x), index=like.index, columns=like.columns)


def _valid(x: Frame | float) -> Frame | bool:
    return x.notna() if isinstance(x, pd.DataFrame) else (not np.isnan(x))


def _hold(r: Frame, k: int) -> Frame:
    if k <= 1:
        return r
    return r.astype(float).rolling(k, min_periods=k).min().eq(1.0)


# ----------------------------------------------------------------------------- 조건·그룹
def _condition(c: Condition, panel: Any, market: Mapping[str, pd.DataFrame] | None, gaps: list,
               memo: dict | None = None, tctx: TimeContext | None = None) -> tuple[Frame, Any]:
    """(결과 bool 표, 유효 표 — 피연산자가 다 값 있는 곳). 유효 표는 그룹 negate 가 쓴다."""
    like = panel.close
    a = _operand(c.left, panel, market, gaps, memo, tctx)
    b = _operand(c.right, panel, market, gaps, memo, tctx) if c.right is not None else None
    valid = _valid(a)
    if b is not None:
        valid = valid & _valid(b)
    if c.op == "gt":
        r = a > b
    elif c.op == "gte":
        r = a >= b
    elif c.op == "lt":
        r = a < b
    elif c.op == "lte":
        r = a <= b
    elif c.op in ("cross_above", "cross_above_within"):
        pa, pb = _prev(a, panel, gaps), _prev(b, panel, gaps)
        r = (a > b) & (pa <= pb)
        valid = valid & _valid(pa) & _valid(pb)
    elif c.op in ("cross_below", "cross_below_within"):
        pa, pb = _prev(a, panel, gaps), _prev(b, panel, gaps)
        r = (a < b) & (pa >= pb)
        valid = valid & _valid(pa) & _valid(pb)
    elif c.op == "is_true":
        r = (a != 0) & valid
    else:  # is_false
        r = (a == 0) & valid
    r = _frame(r, like)
    if c.op in ("cross_above_within", "cross_below_within"):
        r = r.astype(float).rolling(int(c.within), min_periods=1).max().gt(0)  # 최근 k봉(t 포함) 안에 크로스
    return _hold(r, c.hold), valid


def _group(g: Group, panel: Any, market: Mapping[str, pd.DataFrame] | None, gaps: list,
           memo: dict | None = None, tctx: TimeContext | None = None) -> tuple[Frame, Any]:
    like = panel.close
    parts = [
        _group(i, panel, market, gaps, memo, tctx) if isinstance(i, Group) else _condition(i, panel, market, gaps, memo, tctx)
        for i in g.items
    ]
    out, valid = parts[0]
    for r, v in parts[1:]:
        out = (out & r) if g.logic == "all" else (out | r)
        valid = valid & v
    if g.negate:
        out = (~out) & _frame(valid, like)  # 값 없는 곳은 뒤집어도 참이 아니다
    return out, valid


def evaluate_group(
    g: Group, panel: Any, *, values: Mapping[str, float] | None = None,
    market: Mapping[str, pd.DataFrame] | None = None, memo: dict | None = None,
    daily: Any | None = None, bar_minutes: int | None = None, tctx: TimeContext | None = None,
) -> Frame:
    """Group → bool 표. `values` 가 있으면 {"param":..} 를 먼저 채운다. 빈 그룹은 전부 False.

    `memo`(선택, 그리드용): 같은 Panel 로 조합만 바꿔 부를 때 같은 (지표, 파라미터) 계산을 재사용하는 dict.
    **한 Panel 전용**(다른 Panel 이 오면 비우고 새로 시작), 결과 숫자는 memo 없을 때와 같다.
    `daily`·`bar_minutes`: 분봉 실행에서 시간 단위(mN·daily_prev·daily_live)를 쓰는 조건에 필요(일봉 Panel·실행 봉 길이(분)).
    `tctx`: 여러 그룹(진입·청산)이 시간 단위 준비물을 나눠 쓰려고 미리 만든 TimeContext.
    거래정지 빈칸이 있는 종목은 자기 거래일 기준으로 계산하고, 봉이 없는 날(종가 NaN)은 신호도 없다.
    """
    if values is not None:
        g = bind_group(g, values)
    if not g.items:
        return pd.DataFrame(False, index=panel.close.index, columns=panel.close.columns)
    if tctx is None and (daily is not None or bar_minutes is not None):
        tctx = TimeContext(panel, daily, bar_minutes)
    out, _ = _group(g, panel, market, panel_gaps(panel, memo), memo, tctx)
    return out & panel.close.notna()


def evaluate(
    entry: Group, exit_: Group, panel: Any, *, values: Mapping[str, float] | None = None,
    market: Mapping[str, pd.DataFrame] | None = None, market_filter: Group | None = None,
    memo: dict | None = None, daily: Any | None = None, bar_minutes: int | None = None,
) -> Evaluation:
    """진입·청산 bool 표. market_filter 는 진입에만 AND 로 얹는다(청산은 막지 않음). memo: evaluate_group 참고."""
    tctx = TimeContext(panel, daily, bar_minutes) if (daily is not None or bar_minutes is not None) else None
    kw = dict(values=values, market=market, memo=memo, daily=daily, bar_minutes=bar_minutes, tctx=tctx)
    e = evaluate_group(entry, panel, **kw)
    if market_filter is not None:
        e = e & evaluate_group(market_filter, panel, **kw)
    from .position import PosExitPlan, has_pos  # 지연 import — position 이 이 모듈의 함수를 쓴다
    if has_pos(exit_):
        plan = PosExitPlan(exit_, panel, market=market, memo=memo, tctx=tctx, bar_minutes=bar_minutes, values=values)
        return Evaluation(entry=e, exit=pd.DataFrame(False, index=panel.close.index, columns=panel.close.columns), pos_exit=plan)
    return Evaluation(entry=e, exit=evaluate_group(exit_, panel, **kw))


def to_signals(ev: Evaluation) -> Frame:
    """호환 모드용 신호 표: 기본 hold, 진입 → buy, 청산 → sell(둘 다면 sell — 기존 전략 대입 순서와 같음)."""
    arr = np.where(ev.exit.to_numpy(), SELL, np.where(ev.entry.to_numpy(), BUY, HOLD))
    return pd.DataFrame(arr, index=ev.entry.index, columns=ev.entry.columns)


__all__ = ["Evaluation", "evaluate", "evaluate_group", "to_signals", "INDEX_SCALE", "BUY", "SELL", "HOLD"]
