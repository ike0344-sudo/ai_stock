"""지표 카탈로그 — 설계서 §3.7. 이름·파라미터·한국어 설명·모드·시점 규칙의 단일 출처.

순수 데이터 모듈(계산 없음). 분봉 전용 지표 계산은 `intraday.py`, 틱 조건(조립기 지표가 아니라
`spec.tick.catalog`)은 `tick.py`(TICK_CATALOG 는 목록). ast.py 가 검증에, narration.py 가 문장에, 화면이 조립기 메뉴에 쓴다.
단위: change_pct·gap_pct 는 **퍼센트**(5 = +5%) — market 등락률·day_change_pct 와 맞춘다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

FIELDS = ("open", "high", "low", "close", "volume", "value")
MODES = ("daily_single", "daily_portfolio", "intraday", "tick")
_ALL = MODES
_DAILY_INTRA = ("daily_single", "daily_portfolio", "intraday")
_DAILY = ("daily_single", "daily_portfolio")
_INTRA = ("intraday", "tick")
_ONLY_INTRA = ("intraday",)

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


@dataclass(frozen=True)
class IndicatorDef:
    name: str
    label_ko: str
    desc_ko: str
    params: tuple[ParamDef, ...]
    modes: tuple[str, ...]
    timing_ko: str
    compute: bool = True  # False = 목록 전용(계산은 module-6)

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

INDICATORS: dict[str, IndicatorDef] = {d.name: d for d in _DEFS}

# 틱 카탈로그(진입 조건 4종) — 조립기 지표가 아니라 `spec.tick.catalog` 로 표현. 계산은 module-6.
TICK_CATALOG: dict[str, str] = {
    "breakout_min": "N분 고점 돌파([t−w,t), t 제외)",
    "value_speed": "체결대금 속도(인과적 누적 평균 대비 ratio 배)",
    "buy_ratio": "틱룰 매수 비중(w분, 최소 비율)",
    "time_window": "시간대(time_from ~ time_to)",
}

MARKET_NAMES = ("close", "sma", "change_pct")
MARKET_INDEXES = ("kospi", "kosdaq")


def resolve_params(name: str, given: dict[str, Any]) -> dict[str, Any]:
    """기본값을 채운 파라미터 사본. 알 수 없는 키·지표는 KeyError."""
    d = INDICATORS[name]
    unknown = set(given) - {p.name for p in d.params}
    if unknown:
        raise KeyError(f"{name} 에 없는 파라미터: {sorted(unknown)}")
    return {p.name: given.get(p.name, p.default) for p in d.params}
