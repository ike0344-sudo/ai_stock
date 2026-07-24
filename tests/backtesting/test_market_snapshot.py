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


BASE_TS = 1_800_000_000  # 임의의 고정 기준시각(초) — 테스트끼리 겹치지만 무관


def _yahoo_payload(
    price: float, closes: list[float] | None = None, timestamps: list[int] | None = None, latest_ts: int | None = None
) -> dict:
    """실제 Yahoo 차트 API(15분봉) 응답 형태 — meta.regularMarketPrice(최신가) +
    meta.regularMarketTime(기준시각) + timestamp/indicators.quote[0].close(봉별
    시각·종가, 오래된 순). timestamps를 안 주면 closes를
    ROLLING_CHANGE_WINDOW_SECONDS(하루) 간격으로 오래된 순 등간격 배치한다 —
    이러면 closes[-2]가 정확히 "24시간 전" 자리에 와서, 그 값을 전일가로 기대하는
    단순 케이스들이 그대로 성립한다. 24시간 전 근방에 여러 봉을 촘촘히 배치하는
    시나리오(예: 특정 봉이 비는 경우)는 timestamps를 직접 넘겨 제어한다."""
    closes = closes or []
    if latest_ts is None:
        latest_ts = BASE_TS
    if timestamps is None:
        n = len(closes)
        window = market_snapshot.ROLLING_CHANGE_WINDOW_SECONDS
        timestamps = [latest_ts - (n - 1 - i) * window for i in range(n)]
    return {
        "chart": {
            "result": [
                {
                    "meta": {"regularMarketPrice": price, "regularMarketTime": latest_ts},
                    "timestamp": timestamps,
                    "indicators": {"quote": [{"close": closes}]},
                }
            ]
        }
    }


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

def test_nasdaq_snapshot_computes_change_pct_from_nearest_24h_ago_bar(monkeypatch):
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(_yahoo_payload(18200.0, closes=[17500.0, 18000.0, 18200.0])),
    )

    snapshot = _nasdaq_snapshot()

    assert snapshot["value"] == 18200.0
    assert snapshot["change_pct"] == pytest.approx((18200.0 - 18000.0) / 18000.0 * 100)


def test_nasdaq_snapshot_ignores_bars_further_than_24h_ago(monkeypatch):
    # 조회 범위(5일치)에 24시간 전보다 훨씬 오래된 봉들이 섞여 있어도, "24시간 전에
    # 가장 가까운" 봉(여기서는 뒤에서 두 번째, 29316.0)만 골라 써야 한다 — 더 먼
    # 과거 봉(28773.25 등)을 잘못 쓰면 실제로는 하락인데 상승으로 잘못 표시되는
    # 문제가 예전에 있었다.
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


def test_nasdaq_snapshot_falls_back_to_adjacent_bar_when_24h_ago_bar_is_missing(monkeypatch):
    # 실측 버그 재현: 일봉 기준으로는 "어제 종가" 자리가 통째로 None인 세션이 있어서,
    # None을 걸러내고 그다음(2세션 전)을 대신 쓰면 며칠치 변동이 하루치 등락률에 섞여
    # 실제(-0.04%~+0.07%, investing.com/Yahoo 웹페이지 실측 대조)와 동떨어진 큰
    # 값(-1.8%대)이 나왔다. 15분봉은 표본이 촘촘해서(하루 ~96개) 정확히 24시간 전
    # 봉 하나가 비어도 바로 옆(15분 오차) 봉을 대신 쓰면 되므로 오차가 미미하다.
    latest_ts = BASE_TS
    window = market_snapshot.ROLLING_CHANGE_WINDOW_SECONDS
    monkeypatch.setattr(
        market_snapshot.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(
            _yahoo_payload(
                100.0,
                closes=[99.0, None, 100.0],
                timestamps=[latest_ts - window - 900, latest_ts - window, latest_ts],
                latest_ts=latest_ts,
            )
        ),
    )

    snapshot = _nasdaq_snapshot()

    assert snapshot["value"] == 100.0
    assert snapshot["change_pct"] == pytest.approx((100.0 - 99.0) / 99.0 * 100)


def test_nasdaq_snapshot_returns_none_change_pct_when_no_bar_near_24h_ago(monkeypatch):
    # 조회 범위 안에 24시간 전 근방(±12시간) 봉이 아예 없으면(예: 응답에 딱 최신
    # 봉 하나만 온 경우) 억지로 먼 과거/거의 지금 시각 봉을 전일가로 쓰지 않고
    # change_pct를 None으로 반환해야 한다.
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
