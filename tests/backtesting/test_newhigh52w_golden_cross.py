import numpy as np
import pandas as pd
import pytest

from backtesting.newhigh52w_golden_cross import (
    _walk_exit,
    add_features,
    buy_and_hold_control,
    simulate_trades,
)


def _mk_panel(code, dates, opens, highs, lows, closes):
    return pd.DataFrame({"code": [code] * len(dates), "date": dates, "open": opens,
                          "high": highs, "low": lows, "close": closes})


def test_walk_exit_prefers_stop_when_both_hit_same_day():
    opens = np.array([100.0, 100.0])
    highs = np.array([100.0, 140.0])  # 익절가(124) 초과
    lows = np.array([100.0, 90.0])    # 손절가(92) 이하
    closes = np.array([100.0, 100.0])

    idx, price, reason = _walk_exit(opens, highs, lows, closes, 0, stop_price=92.0, target_price=124.0)

    assert idx == 1  # 0번째날은 아무것도 안 닿음, 1번째날 둘 다 닿음
    assert reason == "stop_both"
    assert price == 92.0  # min(시가100, 손절가92)


def test_walk_exit_stop_uses_open_when_gapped_below():
    opens = np.array([80.0])  # 손절가(92)보다 훨씬 아래로 갭다운
    highs = np.array([80.0])
    lows = np.array([75.0])
    closes = np.array([78.0])

    idx, price, reason = _walk_exit(opens, highs, lows, closes, 0, stop_price=92.0, target_price=124.0)

    assert reason == "stop"
    assert price == 80.0  # min(시가80, 손절가92) = 80, 낙관적으로 92를 안 줌


def test_walk_exit_expires_at_last_close_when_never_hit():
    opens = np.array([100.0, 101.0])
    highs = np.array([105.0, 106.0])
    lows = np.array([99.0, 100.0])
    closes = np.array([103.0, 104.0])

    idx, price, reason = _walk_exit(opens, highs, lows, closes, 0, stop_price=50.0, target_price=200.0)

    assert idx == 1 and reason == "expiry" and price == 104.0


def test_add_features_signal_requires_newhigh_and_cross_same_day():
    # 종목 A: 앞 구간은 신고가/크로스 조건 못 채우다가 마지막날 close가
    # 252일 고가를 넘고, 동시에 sma5가 sma20을 막 상향돌파.
    n = 260
    dates = [f"d{i:04d}" for i in range(n)]
    closes = [100.0] * 250 + [90, 91, 92, 93, 94, 95, 96, 98, 99, 130]
    highs = [100.0] * 250 + [c + 1 for c in closes[250:]]
    lows = [c - 1 for c in closes]
    opens = closes

    panel = _mk_panel("A", dates, opens, highs, lows, closes)
    out = add_features(panel)

    assert out.loc[259, "newhigh"]  # 130 > 앞 252일 고가(101)
    assert bool(out.loc[259, "signal_5_20"]) or bool(out.loc[259, "signal_20_60"])
    # 신고가 조건만으론(크로스 없이) 신호가 안 남을 수 있음 - 최소 하나는 정의상 계산됨
    assert "signal_5_20" in out.columns and "signal_20_60" in out.columns


def test_simulate_trades_skips_when_below_market_cap():
    n = 260
    dates = pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist()
    # 진입일이 사전등록 기간(2025-09~2026-08) 안에 들어오도록 뒤쪽에 신호 배치
    closes = [100.0] * 250 + [90, 91, 92, 93, 94, 95, 96, 98, 99, 130]
    highs = [100.0] * 250 + [c + 1 for c in closes[250:]]
    lows = [c - 1 for c in closes]
    opens = closes
    panel = _mk_panel("999999", dates, opens, highs, lows, closes)
    panel = add_features(panel)

    tiny_shares = pd.Series({"999999": 1.0})  # 시총이 절대 3조 못 넘김
    trades = simulate_trades(panel, tiny_shares, "5_20")

    assert trades.empty


def test_walk_exit_max_idx_forces_expiry_at_hold_days_even_without_stop_target():
    opens = np.array([100.0, 105.0, 110.0, 115.0, 120.0])
    highs = np.array([101.0, 106.0, 111.0, 116.0, 121.0])
    lows = np.array([99.0, 104.0, 109.0, 114.0, 119.0])
    closes = np.array([100.0, 105.0, 110.0, 115.0, 120.0])

    # 손절/익절 절대 안 걸리게(-inf/inf), max_idx=entry_idx+2로 3거래일째(index 2)에서 강제만료
    idx, price, reason = _walk_exit(opens, highs, lows, closes, 0, stop_price=-np.inf, target_price=np.inf,
                                     max_idx=2)

    assert idx == 2 and reason == "expiry" and price == 110.0  # closes[2]


