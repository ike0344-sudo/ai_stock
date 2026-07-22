from datetime import date

import numpy as np
import pandas as pd

from backtesting.data_loader import (
    _clean_candles,
    _daily_pages_needed,
    _is_cache_valid,
    _load_local_series,
    _minute_pages_needed,
    _resample_minute,
    load_full_index_minute_history,
    load_full_minute_history,
    load_history,
    load_index_history,
)


def _df(dates: list[str]) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    return pd.DataFrame({"close": [100.0] * len(dates)}, index=index)


def test_cache_valid_when_range_fully_covered():
    cached = _df(["2026-01-01", "2026-01-10"])

    assert _is_cache_valid(cached, date(2026, 1, 2), date(2026, 1, 9)) is True


def test_cache_invalid_when_start_not_covered():
    cached = _df(["2026-01-05", "2026-01-10"])

    assert _is_cache_valid(cached, date(2026, 1, 1), date(2026, 1, 9)) is False


def test_cache_invalid_when_end_not_covered():
    cached = _df(["2026-01-01", "2026-01-05"])

    assert _is_cache_valid(cached, date(2026, 1, 1), date(2026, 1, 9)) is False


def test_cache_invalid_when_empty():
    empty = pd.DataFrame(columns=["close"])
    empty.index = pd.to_datetime([])

    assert _is_cache_valid(empty, date(2026, 1, 1), date(2026, 1, 9)) is False


def _ohlcv(rows: list[dict]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=index)


def test_clean_candles_drops_rows_with_missing_values():
    df = _ohlcv(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"open": np.nan, "high": 101, "low": 99, "close": 100, "volume": 1000},
        ]
    )

    cleaned = _clean_candles(df)

    assert len(cleaned) == 1


def test_clean_candles_drops_zero_volume_rows():
    df = _ohlcv(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 0},  # 거래정지 추정
        ]
    )

    cleaned = _clean_candles(df)

    assert len(cleaned) == 1


def test_clean_candles_drops_non_positive_close():
    df = _ohlcv(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"open": 0, "high": 0, "low": 0, "close": 0, "volume": 500},
        ]
    )

    cleaned = _clean_candles(df)

    assert len(cleaned) == 1


def test_minute_pages_needed_scales_with_date_range():
    short_range = _minute_pages_needed("5", date(2026, 1, 1), date(2026, 1, 10))
    long_range = _minute_pages_needed("5", date(2026, 1, 1), date(2026, 6, 1))

    assert long_range > short_range


def test_minute_pages_needed_shrinks_for_coarser_tic_scope():
    fine = _minute_pages_needed("1", date(2026, 1, 1), date(2026, 3, 1))
    coarse = _minute_pages_needed("60", date(2026, 1, 1), date(2026, 3, 1))

    assert fine > coarse


class _StubMinuteClient:
    def __init__(self, pages: list[dict]):
        self._pages = pages

    def get_minute_chart_pages(self, stock_code, tic_scope="1", max_pages=20):
        return self._pages


def test_load_history_merges_multiple_minute_pages():
    page1 = {
        "stk_min_pole_chart_qry": [
            {
                "cntr_tm": "20260102090500", "open_pric": "100", "high_pric": "101",
                "low_pric": "99", "cur_prc": "100", "trde_qty": "10",
            },
        ]
    }
    page2 = {
        "stk_min_pole_chart_qry": [
            {
                "cntr_tm": "20260101090500", "open_pric": "90", "high_pric": "91",
                "low_pric": "89", "cur_prc": "90", "trde_qty": "20",
            },
        ]
    }
    client = _StubMinuteClient([page1, page2])

    df = load_history(client, "005930", date(2026, 1, 1), date(2026, 1, 3), interval="5", use_cache=False)

    assert len(df) == 2
    assert df.index.is_monotonic_increasing


