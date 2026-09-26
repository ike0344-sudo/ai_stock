"""조건식 AST — 설계서 §3.2. pydantic v2 검증(오류는 loc 경로 포함).

Group(all/any, 깊이 ≤ 2, negate) → Condition(left op right, hold) → Operand(field/ind/market/const/expr/pos).
숫자 칸은 `number | {"param": 이름}` — 최적화 변수. `bind_group`/`bind_tree` 로 값을 채운다.
domain 계층: pydantic·stdlib 만 쓴다(§9.3).

studio-conditions c1 확장(설계 studio-conditions §3.1) — **새 칸은 전부 기본값이 옛 동작**(저장된 명세·프리셋·결과 그대로):
  · 피연산자 `tf`(시간 단위, 기본 "bar") — field·ind 에 붙는다. 모드·live 지원 검사는 여기(지표 단위)와 validation.py(모드·출처·청산 전용)
  · `expr`(산술 + − × ÷, 깊이 ≤ 8, 수식용) · `pos`(포지션 값 — **청산 조건 전용**, 평가는 엔진(c2))
  · Condition `hold`(연속 k봉 만족, 기본 1) · `within`(cross_*_within 의 k) · 연산자 cross_above_within / cross_below_within / is_true / is_false
  · Group `negate`(NOT)
"""
from __future__ import annotations

from typing import Annotated, Any, Iterator, Literal, Mapping, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .catalog import INDICATORS, MARKET_INDEXES, MARKET_NAMES, MINUTE_TIMEFRAMES, N_MAX, N_MIN, ParamDef

