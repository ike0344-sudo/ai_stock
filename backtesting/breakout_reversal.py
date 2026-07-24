"""거래대금 급등 + 모멘텀 진입, 익절/손절/본전손절(ML 반전감지) 3단 청산 전략.

진입: 롤링 window_minutes분간 누적 거래대금(종가×거래량 근사) >= min_trade_value
      AND 같은 구간 수익률 >= min_return_pct
청산: 1) 순수익(수수료 반영) >= take_profit_pct → 익절
      2) 순손실 <= -stop_loss_pct → 손절
      3) peak 수익률이 breakeven_arm_pct 이상 찍은 뒤("무장") 반전이 감지되면
         본전(수수료만 손실) 수준에서 조기 청산 — 반전감지는 ml_reversal.py의 분류기가 담당

데이트레이딩 전제: 포지션은 진입일 안에서만 유지되고, 당일 마감(같은 날짜의 마지막
캔들)에 도달하면 강제 청산된다.

거래소 기준: 이 모듈 자체는 candles(분봉 DataFrame)를 받아 계산만 할 뿐 KRX/통합
구분에 관여하지 않는다 — 그 구분은 호출부가 결정한다(final_strategy.py/전략1,
strategy3_scalp.py/전략3 모두 통합 기준 분봉을 넘긴다, live_monitor.fetch_today_candles
참고).
"""
from dataclasses import dataclass, field

import pandas as pd

DEFAULT_COMMISSION_RATE = 0.00015
DEFAULT_SLIPPAGE_RATE = 0.001


def detect_entries(
    candles: pd.DataFrame,
    window_minutes: int = 3,
    min_trade_value: float = 4_000_000_000,
    min_return_pct: float = 0.015,
) -> pd.Series:
    """day별로 나눠 롤링 거래대금·수익률 조건을 계산 (거래일 경계를 넘어 섞이지 않음).

    거래대금은 분봉에 별도 필드가 없어 close*volume으로 근사한다.
    """
    parts = []
    for _, day_df in candles.groupby(candles.index.normalize()):
        trade_value = (day_df["close"] * day_df["volume"]).rolling(window_minutes).sum()
        ret = day_df["close"].pct_change(window_minutes - 1)
        parts.append((trade_value >= min_trade_value) & (ret >= min_return_pct))
    if not parts:
        return pd.Series(dtype=bool)
    return pd.concat(parts).reindex(candles.index).fillna(False)


@dataclass
class TradePath:
    entry_idx: int
    entry_time: pd.Timestamp
    entry_price: float
    exit_idx: int
    exit_time: pd.Timestamp
    exit_price: float
    exit_reason: str  # "take_profit" | "stop_loss" | "eod"
    net_pnl_pct: float
    peak_pnl_pct: float
    # (idx, net_pct, peak_pct_so_far, armed) 튜플 목록 — ML 라벨링/피처 추출용
    path: list[tuple] = field(default_factory=list)


def simulate_trade_path(
    candles: pd.DataFrame,
    entry_idx: int,
    take_profit_pct: float = 0.03,
    stop_loss_pct: float = 0.02,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
) -> TradePath:
    """entry_idx에 매수했다고 가정하고, 같은 거래일 안에서 익절/손절/EOD 중 먼저
    도달하는 지점까지 전진 시뮬레이션. 경로상 매 분의 순수익률을 기록해 ML
    반전분류기의 학습 데이터로 재사용할 수 있게 한다 (본전손절 로직 자체는 여기 없음
    — 이 함수는 "ML 없이 그대로 뒀다면 어떻게 됐을지"의 기준선/라벨 소스).
    """
    entry_price = candles["close"].iloc[entry_idx] * (1 + slippage_rate)
    entry_time = candles.index[entry_idx]
    entry_day = entry_time.normalize()

    two_way_commission = commission_rate * 2
    n = len(candles)
    path: list[tuple] = []
    peak_pct = 0.0
    exit_idx = entry_idx
    exit_reason = "eod"

    for j in range(entry_idx, n):
        ts = candles.index[j]
        if ts.normalize() != entry_day:
            exit_idx = j - 1
            exit_reason = "eod"
            break

        exit_price_if_now = candles["close"].iloc[j] * (1 - slippage_rate)
        net_pct = (exit_price_if_now - entry_price) / entry_price - two_way_commission
        peak_pct = max(peak_pct, net_pct)
        path.append((j, net_pct, peak_pct))

        if net_pct >= take_profit_pct:
            exit_idx, exit_reason = j, "take_profit"
            break
        if net_pct <= -stop_loss_pct:
            exit_idx, exit_reason = j, "stop_loss"
            break
    else:
        exit_idx, exit_reason = n - 1, "eod"

    exit_price = candles["close"].iloc[exit_idx] * (1 - slippage_rate)
    net_pnl_pct = (exit_price - entry_price) / entry_price - two_way_commission

    return TradePath(
        entry_idx=entry_idx, entry_time=entry_time, entry_price=entry_price,
        exit_idx=exit_idx, exit_time=candles.index[exit_idx], exit_price=exit_price,
        exit_reason=exit_reason, net_pnl_pct=net_pnl_pct, peak_pnl_pct=peak_pct, path=path,
    )


