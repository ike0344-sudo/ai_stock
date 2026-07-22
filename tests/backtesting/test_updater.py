from datetime import date, timedelta

import pandas as pd

from backtesting import updater


def _candles(dates: list[str], closes: list[float]) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * len(closes)},
        index=index,
    )


def test_update_daily_bootstraps_full_history_when_no_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "000660.csv"
    captured = {}

    def fake_load_history(client, code, start, end, interval, use_cache):
        captured["start"] = start
        return _candles(["2026-01-01"], [100])

    monkeypatch.setattr(updater, "load_history", fake_load_history)

    result = updater.update_daily(client=object(), stock_code="000660", path=str(path), years_if_new=5)

    assert len(result) == 1
    assert path.exists()
    assert (date.today() - captured["start"]).days > 4 * 365  # 신규 종목은 ~5년 전부터


def test_update_daily_fetches_only_since_last_stored_date_when_file_exists(tmp_path, monkeypatch):
    path = tmp_path / "000660.csv"
    _candles(["2026-01-01", "2026-01-02"], [100, 101]).to_csv(path)
    captured = {}

    def fake_load_history(client, code, start, end, interval, use_cache):
        captured["start"] = start
        return _candles(["2026-01-08"], [105])

    monkeypatch.setattr(updater, "load_history", fake_load_history)

    updater.update_daily(client=object(), stock_code="000660", path=str(path), overlap_days=5)

    assert captured["start"] == date(2026, 1, 2) - timedelta(days=5)


def test_update_daily_merges_and_overwrites_overlapping_dates(tmp_path, monkeypatch):
    """겹치는 날짜는 새로 받은 값으로 갱신되어야 한다 (정정된 시세 반영)."""
    path = tmp_path / "000660.csv"
    _candles(["2026-01-01", "2026-01-02"], [100, 101]).to_csv(path)

    monkeypatch.setattr(
        updater, "load_history",
        lambda client, code, start, end, interval, use_cache: _candles(["2026-01-02", "2026-01-03"], [999, 102]),
    )

    result = updater.update_daily(client=object(), stock_code="000660", path=str(path))

    assert len(result) == 3  # 01-01, 01-02(갱신), 01-03
    assert result.loc["2026-01-02", "close"] == 999
    assert result.loc["2026-01-01", "close"] == 100


def test_update_minute_bootstraps_full_history_when_no_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "000660.csv"
    calls = []

    monkeypatch.setattr(
        updater, "load_full_minute_history",
        lambda client, code, tic_scope, use_cache: calls.append("full") or _candles(["2026-01-01"], [100]),
    )
    monkeypatch.setattr(
        updater, "load_history",
        lambda *a, **k: calls.append("ranged") or _candles(["2026-01-01"], [100]),
    )

    updater.update_minute(client=object(), stock_code="000660", path=str(path))

    assert calls == ["full"]


def test_update_minute_uses_ranged_fetch_when_file_exists(tmp_path, monkeypatch):
    path = tmp_path / "000660.csv"
    _candles(["2026-01-01 09:00", "2026-01-01 09:01"], [100, 101]).to_csv(path)
    calls = []

    monkeypatch.setattr(
        updater, "load_full_minute_history",
        lambda client, code, tic_scope, use_cache: calls.append("full") or pd.DataFrame(),
    )
    monkeypatch.setattr(
        updater, "load_history",
        lambda client, code, start, end, interval, use_cache: calls.append("ranged") or _candles(["2026-01-02 09:00"], [102]),
    )

    updater.update_minute(client=object(), stock_code="000660", path=str(path))

    assert calls == ["ranged"]


