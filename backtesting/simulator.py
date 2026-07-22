"""신호를 가상 체결로 변환하는 시뮬레이터.

Design: docs/02-design/features/strategy-backtesting.design.md §4.1, §6
"""
import pandas as pd

from .types import Signal, Trade


def run(
    candles: pd.DataFrame,
    signals: pd.Series,
    commission_rate: float,
    slippage_rate: float,
    initial_capital: float,
    stock_code: str = "",
    force_eod_close: bool = False,
) -> list[Trade]:
    """candles(OHLCV, date index) + signals(Signal 시계열)를 받아 Trade 목록을 반환.

    한 번에 하나의 포지션만 전액 매수한다고 가정한다. force_eod_close=True면
    (데이트레이딩) 각 캘린더 날짜의 마지막 캔들에서 보유 포지션을 강제 청산한다.
    마지막까지 청산되지 않은 포지션도 목록에 포함하되(exit_price=None), pnl이 없어
    metrics.compute의 집계 대상에서는 제외된다.
    """
    trades: list[Trade] = []
    open_trade: Trade | None = None
    dates = candles.index.normalize()

    for i, (ts, row) in enumerate(candles.iterrows()):
        signal = signals.loc[ts]
        is_last_of_day = force_eod_close and (i == len(candles) - 1 or dates[i + 1] != dates[i])

        if open_trade is None:
            if signal == Signal.BUY:
                entry_price = row["close"] * (1 + slippage_rate)
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
            continue

        if signal == Signal.SELL or is_last_of_day:
            exit_price = row["close"] * (1 - slippage_rate)
            exit_commission = exit_price * open_trade.quantity * commission_rate
            gross_pnl = (exit_price - open_trade.entry_price) * open_trade.quantity
            total_cost = open_trade.commission + exit_commission

            open_trade.exit_date = ts.date()
            open_trade.exit_price = exit_price
            open_trade.commission += exit_commission
            open_trade.pnl = gross_pnl - total_cost
            open_trade.pnl_pct = open_trade.pnl / (open_trade.entry_price * open_trade.quantity)

            trades.append(open_trade)
            open_trade = None

    if open_trade is not None:
        trades.append(open_trade)

    return trades
