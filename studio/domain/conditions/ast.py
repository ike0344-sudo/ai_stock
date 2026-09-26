"""조건식 AST — 설계서 §3.2. pydantic v2 검증(오류는 loc 경로 포함).

Group(all/any, 깊이 ≤ 2) → Condition(left op right) → Operand(field/ind/market/const).
숫자 칸은 `number | {"param": 이름}` — 최적화 변수. `bind_group`/`bind_tree` 로 값을 채운다.
domain 계층: pydantic·stdlib 만 쓴다(§9.3).
"""
from __future__ import annotations

from typing import Annotated, Any, Iterator, Literal, Mapping, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .catalog import INDICATORS, MARKET_INDEXES, MARKET_NAMES, N_MAX, N_MIN, ParamDef

MAX_GROUP_DEPTH = 2  # 근거: 화면 편집기가 하위 그룹 1단계까지(§5.4)
OFFSET_MAX = N_MAX
OPS = ("gt", "gte", "lt", "lte", "cross_above", "cross_below")


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
    offset: int = Field(0, ge=0, le=OFFSET_MAX)  # 음수 금지 = 미래 참조 금지
    mul: Num = 1.0


class IndOperand(_M):
    kind: Literal["ind"]
    name: str
    params: dict[str, ParamValue] = Field(default_factory=dict)
    offset: int = Field(0, ge=0, le=OFFSET_MAX)
    mul: Num = 1.0

    @model_validator(mode="after")
    def _check(self) -> "IndOperand":
        d = INDICATORS.get(self.name)
        if d is None:
            raise ValueError(f"없는 지표 '{self.name}' (가능: {sorted(INDICATORS)})")
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


Operand = Annotated[
    Union[FieldOperand, IndOperand, MarketOperand, ConstOperand], Field(discriminator="kind")
]


class Condition(_M):
    left: Operand
    op: Literal["gt", "gte", "lt", "lte", "cross_above", "cross_below"]
    right: Operand

    @model_validator(mode="after")
    def _check(self) -> "Condition":
        if isinstance(self.left, ConstOperand) and isinstance(self.right, ConstOperand):
            raise ValueError("상수끼리 비교할 수 없음 — 한쪽은 지표·가격이어야 함")
        return self


class Group(_M):
    logic: Literal["all", "any"]
    items: list[Union[Condition, "Group"]] = Field(default_factory=list)

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


def iter_operands(g: Group) -> Iterator[Operand]:
    for c in iter_conditions(g):
        yield c.left
        yield c.right


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
