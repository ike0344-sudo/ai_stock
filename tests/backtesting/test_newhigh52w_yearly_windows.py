import numpy as np
import pandas as pd
import pytest

from backtesting.newhigh52w_yearly_windows import (
    cap_breadth,
    kospi_index_return,
    stats_from_trades,
    universe_buy_and_hold,
)
import backtesting.newhigh52w_yearly_windows as ywm


def test_cap_breadth_counts_codes_over_threshold_at_window_start():
    panel = pd.DataFrame({
        "code": ["A", "B", "C"],
        "date": ["2020-05-04", "2020-05-04", "2020-05-04"],  # 5/1이 휴일이라 첫 거래일이 5/4인 케이스
        "close": [100.0, 200.0, 300.0],
    })
    shares = pd.Series({"A": 1e10, "B": 1e10, "C": 1e6})  # A:1조, B:2조, C:3억(threshold 3e12 다 미달)

    n = cap_breadth(panel, shares, "2020-05-01")

    assert n == 0  # 셋 다 3조 미달


def test_cap_breadth_uses_earliest_date_on_or_after_start():
    panel = pd.DataFrame({
        "code": ["A", "A"], "date": ["2020-04-30", "2020-05-04"], "close": [10.0, 4_000_000.0],
    })
    shares = pd.Series({"A": 1e6})  # 5/4 종가 기준 시총 = 4e12(3조 초과), 4/30(구간 이전)은 안 봄

    n = cap_breadth(panel, shares, "2020-05-01")

    assert n == 1


def test_stats_from_trades_counts_stop_both_as_stop():
    trades = pd.DataFrame({
        "net_pct": [0.1, -0.1, 0.2],
        "exit_reason": ["target", "stop_both", "target"],
    })

    stats = stats_from_trades(trades)

    assert stats["n"] == 3
    assert stats["stop"] == 1  # stop_both도 손절로 집계
    assert stats["target"] == 2
    assert stats["win_rate"] == pytest.approx(2 / 3)


def test_stats_from_trades_empty():
    stats = stats_from_trades(pd.DataFrame(columns=["net_pct", "exit_reason"]))

    assert stats["n"] == 0
    assert np.isnan(stats["win_rate"])


def test_universe_buy_and_hold_filters_by_cap_then_delegates_to_buy_and_hold_control(monkeypatch):
    # lead 2차지시 A-2: 신호와 무관한 대조군 - 구간시작일 3조+ 유니버스 동일가중 buy&hold.
    panel = pd.DataFrame({
        "code": ["A", "B", "A", "B"],
        "date": ["2020-05-04", "2020-05-04", "2020-06-30", "2020-06-30"],
        "close": [100.0, 50.0, 120.0, 60.0],
    })
    shares = pd.Series({"A": 3e10, "B": 1e9})  # A: 시총 3조(딱 통과), B: 500억(미달, 제외)

    import backtesting.newhigh52w_golden_cross as mod
    monkeypatch.setattr(mod, "PERIOD_START", "2020-05-01")
    monkeypatch.setattr(mod, "PERIOD_END", "2020-12-31")

    ret, n = universe_buy_and_hold(panel, shares, "2020-05-01")

    assert n == 1  # B는 필터 미달로 빠짐
    assert ret == pytest.approx(120.0 / 100.0 - 1)  # A만: 100->120


def test_universe_buy_and_hold_nan_when_nobody_passes_filter():
    panel = pd.DataFrame({"code": ["A"], "date": ["2020-05-04"], "close": [1.0]})
    shares = pd.Series({"A": 1.0})  # 시총 1원, 절대 3조 못 넘음

    ret, n = universe_buy_and_hold(panel, shares, "2020-05-01")

    assert n == 0
    assert np.isnan(ret)


def test_kospi_index_return_computes_close_to_close(monkeypatch):
    # lead 2차지시 A-3: 신규 대조군③(코스피지수).
    idx_df = pd.DataFrame({"date": ["2021-08-01", "2021-08-02", "2021-08-31"], "close": [300.0, 310.0, 330.0]})
    monkeypatch.setattr(ywm, "_INDEX_DF", idx_df)

    ret = kospi_index_return("2021-08-01", "2021-08-31")

    assert ret == pytest.approx(330.0 / 300.0 - 1)


def test_kospi_index_return_nan_when_window_starts_before_data_coverage(monkeypatch):
    # "없으면 없다고 비워라, 추정하지 마라" - 2021-07-26 이전 구간(예: 2020-05)은 NaN.
    idx_df = pd.DataFrame({"date": ["2021-07-26", "2021-08-31"], "close": [300.0, 330.0]})
    monkeypatch.setattr(ywm, "_INDEX_DF", idx_df)

    ret = kospi_index_return("2020-05-01", "2021-04-30")

    assert np.isnan(ret)


def test_reused_trades_csv_read_with_str_dtype_keeps_leading_zeros(tmp_path):
    # 회귀테스트: dtype 지정 없이 읽으면 "000660" -> 660(int)로 앞자리 0이 날아가
    # buy_and_hold_control 조인이 0건으로 조용히 실패했던 버그(실측·수정함).
    csv_path = tmp_path / "trades.csv"
    pd.DataFrame({"code": ["000660"], "net_pct": [0.01], "exit_reason": ["target"]}).to_csv(
        csv_path, index=False
    )

    read_wrong = pd.read_csv(csv_path)
    read_fixed = pd.read_csv(csv_path, dtype={"code": str})

    assert read_wrong["code"].iloc[0] != "000660"  # dtype 안 주면 이렇게 깨진다(재현)
    assert read_fixed["code"].iloc[0] == "000660"  # 실제 코드에서 쓰는 방식
