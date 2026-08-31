from datetime import date

import pandas as pd

from backtesting.gate_ab_check import gate_ab_per_fold
from backtesting.ml_entry_filter import FEATURE_COLUMNS


def _trades(entry_dates: list) -> pd.DataFrame:
    """entry_time만 다르고 나머지는 아무 값 - 폴드 경계(test_start/test_end)만 보는
    테스트라 학습이 실제로 되든 표본부족으로 skip되든 상관없다."""
    n = len(entry_dates)
    row = {
        "code": ["TEST"] * n,
        "entry_time": [pd.Timestamp(d) for d in entry_dates],
        "exit_time": [pd.Timestamp(d) for d in entry_dates],
        "pct": [0.01] * n,
    }
    row.update({c: [0.0] * n for c in FEATURE_COLUMNS})
    return pd.DataFrame(row)


def test_gate_ab_per_fold_fold_boundaries_are_calendar_fixed_when_start_given():
    """회귀 테스트: regime_filter_ab.py에서 발견된 버그 - start/end를 안 주면
    gate_ab_per_fold가 trades_df 자신의 min(entry_time)으로 폴드 시작점을 잡아서,
    entry_time 범위가 다른 두 trades_df를 같은 train/test/step로 돌려도 폴드
    경계(test_start/test_end)가 며칠씩 어긋난다. start/end를 고정해서 넘기면
    데이터 내용과 무관하게 폴드 경계가 완전히 같아야 한다."""
    fixed_start, fixed_end = date(2026, 1, 1), date(2026, 6, 1)

    # 두 trades_df의 entry_time 범위를 일부러 5일 어긋나게 잡는다(둘 다 폴드가
    # 생길 만큼 넓은 범위 - 실측 확인: start/end를 안 주면 이 두 데이터셋은
    # 폴드 경계가 실제로 5일씩 어긋난다).
    df_a = _trades([date(2026, 1, 5), date(2026, 3, 10)])
    df_b = _trades([date(2026, 1, 10), date(2026, 3, 15)])

    ab_a = gate_ab_per_fold(df_a, train_days=30, test_days=15, step_days=15, start=fixed_start, end=fixed_end)
    ab_b = gate_ab_per_fold(df_b, train_days=30, test_days=15, step_days=15, start=fixed_start, end=fixed_end)

    folds_a = ab_a[ab_a["fold"] != "합산"][["test_start", "test_end"]].drop_duplicates().reset_index(drop=True)
    folds_b = ab_b[ab_b["fold"] != "합산"][["test_start", "test_end"]].drop_duplicates().reset_index(drop=True)

    assert len(folds_a) > 0, "테스트 파라미터가 폴드를 하나도 못 만들었다 - 테스트 자체를 점검할 것"
    pd.testing.assert_frame_equal(folds_a, folds_b)


def test_gate_ab_per_fold_defaults_to_data_derived_range_when_start_not_given():
    """start/end 생략 시엔 기존 동작(trades_df 자신의 entry_time 범위) 그대로 - 기존
    단일 trades_df 호출부와의 하위호환 확인."""
    df = _trades([date(2026, 1, 1), date(2026, 1, 20), date(2026, 2, 10)])
    result = gate_ab_per_fold(df, train_days=10, test_days=10, step_days=10)
    assert "합산" in result["fold"].values
