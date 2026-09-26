"""비용 모델 — 수수료·세금·슬리피지 (설계서 §3.5).

기본값은 `breakout_reversal.DEFAULT_*` 와 같다(수수료 0.015%·세금 0.23%·슬리피지 0.1%).
슬리피지 모드:
  rate          — 편도 slippage_rate 고정
  ticks         — 편도 slippage_ticks × 호가단위 ÷ 가격
  max_rate_tick — 위 둘 중 큰 쪽 (기본, `t0_forward_return.round_trip_cost_pct` 와 같은 규칙)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from .market_rules import tick_size_array

SlippageMode = Literal["rate", "ticks", "max_rate_tick"]


@dataclass(frozen=True)
class CostModel:
    commission_rate: float = 0.00015
    tax_rate: float = 0.0023  # 매도에만
    slippage_mode: SlippageMode = "max_rate_tick"
    slippage_rate: float = 0.001
    slippage_ticks: float = 1.0

    def __post_init__(self) -> None:
        if self.slippage_mode not in ("rate", "ticks", "max_rate_tick"):
            raise ValueError(f"slippage_mode: {self.slippage_mode!r}")

    def slippage_frac(self, price):
        """편도 슬리피지(가격 대비 비율). price 는 스칼라/배열 — 같은 형태로 돌려준다."""
        p = np.asarray(price, dtype=float)
        if self.slippage_mode == "rate":
            out = np.full_like(p, self.slippage_rate)
        else:
            tick_frac = self.slippage_ticks * tick_size_array(p) / p
            out = tick_frac if self.slippage_mode == "ticks" else np.maximum(self.slippage_rate, tick_frac)
        return float(out) if out.ndim == 0 else out

    def buy_price(self, reference: float) -> float:
        return reference * (1 + self.slippage_frac(reference))

    def sell_price(self, reference: float) -> float:
        return reference * (1 - self.slippage_frac(reference))

    def round_trip_pct(self, price):
        """왕복비용(소수, 예: 0.0052). 수수료×2 + 세금 + 슬리피지×2. 이름은 pct 지만
        `round_trip_cost_pct` 와 같이 비율(소수)로 돌려준다."""
        return self.commission_rate * 2 + self.tax_rate + self.slippage_frac(price) * 2

    def scaled(self, k: float) -> "CostModel":
        """비용 민감도(§3.8)용 — 수수료·세금·슬리피지 전부 k 배."""
        return CostModel(self.commission_rate * k, self.tax_rate * k, self.slippage_mode,
                         self.slippage_rate * k, self.slippage_ticks * k)
