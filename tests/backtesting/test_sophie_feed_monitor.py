from datetime import datetime
from zoneinfo import ZoneInfo

from backtesting import sophie_feed_monitor
from backtesting.sophie_feed_monitor import (
    check_feed_health,
    count_ai_stock_instances,
    in_closing_auction,
    find_last_heartbeat,
    is_market_hours,
    run_sophie_feed_monitor_loop,
)

SEOUL = ZoneInfo("Asia/Seoul")


class _FakeProc:
    def __init__(self, pid, ppid, name):
        self.pid = pid
        self.info = {"pid": pid, "ppid": ppid, "name": name}


def _write_log(tmp_path, lines):
    path = tmp_path / "app.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


# ---- is_market_hours ----

def test_is_market_hours_true_during_weekday_session():
    assert is_market_hours(datetime(2026, 8, 31, 10, 0, tzinfo=SEOUL))  # 월요일


def test_is_market_hours_false_on_weekend():
    assert not is_market_hours(datetime(2026, 8, 30, 10, 0, tzinfo=SEOUL))  # 일요일


def test_is_market_hours_false_after_close():
    assert not is_market_hours(datetime(2026, 8, 31, 16, 0, tzinfo=SEOUL))


# ---- find_last_heartbeat ----

def test_find_last_heartbeat_parses_latest_tick_line(tmp_path):
    path = _write_log(tmp_path, [
        "2026-08-30 19:31:22,741 INFO    [engine] app.engine.runner: 가동 중 · 틱 10 · 종목 200 · 테마 23",
        "2026-08-30 19:31:52,751 INFO    [engine] app.engine.runner: 가동 중 · 틱 25 · 종목 200 · 테마 23",
    ])

    result = find_last_heartbeat(path)

    assert result is not None
    ts, tick = result
    assert tick == 25
    assert ts == datetime(2026, 8, 30, 19, 31, 52, tzinfo=SEOUL)


def test_find_last_heartbeat_none_when_file_missing(tmp_path):
    assert find_last_heartbeat(str(tmp_path / "no_such.log")) is None


def test_find_last_heartbeat_none_when_no_matching_line(tmp_path):
    path = _write_log(tmp_path, ["2026-08-30 19:31:22,741 INFO 아무 상관없는 줄"])
    assert find_last_heartbeat(path) is None


# ---- check_feed_health ----

def test_check_feed_health_unhealthy_when_log_missing_during_market_hours(tmp_path):
    now = datetime(2026, 8, 31, 10, 0, tzinfo=SEOUL)  # 월요일 장중

    ok, reason, tick, seen_at = check_feed_health(str(tmp_path / "missing.log"), None, None, now=now)

    assert ok is False
    assert "못 찾음" in reason


def test_check_feed_health_healthy_when_log_missing_outside_market_hours(tmp_path):
    """장외엔 앱이 꺼져 있는 게 정상 — 로그가 아예 없어도 이상 아님(2026-08-30 정정)."""
    now = datetime(2026, 8, 30, 19, 0, tzinfo=SEOUL)  # 일요일

    ok, reason, tick, seen_at = check_feed_health(str(tmp_path / "missing.log"), None, None, now=now)

    assert ok is True


def test_check_feed_health_unhealthy_when_heartbeat_stale_during_market_hours(tmp_path):
    path = _write_log(tmp_path, [
        "2026-08-31 10:00:00,000 INFO    [engine] app.engine.runner: 가동 중 · 틱 5 · 종목 200 · 테마 23",
    ])
    now = datetime(2026, 8, 31, 10, 10, 0, tzinfo=SEOUL)  # 10분 뒤, 장중 — LOG_STALE_SECONDS(180초) 초과

    ok, reason, tick, seen_at = check_feed_health(path, None, None, now=now)

    assert ok is False
    assert "안 찍힘" in reason


def test_check_feed_health_healthy_when_tick_increases(tmp_path):
    path = _write_log(tmp_path, [
        "2026-08-31 10:30:00,000 INFO    [engine] app.engine.runner: 가동 중 · 틱 100 · 종목 200 · 테마 23",
    ])
    now = datetime(2026, 8, 31, 10, 30, 5, tzinfo=SEOUL)  # 월요일 장중

    ok, reason, tick, seen_at = check_feed_health(path, prev_tick=50, prev_tick_seen_at=1.0, now=now)

    assert ok is True
    assert tick == 100
    assert seen_at != 1.0  # 틱이 늘었으니 seen_at 갱신됨


def test_check_feed_health_healthy_when_tick_flat_outside_market_hours(tmp_path):
    """장 마감 중엔 틱이 0에서 안 늘어도 정상 — 2026-08-30 실측(일요일 19시)과 같은 상황."""
    path = _write_log(tmp_path, [
        "2026-08-30 19:30:00,000 INFO    [engine] app.engine.runner: 가동 중 · 틱 0 · 종목 200 · 테마 23",
    ])
    now = datetime(2026, 8, 30, 19, 30, 5, tzinfo=SEOUL)  # 일요일

    ok, reason, tick, seen_at = check_feed_health(path, prev_tick=0, prev_tick_seen_at=0.0, now=now)

    assert ok is True


