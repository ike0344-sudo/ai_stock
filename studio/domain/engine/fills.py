"""체결 규칙 — 손절·익절·트레일링 판정 (설계서 §3.5 표의 3·4·5번). 순수 함수.

봉 안 경로는 알 수 없다(틱 없음). 한 봉의 저가가 손절선을, 고가가 익절선을 둘 다 넘으면
어느 쪽이 먼저인지 봉만으로는 모르므로 `same_bar_policy` 로 정한다(기본 손절 먼저 = 보수적).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..models import ExitReason, Position

SameBarPolicy = Literal["stop_first", "target_first"]


@dataclass(frozen=True)
class ExitRules:
    """단위는 % 숫자(7 = 7%). None 이면 끔."""

    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    trailing_stop_pct: float | None = None
    max_holding_bars: int | None = None  # 진입 봉을 1 로 센다 — 20 이면 진입 봉 포함 20번째 봉 종가에 청산


@dataclass(frozen=True)
class FillRules:
    same_bar_policy: SameBarPolicy = "stop_first"
    volume_cap_pct: float | None = None  # 수량 ≤ 전 봉(신호 봉) 거래량 × 이 %

    def __post_init__(self) -> None:
        if self.same_bar_policy not in ("stop_first", "target_first"):
            raise ValueError(f"same_bar_policy: {self.same_bar_policy!r}")


def entry_lines(entry_price: float, rules: ExitRules) -> tuple[float | None, float | None, float | None]:
    """진입가 → (손절선, 익절선, 트레일링 초기 고점)."""
    stop = entry_price * (1 - rules.stop_loss_pct / 100) if rules.stop_loss_pct is not None else None
    target = entry_price * (1 + rules.take_profit_pct / 100) if rules.take_profit_pct is not None else None
    peak = entry_price if rules.trailing_stop_pct is not None else None
    return stop, target, peak


def downside_line(pos: Position, rules: ExitRules) -> tuple[float | None, ExitReason | None]:
    """손절선과 트레일링선 중 높은 쪽(먼저 닿는 쪽)과 그 사유."""
    trail = pos.trail_peak * (1 - rules.trailing_stop_pct / 100) if (
        pos.trail_peak is not None and rules.trailing_stop_pct is not None) else None
    if pos.stop is None and trail is None:
        return None, None
    if trail is not None and (pos.stop is None or trail > pos.stop):
        return trail, ExitReason.TRAILING
    return pos.stop, ExitReason.STOP


def judge_gap(open_px: float, pos: Position, rules: ExitRules) -> tuple[float, ExitReason] | None:
    """시가가 이미 손절선 아래 / 익절선 위 → 시가에 청산(선까지 안 기다린다). 보유 중이던 종목만."""
    line, reason = downside_line(pos, rules)
    if line is not None and open_px <= line:
        return open_px, reason
    if pos.target is not None and open_px >= pos.target:
        return open_px, ExitReason.TARGET
    return None


def judge_intrabar(high: float, low: float, pos: Position, rules: ExitRules,
                   policy: SameBarPolicy) -> tuple[float, ExitReason] | None:
    """봉 안 판정 — (기준가=선 가격, 사유). 둘 다 닿으면 policy."""
    line, reason = downside_line(pos, rules)
    down = line is not None and low <= line
    up = pos.target is not None and high >= pos.target
    if down and up:
        if policy == "stop_first":
            return line, reason
        return pos.target, ExitReason.TARGET
    if down:
        return line, reason
    if up:
        return pos.target, ExitReason.TARGET
    return None
