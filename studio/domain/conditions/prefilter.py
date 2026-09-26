"""분봉 모드의 일봉 조건 — **D−1(직전 거래일) 값만** 쓴다. 설계서 §3.7 시점 규칙, C3 카나리아.

당일 일봉(고가·종가·거래량)은 장중에 모르는 값이다. 그래서 일봉 조건(사전 필터·"전일 거래대금 상위 N")은
일봉 표에서 평가한 뒤, **분봉 날짜 D 보다 엄격히 앞선 마지막 일봉 행**의 값을 그 날의 모든 봉에 붙인다.
D 가 일봉 표에 아직 없어도(오늘치 미갱신) 동작하고, D 가 있어도 D 행은 절대 안 본다.
(D−1 붙이기 자체 `previous_day_flags/values` 는 `intraday.py` — 평가기의 시장 지수 피연산자도 같은 규칙을 쓴다.)
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from .ast import Group
from .evaluator import evaluate_group
from .indicators import compute
from .intraday import previous_day_flags, previous_day_values  # noqa: F401  (호환: 예전 import 경로)

Frame = pd.DataFrame


def daily_prefilter(
    group: Group, daily_panel: Any, bar_index: pd.DatetimeIndex, codes: Sequence[str], *,
    values: Mapping[str, float] | None = None, market: Mapping[str, pd.DataFrame] | None = None,
) -> Frame:
    """일봉 조건 그룹(`spec.intraday.prefilter`) → 분봉 bool 표. 전부 D−1 기준."""
    flags = evaluate_group(group, daily_panel, values=values, market=market)
    return previous_day_flags(flags, bar_index, codes)


def top_value_prefilter(daily_panel: Any, n: int, bar_index: pd.DatetimeIndex, codes: Sequence[str]) -> Frame:
    """"전일 거래대금 상위 n" (`spec.intraday.prefilter_top_value`) — D−1 거래대금 순위 ≤ n 인 종목만 True."""
    rank = compute(daily_panel, "value_rank", {"lookback": 1})
    return previous_day_flags(rank <= n, bar_index, codes)
