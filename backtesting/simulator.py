"""신호를 가상 체결로 변환하는 시뮬레이터.

Design: docs/02-design/features/strategy-backtesting.design.md §4.1, §6
"""
import pandas as pd

from .types import Signal, Trade, is_price_limit_locked, prev_day_close_series

DEFAULT_TAX_RATE = 0.0023  # 매도 증권거래세 0.23% (매도 시에만 부과, 매수엔 붙지 않음)


def run(
    candles: pd.DataFrame,
    signals: pd.Series,
    commission_rate: float,
    slippage_rate: float,
    initial_capital: float,
    stock_code: str = "",
    force_eod_close: bool = False,
    tax_rate: float = DEFAULT_TAX_RATE,
) -> list[Trade]:
    """candles(OHLCV, date index) + signals(Signal 시계열)를 받아 Trade 목록을 반환.

    한 번에 하나의 포지션만 전액 매수한다고 가정한다. force_eod_close=True면
    (데이트레이딩) 각 캘린더 날짜의 마지막 캔들에서 보유 포지션을 강제 청산한다.
    마지막까지 청산되지 않은 포지션도 목록에 포함하되(exit_price=None), pnl이 없어
    metrics.compute의 집계 대상에서는 제외된다.

    체결시점: 신호가 발생한 봉에서 곧바로 체결하지 않고 다음 봉의 시가로 체결한다
    (당일 강제청산만 예외 — 동시호가 마감 체결에 준해 해당 봉 종가로 처리). 체결
    예정 봉이 상하한가에 가격이 고정돼 있으면(전일 종가 대비 ±30% 근접) 그 봉에서는
    체결하지 않고 신호를 다음 봉으로 이월한다.
    """
    trades: list[Trade] = []
    open_trade: Trade | None = None
    pending_signal: Signal | None = None
    dates = candles.index.normalize()
    prev_close_by_day = prev_day_close_series(candles)
    n = len(candles)

    for i, (ts, row) in enumerate(candles.iterrows()):
        day = dates[i]
        prev_close = prev_close_by_day.get(day, float("nan"))
        is_last_of_day = force_eod_close and (i == n - 1 or dates[i + 1] != day)

        if pending_signal is not None and not is_price_limit_locked(row["open"], prev_close):
            if pending_signal == Signal.BUY and open_trade is None:
                entry_price = row["open"] * (1 + slippage_rate)
                quantity = int(initial_capital // entry_price)
                if quantity > 0:
                    commission = entry_price * quantity * commission_rate
                    open_trade = Trade(
                        stock_code=stock_code,
                        entry_date=ts.date(),
                        entry_price=entry_price,
                        quantity=quantity,
                        commission=commission,
                        slippage=entry_price * quantity * slippage_rate,
                    )
            elif pending_signal == Signal.SELL and open_trade is not None:
                exit_price = row["open"] * (1 - slippage_rate)
                _settle_exit(open_trade, ts, exit_price, commission_rate, tax_rate)
                trades.append(open_trade)
                open_trade = None
            pending_signal = None

        if is_last_of_day and open_trade is not None:
            if not is_price_limit_locked(row["close"], prev_close):
                exit_price = row["close"] * (1 - slippage_rate)
                _settle_exit(open_trade, ts, exit_price, commission_rate, tax_rate)
                trades.append(open_trade)
                open_trade = None
                pending_signal = None
            continue

        signal = signals.loc[ts]
        if signal in (Signal.BUY, Signal.SELL):
            pending_signal = signal

    if open_trade is not None:
        trades.append(open_trade)

    return trades


def _settle_exit(
    trade: Trade, ts: pd.Timestamp, exit_price: float, commission_rate: float, tax_rate: float
) -> None:
    """청산 체결가를 확정하고 매도수수료+증권거래세를 반영해 Trade를 완결시킨다."""
    exit_commission = exit_price * trade.quantity * commission_rate
    sell_tax = exit_price * trade.quantity * tax_rate
    gross_pnl = (exit_price - trade.entry_price) * trade.quantity
    total_cost = trade.commission + exit_commission + sell_tax

    trade.exit_date = ts.date()
    trade.exit_price = exit_price
    trade.commission += exit_commission
    trade.pnl = gross_pnl - total_cost
    trade.pnl_pct = trade.pnl / (trade.entry_price * trade.quantity)
