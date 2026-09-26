"""스튜디오 도메인 엔티티 — 설계서 §3.1 그대로.

Panel 속성 이름(open/high/low/close/volume/value/prev_close)은 strategy-agent 의
조건식 평가기가 의존한다 — 바꾸면 그쪽이 깨진다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

import pandas as pd


class ExitReason(StrEnum):
    SIGNAL = "signal"
    STOP = "stop"
    TARGET = "target"
    TRAILING = "trailing"
    TIME = "time"
    EOD = "eod"
    END_OF_DATA = "end_of_data"


@dataclass(frozen=True)
class Panel:
    """넓은 표 묶음 — index=시각(일 또는 봉), columns=종목코드."""

    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    value: pd.DataFrame  # close×volume (거래대금 근사 — §3.7)
    prev_close: pd.DataFrame  # 일자 기준 전일 종가(상하한가 판정)


@dataclass
class Position:
    code: str
    qty: int
    entry_ts: pd.Timestamp
    entry_price: float
    stop: float | None
    target: float | None
    trail_peak: float | None
    bars_held: int
    entry_costs: float


@dataclass(frozen=True)
class Fill:
    ts: pd.Timestamp
    code: str
    side: Literal["buy", "sell"]
    qty: int
    price: float
    reference_price: float
    commission: float
    tax: float
    slippage_cost: float
    reason: str


@dataclass(frozen=True)
class Trade:
    code: str
    entry_ts: pd.Timestamp
    entry_price: float
    exit_ts: pd.Timestamp | None
    exit_price: float | None
    qty: int
    gross_pnl: float | None
    commission: float
    tax: float
    slippage_cost: float
    net_pnl: float | None
    net_pct: float | None
    exit_reason: ExitReason | None
    bars_held: int
    mfe_pct: float | None
    mae_pct: float | None


@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade]
    equity: pd.DataFrame  # ts, cash, positions_value, equity, n_positions
    fills: list[Fill]
    skipped: dict[str, int]  # slots_full · cash · upper_limit · volume_cap · no_data
    diagnostics: dict = field(default_factory=dict)