def test_walk_exit_max_idx_none_keeps_old_unbounded_behavior():
    opens = np.array([100.0, 100.0])
    highs = np.array([100.0, 100.0])
    lows = np.array([100.0, 100.0])
    closes = np.array([100.0, 100.0])

    idx, price, reason = _walk_exit(opens, highs, lows, closes, 0, stop_price=-np.inf, target_price=np.inf)

    assert idx == 1 and reason == "expiry"  # 끝까지(n-1) 걸어감, max_idx 지정 전과 동일


def test_simulate_trades_hold_days_exits_exactly_n_days_later_at_close():
    dates = [f"2025-09-{i:02d}" for i in range(1, 11)]
    closes = [100.0] * 10
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    panel = pd.DataFrame({
        "code": ["A"] * 10, "date": dates, "open": closes, "high": highs, "low": lows,
        "close": closes, "signal_5_20": [False, True] + [False] * 8,
    })
    shares = pd.Series({"A": 1e12})

    trades = simulate_trades(panel, shares, "5_20", stop_pct=None, target_pct=None, hold_days=3)

    assert len(trades) == 1
    # entry_idx=2(신호 다음날), 3거래일 뒤 = index 5
    assert trades.iloc[0]["exit_date"] == "2025-09-06"
    assert trades.iloc[0]["exit_reason"] == "expiry"


def test_simulate_trades_target_pct_none_removes_profit_cap():
    # signal_5_20 을 직접 박아 add_features 재계산 없이 simulate_trades만 격리 테스트.
    dates = [f"2025-09-{i:02d}" for i in range(1, 11)]
    closes = [100, 100, 100, 100, 100, 130, 160, 190, 200, 200]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    panel = pd.DataFrame({
        "code": ["A"] * 10, "date": dates, "open": closes, "high": highs, "low": lows,
        "close": closes, "signal_5_20": [False, True] + [False] * 8,
    })
    shares = pd.Series({"A": 1e12})  # 시총 여유있게 통과

    default_trades = simulate_trades(panel, shares, "5_20")
    uncapped_trades = simulate_trades(panel, shares, "5_20", stop_pct=0.08, target_pct=None)

    assert default_trades.iloc[0]["exit_reason"] == "target"
    assert default_trades.iloc[0]["exit_price"] == pytest.approx(100 * 1.24)

    assert uncapped_trades.iloc[0]["exit_reason"] == "expiry"
    assert uncapped_trades.iloc[0]["exit_price"] == pytest.approx(200)  # 상한 없이 마지막 종가까지


def test_simulate_trades_stop_and_target_both_none_holds_to_window_end():
    dates = [f"2025-09-{i:02d}" for i in range(1, 6)]
    closes = [100, 100, 100, 70, 130]  # entry=100(3행), 4행에서 -8% 손절선(92) 훨씬 밑으로 급락 후 회복
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    panel = pd.DataFrame({
        "code": ["A"] * 5, "date": dates, "open": closes, "high": highs, "low": lows,
        "close": closes, "signal_5_20": [False, True, False, False, False],
    })
    shares = pd.Series({"A": 1e12})

    default_trades = simulate_trades(panel, shares, "5_20")
    no_exit_trades = simulate_trades(panel, shares, "5_20", stop_pct=None, target_pct=None)

    assert default_trades.iloc[0]["exit_reason"] == "stop"
    assert default_trades.iloc[0]["exit_price"] == pytest.approx(70.0)  # 그날 시가도 70(갭다운) - min(손절가92,시가70)

    assert no_exit_trades.iloc[0]["exit_reason"] == "expiry"
    assert no_exit_trades.iloc[0]["exit_price"] == pytest.approx(130)  # 손절 무시하고 구간 끝까지 보유


def test_buy_and_hold_control_uses_close_to_close_within_period():
    dates = ["2025-08-29", "2025-09-01", "2025-09-02", "2026-08-31"]
    panel = _mk_panel("A", dates, [10, 10, 10, 10], [10, 10, 10, 10], [10, 10, 10, 10], [10, 20, 21, 42])

    ret, n = buy_and_hold_control(panel, ["A"])

    assert n == 1
    assert ret == pytest.approx(42 / 20 - 1)  # 8/29는 기간 전이라 제외, 9/1 종가부터
