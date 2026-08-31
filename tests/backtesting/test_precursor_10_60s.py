import numpy as np
import pandas as pd
import pytest

from _precursor_fastpath import SESSION_START
from backtesting.precursor_10_60s import classify_stock_day, compute_stock_day


def test_classify_stock_day_reuses_cluster_bounds_with_custom_gap():
    label_grid = np.zeros(20, dtype=bool)
    label_grid[0:3] = True  # 클러스터: 그리드idx 0~2

    category = classify_stock_day(label_grid, gap=2, post_exclude=2)

    assert category[0] == "positive"
    assert list(category[1:3]) == ["excluded"] * 2  # 클러스터 나머지
    assert list(category[3:5]) == ["excluded"] * 2  # 종료 후 2그리드 사후제외
    assert category[5] == "negative"


def _make_synthetic_tick_file(path, jump_time_str, jump_price, base_price=100.0):
    """09:00:00부터 1초마다 1틱, jump_time_str부터 base_price -> jump_price로
    점프해 유지. 역시간순(최신이 먼저)으로 저장(실제 tick_al 파일 관례)."""
    times = []
    prices = []
    for sec in range(0, 200):
        hh, mm, ss = 9, sec // 60, sec % 60
        t = f"{hh:02d}{mm:02d}{ss:02d}"
        times.append(t)
        prices.append(base_price if t < jump_time_str else jump_price)
    df = pd.DataFrame({
        "time": times, "cur_prc": prices, "trde_qty": [10] * len(times), "pred_pre_sig": [2] * len(times),
    })
    df.iloc[::-1].reset_index(drop=True).to_parquet(path)


def test_compute_stock_day_isolates_onset_and_computes_realized_return(tmp_path):
    path = tmp_path / "20260804.parquet"
    # 09:00:59(세션 59초 지점 - label_shoot 창은 [t,t+horizon-1] 이라 T0=0의
    # 60초 창(0~59초)에 정확히 걸치는 마지막 초)에 100 -> 100.6(+0.6%, 문턱
    # 0.5% 통과)로 점프, 그 뒤 계속 유지.
    _make_synthetic_tick_file(path, jump_time_str="090059", jump_price=100.6)

    df = compute_stock_day(str(path), "TEST", "2026-08-04")

    by_t = df.set_index("t_sec")
    t_before_jump = SESSION_START  # 09:00:00 - 창 안(0~59초)에 점프가 있어 라벨=1이어야 함
    assert by_t.loc[t_before_jump, "category"] == "positive"
    assert by_t.loc[t_before_jump, "realized_ret_60s"] == pytest.approx(0.006)
    # 점프 직후(09:01:10 등)는 같은 클러스터의 나머지/사후제외 구간이라
    # negative가 아니라 excluded여야 한다(상승 후 구간이 섞이면 안 됨).
    t_soon_after_jump = SESSION_START + 70
    assert by_t.loc[t_soon_after_jump, "category"] == "excluded"
    # 사후제외 폭(60초)까지 다 지난 뒤(09:02:00, +120초)는 진짜 negative.
    t_well_after_jump = SESSION_START + 120
    assert by_t.loc[t_well_after_jump, "category"] == "negative"


def test_value_surge_has_no_infinity_when_prior_window_had_zero_volume(tmp_path):
    """[회귀] 실측으로 발견: 창 시작 이전까지(과거)는 거래가 0인데 지금 창 안에는
    거래가 있으면 avg_value(확장평균, 분모)가 0이라 win_value/avg_value가 inf가
    되고, 이게 그대로 roc_auc_score에 들어가 전체 스캔이 죽었다(4,709,695행
    스캔 후 지표 계산 단계에서 실제로 재현됨). 09:00:15에 첫 체결 하나만 있고
    그 전엔 아무 거래도 없는 경우로 재현한다."""
    times = ["090015"] + [f"0900{s:02d}" for s in range(16, 60)]  # 09:00:15만 체결, 그 뒤는 가격유지용 틱
    prices = [100.0] * len(times)
    df_in = pd.DataFrame({
        "time": times, "cur_prc": prices, "trde_qty": [10] * len(times), "pred_pre_sig": [2] * len(times),
    })
    path = tmp_path / "20260804.parquet"
    df_in.iloc[::-1].reset_index(drop=True).to_parquet(path)

    df = compute_stock_day(str(path), "TEST", "2026-08-04")

    assert np.isfinite(df["vs10_value_surge"].dropna().to_numpy()).all()


def test_compute_stock_day_feature_window_counts_ticks_correctly(tmp_path):
    path = tmp_path / "20260804.parquet"
    _make_synthetic_tick_file(path, jump_time_str="099999", jump_price=100.0)  # 점프 없음(항상 100)

    df = compute_stock_day(str(path), "TEST", "2026-08-04")

    # w10 관측창은 [T0-10,T0) - 1초 1틱이니 정확히 10틱/10초 = 초당 1틱
    row = df[df["t_sec"] == SESSION_START + 100].iloc[0]
    assert row["w10_tick_speed"] == pytest.approx(1.0)