MAX_GROUP_DEPTH = 2  # 근거: 화면 편집기가 하위 그룹 1단계까지(§5.4)
OFFSET_MAX = N_MAX
OPS = ("gt", "gte", "lt", "lte", "cross_above", "cross_below", "cross_above_within", "cross_below_within", "is_true", "is_false")
WITHIN_OPS = ("cross_above_within", "cross_below_within")
UNARY_OPS = ("is_true", "is_false")  # 왼쪽 값 하나만 본다(1/0 지표용) — right 없음
MAX_EXPR_DEPTH = 8
MAX_HOLD = 50
MAX_WITHIN = 50
Timeframe = Literal["bar", "m1", "m3", "m5", "m10", "m15", "m30", "m60", "daily_prev", "daily_live"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ParamRef(_M):
    param: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


Num = Union[float, ParamRef]
ParamValue = Union[ParamRef, bool, int, float, str]


def _check_param(owner: str, p: ParamDef, v: Any) -> None:
    if isinstance(v, ParamRef):
        return  # 범위는 Spec 단계에서 params 범위와 대조
    if p.kind == "bool":
        if not isinstance(v, bool):
            raise ValueError(f"{owner}.{p.name}: true/false 여야 함 (받은 값 {v!r})")
    elif p.kind == "enum":
        if v not in (p.choices or ()):
            raise ValueError(f"{owner}.{p.name}: {v!r} 는 허용값 {list(p.choices or ())} 이 아님")
    else:
        if isinstance(v, (bool, str)):
            raise ValueError(f"{owner}.{p.name}: 숫자여야 함 (받은 값 {v!r})")
        if p.kind == "int" and not float(v).is_integer():
            raise ValueError(f"{owner}.{p.name}: 정수여야 함 (받은 값 {v!r})")
        if (p.lo is not None and v < p.lo) or (p.hi is not None and v > p.hi):
            raise ValueError(f"{owner}.{p.name}: {v} 는 범위 {p.lo}~{p.hi} 밖")


class FieldOperand(_M):
    kind: Literal["field"]
    name: Literal["open", "high", "low", "close", "volume", "value"]
    offset: int = Field(0, ge=0, le=OFFSET_MAX)  # 음수 금지 = 미래 참조 금지. 며칠·몇 봉 전은 tf 자신의 단위로
    mul: Num = 1.0
    tf: Timeframe = "bar"


class IndOperand(_M):
    kind: Literal["ind"]
    name: str
    params: dict[str, ParamValue] = Field(default_factory=dict)
    offset: int = Field(0, ge=0, le=OFFSET_MAX)
    mul: Num = 1.0
    tf: Timeframe = "bar"

    @model_validator(mode="after")
    def _check(self) -> "IndOperand":
        d = INDICATORS.get(self.name)
        if d is None:
            raise ValueError(f"없는 지표 '{self.name}' (가능: {sorted(INDICATORS)})")
        if self.tf == "daily_live" and not d.live:
            raise ValueError(f"지표 '{self.name}' 는 일봉 장중(daily_live)을 지원하지 않는다 — 점화식이 O(1) 인 지표만 된다. "
                             "일봉 전일(daily_prev)로 쓰거나 지원 지표(live)로 바꿔라")
        if self.tf in ("daily_prev", "daily_live") and not (set(d.modes) & {"daily_single", "daily_portfolio"}):
            raise ValueError(f"지표 '{self.name}' 는 분봉 전용이라 일봉 시간 단위({self.tf})로 쓸 수 없다")
        if self.tf in MINUTE_TIMEFRAMES and "intraday" not in d.modes:
            raise ValueError(f"지표 '{self.name}' 는 일봉 전용이라 분봉 시간 단위({self.tf})로 쓸 수 없다 — 일봉 시간 단위(daily_prev)를 써라")
        known = {p.name: p for p in d.params}
        for k, v in self.params.items():
            if k not in known:
                raise ValueError(f"지표 '{self.name}' 에 없는 파라미터 '{k}' (가능: {sorted(known)})")
            _check_param(self.name, known[k], v)
        return self


class MarketOperand(_M):
    kind: Literal["market"]
    index: Literal["kospi", "kosdaq"]
    name: Literal["close", "sma", "change_pct"]
    params: dict[str, ParamValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "MarketOperand":
        allowed = set() if self.name == "close" else {"n"}
        extra = set(self.params) - allowed
        if extra:
            raise ValueError(f"시장 '{self.name}' 에 없는 파라미터 {sorted(extra)}")
        if "n" in self.params:
            _check_param(f"market.{self.name}", ParamDef("n", "int", 20, N_MIN, N_MAX), self.params["n"])
        return self


class ConstOperand(_M):
    kind: Literal["const"]
    value: Num


class PosOperand(_M):
    """포지션 값 — 보유 종목마다 봉 t 에서 엔진이 평가한다. **청산 조건 그룹에서만** 쓸 수 있다(보유 전엔 값이 없다 — validation.py)."""

    kind: Literal["pos"]
    name: Literal["return_pct", "bars_held", "minutes_held", "max_return_pct", "drawdown_pct", "entry_price"]


class ExprOperand(_M):
    """산술 피연산자 `left op right` (+ − × ÷) — 사용자 수식용. 깊이 ≤ 8. 0 으로 나누면 NaN(= 조건 거짓)."""

    kind: Literal["expr"]
    op: Literal["+", "-", "*", "/"]
    left: "Operand"
    right: "Operand"

    @property
    def depth(self) -> int:
        return 1 + max(_expr_depth(self.left), _expr_depth(self.right))

    @model_validator(mode="after")
    def _check(self) -> "ExprOperand":
        if self.depth > MAX_EXPR_DEPTH:
            raise ValueError(f"산술 식은 {MAX_EXPR_DEPTH}단계까지 (현재 {self.depth}단계)")
        return self


def _expr_depth(op: Any) -> int:
    return op.depth if isinstance(op, ExprOperand) else 0


Operand = Annotated[
    Union[FieldOperand, IndOperand, MarketOperand, ConstOperand, PosOperand, ExprOperand], Field(discriminator="kind")
]
ExprOperand.model_rebuild()


class Condition(_M):
    left: Operand
    op: Literal["gt", "gte", "lt", "lte", "cross_above", "cross_below",
                "cross_above_within", "cross_below_within", "is_true", "is_false"]
    right: Operand | None = None  # is_true / is_false 는 없음(왼쪽 값 하나만 본다)
    hold: int = Field(1, ge=1, le=MAX_HOLD)  # 연속 k봉 만족(기본 1 = 그 봉만)
    within: int | None = Field(None, ge=1, le=MAX_WITHIN)  # cross_*_within 의 k — 최근 k봉 안에 크로스가 있었나

    @model_validator(mode="after")
    def _check(self) -> "Condition":
        if self.op in UNARY_OPS:
            if self.right is not None:
                raise ValueError(f"연산자 '{self.op}' 는 오른쪽 값이 없다(왼쪽 값이 0 이 아닌지/0 인지만 본다)")
        elif self.right is None:
            raise ValueError(f"연산자 '{self.op}' 는 오른쪽 값이 필요하다")
        if self.op in WITHIN_OPS:
            if self.within is None:
                raise ValueError(f"연산자 '{self.op}' 는 within(최근 몇 봉 안인지)이 필요하다")
        elif self.within is not None:
            raise ValueError(f"within 은 cross_above_within·cross_below_within 에서만 쓴다(연산자 '{self.op}')")
        if isinstance(self.left, ConstOperand) and isinstance(self.right, ConstOperand):
            raise ValueError("상수끼리 비교할 수 없음 — 한쪽은 지표·가격이어야 함")
        return self


class Group(_M):
    logic: Literal["all", "any"]
    items: list[Union[Condition, "Group"]] = Field(default_factory=list)
    negate: bool = False  # 그룹 전체를 뒤집는다(NOT)
    # 사용자 수식 원문(설계 §3.5 "원문도 명세에 같이 저장(재현)") — 맨 위 그룹(entry/exit)에서만 쓴다. **평가·해시에는 무시**(같은 AST 면 같은 전략).
    formula: str | None = Field(None, max_length=2000)

    @property
    def depth(self) -> int:
        return 1 + max((i.depth for i in self.items if isinstance(i, Group)), default=0)

    @model_validator(mode="after")
    def _check(self) -> "Group":
        if self.depth > MAX_GROUP_DEPTH:
            raise ValueError(f"조건 그룹은 {MAX_GROUP_DEPTH}단계까지 (현재 {self.depth}단계)")
        return self


Group.model_rebuild()


def iter_conditions(g: Group) -> Iterator[Condition]:
    for it in g.items:
        if isinstance(it, Group):
            yield from iter_conditions(it)
        else:
            yield it


def _leaves(op: Any) -> Iterator[Any]:
    if isinstance(op, ExprOperand):
        yield from _leaves(op.left)
        yield from _leaves(op.right)
    else:
        yield op


def iter_operands(g: Group) -> Iterator[Operand]:
    """조건 안의 **잎 피연산자**(field·ind·market·const·pos) — expr 는 안쪽 잎으로 펼친다."""
    for c in iter_conditions(g):
        yield from _leaves(c.left)
        if c.right is not None:
            yield from _leaves(c.right)


def iter_param_slots(g: Group) -> Iterator[tuple[str, float | None, float | None, bool]]:
    """{"param":..} 가 쓰인 칸마다 (변수 이름, 허용 최소, 허용 최대, 정수 여부). 범위 없으면 None."""
    for op in iter_operands(g):
        if isinstance(op, IndOperand):
            d = INDICATORS[op.name]
            for k, v in op.params.items():
                p = d.param(k)
                if isinstance(v, ParamRef) and p is not None and p.numeric:
                    yield v.param, p.lo, p.hi, p.kind == "int"
            if isinstance(op.mul, ParamRef):
                yield op.mul.param, None, None, False
        elif isinstance(op, FieldOperand):
            if isinstance(op.mul, ParamRef):
                yield op.mul.param, None, None, False
        elif isinstance(op, MarketOperand):
            v = op.params.get("n")
            if isinstance(v, ParamRef):
                yield v.param, N_MIN, N_MAX, True
        elif isinstance(op, ConstOperand) and isinstance(op.value, ParamRef):
            yield op.value.param, None, None, False


def bind_tree(data: Any, values: Mapping[str, float]) -> Any:
    """dict/list 트리에서 {"param": 이름} 을 값으로 치환한 사본. 값이 없으면 ValueError."""
    if isinstance(data, dict):
        if set(data) == {"param"} and isinstance(data["param"], str):
            name = data["param"]
            if name not in values:
                raise ValueError(f"변수 '{name}' 의 값이 없음 (받은 변수: {sorted(values)})")
            v = values[name]
            return v.item() if hasattr(v, "item") else v  # numpy 스칼라 → 파이썬
        return {k: bind_tree(v, values) for k, v in data.items()}
    if isinstance(data, list):
        return [bind_tree(v, values) for v in data]
    return data


def bind_group(g: Group, values: Mapping[str, float]) -> Group:
    """변수를 값으로 채운 새 Group(다시 검증되므로 범위 밖 값은 오류)."""
    return Group.model_validate(bind_tree(g.model_dump(mode="json"), values))


def has_params(g: Group) -> bool:
    return next(iter_param_slots(g), None) is not None