def test_check_feed_health_unhealthy_when_tick_stalls_during_market_hours(monkeypatch, tmp_path):
    path = _write_log(tmp_path, [
        "2026-08-31 10:00:00,000 INFO    [engine] app.engine.runner: 가동 중 · 틱 300 · 종목 200 · 테마 23",
    ])
    now = datetime(2026, 8, 31, 10, 0, 5, tzinfo=SEOUL)  # 월요일 장중

    monotonic_values = iter([1000.0])
    monkeypatch.setattr(sophie_feed_monitor.time, "monotonic", lambda: next(monotonic_values))

    # prev_tick_seen_at이 TICK_STALL_SECONDS(180초)보다 더 과거
    ok, reason, tick, seen_at = check_feed_health(path, prev_tick=300, prev_tick_seen_at=1000.0 - 200, now=now)

    assert ok is False
    assert "안 늚" in reason


# ---- run_sophie_feed_monitor_loop ----

def test_run_loop_notifies_once_on_down_and_recovery(monkeypatch, tmp_path):
    results = iter([
        (True, "", 1, 0.0),
        (False, "로그 정지", 1, 0.0),
        (True, "", 2, 1.0),
    ])
    monkeypatch.setattr(sophie_feed_monitor, "check_feed_health", lambda *a, **kw: next(results))
    monkeypatch.setattr(sophie_feed_monitor, "count_ai_stock_instances", lambda: 1)

    notified_down = []
    monkeypatch.setattr(sophie_feed_monitor, "notify_sophie_feed_down", lambda reason, bot_token, chat_id: notified_down.append(reason))
    notified_recovered = []
    monkeypatch.setattr(sophie_feed_monitor, "notify_sophie_feed_recovered", lambda bot_token, chat_id: notified_recovered.append(1))

    stop_flag_path = str(tmp_path / "stop_requested.json")
    call_count = {"n": 0}
    from backtesting.stop_control import request_stop

    def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 3:
            request_stop(stop_flag_path)

    monkeypatch.setattr(sophie_feed_monitor.time, "sleep", fake_sleep)

    run_sophie_feed_monitor_loop(
        "TOKEN", "CHAT", poll_interval_seconds=0,
        state_dir=str(tmp_path / "state"), stop_flag_path=stop_flag_path,
    )

    assert notified_down == ["로그 정지"]
    assert notified_recovered == [1]


def test_run_loop_writes_heartbeat_before_first_cycle(monkeypatch, tmp_path):
    from backtesting.heartbeat import read_heartbeat_age_seconds

    monkeypatch.setattr(sophie_feed_monitor, "check_feed_health", lambda *a, **kw: (True, "", 1, 0.0))
    monkeypatch.setattr(sophie_feed_monitor, "is_stop_requested", lambda path: True)

    state_dir = str(tmp_path / "state")
    run_sophie_feed_monitor_loop(
        "TOKEN", "CHAT", state_dir=state_dir, stop_flag_path=str(tmp_path / "stop_requested.json"),
    )

    age = read_heartbeat_age_seconds(state_dir)
    assert age is not None and age < 5


