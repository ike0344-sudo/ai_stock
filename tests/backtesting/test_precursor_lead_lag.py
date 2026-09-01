import numpy as np
import pandas as pd
import pytest

from backtesting.precursor_lead_lag import (
    _cluster_onsets,
    compute_stock_day_events,
    match_lags,
)


def test_cluster_onsets_returns_first_second_of_each_burst():
    label = np.zeros(100, dtype=bool)
    label[10:15] = True  # 클러스터1
    label[50] = True  # 클러스터2(단발)

    onsets = _cluster_onsets(label, gap=5)

    assert list(onsets) == [10, 50]


def test_match_lags_finds_nearest_burst_within_window_and_signs_correctly():
    price_onsets = np.array([100, 500])
    burst_onsets = np.array([90, 105, 470])  # 100에 대해 90(먼저,+10)과 105(나중,-5) 중 105가 더 가까움

    pairs = match_lags(price_onsets, burst_onsets, search_window=180)

    assert pairs[0] == (100, -5)  # 105가 더 가까움 -> lag=100-105=-5(가격이 먼저)
    assert pairs[1] == (500, 30)  # 470이 유일한 후보 -> lag=500-470=+30(버스트가 먼저)


def test_match_lags_returns_none_when_nothing_within_window():
    pairs = match_lags(np.array([1000]), np.array([100]), search_window=50)

    assert pairs == [(1000, None)]


def _make_synthetic_tick_file(path, times, prices, qtys):
    df = pd.DataFrame({
        "time": times, "cur_prc": prices, "trde_qty": qtys, "pred_pre_sig": [2] * len(times),
    })
    df.iloc[::-1].reset_index(drop=True).to_parquet(path)  # 역시간순 저장(실제 파일 관례)


def test_compute_stock_day_events_detects_price_and_burst_onsets(tmp_path):
    path = tmp_path / "20260804.parquet"
    # 09:00:00~09:00:58 평범한 소량 체결, 09:00:59에 대량체결(대금폭발) +
    # 그 직후 가격이 +0.6% 뛰어(가격상승) 60초간 유지.
    times = [f"0900{s:02d}" for s in range(59)] + ["090059", "090100"]
    prices = [100.0] * 59 + [100.0, 100.6]
    qtys = [1] * 59 + [500, 10]
    _make_synthetic_tick_file(path, times, prices, qtys)

    ev = compute_stock_day_events(str(path), "TEST", "2026-08-04")

    assert ev is not None
    assert len(ev["burst_onsets"]) >= 1
    assert len(ev["price_onsets"]) >= 1
