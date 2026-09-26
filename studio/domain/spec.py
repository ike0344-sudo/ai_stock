"""백테스트 명세(Spec) — 설계서 §3.2. pydantic v2, 숫자 칸은 `number | {"param": 이름}`.

Spec 은 "무엇을 돌릴지"만 담는다. 체결·비용 *계산*은 엔진(backtest-agent) 몫 — 여기엔 값과 검사뿐.
domain 계층: pydantic·stdlib 만 쓴다(§9.3). 기존 전략 목록은 infrastructure 를 못 부르므로
`LEGACY_NAMES` 를 여기 두고, 테스트가 legacy_strategies 레지스트리와 같은지 대조한다.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Annotated, Any, Iterator, Literal, Mapping, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .conditions.ast import (
    Group, IndOperand, MarketOperand, ParamRef, bind_tree, iter_operands, iter_param_slots,
)
from .conditions.catalog import INDICATORS

LEGACY_NAMES = (
    "ma_crossover", "rsi", "envelope", "new_high_swing", "pullback_reentry",
    "vcp_breakout", "new_high_leg_exit", "new_high_volume_divergence_exit",
)
_TIME = r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$"
Num = Union[float, ParamRef]
LegacyValue = Union[ParamRef, bool, int, float, str, None]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Period(_M):
    start: dt.date
    end: dt.date

    @model_validator(mode="after")
    def _check(self) -> "Period":
        if self.start > self.end:
            raise ValueError("period.start 가 end 보다 늦음")
        return self


class Universe(_M):
    type: Literal["all", "top_value", "codes"] = "top_value"
    n: int = Field(100, ge=1, le=3000)
    lookback_days: int = Field(1, ge=1, le=60)
    markets: list[Literal["거래소", "코스닥"]] = Field(default_factory=lambda: ["거래소", "코스닥"], min_length=1)
    exclude: list[Literal["spac", "preferred", "mega_cap"]] = Field(
        default_factory=lambda: ["spac", "preferred", "mega_cap"]
    )
    codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "Universe":
        bad =[c for c in self.codes if not re.fullmatch(r"[0-9A-Z]{6}", c)]  # 신형 코드는 영문 섞임
        if bad:
            raise ValueError(f"종목코드 형식 오류(6자리 영숫자): {bad}")
        if self.type == "codes" and not self.codes:
            raise ValueError("universe.type='codes' 인데 codes 가 비어 있음")
        return self


class BuilderStrategy(_M):
    source: Literal["builder"]
    entry: Group
    exit: Group = Field(default_factory=lambda: Group(logic="any", items=[]))


class LegacyStrategy(_M):
    source: Literal["legacy"]
    name: Literal[
        "ma_crossover", "rsi", "envelope", "new_high_swing", "pullback_reentry",
        "vcp_breakout", "new_high_leg_exit", "new_high_volume_divergence_exit",
    ]
    params: dict[str, LegacyValue] = Field(default_factory=dict)


Strategy = Annotated[Union[BuilderStrategy, LegacyStrategy], Field(discriminator="source")]


class Exits(_M):
    stop_loss_pct: Num | None = None
    take_profit_pct: Num | None = None
    trailing_stop_pct: Num | None = None
    max_holding_bars: Num | None = None


class Portfolio(_M):
    initial_capital: float = Field(10_000_000, gt=0)
    max_positions: Num = 5
    sizing: Literal["equal_slot_fixed", "equal_slot_compound", "fixed_amount", "risk_pct"] = "equal_slot_fixed"
    fixed_amount: Num | None = None
    risk_pct: Num | None = None
    max_weight_pct: Num = 25.0
    rank_by: Literal["value", "change_pct", "random"] = "value"
    random_seed: int = 42


class Costs(_M):
    commission_rate: float = Field(0.00015, ge=0, le=0.05)
    tax_rate: float = Field(0.0023, ge=0, le=0.05)
    slippage_mode: Literal["rate", "ticks", "max_rate_tick"] = "max_rate_tick"
    slippage_rate: float = Field(0.001, ge=0, le=0.05)
    slippage_ticks: int = Field(1, ge=0, le=20)


class Fills(_M):
    same_bar_policy: Literal["stop_first", "target_first"] = "stop_first"
    volume_cap_pct: float | None = Field(10.0, gt=0, le=100)


class Intraday(_M):
    bar_minutes: Literal[1, 3, 5, 10, 15, 30, 60] = 5
    # 분봉 출처: al = 통합(KRX+NXT, 기본 — 2026-09-01 "통합만" 규칙), krx = KRX 전용(사용자가 고를 때만, 거래량·거래대금이 통합보다 작다).
    # 옛 명세(칸 없음)는 al 로 읽힌다 — 같은 명세는 같은 출처.
    source: Literal["al", "krx"] = "al"
    prefilter: Group | None = None  # 일봉 사전 필터(D−1 기준 조건)
    prefilter_top_value: int = Field(30, ge=1, le=500)
    eod_time: str = Field("15:20", pattern=_TIME)


class ValueSpeed(_M):
    w: int = Field(ge=1, le=60)  # 창(분)
    ratio: float = Field(gt=0)


class BuyRatio(_M):
    w: int = Field(ge=1, le=60)  # 창(분)
    min: float = Field(ge=0, le=1)


class TickCatalog(_M):
    breakout_min: int | None = Field(5, ge=1, le=60)
    value_speed: ValueSpeed | None = None
    buy_ratio: BuyRatio | None = None
    time_from: str = Field("09:05", pattern=_TIME)
    time_to: str = Field("15:00", pattern=_TIME)

    @model_validator(mode="after")
    def _check(self) -> "TickCatalog":
        if self.breakout_min is None and self.value_speed is None and self.buy_ratio is None:
            raise ValueError("틱 조건이 하나도 없음 (breakout_min·value_speed·buy_ratio 중 하나 필요)")
        if self.time_from >= self.time_to:
            raise ValueError("time_from 이 time_to 보다 같거나 늦음")
        return self


class Tick(_M):
    entry_source: Literal["catalog", "minute_refine"] = "catalog"  # 틱 조건 / 분봉 신호 + 틱 정밀화
    catalog: TickCatalog = Field(default_factory=TickCatalog)
    cooldown_sec: int = Field(300, ge=0)
    exclude_gap_open_pct: float | None = Field(5.0, ge=0)
    time_stop_sec: int | None = Field(600, ge=1)
    eod_time: str = Field("15:19:59", pattern=_TIME)


class Compat(_M):
    legacy: bool = False


class ParamRange(_M):
    default: float
    min: float | None = None
    max: float | None = None
    step: float | None = Field(None, gt=0)

    @model_validator(mode="after")
    def _check(self) -> "ParamRange":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min 이 max 보다 큼")
        if (self.min is not None and self.default < self.min) or (self.max is not None and self.default > self.max):
            raise ValueError("default 가 min~max 밖")
        return self


class Validation(_M):
    holdout_pct: float = Field(20.0, ge=0, le=50)
    objective: Literal["sharpe", "cagr", "calmar", "profit_factor", "expectancy"] = "sharpe"
    min_trades: int = Field(30, ge=1)
    criteria: dict[str, float] = Field(default_factory=dict)  # 사전 판정 기준: 지표 이름 → 통과 최소값


# 숫자 칸 범위: (최소, 최대, 정수 여부, 최소 포함 여부)
_EXIT_RANGES = {
    "stop_loss_pct": (0, 100, False, False), "take_profit_pct": (0, 1000, False, False),
    "trailing_stop_pct": (0, 100, False, False), "max_holding_bars": (1, 5000, True, True),
}
_PORT_RANGES = {
    "max_positions": (1, 100, True, True), "max_weight_pct": (0, 100, False, False),
    "fixed_amount": (0, None, False, False), "risk_pct": (0, 100, False, False),
}


def _out_of_range(v: float, lo: float | None, hi: float | None, lo_inclusive: bool) -> bool:
    return (lo is not None and (v < lo if lo_inclusive else v <= lo)) or (hi is not None and v > hi)


class Spec(_M):
    version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=100)
    mode: Literal["daily_single", "daily_portfolio", "intraday", "tick"]
    period: Period
    universe: Universe = Field(default_factory=Universe)
    strategy: Strategy | None = None
    market_filter: Group | None = None
    exits: Exits = Field(default_factory=Exits)
    portfolio: Portfolio = Field(default_factory=Portfolio)
    costs: Costs = Field(default_factory=Costs)
    fills: Fills = Field(default_factory=Fills)
    intraday: Intraday | None = None
    tick: Tick | None = None
    compat: Compat = Field(default_factory=Compat)
    params: dict[str, ParamRange] = Field(default_factory=dict)
    validation: Validation | None = None

    # ---- 내부: 변수 칸 수집 ----
    def _groups(self) -> Iterator[Group]:
        if isinstance(self.strategy, BuilderStrategy):
            yield self.strategy.entry
            yield self.strategy.exit
        if self.market_filter is not None:
            yield self.market_filter
        if self.intraday is not None and self.intraday.prefilter is not None:
            yield self.intraday.prefilter

    def _slots(self) -> Iterator[tuple[str, str, float | None, float | None, bool, bool]]:
        """(변수 이름, 칸 위치, 최소, 최대, 정수 여부, 최소 포함) — {"param":..} 가 쓰인 모든 칸."""
        for g in self._groups():
            for name, lo, hi, integer in iter_param_slots(g):
                yield name, "조건식", lo, hi, integer, True
        for section, ranges in ((self.exits, _EXIT_RANGES), (self.portfolio, _PORT_RANGES)):
            for field, (lo, hi, integer, inclusive) in ranges.items():
                v = getattr(section, field)
                if isinstance(v, ParamRef):
                    yield v.param, field, lo, hi, integer, inclusive
        if isinstance(self.strategy, LegacyStrategy):
            for k, v in self.strategy.params.items():
                if isinstance(v, ParamRef):
                    yield v.param, f"strategy.params.{k}", None, None, False, True

    @model_validator(mode="after")
    def _check(self) -> "Spec":
        m = self.mode
        if m == "intraday" and self.intraday is None:
            raise ValueError("intraday 모드인데 intraday 설정이 없음")
        if m == "tick" and self.tick is None:
            raise ValueError("tick 모드인데 tick 설정이 없음")
        if self.strategy is None and not (m == "tick" and self.tick and self.tick.entry_source == "catalog"):
            raise ValueError("strategy 가 필요함 (tick 모드의 틱 조건 진입만 생략 가능)")
        if isinstance(self.strategy, BuilderStrategy) and not self.strategy.entry.items:
            raise ValueError("strategy.entry 에 조건이 하나도 없음")
        if m == "daily_single" and not (self.universe.type == "codes" and len(self.universe.codes) == 1):
            raise ValueError("daily_single 은 종목 1개(universe.type='codes', codes 1개)여야 함")
        if self.compat.legacy:
            if m != "daily_single":
                raise ValueError("호환 모드(compat.legacy)는 daily_single 에서만 켤 수 있음")
            if any(v is not None for v in self.exits.model_dump().values()):
                raise ValueError("호환 모드에서는 손절·익절·트레일링·보유기간을 쓸 수 없음(비활성 규칙)")
        p = self.portfolio
        if p.sizing == "fixed_amount" and p.fixed_amount is None:
            raise ValueError("sizing='fixed_amount' 인데 portfolio.fixed_amount 가 없음")
        if p.sizing == "risk_pct" and (p.risk_pct is None or self.exits.stop_loss_pct is None):
            raise ValueError("sizing='risk_pct' 는 portfolio.risk_pct 와 exits.stop_loss_pct 가 모두 필요")
        # 모드 ↔ 지표 (틱 모드의 분봉 정밀화는 분봉 지표를 씀)
        eff = "intraday" if m == "tick" else m
        pre = self.intraday.prefilter if self.intraday is not None else None
        for g in self._groups():
            gm = "daily_portfolio" if g is pre else eff  # 사전 필터는 일봉(D−1) 조건
            for op in iter_operands(g):
                if isinstance(op, IndOperand) and gm not in INDICATORS[op.name].modes:
                    raise ValueError(f"지표 '{op.name}' 는 '{gm}' 조건에서 쓸 수 없음 (가능: {list(INDICATORS[op.name].modes)})")
        # 숫자 칸의 리터럴 범위
        for section, ranges in ((self.exits, _EXIT_RANGES), (self.portfolio, _PORT_RANGES)):
            for field, (lo, hi, integer, inclusive) in ranges.items():
                v = getattr(section, field)
                if v is None or isinstance(v, ParamRef):
                    continue
                if _out_of_range(v, lo, hi, inclusive) or (integer and not float(v).is_integer()):
                    raise ValueError(f"{field}={v} 는 허용 범위({lo}~{hi}{', 정수' if integer else ''}) 밖")
        # 변수 칸 ↔ params 범위
        for name, where, lo, hi, integer, inclusive in self._slots():
            pr = self.params.get(name)
            if pr is None:
                raise ValueError(f"변수 '{name}'({where})가 params 에 정의되지 않음")
            for label, v in (("default", pr.default), ("min", pr.min), ("max", pr.max)):
                if v is None:
                    continue
                if _out_of_range(v, lo, hi, inclusive):
                    raise ValueError(f"변수 '{name}'({where}) {label}={v} 가 허용 범위 {lo}~{hi} 밖")
                if integer and not float(v).is_integer():
                    raise ValueError(f"변수 '{name}'({where}) {label}={v} 는 정수여야 함")
            if integer and pr.step is not None and not float(pr.step).is_integer():
                raise ValueError(f"변수 '{name}'({where}) step={pr.step} 는 정수여야 함")
        return self


def default_values(spec: Spec) -> dict[str, float]:
    return {k: v.default for k, v in spec.params.items()}


def bind_params(spec: Spec, overrides: Mapping[str, float] | None = None) -> Spec:
    """변수를 값(기본값 + overrides)으로 채운 새 Spec. 다시 검증되므로 범위 밖 값은 오류."""
    values = default_values(spec)
    unknown = set(overrides or {}) - set(values)
    if unknown:
        raise ValueError(f"params 에 없는 변수: {sorted(unknown)}")
    values.update(overrides or {})
    data: dict[str, Any] = bind_tree(spec.model_dump(mode="json"), values)
    return Spec.model_validate(data)


@dataclass(frozen=True)
class Problem:
    """실행 전 발견한 문제. severity: 'error'(그대로면 결과가 의미 없음) / 'warning'(일부 구간이 조용히 비어감)."""
    severity: Literal["error", "warning"]
    dataset: str
    message: str


# validate_against 의 ranges 키: 일봉 "daily", 지수 "kospi"·"kosdaq", 분봉 "minute_al"(통합)·"minute_krx"(KRX, intraday.source 로 선택), 틱 "tick_al"
_MODE_DATASET = {"daily_single": "daily", "daily_portfolio": "daily", "intraday": "minute_al", "tick": "tick_al"}
_DATASET_KO = {"daily": "일봉", "kospi": "코스피 지수", "kosdaq": "코스닥 지수", "minute_al": "통합 분봉", "minute_krx": "KRX 분봉",
               "tick_al": "통합 체결"}


def validate_against(spec: Spec, ranges: Mapping[str, tuple[dt.date, dt.date]]) -> list[Problem]:
    """기간이 실제 데이터 범위 밖이면 문제로 돌려준다(순수 함수 — 범위는 호출자가 데이터 허브에서 읽어 넘김).

    - 기간이 범위와 아예 안 겹치면 error, 일부만 벗어나면 warning(그 구간은 신호·거래가 0건이 됨).
    - 쓰는 데이터: 모드별 본 데이터셋 + (분봉 모드의 일봉 지표·사전 필터) + 시장 조건에 쓰인 지수.
    - ranges 에 없는 데이터셋은 error("범위 정보 없음") — 조용히 통과시키지 않는다.
    """
    main = _MODE_DATASET[spec.mode]
    if spec.mode == "intraday" and spec.intraday is not None:
        main = f"minute_{spec.intraday.source}"  # 분봉 출처(al|krx)에 맞는 범위를 요구 — 출처를 섞지 않는다
    need: dict[str, str] = {main: "본 데이터"}
    if spec.mode in ("intraday", "tick"):
        need["daily"] = "일봉 지표·전일 순위(D−1)"
    for g in spec._groups():
        for op in iter_operands(g):
            if isinstance(op, MarketOperand):
                need[op.index] = "시장 조건"
    out: list[Problem] = []
    p0, p1 = spec.period.start, spec.period.end
    for ds, why in need.items():
        ko = _DATASET_KO[ds]
        r = ranges.get(ds)
        if r is None:
            out.append(Problem("error", ds, f"{ko} 데이터 범위 정보가 없음({why})"))
            continue
        d0, d1 = r
        if p1 < d0 or p0 > d1:
            out.append(Problem("error", ds, f"기간 {p0}~{p1} 이 {ko} 데이터({d0}~{d1})와 겹치지 않음({why})"))
            continue
        if p0 < d0:
            out.append(Problem("warning", ds, f"{ko} 데이터가 {d0} 부터라 그 이전({p0}~) 구간은 신호가 0건({why})"))
        if p1 > d1:
            out.append(Problem("warning", ds, f"{ko} 데이터가 {d1} 까지라 그 이후(~{p1}) 구간은 신호가 0건({why})"))
    return out
