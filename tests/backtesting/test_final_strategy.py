import os

import numpy as np
import pandas as pd

from backtesting import final_strategy
from backtesting.final_strategy import (
    RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    RECOMMENDED_PROBA_THRESHOLD,
    TOP_N,
    build_training_dataset,
    describe_strategy_1,
    detect_final_entries,
    evaluate_tiered_exit_from_path,
    evaluate_tiered_exit_from_path_with_exit_idx,
    generate_signals,
    train_and_save_final_model,
)
from backtesting.final_strategy import MIN_TRADE_VALUE
from backtesting.ml_entry_filter import FEATURE_COLUMNS, load_model, predict_quality_proba


def _daily(dates: list[str], closes: list[float]) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * len(closes)}, index=index
    )


def _rising_minute(day: str, closes: list[float]) -> pd.DataFrame:
    index = pd.date_range(f"{day} 09:00", periods=len(closes), freq="1min")
    # 분당 거래대금(종가x거래량)이 MIN_TRADE_VALUE를 넘도록 종가에서 역산한다 —
    # 하한 상수가 바뀌어도 픽스처가 조용히 신호를 잃지 않게 리터럴을 쓰지 않는다.
    volume = int(MIN_TRADE_VALUE / min(closes)) + 1
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [volume] * len(closes)},
        index=index,
    )


def test_describe_strategy_1_returns_entry_exit_operation_sections():
    description = describe_strategy_1()

    assert set(description.keys()) == {"entry", "exit", "operation", "exchange_basis"}
    assert all(isinstance(items, list) and len(items) > 0 for items in description.values())
    assert any(str(TOP_N) in line for line in description["entry"])
    assert any(str(RECOMMENDED_PROBA_THRESHOLD) in line for line in description["operation"])
    assert any(str(RECOMMENDED_MAX_CONCURRENT_POSITIONS) in line for line in description["operation"])


def test_detect_final_entries_true_once_all_conditions_align():
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])  # 전일종가 100
    # 단조 증가하는 상승 -> 3분수익률/거래대금/당일신고가/무하락 조건이 자연스럽게 맞음
    minute = _rising_minute("2026-01-02", [100.5, 102, 105, 108, 111, 115, 120])
    daily_top35 = {pd.Timestamp("2026-01-02"): {"000001"}}
    regime_by_day = {pd.Timestamp("2026-01-02"): True}

    # day_return_ceiling을 0.22로 명시 - 이 테스트는 등락률 상한 자체를 검증하는
    # 게 아니라 다른 조건들을 검증하는 것이므로, 모듈 기본값(2026-08-30 0.15로
    # 변경됨)이 바뀌어도 이 픽스처(8/11/15/20%)가 영향받지 않게 원래 캘리브레이션
    # 값(0.22)으로 고정한다.
    entries = detect_final_entries(minute, daily, "000001", daily_top35, regime_by_day, day_return_ceiling=0.22)

    # idx0~2는 당일상승률(7%) 미달(각 0.5/2/5%), idx3~6(8/11/15/20%)은 모든 조건 충족
    assert list(entries) == [False, False, False, True, True, True, True]


def test_detect_final_entries_false_when_not_in_top35():
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])
    minute = _rising_minute("2026-01-02", [100.5, 102, 105, 108, 111, 115, 120])
    daily_top35 = {pd.Timestamp("2026-01-02"): {"다른종목"}}  # 000001은 top35에 없음
    regime_by_day = {pd.Timestamp("2026-01-02"): True}

    entries = detect_final_entries(minute, daily, "000001", daily_top35, regime_by_day)

    assert not entries.any()


def test_detect_final_entries_false_when_regime_is_down():
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])
    minute = _rising_minute("2026-01-02", [100.5, 102, 105, 108, 111, 115, 120])
    daily_top35 = {pd.Timestamp("2026-01-02"): {"000001"}}
    regime_by_day = {pd.Timestamp("2026-01-02"): False}  # 코스피 지수 60이평선 아래

    entries = detect_final_entries(minute, daily, "000001", daily_top35, regime_by_day)

    assert not entries.any()


