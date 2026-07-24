import json
from datetime import datetime

import pytest

from backtesting import trading_value_ranking
from backtesting.trading_value_ranking import get_ranking, is_extended_hours

MONDAY_0830 = datetime(2026, 7, 20, 8, 30, 0)
MONDAY_0855 = datetime(2026, 7, 20, 8, 55, 0)
MONDAY_0900 = datetime(2026, 7, 20, 9, 0, 0)
MONDAY_1000 = datetime(2026, 7, 20, 10, 0, 0)  # 2026-07-20은 월요일
MONDAY_1300 = datetime(2026, 7, 20, 13, 0, 0)
MONDAY_1900 = datetime(2026, 7, 20, 19, 0, 0)
MONDAY_0700 = datetime(2026, 7, 20, 7, 0, 0)
MONDAY_2100 = datetime(2026, 7, 20, 21, 0, 0)
TUESDAY_1000 = datetime(2026, 7, 21, 10, 0, 0)
SATURDAY_1000 = datetime(2026, 7, 25, 10, 0, 0)


@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    trading_value_ranking._cache = {}
    trading_value_ranking._pre_market_snapshot = {}
    trading_value_ranking._pre_market_snapshot_date = None
    trading_value_ranking._baseline = None
    trading_value_ranking._baseline_date = None
    # 실제 프로젝트의 state/regular_session_baseline.json을 건드리지 않도록 임시 경로로 격리.
    monkeypatch.setattr(trading_value_ranking, "BASELINE_PATH", str(tmp_path / "regular_session_baseline.json"))
    yield
    trading_value_ranking._cache = {}
    trading_value_ranking._pre_market_snapshot = {}
    trading_value_ranking._pre_market_snapshot_date = None
    trading_value_ranking._baseline = None
    trading_value_ranking._baseline_date = None


def _row(code: str, name: str, rank: int, trading_value: int, volume: int = 1000, prev_day_volume: int = 1000) -> dict:
    return {
        "stock_code": code, "name": name, "rank": rank, "trading_value": trading_value,
        "change_rate": 0.0, "current_price": 10000.0, "change_amount": 0.0,
        "volume": volume, "prev_day_volume": prev_day_volume,
        "volume_vs_prev_day_pct": (volume / prev_day_volume * 100) if prev_day_volume else None,
    }


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


# ---- get_ranking (기본 동작 — extended 기준) ----

class _FakeDf:
    def __init__(self, records):
        self._records = records

    def to_dict(self, orient):
        assert orient == "records"
        return self._records


def test_get_ranking_raises_for_unknown_window():
    with pytest.raises(ValueError):
        get_ranking("key", "secret", True, "bogus")


def test_get_ranking_regular_window_active_during_market_hours(monkeypatch):
    rows = [_row("005930", "삼성전자", 1, 1000)]
    monkeypatch.setattr(trading_value_ranking, "top_by_trading_value", lambda client, top_n: _FakeDf(rows))

    result = get_ranking("key", "secret", True, "regular", now=MONDAY_1000)  # 10시 — 정규장 중

    assert result["active"] is True
    assert result["rows"][0]["stock_code"] == "005930"


def test_get_ranking_regular_window_frozen_after_market_close(monkeypatch):
    rows = [_row("005930", "삼성전자", 1, 1000)]
    monkeypatch.setattr(trading_value_ranking, "top_by_trading_value", lambda client, top_n: _FakeDf(rows))

    get_ranking("key", "secret", True, "regular", now=MONDAY_1000)  # 정규장 중에 한 번 채워둠
    result = get_ranking("key", "secret", True, "regular", now=MONDAY_1900)  # 19시 — 정규장 마감 후(애프터마켓)

    assert result["as_of"] == "10:00:00"  # 15:30 이전 마지막 스냅샷 그대로 — 애프터마켓 갱신 없음
    assert result["active"] is False


def test_get_ranking_inactive_outside_window_returns_empty_with_no_fetch(monkeypatch):
    calls = []
    monkeypatch.setattr(trading_value_ranking, "top_by_trading_value", lambda client, top_n: calls.append(1) or _FakeDf([]))

    result = get_ranking("key", "secret", True, "extended", now=MONDAY_2100)  # 확장시간 아님(21시)

    assert result == {"rows": [], "as_of": None, "active": False}
    assert calls == []


