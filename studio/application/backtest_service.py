"""백테스트 실행 유스케이스 — Spec 하나로 끝까지 (설계서 §2.2(e)).

    run_backtest(spec, market_data, legacy=..., overrides={...}) -> RunRecord

흐름: bind_params → validate_against → 유니버스(제외 규칙) → 조건식 평가(워밍업 봉 포함) → 기간으로 자름
→ 엔진(일반: run_portfolio / 호환: run_compat) → 표준 지표 → 경고 → RunRecord.

기간·워밍업: 조건식은 기간 시작 **전** 봉까지 평가해 첫날부터 지표가 채워지게 하고, 엔진에는 기간 안의
봉만 준다(기간 밖 봉으로 체결될 수 없다). 신호는 종가 기준 → 다음 봉 시가 체결이라 기간 첫 봉의 체결은
기간 시작 전 봉의 신호가 아니라 기간 첫 봉의 신호부터 가능하다(그 다음 봉 시가).
호환 모드(compat.legacy)는 기존 CLI 와 숫자를 잇는 게 목적이라 **워밍업 없이 기간 캔들만으로** 신호를 평가한다
(기존 CLI 가 그렇게 돈다).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from studio.domain.conditions.ast import FieldOperand, IndOperand, iter_operands
from studio.domain.conditions.evaluator import Evaluation, evaluate, to_signals
from studio.domain.conditions.indicators import value_rank
from studio.domain.costs import CostModel
from studio.domain.engine.compat import run_compat
from studio.domain.engine.fills import ExitRules, FillRules
from studio.domain.engine.portfolio import PortfolioRules, run_portfolio
from studio.domain.metrics import legacy_metrics, standard_metrics
from studio.domain.robustness import robustness_report
from studio.domain.validation import evaluate_criteria
from studio.domain.models import BacktestResult, Fill, Panel, Trade
from studio.domain.spec import BuilderStrategy, LegacyStrategy, Spec, bind_params, validate_against

from .ports import LegacyStrategies, MarketData, RunRecord

WARMUP_BARS = 600  # 지표 기간 상한(카탈로그 N_MAX=500) + 거래량 평균 등 여유
MIN_TRADES = 30  # §3.8 최소 거래 수 — 미만이면 통계적으로 무의미하다는 경고
_PREFERRED = re.compile(r"\d*우[A-C]?$")

Progress = Callable[[str, float], None]


class BacktestError(Exception):
    """실행 전 검증 실패 — 메시지는 사용자에게 그대로 보여줘도 된다."""


class ModeNotSupportedError(BacktestError):
    """intraday·tick 은 module-6 에서 구현한다."""


# --------------------------------------------------------------------------- 해시


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _strip_new_defaults(o: Any) -> Any:
    """studio-conditions c1 이 조건 AST 에 추가한 칸(tf·hold·within·right(None)·negate)이 **기본값이면 뺀다** — 새 칸이 없던 때 만든
    명세(저장된 실행·홀드아웃 장부·프리셋)의 해시가 스키마가 커져도 그대로 같게."""
    if isinstance(o, list):
        return [_strip_new_defaults(v) for v in o]
    if not isinstance(o, dict):
        return o
    o = {k: _strip_new_defaults(v) for k, v in o.items()}
    if o.get("kind") in ("field", "ind") and o.get("tf") == "bar":
        o.pop("tf")
    if "left" in o and "op" in o and o.get("kind") != "expr":  # Condition
        if o.get("hold") == 1:
            o.pop("hold")
        if o.get("within") is None:
            o.pop("within", None)
        if o.get("right") is None:
            o.pop("right", None)
    if "entry_source" in o and "catalog" in o:  # Tick — c8 이 추가한 칸(filter·prefilter)이 없으면 뺀다
        for k in ("filter", "prefilter"):
            if o.get(k) is None:
                o.pop(k, None)
    if "stop_loss_pct" in o and "max_holding_bars" in o:  # Exits — c2 가 추가한 칸이 기본값이면 뺀다(옛 해시·홀드아웃 장부 보존)
        for k in ("take_profit_levels", "trail_activate_pct", "breakeven_after_pct", "max_holding_minutes"):
            if o.get(k) is None:
                o.pop(k, None)
        if o.get("take_profit_mode") == "intrabar":
            o.pop("take_profit_mode")
    if "logic" in o and "items" in o:  # Group
        if o.get("negate") is False:
            o.pop("negate")
        o.pop("formula", None)  # 수식 원문은 같은 AST 의 표기일 뿐 — 전략 해시에 안 넣는다
    return o


def spec_hash(bound: Spec) -> str:
    """값이 다 채워진 명세의 해시(이름 제외) — 같은 설정이면 같다."""
    d = _strip_new_defaults(bound.model_dump(mode="json"))
    d.pop("name", None)
    return hashlib.sha256(_canon(d).encode()).hexdigest()[:16]


def structure_hash(spec: Spec) -> str:
    """파라미터 **값**을 뺀 구조 해시 — 변수 칸({"param":..})은 그대로 두고 params 범위·이름·기간·검증 설정을 뺀다.
    홀드아웃을 몇 번 열었는지 세는 키(§3.8)."""
    d = _strip_new_defaults(spec.model_dump(mode="json"))
    for k in ("name", "params", "validation", "period"):
        d.pop(k, None)
    return hashlib.sha256(_canon(d).encode()).hexdigest()[:16]


def _strip_numbers(o: Any) -> Any:
    """숫자·코드 리터럴을 전부 자리표시로 — 전략의 '뼈대'(지표 이름·연산·논리·enum 설정)만 남긴다."""
    if isinstance(o, bool) or o is None or isinstance(o, str):
        return o
    if isinstance(o, (int, float)):
        return "#"
    if isinstance(o, dict):
        return {k: _strip_numbers(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_strip_numbers(v) for v in o]
    return o


def family_hash(spec: Spec) -> str:
    """structure_hash 보다 거친 해시 — 숫자 리터럴(조건식 상수·손절 % 등)과 종목 지정·비용·기간을 전부 뺀다.
    structure_hash 는 손절 7% → 10% 처럼 **리터럴로 박은 값**을 바꾸면 다른 구조가 돼 홀드아웃 열람 횟수가 리셋된다.
    같은 전략을 손질하며 홀드아웃을 반복해 여는 것(엿보기)을 잡으려고 만들었고, **홀드아웃 열람 횟수는 이 해시로 센다**
    (lead 판정 2026-09-25). structure_hash 는 식별용으로 함께 기록한다."""
    d = _strip_new_defaults(spec.model_dump(mode="json"))
    for k in ("name", "params", "validation", "period", "costs", "intraday", "tick"):
        d.pop(k, None)
    d["universe"].pop("codes", None)
    d["exits"] = {k: "#" for k in d["exits"]}  # 청산 규칙을 켜고 끄는 것(None ↔ 숫자)도 같은 골격 — 홀드아웃을 본 뒤 손절을 붙였다 떼는 것도 튜닝(lead 판정 2026-09-25)
    return hashlib.sha256(_canon(_strip_numbers(d)).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- 유니버스


def is_spac(name: str) -> bool:
    return "스팩" in name


def is_preferred(code: str, name: str) -> bool:
    """우선주: 이름 끝이 우/우B/2우B 꼴 **이고** 종목코드 끝자리가 0 이 아님(보통주는 0).
    이름만 보면 '성우'(458650) 같은 보통주가 걸린다."""
    return bool(_PREFERRED.search(name)) and not code.endswith("0")


def eligible_codes(spec: Spec, info: pd.DataFrame, mega_cap: frozenset[str], available: list[str]
                   ) -> tuple[list[str], dict[str, int]]:
    """유니버스 조건(시장·제외)에 맞는 종목. 종목을 직접 지정하면(type='codes') 그대로 쓴다 — 명시 선택이 우선."""
    u = spec.universe
    if u.type == "codes":
        return [c for c in u.codes if c in set(available)], {}
    stats = {"spac": 0, "preferred": 0, "mega_cap": 0, "market_unknown": 0, "market_other": 0}
    out = []
    both = set(u.markets) >= {"거래소", "코스닥"}
    for c in available:
        name = str(info["name"].get(c, "") or "") if c in info.index else ""
        market = info["market"].get(c) if c in info.index else None
        if "spac" in u.exclude and is_spac(name):
            stats["spac"] += 1
            continue
        if "preferred" in u.exclude and is_preferred(c, name):
            stats["preferred"] += 1
            continue
        if "mega_cap" in u.exclude and c in mega_cap:
            stats["mega_cap"] += 1
            continue
        if pd.isna(market):
            if not both:  # 시장을 확인할 수 없으면 한 시장만 고른 조건엔 넣지 않는다
                stats["market_unknown"] += 1
                continue
        elif market not in u.markets:
            stats["market_other"] += 1
            continue
        out.append(c)
    return out, stats


# --------------------------------------------------------------------------- Spec → 엔진 규칙


def _holding_bars(spec: Spec) -> int | None:
    """보유 상한(봉) — max_holding_bars 와 max_holding_minutes(봉 길이로 올림)) 중 빠른 쪽."""
    e = spec.exits
    bars = [int(e.max_holding_bars)] if e.max_holding_bars is not None else []
    if e.max_holding_minutes is not None:
        bm = spec.intraday.bar_minutes if spec.intraday is not None else 1
        bars.append(-(-int(e.max_holding_minutes) // bm))
    return min(bars) if bars else None


def to_engine_rules(spec: Spec) -> tuple[CostModel, ExitRules, FillRules, PortfolioRules]:
    """Spec(변수가 채워진) → 엔진 규칙 — 이 변환은 여기 한 곳뿐이다."""
    c, e, f, p = spec.costs, spec.exits, spec.fills, spec.portfolio
    return (
        CostModel(c.commission_rate, c.tax_rate, c.slippage_mode, c.slippage_rate, float(c.slippage_ticks)),
        ExitRules(e.stop_loss_pct, e.take_profit_pct, e.trailing_stop_pct, _holding_bars(spec),
                  tuple((float(x.pct), float(x.fraction)) for x in e.take_profit_levels) if e.take_profit_levels else None,
                  e.take_profit_mode, e.trail_activate_pct, e.breakeven_after_pct),
        FillRules(f.same_bar_policy, f.volume_cap_pct),
        PortfolioRules(p.initial_capital, int(p.max_positions), p.sizing, p.fixed_amount, p.risk_pct,
                       p.max_weight_pct, p.rank_by, p.random_seed),
    )


def condition_warnings(spec: Spec) -> list[str]:
    """쓰인 조건이 요구하는 경고 문구 — 테마·업종 지표는 **현재 구성 기준**(과거에도 오늘의 소속을 씀: 결과가 실제보다 좋게 나올 수 있음)."""
    from studio.domain.conditions.ind_group import warnings_for
    names = {op.name for _, g in spec._role_groups() for op in iter_operands(g) if isinstance(op, IndOperand)}
    return warnings_for(names)


def _uses_value(spec: Spec) -> bool:
    if spec.universe.type == "top_value":
        return True
    groups = []
    if isinstance(spec.strategy, BuilderStrategy):
        groups += [spec.strategy.entry, spec.strategy.exit]
    if spec.market_filter is not None:
        groups.append(spec.market_filter)
    for g in groups:
        for op in iter_operands(g):
            if (isinstance(op, FieldOperand) and op.name == "value") or (
                    isinstance(op, IndOperand) and op.name == "value_rank"):
                return True
    return False


def _slice(panel: Panel, mask: np.ndarray, cols: list[str] | None = None) -> Panel:
    def f(df: pd.DataFrame) -> pd.DataFrame:
        df = df.loc[mask]
        return df if cols is None else df[cols]
    return Panel(*(f(getattr(panel, k)) for k in ("open", "high", "low", "close", "volume", "value", "prev_close")))


# --------------------------------------------------------------------------- 호환 모드 결과 조립


def _compat_result(trades: list[Trade], candles: pd.DataFrame, initial_capital: float,
                   commission_rate: float) -> BacktestResult:
    """호환 모드는 종목 하나·전액 매수 — 표준 지표용으로 일별 평가(실현 + 보유 평가손익)를 만든다."""
    idx = candles.index
    close = candles["close"].to_numpy(dtype=float)
    equity = np.full(len(idx), float(initial_capital))
    pv = np.zeros(len(idx))
    npos = np.zeros(len(idx), dtype=int)
    pos_of = {ts: i for i, ts in enumerate(idx)}
    fills: list[Fill] = []
    for t in trades:
        i0 = pos_of[t.entry_ts]
        i1 = pos_of[t.exit_ts] if t.exit_ts is not None else len(idx)
        entry_comm = t.entry_price * t.qty * commission_rate
        fills.append(Fill(t.entry_ts, t.code, "buy", t.qty, t.entry_price, t.entry_price, entry_comm, 0.0, 0.0, "entry"))
        if t.exit_ts is not None:
            fills.append(Fill(t.exit_ts, t.code, "sell", t.qty, t.exit_price, t.exit_price,
                              t.commission - entry_comm, t.tax, 0.0, "signal"))
            equity[i1:] += t.net_pnl
        hold = slice(i0, i1)  # 진입 봉 ~ 청산 전 봉: 종가 평가손익 − 이미 낸 매수 수수료
        equity[hold] += (close[hold] - t.entry_price) * t.qty - entry_comm
        pv[hold] += close[hold] * t.qty
        npos[hold] += 1
    eq = pd.DataFrame({"ts": idx, "cash": equity - pv, "positions_value": pv, "equity": equity, "n_positions": npos})
    return BacktestResult(trades=trades, equity=eq, fills=fills, skipped={}, diagnostics={"compat": True})


# --------------------------------------------------------------------------- 실행 맥락(그리드에서 재사용)


@dataclass
class RunContext:
    """기간·유니버스가 같으면 조합(변수 값)이 달라도 그대로 재사용하는 무거운 준비물 — 일봉 패널·종목 정보·지수."""

    key: tuple
    panel: Panel  # 유니버스에 든 종목만, 워밍업 봉 포함
    codes: list[str]
    ustats: dict[str, int]
    info: pd.DataFrame
    market: Mapping[str, pd.DataFrame]
    ranges: dict
    in_period: np.ndarray
    warnings: list[str] = field(default_factory=list)
    cache: dict[str, Any] = field(default_factory=dict)  # 조합과 무관한 계산 결과(거래대금 순위 등)


def context_key(spec: Spec) -> tuple:
    """맥락이 유효한 조건 — 이게 같으면 같은 패널이다(변수 값·전략·청산 규칙은 무관)."""
    return (spec.mode, str(spec.period.start), str(spec.period.end), _canon(spec.universe.model_dump(mode="json")),
            spec.compat.legacy)


def prepare_context(spec: Spec, market_data: MarketData, tick: Progress | None = None) -> RunContext:
    tick = tick or (lambda stage, frac: None)
    if spec.mode in ("intraday", "tick"):  # 그리드·워크포워드는 일봉 전용(맥락 재사용 구조가 일봉 패널 기준)
        raise ModeNotSupportedError(f"'{spec.mode}' 모드는 최적화·검증 그리드를 지원하지 않는다(일봉만) — 단일 실행은 run_backtest")
    warnings: list[str] = []
    ranges = market_data.data_ranges()
    problems = validate_against(bind_params(spec), ranges)
    errors = [p.message for p in problems if p.severity == "error"]
    if errors:
        raise BacktestError("; ".join(errors))
    warnings += [p.message for p in problems if p.severity == "warning"]

    start, end = pd.Timestamp(spec.period.start), pd.Timestamp(spec.period.end)
    compat = spec.compat.legacy
    tick("load", 0.05)
    info = market_data.stock_info()
    want = list(spec.universe.codes) if spec.universe.type == "codes" else None
    full = market_data.load_panel(spec.period.start, spec.period.end, 0 if compat else WARMUP_BARS, want)
    codes, ustats = eligible_codes(spec, info, market_data.mega_cap_codes(), list(full.close.columns))
    if not codes:
        raise BacktestError("유니버스에 종목이 없다 (조건·제외 규칙 확인)")
    missing = sorted(set(spec.universe.codes) - set(codes)) if want else []
    if missing:
        warnings.append(f"일봉 데이터가 없는 종목 {len(missing)}개 제외: {missing[:10]}")
    if ustats.get("market_unknown"):
        warnings.append(f"시장 정보가 없어 제외된 종목 {ustats['market_unknown']}개(한 시장만 골랐을 때)")
    panel = _slice(full, np.ones(len(full.close), dtype=bool), codes)
    in_period = (panel.close.index >= start) & (panel.close.index <= end)
    if not in_period.any():
        raise BacktestError("기간 안에 일봉 거래일이 없다")
    return RunContext(context_key(spec), panel, codes, ustats, info, market_data.index_frames(), ranges,
                      in_period, warnings)


def restrict_context(ctx: RunContext, spec: Spec) -> RunContext:
    """이미 올린 패널에서 spec.period 밖의 뒷 봉을 잘라낸 맥락 — 기간 끝만 앞당길 때(최적화 구간·홀드아웃) 다시 안 읽는다.
    기간 시작을 늦추는 것도 되지만(워밍업 봉은 이미 앞에 있다) 시작을 앞당기는 건 안 된다(그 봉은 안 올려 놨다)."""
    start, end = pd.Timestamp(spec.period.start), pd.Timestamp(spec.period.end)
    if start < ctx.panel.close.index[0] and not spec.compat.legacy:
        raise BacktestError("맥락보다 앞선 기간 시작은 만들 수 없다")
    panel = _slice(ctx.panel, np.asarray(ctx.panel.close.index <= end))
    in_period = np.asarray((panel.close.index >= start) & (panel.close.index <= end))
    if not in_period.any():
        raise BacktestError("기간 안에 일봉 거래일이 없다")
    return RunContext(context_key(spec), panel, ctx.codes, ctx.ustats, ctx.info, ctx.market, ctx.ranges, in_period,
                      list(ctx.warnings))


# --------------------------------------------------------------------------- 본체


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.bool_):  # numpy 값끼리 비교한 결과(passed·warn 등)는 np.bool_ — json 이 못 쓴다(실데이터 저장 단계에서 발견)
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if (np.isnan(o) or np.isinf(o)) else float(o)
    return o


def run_backtest(
    spec: Spec,
    market_data: MarketData,
    progress: Progress | None = None,
    *,
    legacy: LegacyStrategies | None = None,
    overrides: Mapping[str, float] | None = None,
    context: RunContext | None = None,
) -> RunRecord:
    """context: 그리드 등 같은 기간·유니버스를 반복 실행할 때 `prepare_context` 결과를 재사용(키가 다르면 무시하고 새로 만든다)."""
    t_start = time.perf_counter()
    tick = progress or (lambda stage, frac: None)

    if spec.mode == "intraday" or (spec.mode == "tick" and spec.tick is not None and spec.tick.entry_source == "minute_refine"):
        from .intraday_service import run_intraday  # 분봉(+모드 A 틱 정밀화) — 순환 import 피하려 지연 import
        return run_intraday(spec, market_data, progress, legacy=legacy, overrides=overrides)
    if spec.mode == "tick":
        from .intraday_service import run_tick  # 모드 B 틱 조건 진입
        return run_tick(spec, market_data, progress, legacy=legacy, overrides=overrides)
    bound = bind_params(spec, overrides)
    if context is None or context.key != context_key(bound):
        context = prepare_context(bound, market_data, tick)
    warnings: list[str] = list(context.warnings)
    ranges, codes, ustats, info = context.ranges, context.codes, context.ustats, context.info
    panel, in_period = context.panel, context.in_period
    compat = bound.compat.legacy
    strat = bound.strategy
    if isinstance(strat, LegacyStrategy) and legacy is None:
        raise BacktestError("기존 전략을 실행하려면 legacy 어댑터가 필요하다")

    # ---- 조건식 평가 (워밍업 포함)
    tick("signals", 0.25)
    market = context.market
    # 지표 memo: 같은 패널(context.panel)로 변수만 바꿔 반복 실행(그리드)할 때 같은 (지표, 파라미터) 계산을 재사용한다.
    # 한 Panel 전용 — 컨텍스트가 패널을 소유하므로 안전하고, 결과 숫자는 memo 없을 때와 같다(strategy-agent 테스트).
    memo = context.cache.setdefault("indicator_memo", {})
    if isinstance(strat, BuilderStrategy):
        ev = evaluate(strat.entry, strat.exit, panel, market=market, market_filter=bound.market_filter, memo=memo)
    else:
        ev = legacy.evaluate(strat.name, strat.params, panel)
        if bound.market_filter is not None:
            from studio.domain.conditions.evaluator import evaluate_group
            ev = Evaluation(ev.entry & evaluate_group(bound.market_filter, panel, market=market, memo=memo), ev.exit)

    entry = ev.entry
    if bound.universe.type == "top_value":  # 신호 봉 t 종가 기준 거래대금 순위(1=최대)
        rank = context.cache.get("value_rank")  # 패널·lookback 이 같으면 조합이 달라도 같다 — 그리드에서 한 번만
        if rank is None:
            rank = context.cache["value_rank"] = value_rank(panel.value, bound.universe.lookback_days)
        entry = entry & (rank <= bound.universe.n)

    # ---- 기간으로 자르고 엔진
    tick("engine", 0.55)
    cost, exit_rules, fill_rules, port = to_engine_rules(bound)
    sub = _slice(panel, in_period)
    ent, ext = entry.loc[in_period], ev.exit.loc[in_period]

    legacy_m = None
    if compat:
        code = codes[0]
        if len(codes) != 1:
            raise BacktestError("호환 모드는 종목 1개만 지원한다")
        candles = pd.DataFrame({k: getattr(sub, k)[code] for k in ("open", "high", "low", "close", "volume")})
        candles = candles[candles["close"].notna()]
        if bound.costs.slippage_mode != "rate":
            warnings.append("호환 모드는 슬리피지를 비율(slippage_rate)로만 적용한다 — slippage_mode 설정은 무시됨")
        sig_panel = _slice(panel, in_period, [code])  # 기간 캔들만으로 평가(워밍업 없음, 기존 CLI 와 같게)
        sigs = (to_signals(evaluate(strat.entry, strat.exit, sig_panel, market=market,
                                    market_filter=bound.market_filter))
                if isinstance(strat, BuilderStrategy) else legacy.signals(strat.name, strat.params, sig_panel))
        trades = run_compat(candles, sigs[code], bound.costs.commission_rate, bound.costs.slippage_rate,
                            port.initial_capital, code, tax_rate=bound.costs.tax_rate)
        result = _compat_result(trades, candles, port.initial_capital, bound.costs.commission_rate)
        legacy_m = legacy_metrics(trades, candles.index.normalize().nunique(), port.initial_capital)
    else:
        result = run_portfolio(sub, ent, ext, cost, exit_rules, fill_rules, port,
                               pos_exit=ev.pos_exit.sliced(in_period) if ev.pos_exit is not None else None)

    # ---- 지표·경고·기록 (분봉·틱 모드와 공통)
    valid = sub.close.notna().to_numpy()  # 종목별 마지막 유효 봉이 기간 마지막 봉보다 앞인 종목 수
    ended_early = int((valid.any(axis=0) & ~valid[-1]).sum()) if len(valid) else 0
    if ended_early:
        warnings.append(f"일봉이 기간 끝보다 먼저 끝난 종목 {ended_early}개(상장폐지·수집 중단) — 마지막 종가로 청산됨")
    return assemble_record(
        spec=spec, bound=bound, result=result, port=port, market=market, info=info, ranges=ranges, warnings=warnings,
        compat=compat, legacy_m=legacy_m, ustats=ustats, n_codes=len(codes), n_bars=int(in_period.sum()),
        period_used=[str(sub.close.index[0].date()), str(sub.close.index[-1].date())],
        warmup_bars=0 if compat else WARMUP_BARS, overrides=overrides, t_start=t_start, tick=tick)


def assemble_record(*, spec: Spec, bound: Spec, result: BacktestResult, port: PortfolioRules, market: Mapping[str, pd.DataFrame],
                    info: pd.DataFrame, ranges: dict, warnings: list[str], compat: bool, legacy_m: dict | None,
                    ustats: dict, n_codes: int, n_bars: int, period_used: list[str], warmup_bars: int,
                    overrides: Mapping[str, float] | None, t_start: float, tick: Progress,
                    extra_summary: dict | None = None, extra_meta: dict | None = None,
                    extra_value_warning: bool = False) -> RunRecord:
    """엔진 결과 → 표준 지표·견고성·경고·거래표·RunRecord. 일봉·분봉·틱 모드가 공유한다(result.equity 는 봉/일 단위 평가금)."""
    # ---- 지표
    tick("metrics", 0.85)
    eq = result.equity.copy()
    bench: dict[str, pd.Series] = {}
    for name in ("kospi", "kosdaq"):
        if name in market:
            s = market[name]["close"].astype(float).reindex(eq["ts"]).ffill()
            if s.notna().all() and len(s):
                bench[name] = pd.Series(s.to_numpy(), index=eq.index)
    std = standard_metrics(result, port.initial_capital,
                           benchmark=bench.get("kospi") if len(eq) else None)
    peak = np.maximum.accumulate(np.maximum(eq["equity"].to_numpy(), port.initial_capital))
    eq["drawdown_pct"] = (eq["equity"].to_numpy() / peak - 1) * 100
    for name, s in bench.items():
        eq[f"benchmark_{name}"] = s / s.iloc[0] * port.initial_capital

    # ---- 경고
    n_closed = sum(1 for t in result.trades if t.net_pnl is not None)
    n_entries = len({(t.entry_id if t.entry_id >= 0 else ("solo", k)) for k, t in enumerate(result.trades) if t.net_pnl is not None})
    warnings += [w for w in condition_warnings(bound) if w not in warnings]
    if n_entries < MIN_TRADES:  # 분할 청산 조각이 아니라 진입 건수로 센다
        warnings.append(f"거래 {n_entries}건 — {MIN_TRADES}건 미만이라 통계적으로 의미 있는 표본이 아니다")
    if n_entries != n_closed:
        warnings.append(f"분할 청산으로 진입 {n_entries}건이 {n_closed}개 조각으로 나뉘었다 — 승률·기대값·손익비는 진입 기준(조각 합산)이다")
    warnings.append("생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다")
    if _uses_value(bound) or extra_value_warning:
        warnings.append("거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)")
    if result.diagnostics.get("end_of_data"):
        warnings.append(f"데이터 끝에서 강제 청산된 종목 {len(result.diagnostics['end_of_data'])}건(end_of_data)")
    if compat and n_closed != len(result.trades):
        warnings.append("끝까지 청산되지 않은 거래가 있다 — 지표 집계에서 제외됨(호환 모드 규칙 7)")

    # ---- 거래표·기록
    trades_df = pd.DataFrame([{
        "code": t.code, "name": (info["name"].get(t.code) if t.code in info.index else None),
        "sector": (info["sector"].get(t.code) if "sector" in info.columns and t.code in info.index else None),
        "entry_ts": t.entry_ts, "entry_price": t.entry_price, "exit_ts": t.exit_ts, "exit_price": t.exit_price,
        "qty": t.qty, "gross_pnl": t.gross_pnl, "commission": t.commission, "tax": t.tax,
        "slippage_cost": t.slippage_cost, "net_pnl": t.net_pnl, "net_pct": t.net_pct,
        "exit_reason": str(t.exit_reason) if t.exit_reason is not None else None,
        "bars_held": t.bars_held, "mfe_pct": t.mfe_pct, "mae_pct": t.mae_pct,
        "entry_id": t.entry_id, "slice": t.slice,  # 분할 청산 조각 — 같은 entry_id 가 한 진입
    } for t in result.trades])
    elapsed = time.perf_counter() - t_start
    summary = _jsonable({
        "metrics": std, "legacy_metrics": legacy_m, "skipped": result.skipped,
        "n_trades": len(result.trades), "n_closed": n_closed, "n_entries": n_entries, "n_codes": n_codes, "n_bars": n_bars,
        "universe_excluded": ustats, "warnings": warnings,
        "robustness": robustness_report(trades_df, port.initial_capital, is_compat=compat) if len(trades_df) else None,
        # 사전 판정 기준(Spec.validation.criteria) — 실행 전에 spec 에 넣은 값 그대로, 이 전체 구간 지표로 판정
        "criteria": evaluate_criteria(bound.validation.criteria, std) if bound.validation and bound.validation.criteria else [],
        **(extra_summary or {}),
    })
    meta = _jsonable({
        "mode": bound.mode, "compat": compat, "spec_hash": spec_hash(bound), "structure_hash": structure_hash(spec),
        "params": {k: v.default for k, v in spec.params.items()} | dict(overrides or {}),
        "data": {k: [str(a), str(b)] for k, (a, b) in ranges.items()},
        "period_used": period_used, "warmup_bars": warmup_bars, "elapsed_sec": round(elapsed, 3), "warnings": warnings,
        **(extra_meta or {}),
    })
    tick("done", 1.0)
    return RunRecord(spec=spec, meta=meta, summary=summary, trades=trades_df, equity=eq, warnings=warnings)
