import pandas as pd

from backtesting.entry_filters import (
    combine_and,
    compute_index_regime_by_day,
    day_return_ceiling_filter,
    day_return_filter,
    intraday_new_high_filter,
    intraday_new_high_filter_batch_duckdb,
    market_regime_filter,
    n_day_high_filter,
    no_prior_drawdown_filter,
    no_prior_drawdown_filter_batch_duckdb,
    time_of_day_filter,
)


def _daily(dates: list[str], highs: list[float]) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    return pd.DataFrame({"open": highs, "high": highs, "low": highs, "close": highs, "volume": [1000] * len(highs)}, index=index)


def _minute(day: str, times: list[str], closes: list[float]) -> pd.DataFrame:
    index = pd.to_datetime([f"{day} {t}" for t in times])
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * len(closes)},
        index=index,
    )


def test_n_day_high_filter_true_when_close_exceeds_prior_n_day_high():
    # daily에는 조회 대상 당일(01-04) 행도 있어야 매핑이 된다 (당일 high 자체는
    # shift(1)로 참조에서 제외되므로 값은 무관 — 존재 여부만 중요).
    daily = _daily(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"], [100, 105, 103, 999])
    # 2026-01-04(당일)의 참조값 = 직전 3일(01-01~01-03) 최고가 = 105
    minute = _minute("2026-01-04", ["09:00", "09:01"], [104, 106])  # 첫 봉은 105 미만, 둘째는 초과

    result = n_day_high_filter(minute, daily, n=3)

    assert result.iloc[0] == False  # noqa: E712
    assert result.iloc[1] == True  # noqa: E712


def test_n_day_high_filter_false_when_insufficient_history():
    daily = _daily(["2026-01-01"], [100])  # n=3인데 1일치밖에 없음 -> rolling(3) NaN
    minute = _minute("2026-01-02", ["09:00"], [200])

    result = n_day_high_filter(minute, daily, n=3)

    assert result.iloc[0] == False  # noqa: E712


def test_n_day_high_filter_excludes_current_day_from_reference():
    """당일 일봉 데이터가 daily_candles에 이미 포함돼 있어도, shift(1) 덕분에
    당일 자신의 고가는 참조값 계산에서 제외되어야 한다 (미래 데이터 누수 방지)."""
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])  # 01-02(당일)의 999는 제외돼야
    minute = _minute("2026-01-02", ["09:00"], [150])  # 100보다는 크지만 999보다는 작음

    result = n_day_high_filter(minute, daily, n=1)

    assert result.iloc[0] == True  # noqa: E712  (참조값은 01-01의 100이어야 함)


def test_day_return_filter_true_when_above_threshold():
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])  # 전일종가=100, 당일(999)은 제외돼야
    minute = _minute("2026-01-02", ["09:00", "09:01"], [104, 106])  # +4%, +6%

    result = day_return_filter(minute, daily, threshold=0.05)

    assert result.iloc[0] == False  # noqa: E712  (4% < 5%)
    assert result.iloc[1] == True  # noqa: E712  (6% >= 5%)


def test_day_return_filter_false_when_no_prior_day():
    daily = _daily(["2026-01-01"], [100])  # 전일 데이터 없음 -> shift(1) NaN
    minute = _minute("2026-01-01", ["09:00"], [200])

    result = day_return_filter(minute, daily, threshold=0.05)

    assert result.iloc[0] == False  # noqa: E712


def test_day_return_ceiling_filter_true_when_below_threshold():
    daily = _daily(["2026-01-01", "2026-01-02"], [100, 999])  # 전일종가=100
    minute = _minute("2026-01-02", ["09:00", "09:01"], [122, 124])  # +22%, +24%

    result = day_return_ceiling_filter(minute, daily, threshold=0.23)

    assert result.iloc[0] == True  # noqa: E712  (22% < 23%)
    assert result.iloc[1] == False  # noqa: E712  (24% >= 23%)


def test_day_return_ceiling_filter_false_when_no_prior_day():
    daily = _daily(["2026-01-01"], [100])  # 전일 데이터 없음 -> shift(1) NaN -> 보수적으로 제외
    minute = _minute("2026-01-01", ["09:00"], [100])

    result = day_return_ceiling_filter(minute, daily, threshold=0.23)

    assert result.iloc[0] == False  # noqa: E712