def test_get_ranking_active_fetches_and_caches(monkeypatch):
    rows = [_row("005930", "삼성전자", 1, 1000)]
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
    rows = [_row("005930", "삼성전자", 1, 1000)]
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
    rows = [_row("005930", "삼성전자", 1, 1000)]
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
    rows = [_row("005930", "삼성전자", 1, 1000)]
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


# ---- regular 창구의 장 시작 전 베이스라인 차감 로직 ----

def test_regular_window_subtracts_pre_market_baseline_from_trading_value(monkeypatch):
    calls = iter([
        [_row("005930", "삼성전자", 1, 5_000_000)],  # 08:55 장전시간외 스냅샷(베이스라인 후보)
        [_row("005930", "삼성전자", 1, 5_800_000, volume=5_000, prev_day_volume=10_000)],  # 10:00 누적치
    ])
    monkeypatch.setattr(trading_value_ranking, "top_by_trading_value", lambda client, top_n: _FakeDf(next(calls)))

    get_ranking("key", "secret", True, "extended", now=MONDAY_0855)  # 장전시간외 조회로 베이스라인 후보 확보
    result = get_ranking("key", "secret", True, "regular", now=MONDAY_1000)

    assert result["rows"][0]["trading_value"] == 800_000  # 5,800,000 - 5,000,000(베이스라인)


def test_regular_window_uses_zero_baseline_for_stock_not_seen_pre_market(monkeypatch):
    # 장전에 top_n 밖이었다가 장중에 처음 등장한 종목은 베이스라인이 없어 누적값 그대로 쓴다.
    monkeypatch.setattr(
        trading_value_ranking, "top_by_trading_value",
        lambda client, top_n: _FakeDf([_row("999999", "장중신규진입", 1, 3_000_000)]),
    )

    result = get_ranking("key", "secret", True, "regular", now=MONDAY_1000)

    assert result["rows"][0]["trading_value"] == 3_000_000


def test_regular_window_resorts_by_adjusted_trading_value(monkeypatch):
    # 원본(누적) 순위는 A > B지만, 장전 베이스라인을 빼면 B의 장중 순증가분이 더 커서
    # 순위가 뒤바뀌어야 한다.
    pre_market = [
        _row("AAA", "A종목", 1, 9_000_000),  # 장전에 이미 900만 누적 — 장중 증가분은 작을 것
        _row("BBB", "B종목", 2, 0),          # 장전엔 활동 없었음
    ]
    regular = [
        _row("AAA", "A종목", 1, 9_500_000),  # 누적 950만 — 장중 증가분 50만
        _row("BBB", "B종목", 2, 8_000_000),  # 누적 800만(전부 장중) — 장중 증가분 800만
    ]
    calls = iter([pre_market, regular])
    monkeypatch.setattr(trading_value_ranking, "top_by_trading_value", lambda client, top_n: _FakeDf(next(calls)))

    get_ranking("key", "secret", True, "extended", now=MONDAY_0855)
    result = get_ranking("key", "secret", True, "regular", now=MONDAY_1000)

    assert [r["stock_code"] for r in result["rows"]] == ["BBB", "AAA"]
    assert [r["rank"] for r in result["rows"]] == [1, 2]


def test_regular_window_recomputes_volume_vs_prev_day_pct_from_adjusted_volume(monkeypatch):
    calls = iter([
        [_row("005930", "삼성전자", 1, 1_000_000, volume=2_000, prev_day_volume=10_000)],
        [_row("005930", "삼성전자", 1, 1_500_000, volume=6_000, prev_day_volume=10_000)],
    ])
    monkeypatch.setattr(trading_value_ranking, "top_by_trading_value", lambda client, top_n: _FakeDf(next(calls)))

    get_ranking("key", "secret", True, "extended", now=MONDAY_0855)
    result = get_ranking("key", "secret", True, "regular", now=MONDAY_1000)

    assert result["rows"][0]["volume"] == 4_000  # 6,000 - 2,000
    assert result["rows"][0]["volume_vs_prev_day_pct"] == pytest.approx(4_000 / 10_000 * 100)


