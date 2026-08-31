import numpy as np

from backtesting.shooting_precursor_onset import (
    classify_stock_day,
    cluster_bounds,
    first_crossing_lead_time,
)


def test_cluster_bounds_merges_within_gap_and_splits_beyond_it():
    true_idx = np.array([0, 1, 2, 3, 4, 5, 20, 21, 22])

    bounds = cluster_bounds(true_idx, gap=10)

    assert bounds == [(0, 5), (20, 22)]


def test_cluster_bounds_empty_input():
    assert cluster_bounds(np.array([]), gap=10) == []


def test_classify_stock_day_marks_first_t_positive_rest_and_post_window_excluded():
    label_grid = np.zeros(30, dtype=bool)
    label_grid[0:6] = True  # 클러스터1: idx 0~5
    label_grid[20:23] = True  # 클러스터2: idx 20~22

    category = classify_stock_day(label_grid)

    assert category[0] == "positive"
    assert list(category[1:6]) == ["excluded"] * 5  # 클러스터1 나머지
    assert list(category[6:16]) == ["excluded"] * 10  # 클러스터1 종료 후 10분(그리드10개)
    assert list(category[16:20]) == ["negative"] * 4  # 두 클러스터 사이 진짜 negative
    assert category[20] == "positive"
    assert list(category[21:23]) == ["excluded"] * 2
    assert list(category[23:30]) == ["excluded"] * 7  # 배열 끝까지 클리핑됨


def test_first_crossing_lead_time_finds_earliest_threshold_cross():
    px = np.array([100.0] * 5 + [101.0, 102.0, 103.0, 103.0])  # idx5=+1%,6=+2%,7=+3%

    lead = first_crossing_lead_time(px, t=0, thresh=0.03, horizon=10)

    assert lead == 7  # 절대 인덱스 - t=0이라 상대/절대가 우연히 같으므로 아래로 t!=0도 검증


def test_first_crossing_lead_time_returns_absolute_index_not_relative():
    """t가 0이 아닐 때 상대 인덱스를 반환하면(과거 버그) t보다 작은 값이 나와
    호출부의 `cross - t` 가 음수로 터진다 - 이 테스트가 그 회귀를 잡는다."""
    px = np.array([100.0] * 20 + [103.0, 103.0])  # idx20에서 +3%
    t = 10

    lead = first_crossing_lead_time(px, t=t, thresh=0.03, horizon=15)

    assert lead == 20
    assert lead - t == 10  # 실제 걸린 시간(초)