def simulate_all_entries(
    candles: pd.DataFrame,
    entries: pd.Series,
    take_profit_pct: float = 0.03,
    stop_loss_pct: float = 0.02,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
) -> list[TradePath]:
    """entries가 True인 모든 시점에 대해 simulate_trade_path를 실행 (고정 규칙 기준선)."""
    entry_positions = [i for i, v in enumerate(entries.to_numpy()) if v]
    return [
        simulate_trade_path(candles, i, take_profit_pct, stop_loss_pct, commission_rate, slippage_rate)
        for i in entry_positions
    ]


@dataclass
class PartialExitTrade:
    entry_idx: int
    entry_time: pd.Timestamp
    entry_price: float
    triggered: bool  # take_profit_pct에 도달해 분할매도가 실제로 발동했는지
    first_leg_exit_idx: int
    first_leg_exit_reason: str  # "take_profit_partial" | "stop_loss" | "eod"
    remainder_exit_idx: int
    remainder_exit_reason: str  # "trailing_stop" | "eod" | "n/a"(triggered=False)
    overall_net_pnl_pct: float
    split_ratio: float
    trailing_stop_pct: float


def simulate_partial_exit_trade(
    candles: pd.DataFrame,
    entry_idx: int,
    take_profit_pct: float = 0.03,
    stop_loss_pct: float = 0.02,
    split_ratio: float = 0.5,
    trailing_stop_pct: float = 0.01,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
) -> PartialExitTrade:
    """take_profit_pct 도달 시 전량 청산 대신 split_ratio만큼만 매도하고, 나머지는
    고점 대비 trailing_stop_pct(가격 기준) 하락 시 청산하는 트레일링 스탑으로 전환.

    take_profit_pct 도달 전에 손절(-stop_loss_pct)이나 EOD가 먼저 오면 분할 자체가
    발동하지 않고(triggered=False) 전량이 그 지점에서 청산된다.
    """
    entry_price = candles["close"].iloc[entry_idx] * (1 + slippage_rate)
    entry_time = candles.index[entry_idx]
    entry_day = entry_time.normalize()
    two_way_commission = commission_rate * 2
    n = len(candles)

    trigger_idx = None
    phase1_exit_idx, phase1_exit_reason = entry_idx, "eod"

    for j in range(entry_idx, n):
        ts = candles.index[j]
        if ts.normalize() != entry_day:
            phase1_exit_idx, phase1_exit_reason = j - 1, "eod"
            break
        price_now = candles["close"].iloc[j] * (1 - slippage_rate)
        net_pct = (price_now - entry_price) / entry_price - two_way_commission
        if net_pct >= take_profit_pct:
            trigger_idx = j
            phase1_exit_idx, phase1_exit_reason = j, "take_profit_partial"
            break
        if net_pct <= -stop_loss_pct:
            phase1_exit_idx, phase1_exit_reason = j, "stop_loss"
            break
    else:
        phase1_exit_idx, phase1_exit_reason = n - 1, "eod"

    if trigger_idx is None:
        exit_price = candles["close"].iloc[phase1_exit_idx] * (1 - slippage_rate)
        overall_pct = (exit_price - entry_price) / entry_price - two_way_commission
        return PartialExitTrade(
            entry_idx=entry_idx, entry_time=entry_time, entry_price=entry_price,
            triggered=False,
            first_leg_exit_idx=phase1_exit_idx, first_leg_exit_reason=phase1_exit_reason,
            remainder_exit_idx=phase1_exit_idx, remainder_exit_reason="n/a",
            overall_net_pnl_pct=overall_pct, split_ratio=split_ratio, trailing_stop_pct=trailing_stop_pct,
        )

    trigger_price = candles["close"].iloc[trigger_idx] * (1 - slippage_rate)
    leg1_pct = (trigger_price - entry_price) / entry_price - two_way_commission

    peak_price = candles["close"].iloc[trigger_idx]
    remainder_exit_idx, remainder_exit_reason = trigger_idx, "eod"

    for j in range(trigger_idx, n):
        ts = candles.index[j]
        if ts.normalize() != entry_day:
            remainder_exit_idx, remainder_exit_reason = j - 1, "eod"
            break
        price_now = candles["close"].iloc[j]
        peak_price = max(peak_price, price_now)
        drawdown_from_peak = (peak_price - price_now) / peak_price
        if drawdown_from_peak >= trailing_stop_pct:
            remainder_exit_idx, remainder_exit_reason = j, "trailing_stop"
            break
    else:
        remainder_exit_idx, remainder_exit_reason = n - 1, "eod"

    remainder_exit_price = candles["close"].iloc[remainder_exit_idx] * (1 - slippage_rate)
    leg2_pct = (remainder_exit_price - entry_price) / entry_price - two_way_commission

    overall_pct = split_ratio * leg1_pct + (1 - split_ratio) * leg2_pct

    return PartialExitTrade(
        entry_idx=entry_idx, entry_time=entry_time, entry_price=entry_price,
        triggered=True,
        first_leg_exit_idx=trigger_idx, first_leg_exit_reason="take_profit_partial",
        remainder_exit_idx=remainder_exit_idx, remainder_exit_reason=remainder_exit_reason,
        overall_net_pnl_pct=overall_pct, split_ratio=split_ratio, trailing_stop_pct=trailing_stop_pct,
    )