def test_baseline_persists_across_process_restart(monkeypatch, tmp_path):
    # 대시보드가 장중에 재시작돼도(모듈 재로딩 = 메모리 상태 초기화) 그날 베이스라인을
    # 잃지 않아야 한다 — 파일에서 다시 읽어옴.
    baseline_path = str(tmp_path / "regular_session_baseline.json")
    monkeypatch.setattr(trading_value_ranking, "BASELINE_PATH", baseline_path)

    monkeypatch.setattr(
        trading_value_ranking, "top_by_trading_value",
        lambda client, top_n: _FakeDf([_row("005930", "삼성전자", 1, 5_000_000)]),
    )
    get_ranking("key", "secret", True, "extended", now=MONDAY_0855)
    get_ranking("key", "secret", True, "regular", now=MONDAY_0900)  # 09:00에 베이스라인 확정+저장

    assert json.loads(open(baseline_path, encoding="utf-8").read())["baseline"]["005930"]["trading_value"] == 5_000_000

    # "재시작" 시뮬레이션 — 메모리 상태만 초기화, 파일은 그대로 둠
    trading_value_ranking._baseline = None
    trading_value_ranking._baseline_date = None
    trading_value_ranking._pre_market_snapshot = {}
    trading_value_ranking._cache = {}

    monkeypatch.setattr(
        trading_value_ranking, "top_by_trading_value",
        lambda client, top_n: _FakeDf([_row("005930", "삼성전자", 1, 5_800_000)]),
    )
    result = get_ranking("key", "secret", True, "regular", now=MONDAY_1000)

    assert result["rows"][0]["trading_value"] == 800_000  # 재시작 후에도 파일에서 베이스라인을 복원


def test_baseline_resets_on_new_trading_day(monkeypatch):
    monkeypatch.setattr(
        trading_value_ranking, "top_by_trading_value",
        lambda client, top_n: _FakeDf([_row("005930", "삼성전자", 1, 5_000_000)]),
    )
    get_ranking("key", "secret", True, "extended", now=MONDAY_0855)
    get_ranking("key", "secret", True, "regular", now=MONDAY_1000)  # 월요일 베이스라인 확정(500만)

    # 화요일 — 장전 스냅샷 없이 바로 장중 조회(정확도 저하는 감수하되, 최소한 월요일
    # 베이스라인을 잘못 재사용하면 안 된다). 캐시는 실제 벽시계 기준 TTL이라 테스트
    # 안에서는 만료되지 않으므로, 하루가 지났다고 가정하고 강제로 만료시킨다.
    trading_value_ranking._cache["regular"]["fetched_at"] = 0.0
    monkeypatch.setattr(
        trading_value_ranking, "top_by_trading_value",
        lambda client, top_n: _FakeDf([_row("005930", "삼성전자", 1, 1_200_000)]),
    )
    result = get_ranking("key", "secret", True, "regular", now=TUESDAY_1000)

    assert result["rows"][0]["trading_value"] == 1_200_000  # 월요일 베이스라인(500만)을 안 빼씀


# ---- start_background_poller ----

def test_start_background_poller_repeatedly_queries_extended_window(monkeypatch):
    calls = []
    monkeypatch.setattr(
        trading_value_ranking, "get_ranking",
        lambda appkey, secretkey, is_mock, window: calls.append(window),
    )
    call_count = {"n": 0}

    def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 3:
            raise RuntimeError("테스트 종료를 위해 루프 탈출")

    monkeypatch.setattr(trading_value_ranking.time, "sleep", fake_sleep)

    thread = trading_value_ranking.start_background_poller("key", "secret", True, interval_seconds=0)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert calls == ["extended", "extended", "extended"]


def test_start_background_poller_survives_get_ranking_exception(monkeypatch):
    # 한 번 조회가 실패해도(네트워크 오류 등) 폴러 스레드 자체는 죽지 않고 다음 주기에
    # 계속 재시도해야 한다.
    calls = []

    def failing_get_ranking(appkey, secretkey, is_mock, window):
        calls.append(window)
        raise RuntimeError("일시적 API 오류")

    monkeypatch.setattr(trading_value_ranking, "get_ranking", failing_get_ranking)
    call_count = {"n": 0}

    def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise SystemExit("테스트 종료를 위해 루프 탈출")

    monkeypatch.setattr(trading_value_ranking.time, "sleep", fake_sleep)

    thread = trading_value_ranking.start_background_poller("key", "secret", True, interval_seconds=0)
    thread.join(timeout=2)

    assert len(calls) == 2  # 실패해도 계속 재시도됨(스레드가 안 죽음)