def test_update_top35_writes_per_stock_files_and_returns_summary(tmp_path, monkeypatch):
    ranking = pd.DataFrame(
        [
            {"stock_code": "000660", "name": "SK하이닉스", "rank": 1, "trading_value": 100},
            {"stock_code": "005930", "name": "삼성전자", "rank": 2, "trading_value": 90},
        ]
    )
    monkeypatch.setattr(updater, "top_by_trading_value", lambda client, top_n, market: ranking)
    monkeypatch.setattr(updater, "load_history", lambda client, code, start, end, interval, use_cache: _candles(["2026-01-01"], [100]))
    monkeypatch.setattr(updater, "load_full_minute_history", lambda client, code, tic_scope, use_cache: _candles(["2026-01-01"], [100]))

    summary = updater.update_top35(client=object(), data_dir=str(tmp_path))

    assert len(summary) == 2
    assert set(summary["status"]) == {"ok"}
    assert (tmp_path / "stocks" / "daily" / "000660.csv").exists()
    assert (tmp_path / "stocks" / "minute" / "005930.csv").exists()


def test_update_top35_continues_after_per_stock_failure(monkeypatch, tmp_path):
    ranking = pd.DataFrame(
        [
            {"stock_code": "000660", "name": "SK하이닉스", "rank": 1, "trading_value": 100},
            {"stock_code": "005930", "name": "삼성전자", "rank": 2, "trading_value": 90},
        ]
    )
    monkeypatch.setattr(updater, "top_by_trading_value", lambda client, top_n, market: ranking)

    def flaky_load_history(client, code, start, end, interval, use_cache):
        if code == "000660":
            raise RuntimeError("API error")
        return _candles(["2026-01-01"], [100])

    monkeypatch.setattr(updater, "load_history", flaky_load_history)
    monkeypatch.setattr(updater, "load_full_minute_history", lambda client, code, tic_scope, use_cache: _candles(["2026-01-01"], [100]))

    summary = updater.update_top35(client=object(), data_dir=str(tmp_path))

    statuses = dict(zip(summary["stock_code"], summary["status"]))
    assert statuses["000660"] != "ok"
    assert statuses["005930"] == "ok"


def test_update_top35_calls_on_progress_after_each_stock_including_failures(monkeypatch, tmp_path):
    ranking = pd.DataFrame(
        [
            {"stock_code": "000660", "name": "SK하이닉스", "rank": 1, "trading_value": 100},
            {"stock_code": "005930", "name": "삼성전자", "rank": 2, "trading_value": 90},
        ]
    )
    monkeypatch.setattr(updater, "top_by_trading_value", lambda client, top_n, market: ranking)

    def flaky_load_history(client, code, start, end, interval, use_cache):
        if code == "000660":
            raise RuntimeError("API error")
        return _candles(["2026-01-01"], [100])

    monkeypatch.setattr(updater, "load_history", flaky_load_history)
    monkeypatch.setattr(updater, "load_full_minute_history", lambda client, code, tic_scope, use_cache: _candles(["2026-01-01"], [100]))

    progress_calls = []
    updater.update_top35(client=object(), data_dir=str(tmp_path), on_progress=lambda processed, total, code: progress_calls.append((processed, total, code)))

    # 실패한 종목도 진행률에는 포함되어야 함(카운트가 멈추지 않도록)
    assert progress_calls == [(1, 2, "000660"), (2, 2, "005930")]


def test_update_top35_works_without_on_progress_argument(monkeypatch, tmp_path):
    """하위호환: on_progress를 넘기지 않는 기존 CLI(update-top35) 호출부가 그대로 동작해야 함."""
    ranking = pd.DataFrame([{"stock_code": "000660", "name": "SK하이닉스", "rank": 1, "trading_value": 100}])
    monkeypatch.setattr(updater, "top_by_trading_value", lambda client, top_n, market: ranking)
    monkeypatch.setattr(updater, "load_history", lambda client, code, start, end, interval, use_cache: _candles(["2026-01-01"], [100]))
    monkeypatch.setattr(updater, "load_full_minute_history", lambda client, code, tic_scope, use_cache: _candles(["2026-01-01"], [100]))

    summary = updater.update_top35(client=object(), data_dir=str(tmp_path))

    assert len(summary) == 1
