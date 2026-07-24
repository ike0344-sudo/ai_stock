import pytest

from backtesting import market_snapshot
from backtesting.market_snapshot import (
    _kiwoom_index_snapshot,
    _nasdaq_snapshot,
    fetch_nasdaq_futures_snapshot,
    get_market_snapshot,
)


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


def _yahoo_payload(price: float, closes: list[float] | None = None) -> dict:
    """실제 Yahoo 차트 API 응답 형태 — meta.regularMarketPrice(최신가) +
    indicators.quote[0].close(일별 종가 배열, 오래된 순). 전일종가는 배열의 뒤에서
    두 번째 값(closes[-2])을 쓴다 — meta.chartPreviousClose는 NQ=F(선물) 조회에서
    신뢰할 수 없는 것으로 확인돼(실측: 조회 범위 첫날 종가를 가리킴) 쓰지 않는다."""
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price}, "indicators": {"quote": [{"close": closes or []}]}}]}}


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

def test_nasdaq_snapshot_computes_change_pct_from_second_to_last_close(monkeypatch):
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18200.0, closes=[17500.0, 18000.0, 18200.0])),
    )

    snapshot = _nasdaq_snapshot()

    assert snapshot["value"] == 18200.0
    assert snapshot["change_pct"] == pytest.approx((18200.0 - 18000.0) / 18000.0 * 100)


def test_nasdaq_snapshot_ignores_stale_first_bar_in_range(monkeypatch):
    # 실측 버그 재현: NQ=F 5일 조회에서 close 배열의 마지막 값이 오늘(regularMarketPrice와
    # 일치), 뒤에서 두 번째가 진짜 전일종가다. 배열 맨 앞(4세션 전) 값을 잘못 전일종가로
    # 쓰면 실제로는 하락인데 상승(+1.5%)으로 표시되는 문제가 있었다.
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(
            _yahoo_payload(29209.75, closes=[28773.25, 28778.75, 29316.0, 29209.75])
        ),
    )

    snapshot = _nasdaq_snapshot()

    assert snapshot["value"] == 29209.75
    assert snapshot["change_pct"] == pytest.approx((29209.75 - 29316.0) / 29316.0 * 100)
    assert snapshot["change_pct"] < 0  # 실제로는 하락 중이어야 함


def test_nasdaq_snapshot_skips_null_gap_in_close_array(monkeypatch):
    # 실측 버그 재현: close 배열 중간에 None이 섞여 나오는 날이 있다
    # (예: [28773.25, 28778.75, 29316.0, None, 29105.75]) — 그대로 뒤에서 두 번째를
    # 쓰면 None이 걸려 change_pct가 null이 돼버린다. None을 걸러낸 뒤 다시 뒤에서
    # 두 번째를 골라야 한다.
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(
            _yahoo_payload(29105.75, closes=[28773.25, 28778.75, 29316.0, None, 29105.75])
        ),
    )

    snapshot = _nasdaq_snapshot()

    assert snapshot["value"] == 29105.75
    assert snapshot["change_pct"] == pytest.approx((29105.75 - 29316.0) / 29316.0 * 100)


def test_nasdaq_snapshot_returns_none_change_pct_with_insufficient_history(monkeypatch):
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18200.0, closes=[18200.0])),
    )

    snapshot = _nasdaq_snapshot()

    assert snapshot["value"] == 18200.0
    assert snapshot["change_pct"] is None


def test_nasdaq_snapshot_returns_none_when_request_fails(monkeypatch):
    def raise_error(url, headers=None, timeout=10):
        raise RuntimeError("network down")

    monkeypatch.setattr(market_snapshot.requests, "get", raise_error)

    assert _nasdaq_snapshot() is None


# ---- fetch_nasdaq_futures_snapshot (공개 래퍼) ----

def test_fetch_nasdaq_futures_snapshot_delegates_to_nasdaq_snapshot(monkeypatch):
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18200.0, closes=[18000.0, 18200.0])),
    )

    snapshot = fetch_nasdaq_futures_snapshot()

    assert snapshot["value"] == 18200.0


# ---- get_market_snapshot ----

def test_get_market_snapshot_combines_all_three_sources(monkeypatch):
    fake_client = _FakeClient(_daily_records([("20260720", 2600.0), ("20260721", 2650.0)]))
    monkeypatch.setattr(market_snapshot, "get_client", lambda appkey, secretkey, is_mock: fake_client)
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18200.0, closes=[17800.0, 18000.0, 18200.0])),
    )

    snapshot = get_market_snapshot("appkey", "secretkey", True)

    assert snapshot["kospi"]["value"] == 2650.0
    assert snapshot["kosdaq"]["value"] == 2650.0
    assert snapshot["nasdaq"]["value"] == 18200.0
    assert fake_client.calls == ["001", "101"]


def test_get_market_snapshot_skips_kiwoom_when_credentials_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(market_snapshot, "get_client", lambda *a, **k: calls.append(1) or _FakeClient())
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18200.0, closes=[18200.0])),
    )

    snapshot = get_market_snapshot("", "", True)

    assert snapshot["kospi"] is None
    assert snapshot["kosdaq"] is None
    assert snapshot["nasdaq"]["value"] == 18200.0
    assert calls == []


def test_get_market_snapshot_keeps_previous_index_when_refetch_fails(monkeypatch):
    # 장 마감 직후처럼 코스피/코스닥 조회가 일시적으로 실패해도, 티커가 바로 "-"로
    # 사라지지 않고 직전 성공값을 그대로 보여줘야 한다(나스닥은 이번 조회도 성공하므로
    # 새 값으로 갱신됨).
    good_client = _FakeClient(_daily_records([("20260720", 2600.0), ("20260721", 2650.0)]))
    monkeypatch.setattr(market_snapshot, "get_client", lambda appkey, secretkey, is_mock: good_client)
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18200.0, closes=[17800.0, 18000.0, 18200.0])),
    )
    first = get_market_snapshot("appkey", "secretkey", True)
    market_snapshot._cached_at = 0.0  # TTL 강제 만료

    failing_client = _FakeClient(error=RuntimeError("일시적 오류"))
    monkeypatch.setattr(market_snapshot, "get_client", lambda appkey, secretkey, is_mock: failing_client)
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18500.0, closes=[18000.0, 18200.0, 18500.0])),
    )

    second = get_market_snapshot("appkey", "secretkey", True)

    assert second["kospi"] == first["kospi"]  # 실패한 지수는 직전 값 유지
    assert second["kosdaq"] == first["kosdaq"]
    assert second["nasdaq"]["value"] == 18500.0  # 성공한 소스는 새 값으로 갱신


def test_get_market_snapshot_uses_cache_within_ttl(monkeypatch):
    fake_client = _FakeClient(_daily_records([("20260720", 2600.0), ("20260721", 2650.0)]))
    monkeypatch.setattr(market_snapshot, "get_client", lambda appkey, secretkey, is_mock: fake_client)
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18200.0, closes=[18200.0])),
    )

    first = get_market_snapshot("appkey", "secretkey", True)
    second = get_market_snapshot("appkey", "secretkey", True)

    assert first is second
    assert fake_client.calls == ["001", "101"]  # 두 번째 호출은 캐시로 응답, 재조회 없음
