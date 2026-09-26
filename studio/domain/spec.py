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
    Group, IndOperand, MarketOperand, ParamRef, PosOperand, bind_tree, iter_operands, iter_param_slots,
)
from .conditions.catalog import INDICATORS
from .conditions.validation import validate_group

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


class TpLevel(_M):
    pct: Num  # 매수가 대비 익절 % (변수 가능)
    fraction: float = Field(gt=0, le=1)  # 그 선에서 **남은 수량** 중 파는 비율 — [{5,0.5},{10,1.0}] = +5% 에 절반, +10% 에 나머지 전부


class Exits(_M):
    stop_loss_pct: Num | None = None
    take_profit_pct: Num | None = None
    trailing_stop_pct: Num | None = None
    max_holding_bars: Num | None = None
    # ---- studio-conditions c2 — 옛 명세엔 칸이 없다 = 기본값(해시에서도 기본값이면 뺀다)
    take_profit_levels: list[TpLevel] | None = Field(None, min_length=1, max_length=10)  # 분할 익절 — take_profit_pct 와 같이 못 씀
    take_profit_mode: Literal["intrabar", "close"] = "intrabar"  # 익절을 봉 안 즉시(기존) / 종가 확인 뒤 다음 봉 시가
    trail_activate_pct: Num | None = None  # 최고 수익률이 X% 를 넘은 다음 봉부터 트레일링 작동(trailing_stop_pct 필요)
    breakeven_after_pct: Num | None = None  # 최고 수익률이 X% 를 넘은 다음 봉부터 손절선을 매수가로
    max_holding_minutes: Num | None = None  # 분봉 시간 청산 — 진입 봉을 1봉(=봉 길이 분)으로 세어 올림한 봉 수에 종가 청산

    def is_default(self) -> bool:
        return all(v is None for k, v in self.model_dump().items() if k != "take_profit_mode") and self.take_profit_mode == "intrabar"


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


class TradeStrength(_M):
    w: int = Field(ge=1, le=3600)  # 창(초)
    min: float = Field(ge=0)  # 체결강도(%) 하한 — 매수체결량 ÷ 매도체결량 × 100


class BlockTrades(_M):
    w: int = Field(ge=1, le=3600)  # 창(초)
    min_value: float = Field(gt=0)  # 대량 체결 1건의 최소 체결대금(원)
    min_count: int = Field(1, ge=1)  # 창 안 대량 체결 최소 건수


class DailyBreakout(_M):
    n: int = Field(ge=1, le=250)  # 전일(D−1)까지 n일 최고가를 넘을 때 — 기준선은 서비스가 일봉에서 계산해 준다


class TickCatalog(_M):
    breakout_min: int | None = Field(5, ge=1, le=60)
    value_speed: ValueSpeed | None = None
    buy_ratio: BuyRatio | None = None
    trade_strength: TradeStrength | None = None  # 옛 명세는 칸이 없다 = None
    block_trades: BlockTrades | None = None
    daily_breakout: DailyBreakout | None = None
    time_from: str = Field("09:05", pattern=_TIME)
    time_to: str = Field("15:00", pattern=_TIME)

    @model_validator(mode="after")
    def _check(self) -> "TickCatalog":
        if all(v is None for v in (self.breakout_min, self.value_speed, self.buy_ratio, self.trade_strength,
                                   self.block_trades, self.daily_breakout)):
            raise ValueError("틱 조건이 하나도 없음 (breakout_min·value_speed·buy_ratio·trade_strength·block_trades·daily_breakout 중 하나 필요)")
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
    "trail_activate_pct": (0, 1000, False, False), "breakeven_after_pct": (0, 1000, False, False),
    "max_holding_minutes": (1, 100000, True, True),
}
_PORT_RANGES = {
    "max_positions": (1, 100, True, True), "max_weight_pct": (0, 100, False, False),
    "fixed_amount": (0, None, False, False), "risk_pct": (0, 100, False, False),
}


