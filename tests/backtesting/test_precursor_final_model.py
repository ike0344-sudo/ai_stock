import numpy as np
import pandas as pd
import pytest

from _precursor_fastpath import SESSION_START
from backtesting.precursor_final_model import FEATURE_COLUMNS, compute_stock_day, evaluate_condition


def _make_synthetic_tick_file(path, times, prices, qtys=None):
    qtys = qtys or [10] * len(times)
    df = pd.DataFrame({
        "time": times, "cur_prc": prices, "trde_qty": qtys, "pred_pre_sig": [2] * len(times),
    })
    df.iloc[::-1].reset_index(drop=True).to_parquet(path)  # 역시간순 저장(실제 파일 관례)


def _hhmmss(sec_from_open: int) -> str:
    hh, mm, ss = 9, sec_from_open // 60, sec_from_open % 60
    return f"{hh:02d}{mm:02d}{ss:02d}"


def test_label_fires_on_5min_2pct_move_and_ret_5m_uses_fixed_close_not_max(tmp_path):
    """라벨(label_shoot)은 5분 창 안의 최고가 기준(+2%↑), 실현수익(ret_5m)은
    T0+300초 시점 종가 기준 - 정의가 서로 다르다는 걸 직접 확인."""
    times = [_hhmmss(s) for s in range(0, 400)]
    prices = [100.0] * 250 + [102.5] * 10 + [101.0] * 140  # t=250~259 잠깐 +2.5% 찍고 되돌림
    path = tmp_path / "20260804.parquet"
    _make_synthetic_tick_file(path, times, prices)

    df = compute_stock_day(str(path), "TEST", "2026-08-04")

    row = df[df["t_sec"] == SESSION_START].iloc[0]  # T0=0, 5분 창 = [0,300)초
    assert row["label"] == 1  # 창 안(250~259초)에 +2.5% 찍었으니 라벨=1
    # ret_5m은 T0+300초 "그 순간" 종가(101.0, +1%) - 최고가(102.5, +2.5%)가 아니다.
    assert row["ret_5m"] == pytest.approx(0.01)


def test_features_do_not_use_future_data_beyond_t0(tmp_path):
    """T0 이후(60초 예산 밖 포함)를 크게 바꿔도 T0 시점 피처(14개)는 전혀 안
    변해야 한다 - label/ret_5m은 미래를 보므로 당연히 변한다(그게 라벨의 정의).
    ml/features.py의 돌연변이 검증과 같은 방식을 이 파이프라인에 적용."""
    times = [_hhmmss(s) for s in range(0, 400)]
    base_prices = [100.0 + (s % 7) * 0.01 for s in range(400)]
    mutated_prices = list(base_prices)
    for s in range(180, 400):  # T0=100 기준 60초 예산(40~100초) 훨씬 밖
        mutated_prices[s] = 500.0

    base_path = tmp_path / "20260804.parquet"
    mut_path = tmp_path / "20260805.parquet"
    _make_synthetic_tick_file(base_path, times, base_prices)
    _make_synthetic_tick_file(mut_path, times, mutated_prices)

    df_base = compute_stock_day(str(base_path), "TEST", "2026-08-04")
    df_mut = compute_stock_day(str(mut_path), "TEST", "2026-08-05")

    row_base = df_base[df_base["t_sec"] == SESSION_START + 100].iloc[0]
    row_mut = df_mut[df_mut["t_sec"] == SESSION_START + 100].iloc[0]

    for col in FEATURE_COLUMNS:
        a, b = row_base[col], row_mut[col]
        if pd.isna(a) and pd.isna(b):
            continue
        assert a == pytest.approx(b), f"{col}이 T0 이후 변조에 영향받음(look-ahead)"

    # 대조: label/ret_5m은 미래(180~400초)를 보므로 실제로 달라져야 한다(음성대조).
    assert row_base["label"] != row_mut["label"] or row_base["ret_5m"] != pytest.approx(row_mut["ret_5m"])


def test_evaluate_condition_direction_handles_both_ge_and_le():
    df = pd.DataFrame({
        "date": ["d1"] * 4, "price_t": [10_000.0] * 4,
        "feat_hi": [1, 2, 3, 4], "feat_lo": [4, 3, 2, 1],
        "ret_5m": [0.01, 0.02, -0.01, 0.03],
    })

    ge_report = evaluate_condition(df, df, {"feat_hi": (">=", 3)})
    le_report = evaluate_condition(df, df, {"feat_lo": ("<=", 2)})

    # feat_hi>=3 -> 행 2,3(값 3,4) 선택. feat_lo<=2 -> 값 2,1인 행(마찬가지 뒤 2행).
    assert ge_report.iloc[0]["n"] == 2
    assert le_report.iloc[0]["n"] == 2


def test_divergence_is_nan_not_inf_when_value_surge_is_zero(tmp_path):
    """price_speed/value_surge_60에서 분모가 0일 때 inf가 아니라 NaN이어야
    한다(precursor_10_60s에서 이미 한 번 잡은 같은 계열 버그 - 여기서도 확인)."""
    times = [_hhmmss(s) for s in range(0, 200)]
    prices = [100.0] * 200  # 가격 변화 없음 -> 거래는 있지만 가격은 고정
    path = tmp_path / "20260804.parquet"
    _make_synthetic_tick_file(path, times, prices)

    df = compute_stock_day(str(path), "TEST", "2026-08-04")

    assert np.isfinite(df["w60_divergence"].dropna().to_numpy()).all()