@dataclass
class TieredExitTrade:
    entry_idx: int
    entry_time: pd.Timestamp
    entry_price: float
    exit_idx: int
    exit_time: pd.Timestamp
    net_pnl_pct: float
    # (idx, reason, fraction, net_pct) 목록 — reason: "take_profit_tier" | "stop_loss" | "breakeven" | "eod"
    legs: list[tuple] = field(default_factory=list)


def simulate_tiered_exit_trade(
    candles: pd.DataFrame,
    entry_idx: int,
    tiers: tuple[float, ...] = (0.02, 0.03, 0.04, 0.05),
    stop_loss_pct: float = 0.02,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
) -> TieredExitTrade:
    """익절 구간(tiers)마다 균등 비율(1/len(tiers))씩 분할매도하고, 한 번이라도 분할매도가
    발동("무장")한 뒤에는 나머지 잔량을 손절 대신 진입가(본전) 재도달 시 청산한다.

    무장 전(아직 한 tier도 안 닿음)에는 -stop_loss_pct에서 잔량 전체를 손절한다.
    tiers를 모두 소진하거나 본전청산/손절/EOD 중 하나에 닿으면 종료.
    """
    entry_price = candles["close"].iloc[entry_idx] * (1 + slippage_rate)
    entry_time = candles.index[entry_idx]
    entry_day = entry_time.normalize()
    two_way_commission = commission_rate * 2
    n = len(candles)

    tier_fraction = 1.0 / len(tiers)
    tiers_remaining = list(tiers)
    remaining_fraction = 1.0
    armed = False
    legs: list[tuple] = []

    last_idx_in_day = entry_idx
    last_net_pct_in_day = -two_way_commission

    for j in range(entry_idx, n):
        ts = candles.index[j]
        if ts.normalize() != entry_day:
            break

        price_now = candles["close"].iloc[j] * (1 - slippage_rate)
        net_pct = (price_now - entry_price) / entry_price - two_way_commission
        last_idx_in_day, last_net_pct_in_day = j, net_pct

        if not armed and net_pct <= -stop_loss_pct:
            legs.append((j, "stop_loss", remaining_fraction, net_pct))
            remaining_fraction = 0.0
            break

        while tiers_remaining and remaining_fraction > 1e-9 and net_pct >= tiers_remaining[0]:
            tiers_remaining.pop(0)
            legs.append((j, "take_profit_tier", tier_fraction, net_pct))
            remaining_fraction -= tier_fraction
            armed = True

        if armed and remaining_fraction > 1e-9 and net_pct <= 0:
            legs.append((j, "breakeven", remaining_fraction, net_pct))
            remaining_fraction = 0.0
            break

        if remaining_fraction <= 1e-9:
            break

    if remaining_fraction > 1e-9:
        legs.append((last_idx_in_day, "eod", remaining_fraction, last_net_pct_in_day))

    net_pnl_pct = sum(fraction * net_pct for _, _, fraction, net_pct in legs)
    exit_idx, _, _, _ = legs[-1]

    return TieredExitTrade(
        entry_idx=entry_idx, entry_time=entry_time, entry_price=entry_price,
        exit_idx=exit_idx, exit_time=candles.index[exit_idx],
        net_pnl_pct=net_pnl_pct, legs=legs,
    )


def simulate_all_tiered_exits(
    candles: pd.DataFrame,
    entries: pd.Series,
    tiers: tuple[float, ...] = (0.02, 0.03, 0.04, 0.05),
    stop_loss_pct: float = 0.02,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
) -> list[TieredExitTrade]:
    entry_positions = [i for i, v in enumerate(entries.to_numpy()) if v]
    return [
        simulate_tiered_exit_trade(candles, i, tiers, stop_loss_pct, commission_rate, slippage_rate)
        for i in entry_positions
    ]


def simulate_all_partial_exits(
    candles: pd.DataFrame,
    entries: pd.Series,
    take_profit_pct: float = 0.03,
    stop_loss_pct: float = 0.02,
    split_ratio: float = 0.5,
    trailing_stop_pct: float = 0.01,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
) -> list[PartialExitTrade]:
    entry_positions = [i for i, v in enumerate(entries.to_numpy()) if v]
    return [
        simulate_partial_exit_trade(
            candles, i, take_profit_pct, stop_loss_pct, split_ratio, trailing_stop_pct,
            commission_rate, slippage_rate,
        )
        for i in entry_positions
    ]
