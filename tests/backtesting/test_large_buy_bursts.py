import pandas as pd
import pytest

from _precursor_fastpath import SESSION_START
from backtesting.large_buy_bursts import compute_stock_day, pattern_contrast_table


def _make_synthetic_tick_file(path, times, prices, qtys):
    df = pd.DataFrame({
        "time": times, "cur_prc": prices, "trde_qty": qtys, "pred_pre_sig": [2] * len(times),
    })
    df.iloc[::-1].reset_index(drop=True).to_parquet(path)  # 역시간순 저장(실제 파일 관례)


def test_compute_stock_day_finds_large_buy_burst_and_pattern_features(tmp_path):
    path = tmp_path / "20260804.parquet"
    # 09:00:00~09:00:19: 평범한 소량 체결(수량 1)로 확장평균을 낮게 유지.
    # 09:00:20~09:00:22: 대량 매수(수량 100, 확장평균의 3배 훨씬 넘음)가 연속 발생,
    # 가격이 100->101로 상승. 그 사이 매도 체결도 소량 섞는다.
    times = [f"0900{s:02d}" for s in range(20)] + ["090020", "090021", "090021", "090022"]
    prices = [100.0] * 20 + [100.2, 100.5, 100.5, 101.0]
    qtys = [1] * 20 + [100, 100, 5, 100]  # 세 번째 틱은 소량(매도로 취급되게 가격 하락 없음 - direction은 tick rule)
    _make_synthetic_tick_file(path, times, prices, qtys)

    df = compute_stock_day(str(path), "TEST", "2026-08-04")

    assert df is not None
    assert len(df) >= 1
    row = df.iloc[0]
    assert row["t_sec"] == SESSION_START + 20  # 구간 첫 초
    assert row["n_ticks"] >= 2  # 대량매수 틱이 여러 개 잡혀야 함
    assert row["price_drift_pct"] > 0  # 구간 동안 가격이 올랐다


def test_pattern_contrast_table_splits_by_outcome_and_reports_means():
    df = pd.DataFrame({
        "ret_5m": [0.01, 0.02, -0.01, -0.02],
        "n_ticks": [3, 5, 1, 1],
        "duration_sec": [2, 3, 1, 1],
        "total_buy_value": [1000, 2000, 100, 100],
        "avg_size_mult": [4.0, 5.0, 3.0, 3.0],
        "price_drift_pct": [0.5, 0.6, 0.0, -0.1],
        "concurrent_sell_value": [100, 200, 500, 500],
        "buy_share": [0.9, 0.9, 0.2, 0.2],
    })

    table = pattern_contrast_table(df)

    n_ticks_row = table[table["feature"] == "n_ticks"].iloc[0]
    assert n_ticks_row["오른_평균"] == pytest.approx(4.0)  # (3+5)/2
    assert n_ticks_row["안오른_평균"] == pytest.approx(1.0)
    assert n_ticks_row["n_오름"] == 2
    assert n_ticks_row["n_안오름"] == 2