def test_detect_final_entries_top25_rank1_auto_suppresses_top35():
    """2026-08-30: top25_return_rank1이 켜지면 top35는 호출자가 disabled_conditions로
    끄지 않아도 자동으로 꺼져야 한다(대체관계 강제) — 안 그러면 오늘 실제로 벌어졌던
    "top35를 같이 안 꺼서 나온 가짜 숫자" 사고가 반복된다."""
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])
    minute = _rising_minute("2026-01-02", [100.5, 102, 105, 108, 111, 115, 120])
    daily_top35 = {pd.Timestamp("2026-01-02"): {"다른종목"}}  # 000001은 top35에 없음
    regime_by_day = {pd.Timestamp("2026-01-02"): True}
    rank1_by_minute = {ts: "000001" for ts in minute.index}  # 매 순간 000001이 1등

    # top35에 없지만 top25_return_rank1이 대신 통과시켜야 한다(자동 대체) - disabled_
    # conditions에 "top35"를 안 넘겼어도 top35 자체가 이제 무시된다.
    entries_on = detect_final_entries(
        minute, daily, "000001", daily_top35, regime_by_day,
        top25_return_rank1_by_minute=rank1_by_minute, day_return_ceiling=0.22,
    )
    assert list(entries_on) == [False, False, False, True, True, True, True]

    # "top25_return_rank1"으로 명시적으로 끄면 top35가 되살아나야 한다(정상 A/B 끔) -
    # 000001은 top35에 없으니 전부 False로 돌아간다.
    entries_off = detect_final_entries(
        minute, daily, "000001", daily_top35, regime_by_day,
        disabled_conditions=frozenset({"top25_return_rank1"}),
        top25_return_rank1_by_minute=rank1_by_minute, day_return_ceiling=0.22,
    )
    assert not entries_off.any()


def test_detect_final_entries_precomputed_conditions_match_default_path():
    """precomputed_base_entries/new_high/no_drawdown를 넘겼을 때 결과가 안 넘겼을 때
    (기존 종목별 pandas 호출)와 완전히 같아야 한다 - scan_all_trades의
    use_duckdb_conditions 스위치가 기대는 배선(딕셔너리 조회+reindex) 자체의 회귀
    테스트. 여기서는 DuckDB를 실제로 안 돌리고 pandas 함수 결과를 그대로 딕셔너리에
    담아 넘겨 "배선"만 검증한다(DuckDB 결과 자체의 동치성은 각 배치 함수의 전용
    테스트가 이미 지킨다)."""
    from backtesting.breakout_reversal import detect_entries
    from backtesting.entry_filters import intraday_new_high_filter, no_prior_drawdown_filter
    from backtesting.final_strategy import DRAWDOWN_THRESHOLD, MIN_RETURN_PCT, MIN_TRADE_VALUE, WINDOW_MINUTES

    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])
    minute = _rising_minute("2026-01-02", [100.5, 102, 105, 108, 111, 115, 120])
    daily_top35 = {pd.Timestamp("2026-01-02"): {"000001"}}
    regime_by_day = {pd.Timestamp("2026-01-02"): True}

    expected = detect_final_entries(minute, daily, "000001", daily_top35, regime_by_day)

    precomputed_base_entries = {"000001": detect_entries(minute, WINDOW_MINUTES, MIN_TRADE_VALUE, MIN_RETURN_PCT)}
    precomputed_new_high = {"000001": intraday_new_high_filter(minute)}
    precomputed_no_drawdown = {"000001": no_prior_drawdown_filter(minute, DRAWDOWN_THRESHOLD)}

    result = detect_final_entries(
        minute, daily, "000001", daily_top35, regime_by_day,
        precomputed_base_entries=precomputed_base_entries,
        precomputed_new_high=precomputed_new_high,
        precomputed_no_drawdown=precomputed_no_drawdown,
    )

    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_detect_final_entries_precomputed_missing_code_defaults_to_all_false():
    """딕셔너리에 그 종목 코드가 없으면(배치 함수가 그 종목을 못 만든 극단 케이스)
    에러 대신 전부 False로 안전하게 처리돼야 한다."""
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])
    minute = _rising_minute("2026-01-02", [100.5, 102, 105, 108, 111, 115, 120])
    daily_top35 = {pd.Timestamp("2026-01-02"): {"000001"}}
    regime_by_day = {pd.Timestamp("2026-01-02"): True}

    result = detect_final_entries(
        minute, daily, "000001", daily_top35, regime_by_day,
        precomputed_base_entries={},  # "000001" 없음
        precomputed_new_high={},
        precomputed_no_drawdown={},
    )

    assert not result.any()


# ---- generate_signals (Strategy 프로토콜 어댑터) ----

