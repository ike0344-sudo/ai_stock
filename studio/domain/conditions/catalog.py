"""지표 카탈로그 — 설계서 §3.7. 이름·파라미터·한국어 설명·모드·시점 규칙의 단일 출처.

순수 데이터 모듈(계산 없음). 분봉 전용 지표 계산은 `intraday.py`, 틱 조건(조립기 지표가 아니라
`spec.tick.catalog`)은 `tick.py`(TICK_CATALOG 는 목록). ast.py 가 검증에, narration.py 가 문장에, 화면이 조립기 메뉴에 쓴다.
단위: change_pct·gap_pct 는 **퍼센트**(5 = +5%) — market 등락률·day_change_pct 와 맞춘다.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Literal

FIELDS = ("open", "high", "low", "close", "volume", "value")
MODES = ("daily_single", "daily_portfolio", "intraday", "tick")
_ALL = MODES
_DAILY_INTRA = ("daily_single", "daily_portfolio", "intraday")
_DAILY = ("daily_single", "daily_portfolio")
_INTRA = ("intraday", "tick")
_ONLY_INTRA = ("intraday",)

# 피연산자 시간 단위(설계 studio-conditions §3.1·§3.2) — 화면·검증·평가기가 이 목록을 쓴다.
TIMEFRAMES = ("bar", "m1", "m3", "m5", "m10", "m15", "m30", "m60", "daily_prev", "daily_live")
MINUTE_TIMEFRAMES = {"m1": 1, "m3": 3, "m5": 5, "m10": 10, "m15": 15, "m30": 30, "m60": 60}
POS_NAMES = ("return_pct", "bars_held", "minutes_held", "max_return_pct", "drawdown_pct", "entry_price")  # 청산 전용 포지션 값

N_MIN, N_MAX = 1, 500  # 기간(봉 수) 범위 — 설계 근거: 일봉 2년 ≈ 500봉


@dataclass(frozen=True)
class ParamDef:
    name: str
    kind: Literal["int", "float", "bool", "enum"]
    default: Any
    lo: float | None = None
    hi: float | None = None
    choices: tuple[str, ...] | None = None
    label_ko: str = ""

    @property
    def numeric(self) -> bool:
        return self.kind in ("int", "float")


# 분류 나무(설계 studio-conditions §5.4) — 화면·검색·/api/meta/indicators 가 이 키·이름을 쓴다.
CATEGORIES: dict[str, str] = {
    "trend": "가격·이평·신고가",
    "oscillator": "보조지표",
    "candle": "캔들",
    "volume": "거래량·순위",
    "group": "테마·업종·시장",
    "intraday": "분봉 전용",
    "tick": "틱 전용",
    "position": "포지션(청산만)",
}


@dataclass(frozen=True)
class IndicatorDef:
    """지표(조건) 정의 — **카탈로그가 유일한 출처**: 평가기·검증·풀이 문장·화면 설명이 전부 여기서 나온다.

    새 지표를 정의하는 쪽(`ind_*.py`)이 채울 칸:
      category   CATEGORIES 의 키
      definition 정의 식 한 줄(화면 설명·도움말) — 예 "SMA_n = (C_t + … + C_{t−n+1}) ÷ n"
      timing_ko  시점 규칙(t 포함/제외, D−1 등) — 기존 칸 그대로(`timing` 은 같은 값의 별칭)
      example    사용 예 한 줄 — 예 "종가가 20일선 위"
      live       `daily_live`(장중 실시간 일봉) 지원 여부 — **점화식이 O(1)** 이라 (D−1 확정값 + 오늘 가상 봉)으로 봉마다 바로 계산되는 것만 True
                 (True 면 `timeframe.LIVE_COMPUTE` 에 같은 이름의 계산 함수가 있어야 한다). 거래량·거래대금 계열은 `volume_based=True` 도 켠다
                 → daily_live 는 KRX 분봉에서만 허용(통합 분봉+KRX 일봉을 섞으면 20~40% 부풀려짐).
    """

    name: str
    label_ko: str
    desc_ko: str
    params: tuple[ParamDef, ...]
    modes: tuple[str, ...]
    timing_ko: str
    compute: bool = True  # False = 목록 전용(계산은 module-6)
    category: str = "trend"
    definition: str = ""
    example: str = ""
    live: bool = False
    volume_based: bool = False

    @property
    def timing(self) -> str:
        return self.timing_ko

    @property
    def live_reason_ko(self) -> str:
        """`daily_live` 지원 여부의 사람 말 — 화면이 비활성 이유/조건으로 보여 준다. 지원하고 조건도 없으면 빈 문자열."""
        if self.live:
            return "거래량·거래대금 계열이라 KRX 분봉(intraday.source=krx)에서만 쓸 수 있다" if self.volume_based else ""
        if self.category in ("intraday", "tick"):
            return "분봉·틱 전용 지표라 일봉 시간 단위가 없다"
        return "일봉 장중 값을 봉마다 O(1) 점화식으로 만들 수 없는 지표라 일봉 전일(daily_prev) 값으로만 쓸 수 있다"

    def param(self, name: str) -> ParamDef | None:
        return next((p for p in self.params if p.name == name), None)


def _n(default: int = 20, name: str = "n") -> ParamDef:
    return ParamDef(name, "int", default, N_MIN, N_MAX, label_ko="기간(봉)")


def _src(default: str = "close") -> ParamDef:
    return ParamDef("src", "enum", default, choices=FIELDS, label_ko="대상 값")


_DEFS: tuple[IndicatorDef, ...] = (
    IndicatorDef("sma", "이동평균", "대상 값의 N봉 단순 이동평균", (_src(), _n()), _ALL, "t 포함"),
    IndicatorDef("ema", "지수이동평균", "대상 값의 N봉 지수 이동평균(span=N)", (_src(), _n()), _ALL, "t 포함"),
    IndicatorDef("rsi", "RSI", "단순평균 RSI — 기존 compute_rsi 와 같음(손실 0 이면 100)", (_n(14),), _ALL, "t 포함"),
    IndicatorDef("rsi_wilder", "RSI(와일더)", "와일더 평활 RSI(alpha=1/N)", (_n(14),), _ALL, "t 포함"),
    IndicatorDef(
        "highest", "N봉 최고값", "직전 N봉 최고값(기본: 오늘 제외 → 돌파 판정용)",
        (_src("high"), _n(), ParamDef("include_current", "bool", False, label_ko="오늘 포함")),
        _ALL, "기본 t 제외",
    ),
    IndicatorDef(
        "lowest", "N봉 최저값", "직전 N봉 최저값(기본: 오늘 제외 → 이탈 판정용)",
        (_src("low"), _n(), ParamDef("include_current", "bool", False, label_ko="오늘 포함")),
        _ALL, "기본 t 제외",
    ),
    IndicatorDef("change_pct", "N봉 등락률(%)", "종가의 N봉 전 대비 등락률(퍼센트)", (_n(1),), _ALL, "t 포함"),
    IndicatorDef("gap_pct", "갭(%)", "당일 시가 ÷ 전일 종가 − 1 (퍼센트)", (), _DAILY_INTRA, "당일 시가"),
    IndicatorDef("atr", "ATR", "진폭(TR)의 N봉 단순평균", (_n(14),), _ALL, "t 포함"),
    IndicatorDef(
        "bb_upper", "볼린저 상단", "종가 SMA + k × 표준편차(모표준편차)",
        (_n(20), ParamDef("k", "float", 2.0, 0.1, 10.0, label_ko="표준편차 배수")), _ALL, "t 포함",
    ),
    IndicatorDef(
        "bb_lower", "볼린저 하단", "종가 SMA − k × 표준편차(모표준편차)",
        (_n(20), ParamDef("k", "float", 2.0, 0.1, 10.0, label_ko="표준편차 배수")), _ALL, "t 포함",
    ),
    IndicatorDef(
        "vol_ratio", "거래량 배수", "거래량 ÷ 직전 N봉 평균(평균은 오늘 제외). 경계값·평균 0 처리가 "
        "`거래량 ≥ 평균 × 배수` 와 미세하게 다를 수 있음", (_n(),), _ALL, "평균 t 제외",
    ),
    IndicatorDef(
        "value_rank", "거래대금 순위", "최근 lookback일 평균 거래대금의 종목 간 순위(1=최대)",
        (ParamDef("lookback", "int", 1, 1, 60, label_ko="평균 일수"),), _DAILY, "t 종가",
    ),
    # ---- 분봉 전용(module-6): 날짜가 여러 개인 분봉 표에서만 계산됨 — 일봉 표에서 부르면 ValueError ----
    IndicatorDef("day_change_pct", "당일 등락률(%)", "봉 종가의 전일 종가(D−1) 대비 등락률(퍼센트)", (), _INTRA, "전일 종가 D−1"),
    IndicatorDef("time", "시각", "봉 끝 시각 HHMM (예: 09:05 → 905)", (), _ONLY_INTRA, "—"),
    IndicatorDef("cum_value", "당일 누적 거래대금", "당일 누적 거래대금(날이 바뀌면 0부터)", (), _ONLY_INTRA, "t 까지"),
    IndicatorDef("vwap", "VWAP", "당일 누적 거래대금 ÷ 당일 누적 거래량(날이 바뀌면 다시 시작)", (), _ONLY_INTRA, "t 까지"),
)

# 기존 지표의 분류·정의 식·예시·live (정의 자체는 위에 그대로 — 여기서만 채운다)
_META: dict[str, dict[str, Any]] = {
    "sma": dict(category="trend", definition="SMA_n = (X_t + … + X_{t−n+1}) ÷ n", example="종가가 20일 이동평균 위", live=True),
    "ema": dict(category="trend", definition="EMA_t = α·X_t + (1−α)·EMA_{t−1}, α = 2÷(n+1) (시작 n봉은 값 없음)", example="종가가 12일 지수이평 위", live=True),
    "rsi": dict(category="oscillator", definition="RSI = 100 − 100÷(1+평균상승÷평균하락), 평균은 n봉 단순평균(하락 0 이면 100)", example="RSI(14) ≥ 70", live=True),
    "rsi_wilder": dict(category="oscillator", definition="RSI 의 평균을 와일더 평활(α=1÷n)로", example="와일더 RSI(14) < 30", live=True),
    "highest": dict(category="trend", definition="직전 n봉 X 의 최댓값(기본 오늘 제외 — 돌파 기준선)", example="종가 > 20일 신고가(어제까지)", live=True),
    "lowest": dict(category="trend", definition="직전 n봉 X 의 최솟값(기본 오늘 제외 — 이탈 기준선)", example="종가 < 10일 최저가(어제까지)", live=True),
    "change_pct": dict(category="trend", definition="(C_t ÷ C_{t−n} − 1) × 100", example="5일 등락률 ≥ 10%", live=True),
    "gap_pct": dict(category="trend", definition="(당일 시가 ÷ 전일 종가 − 1) × 100", example="갭 상승 3% 이상", live=True),
    "atr": dict(category="oscillator", definition="TR = max(H−L, |H−전일C|, |L−전일C|), ATR = TR 의 n봉 단순평균", example="ATR(14) ÷ 종가 ≥ 3%"),
    "bb_upper": dict(category="oscillator", definition="종가 SMA_n + k × 표준편차(모표준편차)", example="종가 > 볼린저 상단(20, 2)", live=True),
    "bb_lower": dict(category="oscillator", definition="종가 SMA_n − k × 표준편차(모표준편차)", example="종가 < 볼린저 하단(20, 2)", live=True),
    "vol_ratio": dict(category="volume", definition="V_t ÷ (직전 n봉 V 평균, 오늘 제외)", example="거래량이 20일 평균의 3배 이상", volume_based=True),
    "value_rank": dict(category="volume", definition="최근 lookback일 평균 거래대금의 종목 간 순위(1=최대)", example="거래대금 순위 ≤ 30", volume_based=True),
    "day_change_pct": dict(category="intraday", definition="(C_t ÷ 전일 종가(D−1) − 1) × 100", example="당일 등락률 ≥ 5%"),
    "time": dict(category="intraday", definition="봉 끝 시각 HHMM (09:05 → 905)", example="09:05 이후 10:30 이전"),
    "cum_value": dict(category="intraday", definition="당일 누적 거래대금(날이 바뀌면 0부터)", example="당일 누적 거래대금 ≥ 100억", volume_based=True),
    "vwap": dict(category="intraday", definition="당일 누적 거래대금 ÷ 당일 누적 거래량(날이 바뀌면 다시 시작)", example="종가 > VWAP", volume_based=True),
}
_DEFS = tuple(replace(d, **_META[d.name]) for d in _DEFS)

INDICATORS: dict[str, IndicatorDef] = {d.name: d for d in _DEFS}

# 확장 지표의 계산 함수 — `register_indicators` 가 채운다. indicators.compute 가 여기를 먼저 본다.
# 시그니처: fn(panel, params: dict) -> DataFrame (panel 은 덕 타이핑 open/high/low/close/volume/value/prev_close, 지표 값은 t 까지만 사용)
COMPUTE_REGISTRY: dict[str, Callable[[Any, dict[str, Any]], Any]] = {}
# `daily_live` 계산 함수 — live=True 인 지표마다 필요. 시그니처는 timeframe.LiveBars 참고.
LIVE_REGISTRY: dict[str, Callable[..., Any]] = {}
# 종목 간 비교 지표(순위·테마·업종) — 열별 재계산(own_days) 없이 전체 Panel 로 한 번만 계산해야 하는 이름. `ind_*.py` 가 채운다.
CROSS_SECTIONAL: set[str] = set()


def register_indicators(defs: Iterable[IndicatorDef], compute: dict[str, Callable] | None = None,
                        live: dict[str, Callable] | None = None) -> None:
    """`ind_*.py` 모듈이 자기 지표를 카탈로그에 올린다(이름 중복은 오류 — 기존 지표를 조용히 덮어쓰지 않는다)."""
    for d in defs:
        if d.name in INDICATORS:
            raise ValueError(f"이미 있는 지표 이름: {d.name}")
        if d.category not in CATEGORIES:
            raise ValueError(f"{d.name}: category {d.category!r} 는 {sorted(CATEGORIES)} 중 하나")
        if d.live and d.name not in (live or {}):
            raise ValueError(f"{d.name}: live=True 인데 live 계산 함수가 없다")
        INDICATORS[d.name] = d
    COMPUTE_REGISTRY.update(compute or {})
    LIVE_REGISTRY.update(live or {})


# 분류별 확장 모듈 — 각 모듈은 import 시 `register_indicators(DEFS, COMPUTE, LIVE)` 를 부른다. 없는 모듈은 건너뜀(병렬 개발 중).
EXTENSION_MODULES = ("ind_trend", "ind_oscillator", "ind_candle", "ind_volume", "ind_group", "ind_intraday")

# 틱 카탈로그(진입 조건 4종) — 조립기 지표가 아니라 `spec.tick.catalog` 로 표현. 계산은 module-6.
TICK_CATALOG: dict[str, str] = {
    "breakout_min": "N분 고점 돌파([t−w,t), t 제외)",
    "value_speed": "체결대금 속도(인과적 누적 평균 대비 ratio 배)",
    "buy_ratio": "틱룰 매수 비중(w분, 최소 비율)",
    "trade_strength": "체결강도(w초 틱룰 매수량÷매도량×100 이상)",
    "block_trades": "대량 체결(w초 안 한 번에 min_value 이상 체결 건수)",
    "daily_breakout": "현재가 > D−1까지 n일 최고가(틱 단위 N일 신고가 돌파)",
    "value_window": "최근 w분 체결대금 합(억 원, 가격×수량 정확값) ≥ min_eok — 창 (s−w, s]",
    "time_window": "시간대(time_from ~ time_to)",
}

MARKET_NAMES = ("close", "sma", "change_pct")
MARKET_INDEXES = ("kospi", "kosdaq")


# daily_prev 규칙(lead 판정 2026-09-26): "오늘(D) 장 시작 전에 알 수 있는 값" — 지표의 **행 D 값이 봉 D 자료에 의존하지 않으면 행 D**(현재 봉을 빼는 지표),
# 의존하면 행 D−1. 기본 False(안전 쪽 D−1). **여기 표시한 지표는 카나리아 필수**(봉 D 변조 → 그날 daily_prev 값 불변): tests/studio/conditions/test_daily_prev_rule.py
_EXCLUDES_CURRENT = {
    "highest": lambda p: not p.get("include_current"),
    "lowest": lambda p: not p.get("include_current"),
}


def excludes_current(name: str, params: dict[str, Any]) -> bool:
    """이 (지표, 파라미터)의 일봉 행 D 값이 봉 D 자료를 쓰지 않나(highest/lowest 의 include_current=False). daily_prev 가 행 D 를 쓸지 정한다."""
    fn = _EXCLUDES_CURRENT.get(name)
    return bool(fn and fn(resolve_params(name, params)))


def resolve_params(name: str, given: dict[str, Any]) -> dict[str, Any]:
    """기본값을 채운 파라미터 사본. 알 수 없는 키·지표는 KeyError."""
    d = INDICATORS[name]
    unknown = set(given) - {p.name for p in d.params}
    if unknown:
        raise KeyError(f"{name} 에 없는 파라미터: {sorted(unknown)}")
    return {p.name: given.get(p.name, p.default) for p in d.params}


def load_extensions() -> list[str]:
    """EXTENSION_MODULES 를 import(각 모듈이 자기 지표를 등록). 이미 불러온 모듈은 그대로. 불러온 모듈 이름 목록."""
    loaded = []
    for m in EXTENSION_MODULES:
        try:
            importlib.import_module(f"{__package__}.{m}")
            loaded.append(m)
        except ModuleNotFoundError as e:
            if e.name != f"{__package__}.{m}":  # 그 모듈 자신이 없는 게 아니라 안쪽 import 실패는 진짜 오류
                raise
    return loaded


load_extensions()  # 파일 맨 아래 — 위 정의가 다 끝난 뒤에 ind_*.py 가 catalog 를 import 해도 안전하다
