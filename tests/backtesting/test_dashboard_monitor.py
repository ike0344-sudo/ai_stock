from backtesting import dashboard_monitor
from backtesting.dashboard_monitor import check_dashboard_health, run_dashboard_monitor_loop


class _StubResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code


# ---- check_dashboard_health ----

def test_check_dashboard_health_returns_true_on_200(monkeypatch):
    monkeypatch.setattr(dashboard_monitor.requests, "get", lambda url, timeout: _StubResponse(200))

    ok, reason = check_dashboard_health("http://127.0.0.1:8765/")

    assert ok is True
    assert reason == ""


def test_check_dashboard_health_returns_false_on_server_error_status(monkeypatch):
    monkeypatch.setattr(dashboard_monitor.requests, "get", lambda url, timeout: _StubResponse(500))

    ok, reason = check_dashboard_health("http://127.0.0.1:8765/")

    assert ok is False
    assert "500" in reason


def test_check_dashboard_health_returns_false_on_connection_error(monkeypatch):
    def raise_error(url, timeout):
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(dashboard_monitor.requests, "get", raise_error)

    ok, reason = check_dashboard_health("http://127.0.0.1:8765/")

    assert ok is False
    assert "Connection refused" in reason


# ---- run_dashboard_monitor_loop ----

def test_run_dashboard_monitor_loop_notifies_once_on_down_and_does_not_repeat(monkeypatch, tmp_path):
    results = iter([(True, ""), (False, "Connection refused"), (False, "Connection refused")])
    monkeypatch.setattr(dashboard_monitor, "check_dashboard_health", lambda url: next(results))

    notified_down = []
    monkeypatch.setattr(dashboard_monitor, "notify_dashboard_down", lambda reason, bot_token, chat_id: notified_down.append(reason))
    notified_recovered = []
    monkeypatch.setattr(dashboard_monitor, "notify_dashboard_recovered", lambda bot_token, chat_id: notified_recovered.append(1))

    stop_flag_path = str(tmp_path / "stop_requested.json")
    call_count = {"n": 0}
    from backtesting.stop_control import request_stop

    def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 3:  # 3개 결과를 전부 소비한 뒤 종료
            request_stop(stop_flag_path)

    monkeypatch.setattr(dashboard_monitor.time, "sleep", fake_sleep)

    run_dashboard_monitor_loop(
        "TOKEN", "CHAT", poll_interval_seconds=0,
        state_dir=str(tmp_path / "state"), stop_flag_path=stop_flag_path,
    )

    assert notified_down == ["Connection refused"]  # 다운 전이 시점에만 1번
    assert notified_recovered == []


def test_run_dashboard_monitor_loop_notifies_recovery_after_down(monkeypatch, tmp_path):
    results = iter([(True, ""), (False, "timeout"), (True, "")])
    monkeypatch.setattr(dashboard_monitor, "check_dashboard_health", lambda url: next(results))

    notified_down = []
    monkeypatch.setattr(dashboard_monitor, "notify_dashboard_down", lambda reason, bot_token, chat_id: notified_down.append(reason))
    notified_recovered = []
    monkeypatch.setattr(dashboard_monitor, "notify_dashboard_recovered", lambda bot_token, chat_id: notified_recovered.append(1))

    stop_flag_path = str(tmp_path / "stop_requested.json")
    call_count = {"n": 0}
    from backtesting.stop_control import request_stop

    def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 3:
            request_stop(stop_flag_path)

    monkeypatch.setattr(dashboard_monitor.time, "sleep", fake_sleep)

    run_dashboard_monitor_loop(
        "TOKEN", "CHAT", poll_interval_seconds=0,
        state_dir=str(tmp_path / "state"), stop_flag_path=stop_flag_path,
    )

    assert notified_down == ["timeout"]
    assert notified_recovered == [1]


def test_run_dashboard_monitor_loop_writes_heartbeat_before_first_cycle(monkeypatch, tmp_path):
    from backtesting.heartbeat import read_heartbeat_age_seconds

    monkeypatch.setattr(dashboard_monitor, "check_dashboard_health", lambda url: (True, ""))
    # clear_stop_flag가 루프 진입 전 항상 stop 파일을 지우므로, is_stop_requested 자체를
    # 패치해 사이클이 0번만 돌게 강제한다 — nasdaq_drop_monitor.py의 같은 테스트와 동일한 발상.
    monkeypatch.setattr(dashboard_monitor, "is_stop_requested", lambda path: True)

    state_dir = str(tmp_path / "state")
    run_dashboard_monitor_loop(
        "TOKEN", "CHAT", state_dir=state_dir, stop_flag_path=str(tmp_path / "stop_requested.json"),
    )

    age = read_heartbeat_age_seconds(state_dir)
    assert age is not None and age < 5


def test_run_dashboard_monitor_loop_survives_cycle_exception(monkeypatch, tmp_path, capsys):
    def raise_error(url):
        raise RuntimeError("boom")

    monkeypatch.setattr(dashboard_monitor, "check_dashboard_health", raise_error)

    stop_flag_path = str(tmp_path / "stop_requested.json")
    call_count = {"n": 0}
    from backtesting.stop_control import request_stop

    def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            request_stop(stop_flag_path)

    monkeypatch.setattr(dashboard_monitor.time, "sleep", fake_sleep)

    run_dashboard_monitor_loop(
        "TOKEN", "CHAT", poll_interval_seconds=0,
        state_dir=str(tmp_path / "state"), stop_flag_path=stop_flag_path,
    )  # 예외가 밖으로 전파되면 이 호출에서 테스트가 바로 실패한다

    assert "boom" in capsys.readouterr().out
