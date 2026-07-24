from types import SimpleNamespace

from backtesting import nasdaq_drop_monitor
from backtesting.nasdaq_drop_monitor import (
    compute_window_change_pct,
    fetch_combined_headlines,
    fetch_related_news_headlines,
    run_nasdaq_drop_monitor,
)


# ---- compute_window_change_pct ----

def test_compute_window_change_pct_returns_none_with_no_history():
    assert compute_window_change_pct([], now_ts=1000.0, window_seconds=180.0) is None


def test_compute_window_change_pct_returns_none_when_no_sample_old_enough():
    # 감시 시작 직후: 가장 오래된 샘플도 180초보다 최근이라 기준가로 쓸 수 없음
    history = [(900.0, 18000.0), (950.0, 17950.0)]
    assert compute_window_change_pct(history, now_ts=1000.0, window_seconds=180.0) is None


def test_compute_window_change_pct_uses_closest_baseline_at_or_before_cutoff():
    # cutoff = 1000 - 180 = 820. 820 이전 중 가장 최신 샘플(800, 18000)이 기준가.
    history = [(700.0, 17000.0), (800.0, 18000.0), (900.0, 17900.0), (1000.0, 17820.0)]

    change_pct = compute_window_change_pct(history, now_ts=1000.0, window_seconds=180.0)

    assert change_pct == (17820.0 - 18000.0) / 18000.0 * 100


def test_compute_window_change_pct_returns_none_when_baseline_price_is_zero():
    history = [(800.0, 0.0), (1000.0, 100.0)]
    assert compute_window_change_pct(history, now_ts=1000.0, window_seconds=180.0) is None


# ---- fetch_related_news_headlines ----

class _FakeRssResponse:
    def __init__(self, xml_bytes):
        self.content = xml_bytes

    def raise_for_status(self):
        pass


def _rss_xml(titles):
    items = "".join(f"<item><title>{t}</title></item>" for t in titles)
    return f"<rss><channel>{items}</channel></rss>".encode("utf-8")


def test_fetch_related_news_headlines_returns_titles_up_to_limit(monkeypatch):
    monkeypatch.setattr(
        nasdaq_drop_monitor.requests, "get",
        lambda url, headers=None, timeout=10: _FakeRssResponse(_rss_xml(["h1", "h2", "h3", "h4", "h5", "h6"])),
    )

    headlines = fetch_related_news_headlines(limit=5)

    assert headlines == ["h1", "h2", "h3", "h4", "h5"]


def test_fetch_related_news_headlines_returns_empty_list_on_request_failure(monkeypatch):
    def raise_error(url, headers=None, timeout=10):
        raise RuntimeError("network down")

    monkeypatch.setattr(nasdaq_drop_monitor.requests, "get", raise_error)

    assert fetch_related_news_headlines() == []


# ---- fetch_combined_headlines ----

def test_fetch_combined_headlines_puts_telegram_first_then_google_news(monkeypatch):
    monkeypatch.setattr(nasdaq_drop_monitor, "fetch_telegram_channel_posts", lambda channel: ["텔레그램1", "텔레그램2"])
    monkeypatch.setattr(nasdaq_drop_monitor, "fetch_related_news_headlines", lambda: ["구글뉴스1"])

    assert fetch_combined_headlines() == ["텔레그램1", "텔레그램2", "구글뉴스1"]


def test_fetch_combined_headlines_survives_one_source_failing(monkeypatch):
    monkeypatch.setattr(nasdaq_drop_monitor, "fetch_telegram_channel_posts", lambda channel: [])
    monkeypatch.setattr(nasdaq_drop_monitor, "fetch_related_news_headlines", lambda: ["구글뉴스1"])

    assert fetch_combined_headlines() == ["구글뉴스1"]


# ---- run_nasdaq_drop_monitor ----

def test_run_nasdaq_drop_monitor_notifies_once_on_drop_and_rearms_after_recovery(monkeypatch, tmp_path):
    # 시나리오: 18000 -> (3분 뒤 기준가 확보) -> -1.5% 급락 -> 알림 1회 -> 회복(-0.1%) ->
    # 다시 -1.2% 급락 -> 재무장 상태이므로 2번째 알림도 발생.
    prices = iter([18000.0, 18000.0, 17730.0, 17982.0, 17766.0])  # 마지막 둘: 회복, 재급락
    now_values = iter([0.0, 200.0, 400.0, 600.0, 800.0])

    monkeypatch.setattr(nasdaq_drop_monitor, "fetch_nasdaq_futures_snapshot", lambda: {"value": next(prices)})
    monkeypatch.setattr(nasdaq_drop_monitor, "_now", lambda: next(now_values))
    monkeypatch.setattr(nasdaq_drop_monitor, "fetch_combined_headlines", lambda: ["헤드라인"])

    notified = []
    monkeypatch.setattr(
        nasdaq_drop_monitor, "notify_nasdaq_drop",
        lambda change_pct, price, headlines, bot_token, chat_id: notified.append((change_pct, price)),
    )

    stop_flag_path = str(tmp_path / "stop_requested.json")
    call_count = {"n": 0}
    from backtesting.stop_control import request_stop

    def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 5:  # 5개 샘플을 전부 소비한 뒤 종료
            request_stop(stop_flag_path)

    monkeypatch.setattr(nasdaq_drop_monitor.time, "sleep", fake_sleep)

    run_nasdaq_drop_monitor(
        "TOKEN", "CHAT", poll_interval_seconds=0, window_seconds=180.0, threshold_pct=-1.0,
        state_dir=str(tmp_path / "state"), stop_flag_path=stop_flag_path,
    )

    assert len(notified) == 2
    assert notified[0][0] == (17730.0 - 18000.0) / 18000.0 * 100
    assert notified[1][0] == (17766.0 - 17982.0) / 17982.0 * 100