def test_run_loop_survives_cycle_exception(monkeypatch, tmp_path, capsys):
    def raise_error(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(sophie_feed_monitor, "check_feed_health", raise_error)

    stop_flag_path = str(tmp_path / "stop_requested.json")
    call_count = {"n": 0}
    from backtesting.stop_control import request_stop

    def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            request_stop(stop_flag_path)

    monkeypatch.setattr(sophie_feed_monitor.time, "sleep", fake_sleep)

    run_sophie_feed_monitor_loop(
        "TOKEN", "CHAT", poll_interval_seconds=0,
        state_dir=str(tmp_path / "state"), stop_flag_path=stop_flag_path,
    )  # 예외가 밖으로 전파되면 이 호출에서 테스트가 바로 실패한다

    assert "boom" in capsys.readouterr().out


# ---- count_ai_stock_instances ----

def test_count_ai_stock_instances_single_bootstrap_worker_pair_counts_as_one(monkeypatch):
    """PyInstaller onefile 정상 실행 1개 = 부모-자식 OS 프로세스 2개(2026-08-30 실측) —
    그냥 개수를 세면 2가 나와 오탐한다."""
    procs = [_FakeProc(100, 50, "ai_stock.exe"), _FakeProc(200, 100, "ai_stock.exe")]
    monkeypatch.setattr(sophie_feed_monitor.psutil, "process_iter", lambda attrs: iter(procs))

    assert count_ai_stock_instances() == 1


def test_count_ai_stock_instances_two_independent_launches_counts_as_two(monkeypatch):
    """2026-08-30 실측 사고 재현 — 73초 간격으로 뜬 두 인스턴스, 각자 부모-자식 쌍."""
    procs = [
        _FakeProc(100, 50, "ai_stock.exe"), _FakeProc(200, 100, "ai_stock.exe"),
        _FakeProc(300, 60, "ai_stock.exe"), _FakeProc(400, 300, "ai_stock.exe"),
    ]
    monkeypatch.setattr(sophie_feed_monitor.psutil, "process_iter", lambda attrs: iter(procs))

    assert count_ai_stock_instances() == 2


def test_count_ai_stock_instances_zero_when_not_running(monkeypatch):
    monkeypatch.setattr(sophie_feed_monitor.psutil, "process_iter", lambda attrs: iter([]))
    assert count_ai_stock_instances() == 0


def test_count_ai_stock_instances_ignores_other_process_names(monkeypatch):
    procs = [_FakeProc(1, 0, "python.exe"), _FakeProc(2, 0, "explorer.exe")]
    monkeypatch.setattr(sophie_feed_monitor.psutil, "process_iter", lambda attrs: iter(procs))
    assert count_ai_stock_instances() == 0


# ---- run_sophie_feed_monitor_loop — 중복 실행 알림 ----

def test_run_loop_notifies_duplicate_and_resolution(monkeypatch, tmp_path):
    monkeypatch.setattr(sophie_feed_monitor, "check_feed_health", lambda *a, **kw: (True, "", 1, 0.0))

    counts = iter([1, 2, 2, 1])  # 정상 -> 중복발생 -> 중복지속(재알림 없어야) -> 해소
    monkeypatch.setattr(sophie_feed_monitor, "count_ai_stock_instances", lambda: next(counts))

    notified_dup = []
    monkeypatch.setattr(sophie_feed_monitor, "notify_sophie_duplicate_process", lambda count, bot_token, chat_id: notified_dup.append(count))
    notified_resolved = []
    monkeypatch.setattr(sophie_feed_monitor, "notify_sophie_duplicate_resolved", lambda bot_token, chat_id: notified_resolved.append(1))

    stop_flag_path = str(tmp_path / "stop_requested.json")
    call_count = {"n": 0}
    from backtesting.stop_control import request_stop

    def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 4:
            request_stop(stop_flag_path)

    monkeypatch.setattr(sophie_feed_monitor.time, "sleep", fake_sleep)

    run_sophie_feed_monitor_loop(
        "TOKEN", "CHAT", poll_interval_seconds=0,
        state_dir=str(tmp_path / "state"), stop_flag_path=stop_flag_path,
    )

    assert notified_dup == [2]      # 전이 시점 1번만
    assert notified_resolved == [1]


def test_마감_동시호가에는_틱이_멎어도_정상(monkeypatch, tmp_path):
    """15:20~15:30 은 단일가라 체결이 없다 — 2026-09-10 에 틱 6,256,509 에서 10분 고정.
    180초 문턱을 매일 넘겨 거짓 경보가 나갔다."""
    path = _write_log(tmp_path, [
        "2026-09-10 15:26:11,291 INFO    [engine] app.engine.runner: 가동 중 · 틱 6256509 · 종목 200 · 테마 23",
    ])
    now = datetime(2026, 9, 10, 15, 26, 15, tzinfo=SEOUL)      # 목요일 마감 동시호가
    monkeypatch.setattr(sophie_feed_monitor.time, "monotonic", lambda: 2000.0)

    ok, reason, tick, seen_at = check_feed_health(
        path, prev_tick=6256509, prev_tick_seen_at=1000.0, now=now)   # 이미 1000초째 멈춤

    assert ok is True and reason == ""
    assert seen_at == 2000.0, "멈춘 시각을 밀어야 15:30 직전에 한 번 터지지 않는다"


def test_동시호가_직전은_그대로_판정한다(monkeypatch, tmp_path):
    """15:19 까지는 진짜 체결이 있어야 한다 — 구간을 넓게 잡으면 진짜 장애를 놓친다."""
    path = _write_log(tmp_path, [
        "2026-09-10 15:19:11,291 INFO    [engine] app.engine.runner: 가동 중 · 틱 6256509 · 종목 200 · 테마 23",
    ])
    now = datetime(2026, 9, 10, 15, 19, 15, tzinfo=SEOUL)
    monkeypatch.setattr(sophie_feed_monitor.time, "monotonic", lambda: 2000.0)

    ok, reason, _, _ = check_feed_health(
        path, prev_tick=6256509, prev_tick_seen_at=1000.0, now=now)

    assert ok is False and "안 늚" in reason


def test_in_closing_auction_경계():
    assert not in_closing_auction(datetime(2026, 9, 10, 15, 19, 59, tzinfo=SEOUL))
    assert in_closing_auction(datetime(2026, 9, 10, 15, 20, 0, tzinfo=SEOUL))
    assert in_closing_auction(datetime(2026, 9, 10, 15, 29, 59, tzinfo=SEOUL))
    assert not in_closing_auction(datetime(2026, 9, 10, 15, 30, 0, tzinfo=SEOUL))
