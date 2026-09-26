"""포지션(pos) 피연산자가 든 청산 조건 — 보유 종목마다 봉 t 에서 평가한다. 설계 studio-conditions §3.3 포지션 표·§3.4, c2.

평가기(evaluator)는 값 표(종목×봉)를 통째로 만들지만 `pos.*` 는 **보유 중인 종목에만** 값이 있고 그 값이 진입 시점·경로에 달려 있어
표로 미리 만들 수 없다. 그래서 청산 그룹을 트리로 컴파일한다:
  · pos 가 없는 조건·하위 그룹 → 평가기로 **미리 계산한 표**(불리언 + 유효 표)를 [t, 종목] 으로 읽는다(값은 t 종가까지의 것)
  · pos 가 든 조건 → 피연산자를 스칼라로 평가(pos 값은 엔진이 넘기고, 나머지는 미리 계산한 표에서 읽는다)
    cross·within·hold 가 쓰는 "이전 봉 값"·"연속 횟수"는 **그 보유 포지션의 자기 상태**(`new_state()`)에 쌓는다.
결과는 봉 t 종가 기준 신호 — 엔진이 다음 봉 시가에 체결한다(exit_reason=signal). 미래 값은 읽지 않는다(C7).

pos 값(봉 t 종가 기준, 엔진이 `vals` 로 준다):
  return_pct = (C_t / 매수가 − 1)×100 · bars_held/minutes_held = 진입 봉을 1로 센 봉 수·분 · max_return_pct = 보유 중 고가 기준 최고 수익률 ·
  drawdown_pct = 보유 중 최고가 대비 현재가 하락률(**양수 %**, 5 = 고점보다 5% 아래) · entry_price = 매수가(슬리피지 반영 체결가).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from .ast import ConstOperand, ExprOperand, Group, PosOperand, bind_group, iter_operands
from .evaluator import _frame, _group, _condition, _num, _operand
from .indicators import panel_gaps
from .timeframe import TimeContext

_NAN = float("nan")
_BIG = 10**9


def has_pos(g: Group) -> bool:
    return any(isinstance(o, PosOperand) for o in iter_operands(g))


def _op_has_pos(op: Any) -> bool:
    if isinstance(op, PosOperand):
        return True
    if isinstance(op, ExprOperand):
        return _op_has_pos(op.left) or _op_has_pos(op.right)
    return False


class PosExitPlan:
    """pos 가 든 청산 그룹 하나의 컴파일 결과. `evaluate()` 가 만들고 엔진(`run_portfolio(pos_exit=...)`)이 부른다."""

    def __init__(self, group: Group, panel: Any, *, market: Mapping[str, pd.DataFrame] | None = None,
                 memo: dict | None = None, tctx: TimeContext | None = None, bar_minutes: int | None = None,
                 values: Mapping[str, float] | None = None) -> None:
        if values is not None:
            group = bind_group(group, values)
        self.bar_minutes = bar_minutes
        self.shape = panel.close.shape
        self._panel, self._market, self._memo, self._tctx = panel, market, memo, tctx
        self._gaps = panel_gaps(panel, memo)
        self._like = panel.close
        self.arrays: list[np.ndarray] = []
        self._n_state = 0
        self._root = self._build(group)
        del self._panel, self._market, self._memo, self._tctx, self._gaps, self._like

    # ------------------------------------------------------------------ 컴파일
    def _add(self, x: Any) -> int:
        self.arrays.append(np.asarray(x.to_numpy() if isinstance(x, pd.DataFrame) else x))
        return len(self.arrays) - 1

    def _build(self, g: Group) -> tuple:
        kids: list[tuple] = []
        for it in g.items:
            if isinstance(it, Group):
                if has_pos(it):
                    kids.append(self._build(it))
                else:
                    r, v = _group(it, self._panel, self._market, self._gaps, self._memo, self._tctx)
                    kids.append(("s", self._add(r.astype(bool)), self._add(_frame(v, self._like).astype(bool))))
            elif _op_has_pos(it.left) or (it.right is not None and _op_has_pos(it.right)):
                fa = self._opfn(it.left)
                fb = self._opfn(it.right) if it.right is not None else None
                self._n_state += 1
                kids.append(("p", self._n_state, it.op, int(it.hold), int(it.within) if it.within else 0, fa, fb))
            else:
                r, v = _condition(it, self._panel, self._market, self._gaps, self._memo, self._tctx)
                kids.append(("s", self._add(r.astype(bool)), self._add(_frame(v, self._like).astype(bool))))
        return ("g", g.logic, bool(g.negate), kids)

    def _opfn(self, op: Any) -> Callable:
        if isinstance(op, ConstOperand):
            v = _num(op.value)
            return lambda A, i, c, vals: v
        if isinstance(op, PosOperand):
            name = op.name
            return lambda A, i, c, vals: vals[name]
        if isinstance(op, ExprOperand):
            fl, fr, o = self._opfn(op.left), self._opfn(op.right), op.op

            def f(A, i, c, vals):
                a, b = fl(A, i, c, vals), fr(A, i, c, vals)
                if o == "+":
                    return a + b
                if o == "-":
                    return a - b
                if o == "*":
                    return a * b
                return a / b if b != 0 and b == b else _NAN  # 0 으로 나누면 값 없음(= 조건 거짓)
            return f
        k = self._add(_operand(op, self._panel, self._market, self._gaps, self._memo, self._tctx))
        return lambda A, i, c, vals: A[k][i, c]

    # ------------------------------------------------------------------ 엔진 쪽
    def sliced(self, mask: Any) -> "PosExitPlan":
        """엔진이 워밍업을 뗀 구간(행 마스크)만 쓸 때 — 표를 같은 마스크로 자른 복사본(트리는 공유)."""
        new = object.__new__(PosExitPlan)
        new.__dict__.update(self.__dict__)
        new.arrays = [a[mask] if a.ndim == 2 else a for a in self.arrays]
        new.shape = (int(np.asarray(mask).sum()), self.shape[1])
        return new

    def new_state(self) -> dict:
        """보유 포지션 하나의 조건별 상태(이전 봉 값·연속 횟수) — 청산되면 버린다."""
        return {}

    def decide(self, i: int, c: int, st: dict, vals: Mapping[str, float]) -> bool:
        """봉 t=i, 종목 c 의 보유 포지션이 이 봉 종가 기준 청산 조건을 만족하나. **매 보유 봉마다 불러야** 한다(상태가 이어진다)."""
        return bool(self._node(self._root, i, c, st, vals)[0])

    def _node(self, n: tuple, i: int, c: int, st: dict, vals: Mapping[str, float]) -> tuple[bool, bool]:
        kind = n[0]
        if kind == "s":
            return bool(self.arrays[n[1]][i, c]), bool(self.arrays[n[2]][i, c])
        if kind == "p":
            return self._cond(n, i, c, st, vals)
        _, logic, negate, kids = n
        res = [self._node(k, i, c, st, vals) for k in kids]  # 짧게 끊지 않는다 — 상태가 있는 조건이 매 봉 갱신돼야 한다
        rs, vs = [r for r, _ in res], [v for _, v in res]
        out = all(rs) if logic == "all" else any(rs)
        valid = all(vs)
        if negate:
            out = (not out) and valid  # 값 없는 곳은 뒤집어도 참이 아니다(평가기와 같음)
        return out, valid

    def _cond(self, n: tuple, i: int, c: int, st: dict, vals: Mapping[str, float]) -> tuple[bool, bool]:
        _, key, op, hold, within, fa, fb = n
        A = self.arrays
        a = fa(A, i, c, vals)
        b = fb(A, i, c, vals) if fb is not None else None
        s = st.setdefault(key, {"pa": _NAN, "pb": _NAN, "run": 0, "since": _BIG})
        valid = a == a and (b is None or b == b)
        if op == "gt":
            r = valid and a > b
        elif op == "gte":
            r = valid and a >= b
        elif op == "lt":
            r = valid and a < b
        elif op == "lte":
            r = valid and a <= b
        elif op in ("cross_above", "cross_above_within", "cross_below", "cross_below_within"):
            pa, pb = s["pa"], s["pb"]
            valid = valid and pa == pa and pb == pb
            up = op.startswith("cross_above")
            r = valid and ((a > b and pa <= pb) if up else (a < b and pa >= pb))
            s["pa"], s["pb"] = a, b
        elif op == "is_true":
            r = valid and a != 0
        else:  # is_false
            r = valid and a == 0
        if op in ("cross_above_within", "cross_below_within"):
            s["since"] = 0 if r else min(s["since"] + 1, _BIG)
            r = s["since"] < within
        if hold > 1:
            s["run"] = s["run"] + 1 if r else 0
            r = s["run"] >= hold
        return bool(r), bool(valid)


__all__ = ["PosExitPlan", "has_pos"]
