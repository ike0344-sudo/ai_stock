import math

import pandas as pd
import pytest

from _precursor_fastpath import SESSION_START
from backtesting.mfe_mae import compute_mfe_mae_labels


def _make_synthetic_tick_file(path, times, prices, qtys=None):
    qtys = qtys or [10] * len(times)
    df = pd.DataFrame({
        "time": times, "cur_prc": prices, "trde_qty": qtys, "pred_pre_sig": [2] * len(times),
    })
    df.iloc[::-1].reset_index(drop=True).to_parquet(path)  # 역시간순 저장(실제 파일 관례)


def test_mfe_mae_matches_manual_min_max_within_horizon(tmp_path):
    path = tmp_path / "20260804.parquet"
    # 09:00:00=100, 이후 60초 안에 105(고점)까지 올랐다가 97(저점)로 내려간 뒤 유지.
    times = ["090000", "090010", "090030", "090050", "090059", "090200"]
    prices = [100.0, 105.0, 97.0, 101.0, 101.0, 101.0]
    _make_synthetic_tick_file(path, times, prices)

    df = compute_mfe_mae_labels(str(path), "TEST", "2026-08-04")

    row = df.set_index("t_sec").loc[SESSION_START]
    assert row["mfe_1m"] == pytest.approx(105.0 / 100.0 - 1)
    assert row["mae_1m"] == pytest.approx(97.0 / 100.0 - 1)
    assert row["ev_1m"] == pytest.approx(row["mfe_1m"] + row["mae_1m"])


def test_mfe_mae_is_nan_when_horizon_exceeds_session(tmp_path):
    path = tmp_path / "20260804.parquet"
    # 세션 막판(15:25:00) - 10분(600초) 뒤는 세션을 넘는다.
    times = ["152500", "152510"]
    prices = [100.0, 101.0]
    _make_synthetic_tick_file(path, times, prices)

    df = compute_mfe_mae_labels(str(path), "TEST", "2026-08-04")

    row = df[df["t_sec"] == 15 * 3600 + 25 * 60].iloc[0]
    assert math.isnan(row["mfe_10m"])
    assert math.isnan(row["mae_10m"])
    # 1분 라벨은 살아있어야 한다(행을 통째로 버리지 않는다는 기존 원칙)
    assert not math.isnan(row["mfe_1m"])
