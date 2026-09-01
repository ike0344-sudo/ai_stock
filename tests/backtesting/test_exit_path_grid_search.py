import numpy as np
import pandas as pd
import pytest

from backtesting.exit_path_grid_search import evaluate_combo, trade_stats


def _path(returns, horizon=10):
    """returns: {second: rel_return}. 나머지는 마지막 값으로 유지(가격 정체)."""
    arr = np.zeros(horizon + 1)
    last = 0.0
    for t in range(horizon + 1):
        if t in returns:
            last = returns[t]
        arr[t] = last
    return arr


def test_evaluate_combo_stop_hit_before_target():
    # 3초째 -1%(손절선 -0.5% 이하), 6초째 +2%(익절선 +1%) - 손절이 먼저 와야 함
    paths = np.array([_path({3: -0.01, 6: 0.02})])

    result = evaluate_combo(paths, stop=0.005, target=0.01, time_stop_sec=10)

    assert result.loc[0, "exit_type"] == "stop"
    assert result.loc[0, "gross_ret"] == pytest.approx(-0.005)


def test_evaluate_combo_target_hit_before_stop():
    paths = np.array([_path({2: 0.02, 5: -0.01})])  # 2초째 익절 먼저, 5초째 손절은 무의미

    result = evaluate_combo(paths, stop=0.005, target=0.01, time_stop_sec=10)

    assert result.loc[0, "exit_type"] == "target"
    assert result.loc[0, "gross_ret"] == pytest.approx(0.01)


def test_evaluate_combo_neither_hit_exits_at_time_stop():
    paths = np.array([_path({5: 0.002})])  # 손절/익절 문턱 안 닿음

    result = evaluate_combo(paths, stop=0.005, target=0.01, time_stop_sec=10)

    assert result.loc[0, "exit_type"] == "time"
    assert result.loc[0, "gross_ret"] == pytest.approx(0.002)


def test_evaluate_combo_simultaneous_hit_is_structurally_impossible_for_positive_grids():
    """발견: stop>0·target>0인 정상 그리드에서는 같은 초의 가격 하나가
    "진입가 대비 -stop% 이하"이면서 동시에 "+target% 이상"일 수 없다(부호가
    반대라 한 값이 둘 다 만족 못 함) - 그래서 동시타격은 이 구현에서 구조적으로
    0건이다. 이게 "봉 내부 경로 문제"가 초단위 해상도에서는 이 체크에 한해
    발생하지 않는다는 뜻이라 리포트에 근거로 남긴다."""
    paths = np.array([_path({4: -0.01})])  # 손절선만 닿음

    result = evaluate_combo(paths, stop=0.005, target=0.005, time_stop_sec=10)

    assert bool(result.loc[0, "simultaneous_hit"]) is False
    assert result.loc[0, "exit_type"] == "stop"


def test_evaluate_combo_marks_invalid_when_session_truncated_before_time_stop():
    paths = np.array([_path({}, horizon=10)])
    paths[0, 5:] = np.nan  # 5초 이후 세션 밖(데이터 없음)

    result = evaluate_combo(paths, stop=0.02, target=0.02, time_stop_sec=10)

    assert result.loc[0, "exit_type"] == "invalid"
    assert np.isnan(result.loc[0, "gross_ret"])


def test_trade_stats_computes_max_consecutive_losses_in_entry_order():
    df = pd.DataFrame({
        "net_ret": [0.01, -0.01, -0.02, -0.01, 0.02, -0.01],
        "exit_type": ["target", "stop", "stop", "stop", "target", "stop"],
        "simultaneous_hit": [False] * 6,
        "date": ["d1"] * 6,
    })
    signals = pd.DataFrame({"date": ["d1"] * 6})

    stats = trade_stats(df, signals)

    assert stats["max_consecutive_losses"] == 3
    assert stats["n_trades"] == 6
    assert stats["stop_hit_rate_pct"] == pytest.approx(4 / 6 * 100)
