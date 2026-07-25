import pandas as pd
import pytest

from backtesting import simulator
from backtesting.types import Signal


def _candles_and_signals(
    closes: list[float], signal_map: dict[int, Signal], opens: list[float] | None = None
) -> tuple[pd.DataFrame, pd.Series]:
    index = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    candles = pd.DataFrame({"open": opens if opens is not None else closes, "close": closes}, index=index)
    signals = pd.Series(Signal.HOLD, index=index)
    for i, signal in signal_map.items():
        signals.iloc[i] = signal
    return candles, signals


def test_buy_then_sell_fills_at_next_bar_open_and_applies_commission_and_slippage():
    # 신호는 idx1(BUY)/idx3(SELL)에서 나오지만, 체결시점 보수화로 실제 체결은 각각
    # idx2/idx4의 시가에서 이뤄진다.
    opens = [100, 100, 105, 108, 112]
    closes = [100, 100, 106, 110, 112]
    candles, signals = _candles_and_signals(closes, {1: Signal.BUY, 3: Signal.SELL}, opens=opens)

    trades = simulator.run(
        candles, signals, commission_rate=0.01, slippage_rate=0.01, initial_capital=10_000, tax_rate=0.0
    )

    assert len(trades) == 1
    trade = trades[0]
    expected_entry_price = 105 * 1.01
    expected_exit_price = 112 * 0.99
    assert trade.entry_price == expected_entry_price
    assert trade.exit_price == expected_exit_price
    assert trade.quantity == int(10_000 // expected_entry_price)
    assert trade.pnl is not None
    expected_gross = (expected_exit_price - expected_entry_price) * trade.quantity
    assert trade.pnl == expected_gross - trade.commission


def test_signal_on_last_bar_never_fills():
    # 신호가 데이터의 마지막 봉에서 나오면 체결할 다음 봉이 없어 거래가 발생하지 않는다.
    candles, signals = _candles_and_signals([100, 105], {1: Signal.BUY})

    trades = simulator.run(candles, signals, commission_rate=0.0, slippage_rate=0.0, initial_capital=10_000)

    assert trades == []


def test_sell_tax_reduces_pnl_by_tax_rate_on_sale_proceeds():
    opens = [100, 100, 105, 108, 112]
    closes = [100, 100, 106, 110, 112]
    candles, signals = _candles_and_signals(closes, {1: Signal.BUY, 3: Signal.SELL}, opens=opens)

    no_tax = simulator.run(
        candles, signals, commission_rate=0.0, slippage_rate=0.0, initial_capital=10_000, tax_rate=0.0
    )[0]
    with_tax = simulator.run(
        candles, signals, commission_rate=0.0, slippage_rate=0.0, initial_capital=10_000, tax_rate=0.0023
    )[0]

    expected_tax = with_tax.exit_price * with_tax.quantity * 0.0023
    assert no_tax.pnl - with_tax.pnl == pytest.approx(expected_tax)


def test_default_tax_rate_is_applied_when_not_specified():
    opens = [100, 100, 105, 108, 112]
    closes = [100, 100, 106, 110, 112]
    candles, signals = _candles_and_signals(closes, {1: Signal.BUY, 3: Signal.SELL}, opens=opens)

    trade = simulator.run(candles, signals, commission_rate=0.0, slippage_rate=0.0, initial_capital=10_000)[0]

    expected_tax = trade.exit_price * trade.quantity * simulator.DEFAULT_TAX_RATE
    expected_pnl = (trade.exit_price - trade.entry_price) * trade.quantity - expected_tax
    assert trade.pnl == expected_pnl


def test_price_limit_locked_bar_defers_fill_to_next_unlocked_bar():
    # day1 종가 100 -> day2 상한가(130, +30%)에서 하루 시작, 한 봉 동안 고정됐다가
    # 되돌림. BUY 신호는 day2 첫 봉에서 나오고, 체결은 상한가에 고정된 두 번째 봉을
    # 건너뛰고 그 다음(고정 풀린) 봉의 시가에서 이뤄져야 한다.
    index = pd.to_datetime(
        ["2026-01-01 09:00", "2026-01-02 09:00", "2026-01-02 09:01", "2026-01-02 09:02"]
    )
    candles = pd.DataFrame(
        {"open": [100, 100, 130, 120], "close": [100, 100, 130, 120]}, index=index
    )
    signals = pd.Series(
        [Signal.HOLD, Signal.BUY, Signal.HOLD, Signal.HOLD], index=index
    )

    trades = simulator.run(
        candles, signals, commission_rate=0.0, slippage_rate=0.0, initial_capital=10_000, tax_rate=0.0
    )

    assert len(trades) == 1
    assert trades[0].entry_price == 120


def test_force_eod_close_liquidates_open_position_at_day_end():
    index = pd.to_datetime(
        ["2026-01-01 09:00", "2026-01-01 09:05", "2026-01-01 15:20", "2026-01-02 09:00"]
    )
    candles = pd.DataFrame({"open": [100, 105, 108, 120], "close": [100, 105, 108, 120]}, index=index)
    signals = pd.Series(
        [Signal.BUY, Signal.HOLD, Signal.HOLD, Signal.HOLD], index=index
    )

    trades = simulator.run(
        candles,
        signals,
        commission_rate=0.0,
        slippage_rate=0.0,
        initial_capital=10_000,
        force_eod_close=True,
        tax_rate=0.0,
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_price == 108
    assert trade.pnl is not None


def test_unclosed_position_included_without_pnl():
    candles, signals = _candles_and_signals([100, 105, 110], {0: Signal.BUY})

    trades = simulator.run(
        candles, signals, commission_rate=0.0, slippage_rate=0.0, initial_capital=10_000
    )

    assert len(trades) == 1
    assert trades[0].pnl is None
    assert trades[0].exit_price is None
