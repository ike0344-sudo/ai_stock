"""분봉 전용 지표의 카탈로그 등록 — 설계 studio-conditions §3.3 「분봉 전용」. 계산은 `intraday.py`(순수 함수).

기존 4종(day_change_pct·time·cum_value·vwap)은 `catalog.py` 에 있고, 여기는 추가분. 계산은 `compute` 가 INTRADAY_ONLY 이름을
`compute_intraday` 로 바로 보내므로(빈 봉 재계산 경로 없음) COMPUTE 등록은 필요 없다.
전부 t 까지의 값만 쓴다 — 하루 안 누적·앞 봉 최고·첫 봉 시가·같은 시각 다른 종목 값.
"""
from __future__ import annotations

from .catalog import IndicatorDef, ParamDef, register_indicators
from .intraday import INTRADAY_ONLY

_ONLY = ("intraday",)

DEFS = (
    IndicatorDef(
        "open_change_pct", "당일 시가 대비(%)", "봉 종가 ÷ 당일 시가 − 1 (퍼센트). 당일 시가 = 그 날 첫 봉 시가", (), _ONLY, "t 까지",
        category="intraday", definition="(C_t ÷ 당일 첫 봉 시가 − 1) × 100", example="시가 대비 3% 이상 상승 중",
    ),
    IndicatorDef(
        "day_high_break", "당일 고점 돌파(1/0)", "t 봉이 당일 앞 봉들의 최고가를 넘으면 1(첫 봉은 값 없음)",
        (ParamDef("src", "enum", "close", choices=("close", "high"), label_ko="비교 값(종가/고가)"),), _ONLY, "앞 봉 t 제외",
        category="intraday", definition="X_t > max(당일 앞 봉 고가), X = 종가 또는 고가", example="종가가 당일 고점을 갱신",
    ),
    IndicatorDef(
        "day_low_break", "당일 저점 이탈(1/0)", "t 봉이 당일 앞 봉들의 최저가 아래면 1(첫 봉은 값 없음)",
        (ParamDef("src", "enum", "close", choices=("close", "low"), label_ko="비교 값(종가/저가)"),), _ONLY, "앞 봉 t 제외",
        category="intraday", definition="X_t < min(당일 앞 봉 저가), X = 종가 또는 저가", example="종가가 당일 저점을 이탈",
    ),
    IndicatorDef(
        "minutes_since_open", "장 시작 후 경과(분)", "09:00 부터 봉 끝까지 경과 분(장 전 봉은 음수)", (), _ONLY, "—",
        category="intraday", definition="봉 끝 시각 − 09:00 (분)", example="장 시작 후 30분 이내",
    ),
    IndicatorDef(
        "first_n_value", "장 초반 N분 누적 대금", "장 시작 후 N분 동안 누적 거래대금 — N분이 지난 봉부터 값이 있음(N 은 봉 길이의 배수)",
        (ParamDef("n", "int", 5, 1, 390, label_ko="분"),), _ONLY, "N분 뒤부터",
        category="intraday", definition="Σ 대금(09:00 < 봉 끝 ≤ 09:00+n) — n분 뒤부터 고정", example="장 시작 5분 대금 ≥ 50억",
        volume_based=True,
    ),
    IndicatorDef(
        "vwap_disparity", "VWAP 이격(%)", "봉 종가의 당일 VWAP 대비 이격(퍼센트)", (), _ONLY, "t 까지",
        category="intraday", definition="(C_t ÷ VWAP_t − 1) × 100", example="VWAP 위 1% 이상", volume_based=True,
    ),
    IndicatorDef(
        "cum_value_rank", "당일 누적 대금 순위", "같은 시각 유니버스(표의 종목들) 안 당일 누적 거래대금 순위(1=최대, 동률 같은 순위)",
        (), _ONLY, "t 시각의 다른 종목 값",
        category="intraday", definition="rank_desc(당일 누적 대금_t) — 종목 간(같은 t)", example="지금 누적 대금 상위 10위",
        volume_based=True,
    ),
)
assert {d.name for d in DEFS} <= set(INTRADAY_ONLY)  # 계산 분기와 어긋나면 import 에서 바로 실패
register_indicators(DEFS)
