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
    entry_id: int = -1  # 이 진입의 번호 — 분할 청산 조각(Trade)이 같은 번호를 단다
    slices: int = 0  # 이미 판 조각 수
    tp_levels: list = field(default_factory=list)  # 남은 분할 익절 [(선 가격, 남은 수량 중 파는 비율)] — 가격 오름차순
    trail_on: bool = True  # 트레일링 발동(trail_activate_pct 가 있으면 최고 수익률이 넘기 전까지 False)


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
    entry_id: int = -1  # 같은 진입에서 나온 조각은 같은 번호(분할 익절) — 승률·기대값은 이 번호로 묶어 센다. -1 = 조각 없음(자기 자신이 한 진입)
    slice: int = 1  # 그 진입의 몇 번째 조각


@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade]
    equity: pd.DataFrame  # ts, cash, positions_value, equity, n_positions
    fills: list[Fill]
    skipped: dict[str, int]  # slots_full · cash · upper_limit · volume_cap · no_data
    diagnostics: dict = field(default_factory=dict)