def test_run_nasdaq_drop_monitor_does_not_repeat_alert_while_still_dropped(monkeypatch, tmp_path):
    # 회복(REARM_THRESHOLD_PCT 이상) 없이 계속 -1% 밑에 머무르면(무장 해제 상태),
    # 다음 사이클에서도 다시 알리지 않는다.
    prices = iter([18000.0, 18000.0, 17730.0, 17700.0])
    now_values = iter([0.0, 200.0, 250.0, 300.0])

    monkeypatch.setattr(nasdaq_drop_monitor, "fetch_nasdaq_futures_snapshot", lambda: {"value": next(prices)})
    monkeypatch.setattr(nasdaq_drop_monitor, "_now", lambda: next(now_values))
    monkeypatch.setattr(nasdaq_drop_monitor, "fetch_combined_headlines", lambda: [])

    notified = []
    monkeypatch.setattr(
        nasdaq_drop_monitor, "notify_nasdaq_drop",
        lambda change_pct, price, headlines, bot_token, chat_id: notified.append(change_pct),
    )

    stop_flag_path = str(tmp_path / "stop_requested.json")
    call_count = {"n": 0}
    from backtesting.stop_control import request_stop

    def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 4:
            request_stop(stop_flag_path)

    monkeypatch.setattr(nasdaq_drop_monitor.time, "sleep", fake_sleep)

    run_nasdaq_drop_monitor(
        "TOKEN", "CHAT", poll_interval_seconds=0, window_seconds=180.0, threshold_pct=-1.0,
        state_dir=str(tmp_path / "state"), stop_flag_path=stop_flag_path,
    )

    assert len(notified) == 1  # 계속 하락 상태라 재알림 없음


def test_run_nasdaq_drop_monitor_writes_heartbeat_before_first_cycle(monkeypatch, tmp_path):
    from backtesting.heartbeat import read_heartbeat_age_seconds

    monkeypatch.setattr(nasdaq_drop_monitor, "fetch_nasdaq_futures_snapshot", lambda: None)
    monkeypatch.setattr(nasdaq_drop_monitor, "_now", lambda: 0.0)
    # clear_stop_flag가 루프 진입 전 항상 stop 파일을 지우므로, 파일 기반으로 미리
    # 중지를 걸어둘 수 없다 — is_stop_requested 자체를 패치해 사이클이 0번(진입 즉시
    # while 조건 실패)만 돌게 강제한다(다른 전략들의 "market_open을 False로 패치해
    # 0사이클 강제"와 같은 발상).
    monkeypatch.setattr(nasdaq_drop_monitor, "is_stop_requested", lambda path: True)

    state_dir = str(tmp_path / "state")
    run_nasdaq_drop_monitor("TOKEN", "CHAT", state_dir=state_dir, stop_flag_path=str(tmp_path / "stop_requested.json"))

    age = read_heartbeat_age_seconds(state_dir)
    assert age is not None and age < 5


def test_run_nasdaq_drop_monitor_skips_gracefully_when_snapshot_unavailable(monkeypatch, tmp_path):
    # market_snapshot이 None을 반환해도(네트워크 실패 등) 예외 없이 계속 폴링해야 함
    monkeypatch.setattr(nasdaq_drop_monitor, "fetch_nasdaq_futures_snapshot", lambda: None)
    monkeypatch.setattr(nasdaq_drop_monitor, "_now", lambda: 0.0)

    notified = []
    monkeypatch.setattr(
        nasdaq_drop_monitor, "notify_nasdaq_drop",
        lambda *a, **k: notified.append(1),
    )

    stop_flag_path = str(tmp_path / "stop_requested.json")
    call_count = {"n": 0}
    from backtesting.stop_control import request_stop

    def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            request_stop(stop_flag_path)

    monkeypatch.setattr(nasdaq_drop_monitor.time, "sleep", fake_sleep)

    run_nasdaq_drop_monitor(
        "TOKEN", "CHAT", state_dir=str(tmp_path / "state"), stop_flag_path=stop_flag_path,
    )

    assert notified == []
