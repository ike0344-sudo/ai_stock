"""분봉 세션 규칙 — 설계서 §3.5 7번(`eod_time` 봉 종가 청산) + 분봉 2단계의 하루 단위 제약.

분봉 엔진은 일봉 엔진(`portfolio.run_portfolio`)을 그대로 쓰고, 이 모듈이 만드는 `SessionRules` 만 얹는다:
  · **EOD 봉**: 그 날 봉 끝 시각이 `eod_time` 이하인 마지막 봉 — 남은 포지션을 그 봉 **종가**에 청산(잠김이면 다음 봉으로 이월).
  · **EOD 이후 봉**(봉 끝 시각 > eod_time): 거래 불가 — 새 진입도 체결도 없다. 15:30 종가 단일가 봉(끝 라벨 15:35)이 여기 든다.
  · **날 경계**: 신호는 다음 봉 시가에 체결되는데, 그 봉이 **다음 날 첫 봉**이면 체결하지 않는다(신호 봉과 같은 날만).
봉 시각은 **봉 끝 라벨**이다(data-agent 로더 계약: 봉 시작 + bar_minutes).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, eq=False)
class SessionRules:
    after_eod: np.ndarray  # bool[n] — 이 봉은 거래 불가
    eod_bar: np.ndarray  # bool[n] — 이 봉 종가에 남은 포지션 청산
    day_id: np.ndarray  # int[n] — 같은 날이면 같은 값


def _eod_minutes(eod_time: str) -> int:
    p = [int(x) for x in eod_time.split(":")]
    return p[0] * 60 + p[1] + (1 if len(p) > 2 and p[2] > 0 else 0)  # 15:19:59 → 15:20 로 올림(초 단위 봉 없음)


def bar_sessions(index: pd.DatetimeIndex, eod_time: str = "15:20") -> SessionRules:
    """봉 끝 라벨 index(여러 날, 시간순) → 세션 규칙."""
    days = index.normalize()
    day_id = pd.factorize(days)[0].astype(np.int64)
    end_min = (index.hour * 60 + index.minute).to_numpy()
    eod_min = _eod_minutes(eod_time)
    after = end_min > eod_min
    ok = ~after
    n = len(index)
    eod = np.zeros(n, dtype=bool)
    # 날마다 "끝 시각 <= eod" 인 마지막 봉
    last_ok = pd.Series(np.where(ok, np.arange(n), -1)).groupby(day_id).max().to_numpy()
    for i in last_ok[last_ok >= 0]:
        eod[i] = True
    return SessionRules(after_eod=after, eod_bar=eod, day_id=day_id)