def _minute_hlc(day: str, times: list[str], highs: list[float], closes: list[float]) -> pd.DataFrame:
    index = pd.to_datetime([f"{day} {t}" for t in times])
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": closes, "close": closes, "volume": [1000] * len(closes)},
        index=index,
    )


def test_intraday_new_high_filter_true_only_when_high_sets_new_day_high():
    minute = _minute_hlc(
        "2026-01-01", ["09:00", "09:01", "09:02", "09:03"],
        highs=[100, 105, 103, 106],
        closes=[100, 105, 103, 106],
    )

    result = intraday_new_high_filter(minute)

    assert list(result) == [True, True, False, True]


def test_intraday_new_high_filter_does_not_leak_across_day_boundary():
    day1 = _minute_hlc("2026-01-01", ["09:00"], highs=[200], closes=[200])
    day2 = _minute_hlc("2026-01-02", ["09:00"], highs=[100], closes=[100])  # day1보다 낮아도 day2 첫봉은 신고가
    combined = pd.concat([day1, day2])

    result = intraday_new_high_filter(combined)

    assert list(result) == [True, True]


def test_intraday_new_high_filter_batch_duckdb_matches_pandas_version(tmp_path):
    """배치 DuckDB 버전이 종목별 pandas 버전과 완전히 같은 결과를 내는지 - 여러
    종목·이틀치(당일 리셋 포함)로 확인한다. 다르면 이 함수를 쓰지 않는다."""
    minute_dir = tmp_path / "stocks" / "minute"
    minute_dir.mkdir(parents=True)

    # A: 기존 단일종목 pandas 테스트와 같은 값(신고가/비신고가 섞임, 하루치)
    a_combined = _minute_hlc(
        "2026-01-01", ["09:00", "09:01", "09:02", "09:03"],
        highs=[100, 105, 103, 106], closes=[100, 105, 103, 106],
    )
    # B: 이틀치 - 둘째날 첫봉이 전날보다 낮아도 당일 리셋으로 신고가여야 함
    b_combined = pd.concat([
        _minute_hlc("2026-01-01", ["09:00"], highs=[200], closes=[200]),
        _minute_hlc("2026-01-02", ["09:00"], highs=[100], closes=[100]),
    ])

    for code, combined in [("A", a_combined), ("B", b_combined)]:
        csv_index = combined.index.copy()
        csv_index.name = "date"
        combined.set_axis(csv_index).to_csv(minute_dir / f"{code}.csv")

    expected = {"A": intraday_new_high_filter(a_combined), "B": intraday_new_high_filter(b_combined)}
    result = intraday_new_high_filter_batch_duckdb(str(tmp_path))

    assert set(result.keys()) == {"A", "B"}
    for code in ("A", "B"):
        pd.testing.assert_series_equal(
            result[code], expected[code], check_names=False, check_freq=False
        )


def test_no_prior_drawdown_filter_true_when_pullback_stays_under_threshold():
    minute = _minute_hlc(
        "2026-01-01", ["09:00", "09:01", "09:02"],
        highs=[100, 97, 101], closes=[100, 97, 101],
    )  # 최대 되돌림 3% < 5%, 이후 신고가 경신

    result = no_prior_drawdown_filter(minute, drawdown_threshold=0.05)

    assert list(result) == [True, True, True]


def test_no_prior_drawdown_filter_becomes_false_and_stays_false_after_trigger():
    minute = _minute_hlc(
        "2026-01-01", ["09:00", "09:01", "09:02", "09:03"],
        highs=[100, 96, 94, 99], closes=[100, 96, 94, 99],
    )  # 고점100 -> -4%(미발동) -> -6%(발동) -> 99로 회복해도 그날은 계속 제외돼야 함

    result = no_prior_drawdown_filter(minute, drawdown_threshold=0.05)

    assert list(result) == [True, True, False, False]