class _FlakyDailyClient:
    """처음 N번은 실패하다 이후 성공하는 클라이언트 (재시도 백오프 테스트용)."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    def get_daily_chart_pages(self, stock_code, base_date="", max_pages=10):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("429 Client Error")
        return [
            {
                "stk_dt_pole_chart_qry": [
                    {"dt": "20260101", "open_pric": "100", "high_pric": "101", "low_pric": "99", "cur_prc": "100", "trde_qty": "10"},
                ]
            }
        ]


def test_load_history_backs_off_between_retries(monkeypatch):
    """실제 429 레이트리밋을 겪은 뒤, 재시도 사이에 지연 없이 바로 재요청하면 다시
    걸리기 쉬워 백오프를 추가함. 대기 시간이 시도마다 늘어나는지 확인."""
    sleeps = []
    monkeypatch.setattr("backtesting.data_loader.time.sleep", lambda s: sleeps.append(s))

    client = _FlakyDailyClient(fail_times=2)

    df = load_history(client, "005930", date(2026, 1, 1), date(2026, 1, 1), use_cache=False)

    assert len(df) == 1
    assert sleeps == [1, 2]  # 2**0, 2**1 (마지막 성공 시도 전에는 대기 없음)


def test_load_history_does_not_sleep_after_final_failed_attempt(monkeypatch):
    sleeps = []
    monkeypatch.setattr("backtesting.data_loader.time.sleep", lambda s: sleeps.append(s))

    client = _FlakyDailyClient(fail_times=10)  # max_retries(3)보다 많이 실패

    try:
        load_history(client, "005930", date(2026, 1, 1), date(2026, 1, 1), use_cache=False, max_retries=3)
    except Exception:
        pass

    assert len(sleeps) == 2  # 시도 3번, 대기는 1·2번째 실패 후에만 (마지막 실패 후엔 없음)


def test_daily_pages_needed_scales_with_date_range():
    short_range = _daily_pages_needed(date(2026, 1, 1), date(2026, 6, 1))
    long_range = _daily_pages_needed(date(2020, 1, 1), date(2026, 1, 1))

    assert long_range > short_range


class _StubDailyPagesClient:
    def __init__(self, pages: list[dict]):
        self._pages = pages

    def get_daily_chart_pages(self, stock_code, base_date="", max_pages=10):
        return self._pages


def test_load_history_merges_multiple_daily_pages():
    page1 = {
        "stk_dt_pole_chart_qry": [
            {"dt": "20260302", "open_pric": "110", "high_pric": "111", "low_pric": "109", "cur_prc": "110", "trde_qty": "10"},
        ]
    }
    page2 = {
        "stk_dt_pole_chart_qry": [
            {"dt": "20260101", "open_pric": "100", "high_pric": "101", "low_pric": "99", "cur_prc": "100", "trde_qty": "20"},
        ]
    }
    client = _StubDailyPagesClient([page1, page2])

    df = load_history(client, "005930", date(2026, 1, 1), date(2026, 3, 2), use_cache=False)

    assert len(df) == 2
    assert df.index.is_monotonic_increasing


class _StubFullMinuteClient:
    def __init__(self, pages: list[dict]):
        self._pages = pages
        self.calls = 0

    def get_minute_chart_pages(self, stock_code, tic_scope="1", max_pages=20):
        self.calls += 1
        return self._pages


def test_load_full_minute_history_returns_all_available_pages(tmp_path, monkeypatch):
    monkeypatch.setattr("backtesting.data_loader.CACHE_DIR", str(tmp_path))
    page = {
        "stk_min_pole_chart_qry": [
            {
                "cntr_tm": "20260102090500", "open_pric": "100", "high_pric": "101",
                "low_pric": "99", "cur_prc": "100", "trde_qty": "10",
            },
        ]
    }
    client = _StubFullMinuteClient([page])

    df = load_full_minute_history(client, "005930", tic_scope="1", use_cache=False)

    assert len(df) == 1
    assert client.calls == 1


def test_load_full_minute_history_uses_cache_on_second_call(tmp_path, monkeypatch):
    monkeypatch.setattr("backtesting.data_loader.CACHE_DIR", str(tmp_path))
    page = {
        "stk_min_pole_chart_qry": [
            {
                "cntr_tm": "20260102090500", "open_pric": "100", "high_pric": "101",
                "low_pric": "99", "cur_prc": "100", "trde_qty": "10",
            },
        ]
    }
    client = _StubFullMinuteClient([page])

    load_full_minute_history(client, "005930", tic_scope="1", use_cache=True)
    load_full_minute_history(client, "005930", tic_scope="1", use_cache=True)

    assert client.calls == 1  # 두 번째 호출은 캐시에서 읽음


class _StubIndexClient:
    def __init__(self, daily_pages=None, minute_pages=None):
        self._daily_pages = daily_pages or []
        self._minute_pages = minute_pages or []
        self.daily_calls = []
        self.minute_calls = []

    def get_index_daily_chart_pages(self, index_code, base_date="", max_pages=10):
        self.daily_calls.append(index_code)
        return self._daily_pages

    def get_index_minute_chart_pages(self, index_code, tic_scope="1", max_pages=20):
        self.minute_calls.append((index_code, tic_scope))
        return self._minute_pages


def test_load_index_history_uses_index_daily_endpoint():
    page = {
        "inds_dt_pole_qry": [
            {"dt": "20260101", "open_pric": "2500", "high_pric": "2550", "low_pric": "2480", "cur_prc": "2520", "trde_qty": "100"},
        ]
    }
    client = _StubIndexClient(daily_pages=[page])

    df = load_index_history(client, "001", date(2026, 1, 1), date(2026, 1, 1), use_cache=False)

    assert len(df) == 1
    assert client.daily_calls == ["001"]


def test_load_index_history_uses_index_minute_endpoint_for_non_day_interval():
    page = {
        "inds_min_pole_qry": [
            {"cntr_tm": "20260101090000", "open_pric": "2500", "high_pric": "2550", "low_pric": "2480", "cur_prc": "2520", "trde_qty": "100"},
        ]
    }
    client = _StubIndexClient(minute_pages=[page])

    df = load_index_history(client, "101", date(2026, 1, 1), date(2026, 1, 1), interval="1", use_cache=False)

    assert len(df) == 1
    assert client.minute_calls == [("101", "1")]


def test_load_full_index_minute_history_returns_data(tmp_path, monkeypatch):
    monkeypatch.setattr("backtesting.data_loader.CACHE_DIR", str(tmp_path))
    page = {
        "inds_min_pole_qry": [
            {"cntr_tm": "20260101090000", "open_pric": "2500", "high_pric": "2550", "low_pric": "2480", "cur_prc": "2520", "trde_qty": "100"},
        ]
    }
    client = _StubIndexClient(minute_pages=[page])

    df = load_full_index_minute_history(client, "001", use_cache=False)

    assert len(df) == 1


def _minute_df(day: str, times: list[str], closes: list[float]) -> pd.DataFrame:
    index = pd.to_datetime([f"{day} {t}" for t in times])
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes], "low": [c - 1 for c in closes], "close": closes, "volume": [100] * len(closes)},
        index=index,
    )


def test_resample_minute_aggregates_ohlcv_correctly():
    one_min = _minute_df("2026-01-01", ["09:00", "09:01", "09:02", "09:03"], [100, 102, 98, 101])

    result = _resample_minute(one_min, target_minutes=2)

    first_bucket = result.iloc[0]
    assert first_bucket["open"] == 100  # 09:00의 open
    assert first_bucket["high"] == 103  # max(101,103)
    assert first_bucket["low"] == 99  # min(99,101)
    assert first_bucket["close"] == 102  # 09:01의 close
    assert first_bucket["volume"] == 200  # 100+100


def test_resample_minute_does_not_merge_across_trading_days():
    day1 = _minute_df("2026-01-01", ["15:29", "15:30"], [100, 101])
    day2 = _minute_df("2026-01-02", ["09:00", "09:01"], [200, 201])
    combined = pd.concat([day1, day2])

    result = _resample_minute(combined, target_minutes=5)

    # 5분 버킷에 전날 마감(15:29~15:30)과 다음날 시가(09:00~09:01)가 섞이면 안 됨
    assert result.index.normalize().nunique() == 2
    assert result.loc["2026-01-01":"2026-01-01", "close"].iloc[-1] == 101
    assert result.loc["2026-01-02":"2026-01-02", "open"].iloc[0] == 200


def test_resample_minute_returns_input_unchanged_for_target_of_one():
    one_min = _minute_df("2026-01-01", ["09:00", "09:01"], [100, 101])

    result = _resample_minute(one_min, target_minutes=1)

    assert result is one_min


def test_load_local_series_reads_daily_csv(tmp_path):
    daily_dir = tmp_path / "stocks" / "daily"
    daily_dir.mkdir(parents=True)
    _df(["2026-01-01", "2026-01-02"]).to_csv(daily_dir / "000660.csv")

    result = _load_local_series("000660", "day", str(tmp_path), "stocks")

    assert result is not None
    assert len(result) == 2


def test_load_local_series_returns_none_when_file_missing(tmp_path):
    result = _load_local_series("999999", "day", str(tmp_path), "stocks")

    assert result is None


def test_load_local_series_resamples_minute_csv_to_requested_interval(tmp_path):
    minute_dir = tmp_path / "stocks" / "minute"
    minute_dir.mkdir(parents=True)
    _minute_df("2026-01-01", ["09:00", "09:01", "09:02", "09:03"], [100, 102, 98, 101]).to_csv(minute_dir / "000660.csv")

    result = _load_local_series("000660", "5", str(tmp_path), "stocks")

    assert result is not None
    assert len(result) == 1  # 4분치 데이터가 5분봉 1개로


def test_load_history_uses_local_data_when_available_and_sufficient(tmp_path, monkeypatch):
    daily_dir = tmp_path / "stocks" / "daily"
    daily_dir.mkdir(parents=True)
    _df(["2026-01-01", "2026-01-05", "2026-01-10"]).to_csv(daily_dir / "000660.csv")

    def fail_if_called(*a, **k):
        raise AssertionError("로컬 데이터가 있는데 API를 호출하면 안 됨")

    client = type("C", (), {"get_daily_chart_pages": fail_if_called})()

    result = load_history(
        client, "000660", date(2026, 1, 2), date(2026, 1, 9),
        use_local_data=True, data_dir=str(tmp_path), use_cache=False,
    )

    assert len(result) > 0


def test_load_history_falls_back_to_api_when_local_data_insufficient(tmp_path):
    daily_dir = tmp_path / "stocks" / "daily"
    daily_dir.mkdir(parents=True)
    _df(["2026-01-01", "2026-01-05"]).to_csv(daily_dir / "000660.csv")  # 요청 구간을 못 채움

    client = _StubDailyPagesClient(
        [{"stk_dt_pole_chart_qry": [{"dt": "20260109", "open_pric": "100", "high_pric": "101", "low_pric": "99", "cur_prc": "100", "trde_qty": "10"}]}]
    )

    result = load_history(
        client, "000660", date(2026, 1, 1), date(2026, 1, 9),
        use_local_data=True, data_dir=str(tmp_path), use_cache=False,
    )

    assert len(result) == 1  # API 스텁 응답으로 대체됨


def test_load_history_ignores_local_data_by_default(tmp_path):
    """use_local_data 기본값은 False — 기존 호출부/테스트가 실제 data/ 폴더 존재에
    영향받지 않도록 보수적으로 유지 (opt-in 설계)."""
    daily_dir = tmp_path / "stocks" / "daily"
    daily_dir.mkdir(parents=True)
    _df(["2026-01-01", "2026-01-10"]).to_csv(daily_dir / "000660.csv")

    client = _StubDailyPagesClient(
        [{"stk_dt_pole_chart_qry": [{"dt": "20260105", "open_pric": "1", "high_pric": "1", "low_pric": "1", "cur_prc": "1", "trde_qty": "1"}]}]
    )

    result = load_history(client, "000660", date(2026, 1, 2), date(2026, 1, 9), use_cache=False)

    assert len(result) == 1  # 로컬 파일 무시하고 API 스텁 응답 사용


def test_load_index_history_uses_local_data_when_available(tmp_path):
    index_dir = tmp_path / "index" / "daily"
    index_dir.mkdir(parents=True)
    _df(["2026-01-01", "2026-01-05", "2026-01-10"]).to_csv(index_dir / "001.csv")

    def fail_if_called(*a, **k):
        raise AssertionError("로컬 데이터가 있는데 API를 호출하면 안 됨")

    client = type("C", (), {"get_index_daily_chart_pages": fail_if_called})()

    result = load_index_history(
        client, "001", date(2026, 1, 2), date(2026, 1, 9),
        use_local_data=True, data_dir=str(tmp_path), use_cache=False,
    )

    assert len(result) > 0