def _has_pos(g: Group) -> bool:
    return any(isinstance(o, PosOperand) for o in iter_operands(g))


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

    def _role_groups(self) -> Iterator[tuple[str, Group]]:
        """(역할, 그룹) — 진입·청산·시장 필터·사전 필터. 역할별 규칙(pos 는 청산만 등)을 위해 _groups 와 따로 둔다."""
        if isinstance(self.strategy, BuilderStrategy):
            yield "entry", self.strategy.entry
            yield "exit", self.strategy.exit
        if self.market_filter is not None:
            yield "market_filter", self.market_filter
        if self.intraday is not None and self.intraday.prefilter is not None:
            yield "prefilter", self.intraday.prefilter

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
        for j, lv in enumerate(self.exits.take_profit_levels or []):
            if isinstance(lv.pct, ParamRef):
                yield lv.pct.param, f"exits.take_profit_levels.{j}.pct", 0, 1000, False, False
        if isinstance(self.strategy, LegacyStrategy):
            for k, v in self.strategy.params.items():
                if isinstance(v, ParamRef):
                    yield v.param, f"strategy.params.{k}", None, None, False, True

    def _check_exits(self, m: str) -> None:
        """청산 확장 칸(c2)끼리·모드와의 관계 — 조용히 무시되는 조합은 오류로 막는다."""
        ex = self.exits
        lv = ex.take_profit_levels
        if lv is not None:
            if ex.take_profit_pct is not None:
                raise ValueError("exits.take_profit_levels 와 exits.take_profit_pct 는 같이 쓸 수 없음(분할 익절이 단일 익절을 대신한다)")
            pcts = [x.pct for x in lv]
            if all(not isinstance(v, ParamRef) for v in pcts):
                if any(v <= 0 or v > 1000 for v in pcts):
                    raise ValueError("exits.take_profit_levels 의 pct 는 0 초과 1000 이하")
                if any(b <= a for a, b in zip(pcts, pcts[1:])):
                    raise ValueError("exits.take_profit_levels 의 pct 는 오름차순(중복 없음)이어야 함")
        if ex.take_profit_mode == "close" and ex.take_profit_pct is None and lv is None:
            raise ValueError("exits.take_profit_mode='close' 는 익절(take_profit_pct 또는 take_profit_levels)이 있어야 함")
        if ex.trail_activate_pct is not None and ex.trailing_stop_pct is None:
            raise ValueError("exits.trail_activate_pct 는 exits.trailing_stop_pct 가 있어야 함(발동 문턱만 있고 트레일링이 없다)")
        if ex.max_holding_minutes is not None and m != "intraday":
            raise ValueError("exits.max_holding_minutes 는 분봉(intraday) 모드에서만 쓸 수 있음 — 일봉은 max_holding_bars")
        if m == "tick":
            if ex.take_profit_mode != "intrabar" or any(getattr(ex, k) is not None for k in (
                    "take_profit_levels", "trail_activate_pct", "breakeven_after_pct", "max_holding_minutes")):
                raise ValueError("틱 모드는 분할 익절·종가 확인 익절·트레일링 발동·본전 손절·분 단위 보유 청산을 아직 지원하지 않음")
            if isinstance(self.strategy, BuilderStrategy) and _has_pos(self.strategy.exit):
                raise ValueError("틱 모드는 포지션(pos) 조건 청산을 아직 지원하지 않음")

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
            if not self.exits.is_default():
                raise ValueError("호환 모드에서는 손절·익절·트레일링·보유기간을 쓸 수 없음(비활성 규칙)")
            if isinstance(self.strategy, BuilderStrategy) and _has_pos(self.strategy.exit):
                raise ValueError("호환 모드에서는 포지션(pos) 조건 청산을 쓸 수 없음")
        self._check_exits(m)
        p = self.portfolio
        if p.sizing == "fixed_amount" and p.fixed_amount is None:
            raise ValueError("sizing='fixed_amount' 인데 portfolio.fixed_amount 가 없음")
        if p.sizing == "risk_pct" and (p.risk_pct is None or self.exits.stop_loss_pct is None):
            raise ValueError("sizing='risk_pct' 는 portfolio.risk_pct 와 exits.stop_loss_pct 가 모두 필요")
        # 모드 ↔ 지표 (틱 모드의 분봉 정밀화는 분봉 지표를 씀)
        # 규칙(모드·시간 단위 tf·청산 전용 pos)은 conditions/validation.py — studio-conditions c1
        bm = self.intraday.bar_minutes if self.intraday is not None else 5
        src = self.intraday.source if self.intraday is not None else "al"
        for role, g in self._role_groups():
            validate_group(g, role, mode=m, bar_minutes=bm, source=src)
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