def test_generate_signals_maps_detect_final_entries_to_signal_column():
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])
    minute = _rising_minute("2026-01-02", [100.5, 102, 105, 108, 111, 115, 120])
    daily_top35 = {pd.Timestamp("2026-01-02"): {"000001"}}
    regime_by_day = {pd.Timestamp("2026-01-02"): True}

    # day_return_ceiling=0.22로 고정 - 이유는 위 detect_final_entries 테스트와 동일
    # (이 테스트는 상한 자체가 아니라 signal 컬럼 매핑을 검증하는 것).
    out = generate_signals(minute, daily, "000001", daily_top35, regime_by_day, day_return_ceiling=0.22)

    assert list(out["signal"]) == [0, 0, 0, 1, 1, 1, 1]
    assert list(out["close"]) == list(minute["close"])  # 원본 컬럼은 그대로 보존


def test_generate_signals_exposes_name_and_params():
    assert generate_signals.name == "strategy_1"
    assert generate_signals.params["top_n"] == TOP_N


def test_evaluate_tiered_exit_from_path_all_tiers_hit_gives_positive_pnl():
    # 4단계 익절 목표(2.5/4/5.5/7%)를 모두 넘는 순수익률 경로
    path = [(0, 0.03, 0.03), (1, 0.045, 0.045), (2, 0.06, 0.06), (3, 0.08, 0.08)]

    pct = evaluate_tiered_exit_from_path(path)

    assert pct > 0


def test_evaluate_tiered_exit_from_path_with_exit_idx_matches_pct_and_returns_last_leg_idx():
    path = [(0, 0.03, 0.03), (1, 0.045, 0.045), (2, 0.06, 0.06), (3, 0.08, 0.08)]

    pct, exit_idx = evaluate_tiered_exit_from_path_with_exit_idx(path)

    assert pct == evaluate_tiered_exit_from_path(path)
    assert exit_idx == 3  # 마지막 tier가 idx=3에서 발동, 전량 소진되므로 그 지점이 종료 시점


def test_evaluate_tiered_exit_from_path_with_exit_idx_stop_loss_case():
    path = [(0, -0.03, 0.0)]  # 무장 전 즉시 손절

    pct, exit_idx = evaluate_tiered_exit_from_path_with_exit_idx(path)

    assert exit_idx == 0
    assert pct < 0


def test_build_training_dataset_produces_one_row_per_qualifying_entry(tmp_path, monkeypatch):
    daily_dir = tmp_path / "stocks" / "daily"
    minute_dir = tmp_path / "stocks" / "minute"
    daily_dir.mkdir(parents=True)
    minute_dir.mkdir(parents=True)

    _daily(["2026-01-01", "2026-01-02"], [100, 999]).to_csv(daily_dir / "000001.csv")
    _rising_minute("2026-01-02", [100.5, 102, 105, 108, 111, 115, 120]).to_csv(minute_dir / "000001.csv")
    # 코스피 지수 로컬 데이터가 tmp_path에 없으므로, 레짐 판단은 고정값으로 대체
    monkeypatch.setattr(
        final_strategy, "load_kospi_regime_by_day", lambda data_dir: {pd.Timestamp("2026-01-02"): True}
    )

    features_df, labels_s = build_training_dataset(str(tmp_path))

    assert list(features_df.columns) == FEATURE_COLUMNS
    # build_training_dataset은 day_return_ceiling을 인자로 안 받는다(항상 모듈
    # 기본값 사용, 지금은 0.15) - idx5(15%)/idx6(20%)이 이제 상한에 걸려 빠지고
    # idx3(8%)/idx4(11%)만 남는다. top25_return_rank1이 기본 ON으로 top35를 자동
    # 대체하지만(2026-08-30 strategy-agent 변경) 이 fixture는 종목이 000001
    # 하나뿐이라 매 순간 자동으로 1등이라 결과 건수엔 영향 없음을 확인함.
    assert len(features_df) == 2
    assert len(labels_s) == 2
    assert labels_s.isin([0, 1]).all()


def test_train_and_save_final_model_persists_loadable_model(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    synthetic_features = pd.DataFrame({c: rng.normal(size=100) for c in FEATURE_COLUMNS})
    synthetic_labels = pd.Series((synthetic_features["return_pct"] > 0).astype(int))
    monkeypatch.setattr(
        final_strategy, "build_training_dataset",
        lambda data_dir, disabled_conditions=frozenset(): (synthetic_features, synthetic_labels),
    )
    model_path = str(tmp_path / "nested" / "entry_filter_model.joblib")

    trained, features_df, labels_s = train_and_save_final_model(
        data_dir="unused", model_path=model_path, n_estimators=10
    )

    assert os.path.exists(model_path)
    loaded = load_model(model_path)
    proba = predict_quality_proba(loaded, features_df)
    assert len(proba) == len(labels_s)
    assert proba.between(0, 1).all()