def test_no_prior_drawdown_filter_batch_duckdb_matches_pandas_version(tmp_path):
    """배치 DuckDB 버전이 종목별 pandas 버전과 완전히 같은 결과를 내는지 - 발동 전/
    발동 후 sticky 유지/날짜경계 리셋 세 시나리오를 종목 3개로 재구성해 확인한다."""
    minute_dir = tmp_path / "stocks" / "minute"
    minute_dir.mkdir(parents=True)

    a_combined = _minute_hlc(
        "2026-01-01", ["09:00", "09:01", "09:02", "09:03"],
        highs=[100, 96, 94, 99], closes=[100, 96, 94, 99],
    )  # 발동 후 계속 False
    b_combined = pd.concat([
        _minute_hlc("2026-01-01", ["09:00", "09:01"], highs=[100, 93], closes=[100, 93]),  # -7% 발동
        _minute_hlc("2026-01-02", ["09:00"], highs=[80], closes=[80]),  # 새 날짜는 리셋
    ])

    for code, combined in [("A", a_combined), ("B", b_combined)]:
        csv_index = combined.index.copy()
        csv_index.name = "date"
        combined.set_axis(csv_index).to_csv(minute_dir / f"{code}.csv")

    expected = {
        "A": no_prior_drawdown_filter(a_combined, drawdown_threshold=0.05),
        "B": no_prior_drawdown_filter(b_combined, drawdown_threshold=0.05),
    }
    result = no_prior_drawdown_filter_batch_duckdb(str(tmp_path), drawdown_threshold=0.05)

    assert set(result.keys()) == {"A", "B"}
    for code in ("A", "B"):
        pd.testing.assert_series_equal(
            result[code], expected[code], check_names=False, check_freq=False
        )


def test_no_prior_drawdown_filter_resets_across_day_boundary():
    day1 = _minute_hlc("2026-01-01", ["09:00", "09:01"], highs=[100, 93], closes=[100, 93])  # -7% 발동
    day2 = _minute_hlc("2026-01-02", ["09:00"], highs=[80], closes=[80])  # day1 고점(100)보다 낮아도 새 날은 초기화
    combined = pd.concat([day1, day2])

    result = no_prior_drawdown_filter(combined, drawdown_threshold=0.05)

    assert list(result) == [True, False, True]


def test_compute_index_regime_by_day_ma_spans_day_boundary_and_flags_first_bar_per_day():
    # resample_minutes=1 -> _resample_minute이 사실상 그대로 반환(재표본화 no-op)해
    # 1분봉을 "재표본화된 봉"처럼 다루면서 핵심 로직(이평선 연속 계산, 날짜별 첫봉
    # 추출)만 검증한다. ma_period=2.
    day1 = _minute("2026-01-01", ["09:00", "09:01"], [100, 102])
    day2 = _minute("2026-01-02", ["09:00", "09:01"], [104, 90])
    day3 = _minute("2026-01-03", ["09:00", "09:01"], [80, 200])
    combined = pd.concat([day1, day2, day3])
    # 전체 종가: [100,102,104,90,80,200], rolling(2).mean(): [NaN,101,103,97,85,140]
    # above: [F, T, T, F, F, T] -> 날짜별 첫봉: day1(idx0)=F, day2(idx2)=T, day3(idx4)=F

    result = compute_index_regime_by_day(combined, ma_period=2, resample_minutes=1)

    assert result[pd.Timestamp("2026-01-01")] is False
    assert result[pd.Timestamp("2026-01-02")] is True
    assert result[pd.Timestamp("2026-01-03")] is False


def test_market_regime_filter_broadcasts_day_level_flag_to_all_minutes():
    minute = _minute("2026-01-02", ["09:00", "09:01", "10:00"], [100, 101, 102])
    regime_by_day = {pd.Timestamp("2026-01-02"): True, pd.Timestamp("2026-01-03"): False}

    result = market_regime_filter(minute, regime_by_day)

    assert list(result) == [True, True, True]


def test_market_regime_filter_defaults_false_for_unknown_day():
    minute = _minute("2026-01-05", ["09:00"], [100])

    result = market_regime_filter(minute, regime_by_day={})

    assert list(result) == [False]


def test_time_of_day_filter_selects_within_range():
    minute = _minute("2026-01-01", ["09:00", "11:00", "14:30"], [100, 101, 102])

    result = time_of_day_filter(minute, "10:30", "11:30")

    assert list(result) == [False, True, False]


def test_combine_and_requires_all_true():
    a = pd.Series([True, True, False])
    b = pd.Series([True, False, False])

    result = combine_and(a, b)

    assert list(result) == [True, False, False]
