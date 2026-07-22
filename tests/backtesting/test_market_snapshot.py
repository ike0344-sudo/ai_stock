import pytest

from backtesting import market_snapshot
from backtesting.market_snapshot import _kiwoom_index_snapshot, _nasdaq_snapshot, get_market_snapshot


@pytest.fixture(autouse=True)
def reset_snapshot_cache():
    market_snapshot._cached_snapshot = None
    market_snapshot._cached_at = 0.0
    yield
    market_snapshot._cached_snapshot = None
    market_snapshot._cached_at = 0.0


class _FakeClient:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error
        self.calls = []

    def get_index_daily_chart(self, index_code):
        self.calls.append(index_code)
        if self._error:
            raise self._error
        return self._payload


def _daily_records(rows):
    """[(date, close), ...] -> ka20006 응답 형태(list 필드에 담긴 레코드들)."""
    return {
        "list": [
            {
                "dt": date, "open_pric": str(close), "high_pric": str(close),
                "low_pric": str(close), "cur_prc": str(close), "trde_qty": "1000",
            }
            for date, close in rows
        ]
    }


class _FakeResponse:
    def __init__(self, json_data=None, status_error=None):
        self._json_data = json_data
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error:
            raise self._status_error

    def json(self):
        return self._json_data


def _yahoo_payload(price: float, previous_close: float | None):
    meta = {"regularMarketPrice": price}
    if previous_close is not None:
        meta["chartPreviousClose"] = previous_close
    return {"chart": {"result": [{"meta": meta}]}}


# ---- _kiwoom_index_snapshot ----

def test_kiwoom_index_snapshot_computes_change_pct_from_last_two_closes():
    client = _FakeClient(_daily_records([("20260720", 2600.0), ("20260721", 2650.0)]))

    snapshot = _kiwoom_index_snapshot(client, "001")

    assert snapshot["value"] == 2650.0
    assert snapshot["change_pct"] == pytest.approx((2650.0 - 2600.0) / 2600.0 * 100)


def test_kiwoom_index_snapshot_returns_none_change_pct_with_single_row():
    client = _FakeClient(_daily_records([("20260721", 2650.0)]))

    snapshot = _kiwoom_index_snapshot(client, "001")

    assert snapshot["value"] == 2650.0
    assert snapshot["change_pct"] is None


def test_kiwoom_index_snapshot_returns_none_when_client_raises():
    client = _FakeClient(error=RuntimeError("network down"))

    snapshot = _kiwoom_index_snapshot(client, "001")

    assert snapshot is None


# ---- _nasdaq_snapshot ----

def test_nasdaq_snapshot_computes_change_pct_from_yahoo_meta(monkeypatch):
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18200.0, 18000.0)),
    )

    snapshot = _nasdaq_snapshot()

    assert snapshot["value"] == 18200.0
    assert snapshot["change_pct"] == pytest.approx((18200.0 - 18000.0) / 18000.0 * 100)


def test_nasdaq_snapshot_returns_none_when_request_fails(monkeypatch):
    def raise_error(url, headers=None, timeout=10):
        raise RuntimeError("network down")

    monkeypatch.setattr(market_snapshot.requests, "get", raise_error)

    assert _nasdaq_snapshot() is None


# ---- get_market_snapshot ----

def test_get_market_snapshot_combines_all_three_sources(monkeypatch):
    fake_client = _FakeClient(_daily_records([("20260720", 2600.0), ("20260721", 2650.0)]))
    monkeypatch.setattr(market_snapshot, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18200.0, 18000.0)),
    )

    snapshot = get_market_snapshot("appkey", "secretkey", True)

    assert snapshot["kospi"]["value"] == 2650.0
    assert snapshot["kosdaq"]["value"] == 2650.0
    assert snapshot["nasdaq"]["value"] == 18200.0
    assert fake_client.calls == ["001", "101"]


def test_get_market_snapshot_skips_kiwoom_when_credentials_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(market_snapshot, "KiwoomClient", lambda *a, **k: calls.append(1) or _FakeClient())
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18200.0, None)),
    )

    snapshot = get_market_snapshot("", "", True)

    assert snapshot["kospi"] is None
    assert snapshot["kosdaq"] is None
    assert snapshot["nasdaq"]["value"] == 18200.0
    assert calls == []


def test_get_market_snapshot_uses_cache_within_ttl(monkeypatch):
    fake_client = _FakeClient(_daily_records([("20260720", 2600.0), ("20260721", 2650.0)]))
    monkeypatch.setattr(market_snapshot, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18200.0, None)),
    )

    first = get_market_snapshot("appkey", "secretkey", True)
    second = get_market_snapshot("appkey", "secretkey", True)

    assert first is second
    assert fake_client.calls == ["001", "101"]  # 두 번째 호출은 캐시로 응답, 재조회 없음
