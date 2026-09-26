"""거래량·순위 지표 — 설계서 studio-conditions §3.3 「거래량·순위」. 순수 계산(numpy/pandas)만.

- `vol_change_pct`·`value_ratio` — 한 종목 시계열 안의 계산(빈칸 종목은 `own_days` 가 자기 거래일로 다시 계산).
- `volume_rank`·`top_value_count` — **종목 간 비교**라 열별 재계산이 불가능하다 → `CROSS_SECTIONAL` 에 올려
  `compute` 가 전체 Panel 로 한 번만 부르게 한다(`value_rank` 와 같은 처리: 평균은 자기 거래일로, 순위는 전체로).
- 시점: 전부 **t 까지**의 값(순위는 그날 종가 기준 = t 포함, 평균 기준선은 t 제외). 분봉에서 일봉 순위를 쓰려면 `tf=daily_prev`(D−1).
- `daily_live`: vol_change_pct·value_ratio 는 지원(`live=True`, 거래량 계열이라 KRX 분봉에서만 허용 — validation 이 막음).
  오늘 가상 봉의 누적 거래량·대금(`live.v`/`live.val`) ÷ D−1 확정 기준값. 빈칸(거래정지) 종목은 마지막 자기 거래일 값(ffill).
  volume_rank·top_value_count 는 종목 간 비교라 live 없음(`daily_prev` 만).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .catalog import CROSS_SECTIONAL, IndicatorDef, ParamDef, register_indicators

Frame = pd.DataFrame
_DAILY_INTRA = ("daily_single", "daily_portfolio", "intraday")
_DAILY = ("daily_single", "daily_portfolio")


def _n(default: int) -> ParamDef:
    return ParamDef("n", "int", default, 1, 500, label_ko="기간(봉)")


def vol_change_pct(volume: Frame) -> Frame:
    """V_t ÷ V_{t−1} × 100. 직전 거래량이 0/없음이면 값 없음."""
    prev = volume.shift(1)
    return volume / prev.where(prev > 0) * 100


def value_ratio(value: Frame, n: int) -> Frame:
    """거래대금 ÷ 직전 n봉 평균(오늘 제외). 평균이 0 이하면 값 없음."""
    avg = value.shift(1).rolling(n).mean()
    return value / avg.where(avg > 0)


def _rank_desc(x: Frame) -> Frame:
    return x.rank(axis=1, ascending=False, method="min")  # 1=최대, 동률은 같은 순위(value_rank 와 같음)


def volume_rank(panel: Any, lookback: int) -> Frame:
    from .indicators import own_days  # 지연 import — catalog 가 이 모듈을 불러오는 중에 indicators 를 다시 부르지 않게

    base = panel.volume if lookback == 1 else own_days(panel, lambda pn: pn.volume.rolling(lookback).mean())
    return _rank_desc(base)


def top_value_count(value: Frame, n: int, m: int) -> Frame:
    """최근 n거래일(t 포함) 중 그날 거래대금 순위가 m 이내였던 날 수. 창이 다 안 찼으면 값 없음."""
    hit = (_rank_desc(value) <= m).astype(float)
    return hit.rolling(n, min_periods=n).sum()


def _compute_volume_rank(panel: Any, p: dict[str, Any]) -> Frame:
    return volume_rank(panel, int(p["lookback"]))


def _compute_top_value_count(panel: Any, p: dict[str, Any]) -> Frame:
    return top_value_count(panel.value, int(p["n"]), int(p["m"]))


DEFS = (
    IndicatorDef(
        "vol_change_pct", "직전 봉 대비 거래량(%)", "거래량 ÷ 직전 봉 거래량 × 100(직전이 0 이면 값 없음)", (),
        _DAILY_INTRA, "t 포함", category="volume", definition="V_t ÷ V_{t−1} × 100",
        example="거래량이 어제의 3배(300%) 이상", volume_based=True, live=True,
    ),
    IndicatorDef(
        "value_ratio", "거래대금 N봉 평균 대비", "거래대금 ÷ 직전 N봉 평균(평균은 오늘 제외, 평균 0 이면 값 없음)", (_n(20),),
        _DAILY_INTRA, "평균 t 제외", category="volume", definition="대금_t ÷ (직전 n봉 대금 평균, 오늘 제외)",
        example="거래대금이 20일 평균의 5배 이상", volume_based=True, live=True,
    ),
    IndicatorDef(
        "volume_rank", "거래량 순위", "최근 lookback일 평균 거래량의 종목 간 순위(1=최대, 동률은 같은 순위)",
        (ParamDef("lookback", "int", 1, 1, 60, label_ko="평균 일수"),), _DAILY, "t 종가",
        category="volume", definition="최근 lookback일 평균 거래량의 종목 간 순위(1=최대)",
        example="거래량 순위 ≤ 30", volume_based=True,
    ),
    IndicatorDef(
        "top_value_count", "대금 상위 진입 횟수",
        "최근 n일(오늘 포함) 중 그날 거래대금 순위가 m 이내였던 날 수 — 종목 하나의 시간축 횟수(테마 안 종목 수가 아님)",
        (ParamDef("n", "int", 10, 1, 250, label_ko="최근 일수"), ParamDef("m", "int", 30, 1, 500, label_ko="상위 순위")),
        _DAILY, "t 종가(오늘 포함)", category="volume",
        definition="Σ_{i=0..n−1} [ 대금순위_{t−i} ≤ m ]  (n일 창이 다 차야 값이 있음)",
        example="최근 10일 중 대금 상위 30위에 5번 이상", volume_based=True,
    ),
)
COMPUTE = {"volume_rank": _compute_volume_rank, "top_value_count": _compute_top_value_count}

# 순위는 종목 간 비교 → 열별 재계산(own_days) 금지. volume_rank 는 평균을 안에서 자기 거래일로 낸다.
CROSS_SECTIONAL.update(COMPUTE)


def _elementwise(name: str):
    if name == "vol_change_pct":
        return lambda panel, p: vol_change_pct(panel.volume)
    return lambda panel, p: value_ratio(panel.value, int(p["n"]))


COMPUTE.update({d.name: _elementwise(d.name) for d in DEFS if d.name in ("vol_change_pct", "value_ratio")})


def _live_vol_change_pct(live: Any, p: dict[str, Any]) -> Frame:
    prev = live.prev(live.own(lambda pn: pn.volume).ffill())  # 마지막 자기 거래일 거래량(D−1 이하)
    return live.v / prev.where(prev > 0) * 100


def _live_value_ratio(live: Any, p: dict[str, Any]) -> Frame:
    n = int(p["n"])
    avg = live.prev(live.own(lambda pn: pn.value.rolling(n).mean()).ffill())  # D−n..D−1 평균 — 오늘 제외
    return live.val / avg.where(avg > 0)


LIVE = {"vol_change_pct": _live_vol_change_pct, "value_ratio": _live_value_ratio}
register_indicators(DEFS, COMPUTE, LIVE)
