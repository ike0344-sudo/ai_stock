import math

import numpy as np
import pandas as pd
import pytest

from _precursor_fastpath import SESSION_START
from backtesting.t0_forward_return import (
    _day_clustered_mean_se,
    compute_stock_day,
    decile_table,
    entry_condition_stats,
    krx_tick_size,
    round_trip_cost_pct,
)


def test_krx_tick_size_bands():
    assert krx_tick_size(1_500) == 1.0
    assert krx_tick_size(3_000) == 5.0
    assert krx_tick_size(10_000) == 10.0
    assert krx_tick_size(30_000) == 50.0
    assert krx_tick_size(100_000) == 100.0
    assert krx_tick_size(300_000) == 500.0
    assert krx_tick_size(600_000) == 1_000.0


def test_round_trip_cost_uses_tick_floor_for_cheap_stocks():
    cheap = round_trip_cost_pct(np.array([1_500.0]))
    # 기본 슬리피지(0.1%)가 1틱(1/1500=0.067%)보다 이미 크므로 기본값이 하한을
    # 결정한다 - 최소한 수수료 2회+세금+슬리피지 2회는 반드시 포함돼야 한다.
    expected_min = 0.00015 * 2 + 0.0023 + 0.001 * 2
    assert cheap[0] == pytest.approx(expected_min)


def _make_synthetic_tick_file(path, times, prices, qtys):
    df = pd.DataFrame({
        "time": times, "cur_prc": prices, "trde_qty": qtys, "pred_pre_sig": [2] * len(times),
    })
    df.iloc[::-1].reset_index(drop=True).to_parquet(path)  # 역시간순으로 저장(실제 파일 관례)


def test_compute_stock_day_ret_1m_matches_manual_price_ratio(tmp_path):
    path = tmp_path / "20260804.parquet"
    times = [f"09{m:02d}00" for m in range(10)]  # 090000..090900, 1분마다 1틱
    prices = [100.0, 102.0] + [102.0] * 8  # 09:00->09:01 사이 +2%
    _make_synthetic_tick_file(path, times, prices, [10] * 10)

    df = compute_stock_day(str(path), "TEST", "2026-08-04")

    row = df.set_index("t_sec").loc[SESSION_START]
    assert row["price_t"] == 100.0
    assert row["ret_1m"] == pytest.approx(102.0 / 100.0 - 1)


def test_compute_stock_day_keeps_row_when_only_long_horizon_label_is_nan(tmp_path):
    """세션 막판 T0는 10분 라벨은 못 내도 1분 라벨은 살아있어야 한다(행을 통째로
    버리지 말라는 지시)."""
    path = tmp_path / "20260804.parquet"
    times = ["152900", "152910"]  # 15:29:00(세션 거의 끝) - 10분 뒤는 세션을 넘는다
    prices = [200.0, 202.0]
    _make_synthetic_tick_file(path, times, prices, [5, 5])

    df = compute_stock_day(str(path), "TEST", "2026-08-04")

    row = df[df["t_sec"] == 15 * 3600 + 29 * 60].iloc[0]
    assert row["ret_1m"] == pytest.approx(202.0 / 200.0 - 1)
    assert math.isnan(row["ret_10m"])


def test_day_clustered_mean_se_uses_daily_means_not_raw_row_count():
    """일자별 평균 3개(1.0, 1.0, 1.0)면 값이 전부 같으니 SE=0이어야 한다 - 표본
    내 행 개수(자기상관 있는 1분 표본)로 순진하게 SE를 냈다면 0이 아니게 나온다."""
    df = pd.DataFrame({
        "date": ["d1"] * 100 + ["d2"] * 5 + ["d3"] * 50,
        "x": [1.0] * 155,
    })

    mean, se, n, n_days = _day_clustered_mean_se(df, "x")

    assert mean == 1.0
    assert se == 0.0
    assert n == 155
    assert n_days == 3


def test_decile_table_is_monotonic_for_a_clean_linear_relationship():
    rng = np.random.default_rng(0)
    n = 2000
    feature = rng.uniform(0, 1, n)
    label = feature + rng.normal(0, 0.01, n)  # 강한 양의 관계
    df = pd.DataFrame({"feat": feature, "ret_5m": label, "date": ["d1"] * n})

    table = decile_table(df, "feat")

    assert len(table) == 10
    assert table["mean_ret5m"].is_monotonic_increasing


def test_entry_condition_stats_applies_is_threshold_to_oos_unchanged():
    """OOS 통계는 IS 문턱값 그대로 적용한 결과여야 한다 - OOS 데이터로 문턱을
    다시 고르면(누출) 이 테스트가 잡아낼 만큼 다른 표본이 걸린다."""
    train = pd.DataFrame({
        "date": ["d1"] * 5 + ["d2"] * 5,
        "feat": [1, 2, 3, 4, 5, 1, 2, 3, 4, 5],
        "ret_5m": [0.01] * 10,
        "price_t": [10_000.0] * 10,
    })
    test = pd.DataFrame({
        "date": ["d3"] * 5,
        "feat": [1, 2, 3, 4, 5],
        "ret_5m": [0.02] * 5,
        "price_t": [10_000.0] * 5,
    })
    thr = train["feat"].quantile(0.20)  # IS 하위 20% = 1

    result = entry_condition_stats(train, test, {"feat": thr})

    oos_row = result[result["group"] == "OOS"].iloc[0]
    assert oos_row["n"] == 1  # OOS에서도 feat<=1 인 행 1개만 걸려야 함(문턱 재계산 안 함)
    assert oos_row["gross_mean_pct"] == pytest.approx(2.0)
