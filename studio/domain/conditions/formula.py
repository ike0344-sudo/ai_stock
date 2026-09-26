"""사용자 수식 → 조건 AST — 설계서 §3.5·§7. 토큰 → 재귀 하강 → AST(dict). **eval·exec·import 없음**.

`compile_formula(text)` 는 `Group` 형식의 dict 를 돌려준다(검증은 `Group.model_validate` — 형식이 아직 AST 에 없는
칸(tf·expr·pos·hold·negate)은 backtest-agent 의 AST 가 받아야 통과한다). 문법 오류는 `FormulaError(line, col, expected)`.

문법(대소문자 무시):  식 = 논리합 / 논리합 = 논리곱 (OR 논리곱)* / 논리곱 = 부정 (AND 부정)* / 부정 = NOT 부정 | 비교
  비교 = 합 (>|>=|<|<= 합)? | CROSSUP(합,합) | CROSSDOWN(합,합) | HOLD(비교,k)
  합 = 곱 ((+|-) 곱)* / 곱 = 단항 ((*|/) 단항)* / 단항 = -단항 | 뒤붙이 / 뒤붙이 = 기본 ('(' 정수 ')')?
  기본 = 숫자 | [단위.]필드 | [단위.]지표(인자,…) | POS.이름 | '(' 식 ')'     단위 = D DL M1 M3 M5 M10 M15 M30 M60

설계와 다르게 한 곳(근거는 보고서): ① NOT 은 비교 연산자를 뒤집어 안으로 밀어 넣는다(`NOT a>b` → `a<=b`, `NOT X` → is_false) — negate 그룹은
그룹 깊이(≤2)를 한 단 쓰기 때문이다(평가기의 negate 도 워밍업 NaN 을 참으로 만들지 않아 결과는 같다). 뒤집을 수 없는 것(크로스·within·HOLD)만 그룹 `negate`.
② 맨몸 값(`NEW_HIGH(20)`)은 `is_true`. ③ `=`·`!=` 는 AST 에 연산자가 없어 거부한다(부동소수 동치 비교도 의미가 약하다).
④ 컴파일러는 문자 그대로다(마법 없음). 시간 단위 규칙: `D.` = 일봉 지표를 **오늘 장 시작 전에 알 수 있는 값**으로 — 현재 봉을 빼는
highest/lowest(기본)는 일봉 행 D, 나머지(SMA·RSI 등)는 D−1. 그래서 `C > D.HIGHEST(H,20)` = 전일까지 20일 신고가 돌파(= `DL.HIGHEST(H,20)`
= `D.HIGHEST(H,20,TRUE)`; 설계서 §3.2 v0.3).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from .ast import MAX_EXPR_DEPTH, MAX_GROUP_DEPTH, MAX_HOLD, MAX_WITHIN, OFFSET_MAX  # 명세가 받는 한도와 같은 값을 쓴다
from .catalog import INDICATORS, ParamDef

MAX_LEN = 2_000      # 설계 §3.5 상한
MAX_DEPTH = 20
MAX_CALLS = 50

_FIELD_ALIAS = {"O": "open", "H": "high", "L": "low", "C": "close", "V": "volume", "VALUE": "value",
                "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close", "VOLUME": "volume"}
_UNITS = {"D": "daily_prev", "DL": "daily_live", **{f"M{n}": f"m{n}" for n in (1, 3, 5, 10, 15, 30, 60)}}
_POS_NAMES = ("return_pct", "bars_held", "minutes_held", "max_return_pct", "drawdown_pct", "entry_price")
_ALIAS_FUNC = {"MA": "sma"}
_RESERVED = {"AND", "OR", "NOT", "CROSSUP", "CROSSDOWN", "HOLD", "POS", *_UNITS}
_CMP = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}
_INVERSE = {"gt": "lte", "gte": "lt", "lt": "gte", "lte": "gt", "is_true": "is_false", "is_false": "is_true"}

_TOKEN = re.compile(r"""(?P<ws>\s+)|(?P<num>\d+(?:\.\d+)?)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)
                        |(?P<op>>=|<=|!=|==|>|<|=)|(?P<sym>[()+\-*/,.])""", re.X)


class FormulaError(ValueError):
    """수식 오류 — 위치는 1부터 센 (줄, 칸). expected 는 그 자리에 올 수 있는 것."""

    def __init__(self, message: str, line: int, col: int, expected: str = "") -> None:
        super().__init__(f"{line}줄 {col}칸: {message}" + (f" (예상: {expected})" if expected else ""))
        self.message, self.line, self.col, self.expected = message, line, col, expected

    def to_dict(self) -> dict[str, Any]:
        return {"message": self.message, "line": self.line, "col": self.col, "expected": self.expected}


@dataclass(frozen=True)
class _Tok:
    kind: str   # num name op sym end
    text: str
    line: int
    col: int

    @property
    def up(self) -> str:
        return self.text.upper()


def _tokenize(text: str) -> list[_Tok]:
    if len(text) > MAX_LEN:
        raise FormulaError(f"수식이 너무 깁니다({len(text)}자)", *_pos_of(text, MAX_LEN), f"{MAX_LEN}자 이하")
    out: list[_Tok] = []
    i = 0
    while i < len(text):
        m = _TOKEN.match(text, i)
        line, col = _pos_of(text, i)
        if m is None:
            raise FormulaError(f"알 수 없는 문자 {text[i]!r}", line, col, "숫자·이름·연산자·괄호")
        if m.lastgroup != "ws":
            out.append(_Tok(m.lastgroup or "", m.group(), line, col))
        i = m.end()
    line, col = _pos_of(text, len(text))
    out.append(_Tok("end", "", line, col))
    return out


def _pos_of(text: str, i: int) -> tuple[int, int]:
    head = text[:i]
    return head.count("\n") + 1, i - (head.rfind("\n") + 1) + 1


# ---- 중간 표현 ----
@dataclass
class _Val:
    """값(피연산자). num 이 있으면 상수(접기 대상)."""
    op: dict[str, Any]
    line: int
    col: int
    num: float | None = None
    pure: bool = False  # 필드·지표 피연산자(곱셈 상수를 mul 로 접을 수 있음)


@dataclass
class _Bool:
    d: dict[str, Any]   # Condition 또는 Group dict
    line: int
    col: int


def _const(v: float) -> dict[str, Any]:
    return {"kind": "const", "value": v}


def _is_group(d: dict[str, Any]) -> bool:
    return "logic" in d


def _group_depth(d: dict[str, Any]) -> int:
    return 1 + max((_group_depth(i) for i in d["items"] if _is_group(i)), default=0)


def _expr_depth(op: dict[str, Any]) -> int:
    return 1 + max(_expr_depth(op["left"]), _expr_depth(op["right"])) if op["kind"] == "expr" else 0


def _negate(node: dict[str, Any]) -> dict[str, Any]:
    """NOT — 뒤집을 수 있으면 연산자를 뒤집고 드모르간으로 안으로 민다, 못 뒤집는 것만 negate 그룹으로 감싼다."""
    if _is_group(node):
        if node.get("negate"):  # NOT(NOT g) = g
            return {k: v for k, v in node.items() if k != "negate"}
        return {"logic": "any" if node["logic"] == "all" else "all", "items": [_negate(i) for i in node["items"]]}
    if node["op"] in _INVERSE and node.get("hold", 1) == 1:
        return {k: (_INVERSE[node["op"]] if k == "op" else v) for k, v in node.items()}
    return {"logic": "all", "items": [node], "negate": True}


class _Parser:
    def __init__(self, text: str) -> None:
        self.toks = _tokenize(text)
        self.i = 0
        self.depth = 0
        self.calls = 0

    # ---- 토큰 도우미 ----
    @property
    def t(self) -> _Tok:
        return self.toks[self.i]

    def peek(self, k: int = 1) -> _Tok:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def take(self) -> _Tok:
        tok = self.toks[self.i]
        if tok.kind != "end":
            self.i += 1
        return tok

    def fail(self, msg: str, expected: str = "", tok: _Tok | None = None) -> FormulaError:
        tok = tok or self.t
        return FormulaError(msg, tok.line, tok.col, expected)

    def expect_sym(self, s: str, expected: str = "") -> _Tok:
        if self.t.kind == "sym" and self.t.text == s:
            return self.take()
        raise self.fail(f"{self.t.text or '수식 끝'!r} 자리에 '{s}' 가 필요합니다", expected or f"'{s}'")

    def is_sym(self, s: str) -> bool:
        return self.t.kind == "sym" and self.t.text == s

    def is_kw(self, w: str) -> bool:
        return self.t.kind == "name" and self.t.up == w

    def enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise self.fail(f"괄호·NOT·함수 중첩이 너무 깊습니다({MAX_DEPTH}단계 초과)", f"{MAX_DEPTH}단계 이하")

    def leave(self) -> None:
        self.depth -= 1

    # ---- 논리 ----
    def parse(self) -> dict[str, Any]:
        b = self.or_()
        if self.t.kind != "end":
            raise self.fail(f"{self.t.text!r} 를 해석할 수 없습니다", "AND · OR · 수식 끝")
        d = b.d if _is_group(b.d) else {"logic": "all", "items": [b.d]}
        if _group_depth(d) > MAX_GROUP_DEPTH:
            raise FormulaError(f"AND/OR 를 {MAX_GROUP_DEPTH}겹 넘게 섞을 수 없습니다(현재 {_group_depth(d)}겹)", b.line, b.col,
                               "괄호를 줄이거나 조건을 나눠서 저장")
        return d

    def _join(self, logic: str, parts: list[_Bool]) -> _Bool:
        if len(parts) == 1:
            return parts[0]
        items: list[dict[str, Any]] = []
        for p in parts:  # 같은 논리의 중첩(negate 없음)은 펴서 단계를 아낀다 — 결합법칙
            if _is_group(p.d) and p.d["logic"] == logic and not p.d.get("negate"):
                items.extend(p.d["items"])
            else:
                items.append(p.d)
        return _Bool({"logic": logic, "items": items}, parts[0].line, parts[0].col)

    def or_(self) -> _Bool:
        parts = [self.and_()]
        while self.is_kw("OR"):
            self.take()
            parts.append(self.and_())
        return self._join("any", parts)

    def and_(self) -> _Bool:
        parts = [self.not_()]
        while self.is_kw("AND"):
            self.take()
            parts.append(self.not_())
        return self._join("all", parts)

    def not_(self) -> _Bool:
        if self.is_kw("NOT"):
            tok = self.take()
            self.enter()
            inner = self.not_()
            self.leave()
            return _Bool(_negate(inner.d), tok.line, tok.col)
        return self.compare()

    def compare(self) -> _Bool:
        start = self.t
        if start.kind == "name" and start.up in ("CROSSUP", "CROSSDOWN"):
            return self.cross()
        if start.kind == "name" and start.up == "HOLD":
            return self.hold()
        if self.is_sym("(") and self._paren_is_logic():
            self.take()
            self.enter()
            inner = self.or_()
            self.expect_sym(")")
            self.leave()
            return _Bool(inner.d, start.line, start.col)
        left = self.add()
        if self.t.kind == "op":
            optok = self.take()
            if optok.text not in _CMP:
                raise self.fail(f"'{optok.text}' 비교는 아직 지원하지 않습니다(부동소수 같음 비교는 의미가 약합니다)",
                                "> >= < <=  (값이 1/0 인 지표는 그냥 `조건` 만 쓰면 됩니다)", optok)
            right = self.add()
            if self.t.kind == "op":
                raise self.fail("비교를 한 번에 두 번 쓸 수 없습니다", "AND 로 나눠 쓰세요(예: A < B AND B < C)")
            return self._cond(left, _CMP[optok.text], right, start)
        # 맨몸 값 = 1/0 지표의 참 여부 → is_true(right 없음)
        if left.num is not None:
            raise FormulaError("상수만으로는 조건이 안 됩니다", start.line, start.col, "지표·가격과의 비교")
        return _Bool({"left": left.op, "op": "is_true"}, start.line, start.col)

    def _paren_is_logic(self) -> bool:
        """지금 '(' 가 논리 묶음인가 산술 괄호인가 — 짝이 맞는 ')' 까지 훑어 비교 연산자·AND/OR/NOT/CROSS/HOLD 가 있으면 논리.
        (산술 괄호 안에는 이런 게 못 온다 — 함수 인자는 숫자 상수뿐.) 짝이 안 맞으면 산술로 보고 거기서 오류를 낸다."""
        depth = 0
        logic = False
        for tok in self.toks[self.i:]:
            if tok.kind == "sym" and tok.text == "(":
                depth += 1
            elif tok.kind == "sym" and tok.text == ")":
                depth -= 1
                if depth == 0:
                    return logic
            elif tok.kind == "op" or (tok.kind == "name" and tok.up in ("AND", "OR", "NOT", "CROSSUP", "CROSSDOWN", "HOLD")):
                logic = True
        return False

    def _cond(self, left: _Val, op: str, right: _Val, start: _Tok) -> _Bool:
        if left.num is not None and right.num is not None:
            raise FormulaError("상수끼리 비교할 수 없습니다", start.line, start.col, "한쪽은 지표·가격")
        return _Bool({"left": left.op, "op": op, "right": right.op}, start.line, start.col)

    def cross(self) -> _Bool:
        kw = self.take()
        self.calls_inc(kw)
        self.expect_sym("(")
        self.enter()
        a = self.add()
        self.expect_sym(",", "두 번째 값")
        b = self.add()
        within = None
        if self.is_sym(","):  # CROSSUP(a, b, k) = 최근 k봉 안에 상향 돌파가 있었다
            self.take()
            ktok = self.t
            k = self.add()
            if k.num is None or not float(k.num).is_integer() or not 1 <= k.num <= MAX_WITHIN:
                raise self.fail(f"k 는 1~{MAX_WITHIN} 정수여야 합니다", f"1~{MAX_WITHIN} 의 정수", ktok)
            within = int(k.num)
        self.leave()
        self.expect_sym(")", "')'")
        up = kw.up == "CROSSUP"
        r = self._cond(a, ("cross_above" if up else "cross_below") + ("_within" if within else ""), b, kw)
        if within:
            r.d["within"] = within
        return r

    def hold(self) -> _Bool:
        kw = self.take()
        self.calls_inc(kw)
        self.expect_sym("(")
        self.enter()
        inner = self.compare()
        self.leave()
        if _is_group(inner.d):
            raise FormulaError("HOLD 는 비교 하나에만 걸 수 있습니다(AND/OR 묶음 불가)", inner.line, inner.col, "HOLD(비교, k)")
        self.expect_sym(",", "연속 봉 수 k")
        ktok = self.t
        k = self.add()
        if k.num is None or not float(k.num).is_integer() or not 1 <= k.num <= MAX_HOLD:
            raise self.fail(f"연속 봉 수 k 는 1~{MAX_HOLD} 정수여야 합니다", f"1~{MAX_HOLD} 의 정수", ktok)
        self.expect_sym(")")
        if inner.d.get("hold", 1) != 1:  # HOLD(HOLD(..)) 같은 겹침은 의미가 모호하다
            raise FormulaError("HOLD 를 겹쳐 쓸 수 없습니다", kw.line, kw.col, "HOLD(비교, k)")
        d = {**inner.d, "hold": int(k.num)}
        return _Bool(d, kw.line, kw.col)

    def calls_inc(self, tok: _Tok) -> None:
        self.calls += 1
        if self.calls > MAX_CALLS:
            raise self.fail(f"함수 호출이 너무 많습니다({MAX_CALLS}개 초과)", f"{MAX_CALLS}개 이하", tok)

    # ---- 산술 ----
    def add(self) -> _Val:
        left = self.mul()
        while self.is_sym("+") or self.is_sym("-"):
            op = self.take().text
            left = self._arith(op, left, self.mul())
        return left

    def mul(self) -> _Val:
        left = self.unary()
        while self.is_sym("*") or self.is_sym("/"):
            optok = self.take()
            left = self._arith(optok.text, left, self.unary(), optok)
        return left

    def unary(self) -> _Val:
        if self.is_sym("-"):
            tok = self.take()
            self.enter()
            x = self.unary()
            self.leave()
            return self._arith("*", _Val(_const(-1.0), tok.line, tok.col, num=-1.0), x)
        if self.is_sym("+"):  # 단항 + 는 문법에 없다
            raise self.fail("단항 '+' 는 쓸 수 없습니다", "숫자·이름·'-'·'('")
        return self.postfix()

    def _arith(self, op: str, a: _Val, b: _Val, optok: _Tok | None = None) -> _Val:
        if a.num is not None and b.num is not None:  # 상수 접기
            if op == "/" and b.num == 0:
                t = optok or self.t
                raise FormulaError("0 으로 나눌 수 없습니다", t.line, t.col, "0 이 아닌 값")
            r = {"+": a.num + b.num, "-": a.num - b.num, "*": a.num * b.num, "/": a.num / b.num if b.num else 0.0}[op]
            if not math.isfinite(r):
                raise FormulaError("계산 결과가 너무 큽니다", a.line, a.col)
            return _Val(_const(r), a.line, a.col, num=r)
        if op == "*":  # 필드·지표 × 상수 → mul (조립기로 만든 명세와 같은 모양)
            for x, k in ((a, b), (b, a)):
                if x.pure and k.num is not None:
                    m = float(x.op["mul"]) * k.num
                    return _Val({**x.op, "mul": m}, a.line, a.col, pure=True)
        node = {"kind": "expr", "op": op, "left": a.op, "right": b.op}
        if _expr_depth(node) > MAX_EXPR_DEPTH:
            raise FormulaError(f"산술이 너무 깊습니다({MAX_EXPR_DEPTH}단계 초과)", a.line, a.col, f"{MAX_EXPR_DEPTH}단계 이하")
        return _Val(node, a.line, a.col)

    # ---- 기본 ----
    def postfix(self) -> _Val:
        start = self.t
        v = self.primary()
        if self.is_sym("("):  # 오프셋 X(k)
            if not v.pure:
                raise self.fail("오프셋 (k) 는 필드·지표 바로 뒤에만 쓸 수 있습니다", "연산자")
            self.take()
            ktok = self.t
            if self.is_sym("-"):
                raise self.fail("오프셋은 음수일 수 없습니다(미래 값은 볼 수 없습니다)", "0 이상의 정수")
            if ktok.kind != "num" or not ktok.text.isdigit() or int(ktok.text) > OFFSET_MAX:
                raise self.fail("오프셋은 0~%d 의 정수여야 합니다" % OFFSET_MAX, "0~%d 의 정수" % OFFSET_MAX)
            self.take()
            self.expect_sym(")")
            v = _Val({**v.op, "offset": int(ktok.text)}, start.line, start.col, pure=True)
        return v

    def primary(self) -> _Val:
        tok = self.t
        if tok.kind == "num":
            self.take()
            n = float(tok.text)
            if not math.isfinite(n):
                raise self.fail("숫자가 너무 큽니다", "", tok)
            return _Val(_const(n), tok.line, tok.col, num=n)
        if self.is_sym("("):
            self.take()
            self.enter()
            v = self.add()
            self.leave()
            self.expect_sym(")")
            return _Val(v.op, tok.line, tok.col, v.num, False)  # 괄호로 묶은 값에는 오프셋 불가(pure 해제)
        if tok.kind != "name":
            raise self.fail(f"{tok.text or '수식 끝'!r} 자리에 값이 필요합니다", "숫자 · 필드(C,O,H,L,V,VALUE) · 지표 · '('")
        return self.named()

    def named(self) -> _Val:
        first = self.take()
        up = first.up
        unit: str | None = None
        if up == "POS" and self.is_sym("."):
            self.take()
            nt = self.t
            if nt.kind != "name" or nt.text.lower() not in _POS_NAMES:
                raise self.fail(f"모르는 포지션 값 {nt.text!r}", ", ".join(n.upper() for n in _POS_NAMES))
            self.take()
            return _Val({"kind": "pos", "name": nt.text.lower()}, first.line, first.col)
        if up in _UNITS:
            if not self.is_sym("."):
                raise self.fail(f"'{first.text}' 는 시간 단위입니다 — 뒤에 '.' 과 필드·지표가 와야 합니다(예: {first.up}.C)",
                                "'.'", self.t)
            self.take()
            unit = _UNITS[up]
            first = self.take() if self.t.kind == "name" else self.t
            if first.kind != "name":
                raise self.fail("단위 뒤에는 필드나 지표 이름이 와야 합니다", "C · MA(C,20) 같은 이름", first)
            up = first.up
            if up in _UNITS or up == "POS":
                raise self.fail("단위를 두 번 붙일 수 없습니다", "", first)
        if up in _RESERVED:
            raise self.fail(f"'{first.text}' 는 예약어라 값 자리에 쓸 수 없습니다", "필드 · 지표", first)
        if up in _FIELD_ALIAS:
            op: dict[str, Any] = {"kind": "field", "name": _FIELD_ALIAS[up], "offset": 0, "mul": 1.0}
        else:
            op = self.indicator(first)
        if unit is not None:
            op["tf"] = unit
        return _Val(op, first.line, first.col, pure=True)

    def indicator(self, first: _Tok) -> dict[str, Any]:
        name = _ALIAS_FUNC.get(first.up) or next((n for n in INDICATORS if n.upper() == first.up), None)
        if name is None:
            near = sorted(n.upper() for n in INDICATORS)
            raise self.fail(f"모르는 이름 '{first.text}'", "필드(O H L C V VALUE) 또는 지표: " + " ".join(near), first)
        d = INDICATORS[name]
        params: dict[str, Any] = {}
        if self.is_sym("("):
            self.calls_inc(first)
            self.take()
            self.enter()
            if not self.is_sym(")"):
                while True:
                    if len(params) >= len(d.params):
                        raise self.fail(f"{first.up} 의 인자는 최대 {len(d.params)}개입니다", self._sig(d))
                    p = d.params[len(params)]
                    params[p.name] = self.param_value(first, p)
                    if self.is_sym(","):
                        self.take()
                        continue
                    break
            self.leave()
            self.expect_sym(")", self._sig(d))
        elif d.params:
            raise self.fail(f"{first.up} 뒤에는 '(' 인자 ')' 가 필요합니다", self._sig(d), self.t)
        return {"kind": "ind", "name": name, "params": params, "offset": 0, "mul": 1.0}

    @staticmethod
    def _sig(d: Any) -> str:
        return f"{d.name.upper()}(" + ", ".join(p.name for p in d.params) + ")"

    def param_value(self, fn: _Tok, p: ParamDef) -> Any:
        tok = self.t
        if p.kind == "enum":
            if tok.kind != "name":
                raise self.fail(f"{p.name} 는 {list(p.choices or ())} 중 하나여야 합니다", " ".join(p.choices or ()))
            self.take()
            low = tok.text.lower()
            v = low if low in (p.choices or ()) else _FIELD_ALIAS.get(tok.up)
            if v not in (p.choices or ()):
                raise self.fail(f"{p.name} 에 {tok.text!r} 는 쓸 수 없습니다", " ".join(p.choices or ()), tok)
            return v
        if p.kind == "bool":
            self.take()
            v = {"TRUE": True, "FALSE": False, "1": True, "0": False}.get(tok.up)
            if v is None:
                raise self.fail(f"{p.name} 는 TRUE/FALSE(또는 1/0) 여야 합니다", "TRUE · FALSE", tok)
            return v
        val = self.add()  # 숫자 인자는 상수 식(예: 10*2)까지 허용 — 접혀서 상수가 되어야 한다
        if val.num is None:
            raise self.fail(f"{p.name} 는 숫자 상수여야 합니다(지표·가격은 인자로 쓸 수 없습니다)", "숫자", tok)
        n = val.num
        if p.kind == "int":
            if not float(n).is_integer():
                raise self.fail(f"{p.name} 는 정수여야 합니다(받은 값 {n:g})", "정수", tok)
            n = int(n)
        if (p.lo is not None and n < p.lo) or (p.hi is not None and n > p.hi):
            raise self.fail(f"{p.name} 는 {p.lo:g}~{p.hi:g} 범위여야 합니다(받은 값 {n:g})", f"{p.lo:g}~{p.hi:g}", tok)
        return n


def compile_formula(text: str) -> dict[str, Any]:
    """수식 문자열 → `Group` 형식 dict. 실패하면 `FormulaError`. 상태 없음·부작용 없음."""
    if not isinstance(text, str) or not text.strip():
        raise FormulaError("수식이 비어 있습니다", 1, 1, "조건식")
    return _Parser(text).parse()
