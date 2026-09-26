"""기존 전략 8종 레지스트리 + 넓은 표 어댑터 — 설계서 §3.2 strategy.source="legacy", §5.4.

`backtesting/strategies/*` 를 **수정하지 않고** 그대로 부른다(읽기 전용 재사용). 종목마다
그 종목 자신의 거래일 캔들(종가 있는 날)로 `evaluate` 를 호출해 기존 연구와 신호가 같게 한다.
ml_strategy 는 제외(스튜디오 범위 밖). `backtesting.strategies` 패키지는 __init__ 에서 ml_strategy
(lightgbm 등)를 끌고 오므로 **지연 import** — 실패해도 스튜디오 나머지가 살아 있게.
기본값·범위 출처: cli.py 격자(ma 5/20·rsi 14/30/70·envelope 60/0.02/ma_touch)와 각 전략 클래스 상수.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

import pandas as pd

from studio.domain.conditions.evaluator import BUY, HOLD, SELL, Evaluation


@dataclass(frozen=True)
class LegacyParam:
    name: str
    kind: str  # "int" | "float" | "enum"
    default: Any
    lo: float | None = None
    hi: float | None = None
    choices: tuple[str, ...] | None = None
    label_ko: str = ""
    optional: bool = False  # None 허용(전략이 알아서 기본 계산)


@dataclass(frozen=True)
class LegacyDef:
    name: str
    label_ko: str
    module: str
    cls: str
    params: tuple[LegacyParam, ...]
    deprecated: bool = False
    note: str = ""


_N = LegacyParam("n_day_high", "int", 20, 2, 500, label_ko="신고가 기준 일수(그리드: 20/60/120)")
_EXIT_LOW = LegacyParam(
    "exit_low_days", "int", None, 2, 500, label_ko="청산 저가채널 일수(비우면 신고가 일수 ÷ 3)", optional=True
)

REGISTRY: dict[str, LegacyDef] = {d.name: d for d in (
    LegacyDef("ma_crossover", "이동평균 크로스", "ma_crossover", "MovingAverageCrossover", (
        LegacyParam("short_window", "int", 5, 1, 499, label_ko="단기 이평(일)"),
        LegacyParam("long_window", "int", 20, 2, 500, label_ko="장기 이평(일)"),
    )),
    LegacyDef("rsi", "RSI 과매도·과매수", "rsi_strategy", "RsiStrategy", (
        LegacyParam("period", "int", 14, 1, 500, label_ko="RSI 기간"),
        LegacyParam("buy_below", "float", 30, 0, 100, label_ko="이 값 미만이면 매수"),
        LegacyParam("sell_above", "float", 70, 0, 100, label_ko="이 값 초과면 매도"),
    )),
    LegacyDef("envelope", "엔벨로프 평균회귀", "envelope", "EnvelopeStrategy", (
        LegacyParam("ma_window", "int", 60, 1, 500, label_ko="이평 기간(일)"),
        LegacyParam("envelope_pct", "float", 0.02, 0.001, 0.5, label_ko="밴드 폭(0.02 = ±2%)"),
        LegacyParam("exit_mode", "enum", "ma_touch", choices=("ma_touch", "opposite_band"), label_ko="청산 방식"),
    )),
    LegacyDef("new_high_swing", "N일 신고가 스윙", "new_high_swing", "NewHighSwing", (_N, _EXIT_LOW)),
    LegacyDef("pullback_reentry", "눌림목 재돌파", "pullback_reentry", "PullbackReentry", (
        _N, _EXIT_LOW,
        LegacyParam("pullback_window_days", "int", 10, 1, 250, label_ko="눌림 허용 일수"),
        LegacyParam("reentry_days", "int", 3, 1, 250, label_ko="재돌파 확인 일수"),
    ), deprecated=True, note="가설 기각으로 폐기(기록용) — 코스피 상관 0.34, 국면의존"),
    LegacyDef("vcp_breakout", "변동성 수축 신고가 돌파", "vcp_breakout", "VcpBreakout", (_N, _EXIT_LOW)),
    LegacyDef("new_high_leg_exit", "신고가 스윙 · 청산가설A(구간 저점 이탈)", "new_high_leg_exit", "NewHighLegExit", (_N,)),
    LegacyDef(
        "new_high_volume_divergence_exit", "신고가 스윙 · 청산가설B(거래량 다이버전스)",
        "new_high_volume_divergence_exit", "NewHighVolumeDivergenceExit", (_N,),
    ),
)}


def validate_params(name: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """기본값을 채우고 형·범위를 검사한 사본(None 인 선택 파라미터는 뺀다). 오류는 ValueError."""
    d = REGISTRY.get(name)
    if d is None:
        raise ValueError(f"없는 기존 전략 '{name}' (가능: {sorted(REGISTRY)})")
    given = dict(params or {})
    known = {p.name: p for p in d.params}
    unknown = set(given) - set(known)
    if unknown:
        raise ValueError(f"{name} 에 없는 파라미터 {sorted(unknown)} (가능: {sorted(known)})")
    out: dict[str, Any] = {}
    for p in d.params:
        v = given.get(p.name, p.default)
        if v is None:
            if not p.optional:
                raise ValueError(f"{name}.{p.name} 는 필수")
            continue
        if p.kind == "enum":
            if v not in (p.choices or ()):
                raise ValueError(f"{name}.{p.name}: {v!r} 는 허용값 {list(p.choices or ())} 이 아님")
        else:
            if isinstance(v, (bool, str)):
                raise ValueError(f"{name}.{p.name}: 숫자여야 함 ({v!r})")
            if p.kind == "int":
                if not float(v).is_integer():
                    raise ValueError(f"{name}.{p.name}: 정수여야 함 ({v!r})")
                v = int(v)
            if (p.lo is not None and v < p.lo) or (p.hi is not None and v > p.hi):
                raise ValueError(f"{name}.{p.name}: {v} 는 범위 {p.lo}~{p.hi} 밖")
        out[p.name] = v
    if name == "ma_crossover" and out["short_window"] >= out["long_window"]:
        raise ValueError("ma_crossover: short_window 는 long_window 보다 작아야 함")
    return out


def _strategy(d: LegacyDef) -> Any:
    try:
        mod = importlib.import_module(f"backtesting.strategies.{d.module}")
    except Exception as e:  # ml_strategy 의존성(lightgbm 등) 누락 포함
        raise RuntimeError(f"기존 전략 '{d.name}' 를 불러오지 못함: {e}") from e
    return getattr(mod, d.cls)()


def legacy_signals(name: str, params: dict[str, Any] | None, panel: Any) -> pd.DataFrame:
    """종목별 기존 전략 신호 표('buy'/'sell'/'hold' — Signal.value 와 같은 문자열).

    종목마다 **종가가 있는 날만** 남겨 `evaluate` 를 부른다 — 기존 연구가 보던 캔들과 같게(거래정지일이
    NaN 으로 끼면 rolling 이 어긋나 신호가 달라진다).
    """
    d = REGISTRY[name]
    p = validate_params(name, params)
    strat = _strategy(d)
    idx, cols = panel.close.index, panel.close.columns
    out = pd.DataFrame(HOLD, index=idx, columns=cols, dtype=object)
    for code in cols:
        candles = pd.DataFrame({f: getattr(panel, f)[code] for f in ("open", "high", "low", "close", "volume")})
        candles = candles[candles["close"].notna()]
        if candles.empty:
            continue
        sig = strat.evaluate(candles, p)
        out.loc[candles.index, code] = [s.value for s in sig]
    return out


def evaluate_legacy(name: str, params: dict[str, Any] | None, panel: Any) -> Evaluation:
    """조립기 평가기와 같은 출력(진입·청산 bool 표). BUY→진입, SELL→청산."""
    sig = legacy_signals(name, params, panel)
    return Evaluation(entry=sig.eq(BUY), exit=sig.eq(SELL))
