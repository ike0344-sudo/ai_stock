from datetime import datetime

import pytest

from backtesting import trading_value_ranking
from backtesting.trading_value_ranking import get_ranking, is_extended_hours

MONDAY_1000 = datetime(2026, 7, 20, 10, 0, 0)  # 2026-07-20은 월요일
MONDAY_0830 = datetime(2026, 7, 20, 8, 30, 0)
MONDAY_1900 = datetime(2026, 7, 20, 19, 0, 0)
MONDAY_0700 = datetime(2026, 7, 20, 7, 0, 0)
MONDAY_2100 = datetime(2026, 7, 20, 21, 0, 0)
SATURDAY_1000 = datetime(2026, 7, 25, 10, 0, 0)


@pytest.fixture(autouse=True)
def reset_cache():
    trading_value_ranking._cache = {}
    yield
    trading_value_ranking._cache = {}


# ---- is_extended_hours ----

def test_is_extended_hours_true_within_08_to_20_on_weekday():
    assert is_extended_hours(MONDAY_0830) is True
    assert is_extended_hours(MONDAY_1000) is True
    assert is_extended_hours(MONDAY_1900) is True


def test_is_extended_hours_false_outside_08_to_20():
    assert is_extended_hours(MONDAY_0700) is False
    assert is_extended_hours(MONDAY_2100) is False


def test_is_extended_hours_false_on_weekend():
    assert is_extended_hours(SATURDAY_1000) is False


# ---- get_ranking ----

class _FakeDf:
    def __init__(self, records):
        self._records = records

    def to_dict(self, orient):
        assert orient == "records"
        return self._records


def test_get_ranking_raises_for_unknown_window():
    with pytest.raises(ValueError):
        get_ranking("key", "secret", True, "bogus")


def test_get_ranking_rejects_regular_window():
    # 정규장 전용 패널은 삭제됨 — extended만 유효한 window.
    with pytest.raises(ValueError):
        get_ranking("key", "secret", True, "regular", now=MONDAY_1000)


def test_get_ranking_inactive_outside_window_returns_empty_with_no_fetch(monkeypatch):
    calls = []
    monkeypatch.setattr(trading_value_ranking, "top_by_trading_value", lambda client, top_n: calls.append(1) or _FakeDf([]))

    result = get_ranking("key", "secret", True, "extended", now=MONDAY_2100)  # 확장시간 아님(21시)

    assert result == {"rows": [], "as_of": None, "active": False}
    assert calls == []


def test_get_ranking_active_fetches_and_caches(monkeypatch):
    rows = [{"stock_code": "005930", "name": "삼성전자", "rank": 1, "trading_value": 1000}]
    calls = []
    monkeypatch.setattr(
        trading_value_ranking, "top_by_trading_value",
        lambda client, top_n: calls.append(1) or _FakeDf(rows),
    )

    result = get_ranking("key", "secret", True, "extended", now=MONDAY_1000)

    assert result["rows"] == rows
    assert result["as_of"] == "10:00:00"
    assert result["active"] is True
    assert len(calls) == 1


def test_get_ranking_uses_cache_within_ttl(monkeypatch):
    rows = [{"stock_code": "005930", "name": "삼성전자", "rank": 1, "trading_value": 1000}]
    calls = []
    monkeypatch.setattr(
        trading_value_ranking, "top_by_trading_value",
        lambda client, top_n: calls.append(1) or _FakeDf(rows),
    )

    first = get_ranking("key", "secret", True, "extended", now=MONDAY_1000)
    second = get_ranking("key", "secret", True, "extended", now=MONDAY_1000)

    assert first == second
    assert len(calls) == 1  # 두 번째는 캐시로 응답, 재조회 없음


def test_get_ranking_inactive_but_cached_returns_last_snapshot(monkeypatch):
    rows = [{"stock_code": "005930", "name": "삼성전자", "rank": 1, "trading_value": 1000}]
    monkeypatch.setattr(trading_value_ranking, "top_by_trading_value", lambda client, top_n: _FakeDf(rows))

    get_ranking("key", "secret", True, "extended", now=MONDAY_1000)  # 활성 시간대에 한 번 채워둠
    result = get_ranking("key", "secret", True, "extended", now=MONDAY_2100)  # 비활성 시간대(21시)

    assert result["rows"] == rows
    assert result["as_of"] == "10:00:00"  # 마지막 조회 시각 그대로 — 새로 안 바뀜
    assert result["active"] is False


def test_get_ranking_skips_fetch_when_credentials_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(
        trading_value_ranking, "top_by_trading_value",
        lambda client, top_n: calls.append(1) or _FakeDf([]),
    )

    result = get_ranking("", "", True, "extended", now=MONDAY_1000)

    assert result == {"rows": [], "as_of": None, "active": True}
    assert calls == []


def test_get_ranking_keeps_previous_snapshot_when_refetch_fails(monkeypatch):
    rows = [{"stock_code": "005930", "name": "삼성전자", "rank": 1, "trading_value": 1000}]
    monkeypatch.setattr(trading_value_ranking, "top_by_trading_value", lambda client, top_n: _FakeDf(rows))
    get_ranking("key", "secret", True, "extended", now=MONDAY_1000)

    def failing(client, top_n):
        raise RuntimeError("API 오류")

    monkeypatch.setattr(trading_value_ranking, "top_by_trading_value", failing)
    # TTL을 강제로 만료시켜 재조회를 시도하게 함
    trading_value_ranking._cache["extended"]["fetched_at"] = 0.0

    result = get_ranking("key", "secret", True, "extended", now=MONDAY_1000)

    assert result["rows"] == rows  # 실패했지만 마지막 성공값 유지
    assert result["active"] is True
