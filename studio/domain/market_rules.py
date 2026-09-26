"""한국 시장 규칙 — 상하한가·호가단위·정규장 시각 (설계서 §3.5).

기존 `backtesting/types.py`(상하한가)·`t0_forward_return.krx_tick_size`(호가단위) 와
같은 값·같은 판정이다. 도메인은 backtesting 을 import 할 수 없어(§9.3) 복제하되,
같은지는 tests/studio/domain 이 기존 함수와 직접 대조한다.
"""
from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd

PRICE_LIMIT_PCT = 0.30  # 전일 종가 대비 ±30%
PRICE_LIMIT_TOLERANCE_PCT = 0.005  # 호가단위 반올림 오차 흡수 여유

REGULAR_OPEN = time(9, 0)
REGULAR_CLOSE = time(15, 30)
CLOSING_AUCTION_START = time(15, 20)  # 15:20~15:30 종가 단일가


def krx_tick_size(price: float) -> float:
    """KRX 호가단위(원). 가격대별 최소 호가 간격."""
    if price < 2_000:
        return 1.0
    if price < 5_000:
        return 5.0
    if price < 20_000:
        return 10.0
    if price < 50_000:
        return 50.0
    if price < 200_000:
        return 100.0
    if price < 500_000:
        return 500.0
    return 1_000.0


def tick_size_array(price: np.ndarray) -> np.ndarray:
    """krx_tick_size 의 벡터판(같은 경계: `<`)."""
    price = np.asarray(price, dtype=float)
    return np.select(
        [price < 2_000, price < 5_000, price < 20_000, price < 50_000, price < 200_000, price < 500_000],
        [1.0, 5.0, 10.0, 50.0, 100.0, 500.0],
        default=1_000.0,
    )


def is_price_limit_locked(price: float, prev_close: float) -> bool:
    """전일 종가 대비 ±30% 근처면 상하한가 고정 → 체결 불가. prev_close 가 NaN 이면 판정 안 함."""
    if pd.isna(prev_close):
        return False
    upper = prev_close * (1 + PRICE_LIMIT_PCT)
    lower = prev_close * (1 - PRICE_LIMIT_PCT)
    return bool(price >= upper * (1 - PRICE_LIMIT_TOLERANCE_PCT) or price <= lower * (1 + PRICE_LIMIT_TOLERANCE_PCT))


def is_regular_session(ts: pd.Timestamp) -> bool:
    """정규장(09:00~15:30) 안의 봉 시각인가. 일봉(자정)은 호출 대상이 아니다."""
    t = ts.time()
    return REGULAR_OPEN <= t <= REGULAR_CLOSE
