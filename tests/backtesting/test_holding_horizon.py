import numpy as np
import pandas as pd
import pytest

from _precursor_fastpath import SESSION_START
from backtesting.holding_horizon import (
    compute_intraday_long_labels,
    concurrent_position_estimate,
    daily_labels_and_gap_decomposition,
    verify_price_consistency,
)


def test_verify_price_consistency_flags_large_mismatch(tmp_path, monkeypatch):
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    pd.DataFrame({
        "date": ["2026-08-04", "2026-08-05"],
        "open": [100, 100], "high": [100, 100], "low": [100, 100],
        "close": [100.0, 130.0], "volume": [1, 1],
    }).to_csv(daily_dir / "000001.csv", index=False)

    dataset = pd.DataFrame({
        "code": ["000001", "000001"], "date": ["2026-08-04", "2026-08-05"],
        "t_sec": [100, 200], "price_t": [100.0, 130.0],
    })

    result = verify_price_consistency(dataset, daily_dir=str(daily_dir))

    # 08-04는 틱=100/일봉종가=100 -> 정상, 08-05는 완전히 일치(130/130)라 둘 다 정상
    assert not result["flagged"].any()


def test_verify_price_consistency_flags_split_like_ratio(tmp_path):
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    pd.DataFrame({
        "date": ["2026-08-04"], "open": [100], "high": [100], "low": [100],
        "close": [100.0], "volume": [1],
    }).to_csv(daily_dir / "000002.csv", index=False)
    dataset = pd.DataFrame({"code": ["000002"], "date": ["2026-08-04"], "t_sec": [100], "price_t": [130.0]})

    result = verify_price_consistency(dataset, daily_dir=str(daily_dir))

    assert result["flagged"].iloc[0]  # 130/100 = 1.30, 2% 허용치 밖


def _make_daily_csv(path, dates, opens, closes):
    pd.DataFrame({"date": dates, "open": opens, "high": closes, "low": opens,
                  "close": closes, "volume": [1] * len(dates)}).to_csv(path, index=False)


def test_daily_labels_and_gap_decomposition_matches_manual_calc(tmp_path):
    # day0 close=100, day1 open=102/close=104, day2 open=103/close=106
    dates = ["2026-08-04", "2026-08-05", "2026-08-06"]
    _make_daily_csv(tmp_path / "000003.csv", dates, [100, 102, 103], [100, 104, 106])

    out = daily_labels_and_gap_decomposition("000003", "2026-08-04", daily_dir=str(tmp_path))

    assert out["exit_close_1d"] == 104
    assert np.isnan(out["exit_close_3d"])  # 3거래일 뒤는 데이터 범위 밖
    expected_gap_1d = np.log(102 / 100)  # day0->day1 갭 하나
    assert out["gap_log_1d"] == pytest.approx(expected_gap_1d)


def test_gap_log_3d_sums_three_overnight_transitions(tmp_path):
    dates = ["2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]
    opens = [100, 102, 105, 108]
    closes = [100, 104, 107, 110]
    _make_daily_csv(tmp_path / "000005.csv", dates, opens, closes)

    out = daily_labels_and_gap_decomposition("000005", "2026-08-04", daily_dir=str(tmp_path))

    expected = np.log(102 / 100) + np.log(105 / 104) + np.log(108 / 107)
    assert out["gap_log_3d"] == pytest.approx(expected)
    assert out["exit_close_3d"] == 110


def test_ret_session_last_is_not_the_true_daily_close_by_construction(tmp_path):
    """[정정 회귀] `ret_session_last`는 이름 그대로 "정규장 마지막 체결"이지
    "당일종가"가 아니다 - 15:20~15:30(동시호가)엔 원본에 틱이 없어 마지막
    연속체결가(15:19대)가 그대로 끝까지 이어진다. 진짜 종가(동시호가 이후
    확정되는 값)가 그 마지막 연속체결가와 다를 수 있다는 걸 값으로 고정한다 -
    이 테스트가 깨지면(둘이 항상 같다고 가정하는 코드가 들어오면) 그게 바로
    `backtest-agent_20260831-195143_...` 가 지적한 착각이 되돌아온 것이다."""
    times = ["090000", "151900"]  # 정규장 마지막 연속체결 = 15:19:00
    prices = [100.0, 100.0]
    df = pd.DataFrame({"time": times, "cur_prc": prices, "trde_qty": [10, 10], "pred_pre_sig": [2, 2]})
    path = tmp_path / "20260804.parquet"
    df.iloc[::-1].reset_index(drop=True).to_parquet(path)

    labels = compute_intraday_long_labels(str(path), "000006", "2026-08-04")

    row = labels[labels["t_sec"] == SESSION_START].iloc[0]
    session_last_price = 100.0 * (1 + row["ret_session_last"])
    true_close = 103.0  # 가상의 실제(동시호가 이후) 종가 - 우리 데이터엔 없는 값
    assert session_last_price == pytest.approx(100.0)  # 마지막 연속체결가 그대로
    assert session_last_price != pytest.approx(true_close)  # 종가와 같다고 가정하면 안 됨


def test_concurrent_position_estimate_sums_within_rolling_window():
    # 종목 A: day1에 3건, day2에 2건, day3에 1건 신호. k=2 롤링합 최대는 day1+day2=5.
    signal_df = pd.DataFrame({
        "code": ["A"] * 6,
        "date": ["d1", "d1", "d1", "d2", "d2", "d3"],
    })

    est = concurrent_position_estimate(signal_df, trading_days_held=2)

    assert est["max_concurrent"] == 5.0
