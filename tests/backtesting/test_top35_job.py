import threading
import time
from datetime import datetime

import pandas as pd
import pytest

from backtesting import top35_job
from backtesting.top35_job import _errored_recently, Top35JobState, _finished_successfully_today, _should_run_daily_update, get_status, start_job


@pytest.fixture(autouse=True)
def reset_job_state():
    top35_job._state = Top35JobState()
    yield
    top35_job._state = Top35JobState()


def _wait_until(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_start_job_from_idle_returns_true_and_sets_running(monkeypatch):
    release = threading.Event()

    def blocking_update_top35(client, data_dir, market, on_progress=None):
        release.wait(timeout=2.0)
        return pd.DataFrame([{"stock_code": "005930", "name": "삼성전자", "status": "ok"}])

    monkeypatch.setattr(top35_job, "update_top35", blocking_update_top35)

    started = start_job("key", "secret", True)

    assert started is True
    assert _wait_until(lambda: get_status()["status"] == "running")
    release.set()
    assert _wait_until(lambda: get_status()["status"] == "done")


def test_start_job_while_running_returns_false_and_does_not_restart(monkeypatch):
    release = threading.Event()
    call_count = []

    def blocking_update_top35(client, data_dir, market, on_progress=None):
        call_count.append(1)
        release.wait(timeout=2.0)
        return pd.DataFrame([{"stock_code": "005930", "name": "삼성전자", "status": "ok"}])

    monkeypatch.setattr(top35_job, "update_top35", blocking_update_top35)

    assert start_job("key", "secret", True) is True
    assert _wait_until(lambda: get_status()["status"] == "running")

    started_again = start_job("key", "secret", True)

    assert started_again is False
    assert len(call_count) == 1  # 두 번째 트리거는 실제로 실행되지 않음
    release.set()
    assert _wait_until(lambda: get_status()["status"] == "done")


def test_job_completes_with_correct_success_and_fail_counts(monkeypatch):
    summary = pd.DataFrame(
        [
            {"stock_code": "005930", "name": "삼성전자", "status": "ok"},
            {"stock_code": "000660", "name": "SK하이닉스", "status": "ok"},
            {"stock_code": "035420", "name": "NAVER", "status": "실패: API error"},
        ]
    )
    monkeypatch.setattr(top35_job, "update_top35", lambda client, data_dir, market, on_progress=None: summary)

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "done")
    status = get_status()
    assert status["success_count"] == 2
    assert status["fail_count"] == 1


def test_job_records_per_stock_results_on_completion(monkeypatch):
    summary = pd.DataFrame(
        [
            {"stock_code": "005930", "name": "삼성전자", "status": "ok"},
            {"stock_code": "035420", "name": "NAVER", "status": "실패: API error"},
        ]
    )
    monkeypatch.setattr(top35_job, "update_top35", lambda client, data_dir, market, on_progress=None: summary)

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "done")
    results = get_status()["results"]
    assert results == [
        {"stock_code": "005930", "name": "삼성전자", "status": "ok", "daily_range": "", "minute_range": ""},
        {"stock_code": "035420", "name": "NAVER", "status": "실패: API error", "daily_range": "", "minute_range": ""},
    ]


def test_job_results_empty_before_completion():
    assert get_status()["results"] == []


def test_job_records_error_status_when_update_top35_raises(monkeypatch):
    def failing_update_top35(client, data_dir, market, on_progress=None):
        raise RuntimeError("키움 API 오류")

    monkeypatch.setattr(top35_job, "update_top35", failing_update_top35)

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "error")
    status = get_status()
    assert "키움 API 오류" in status["error_message"]


def test_progress_callback_updates_state_while_running(monkeypatch):
    progress_seen = threading.Event()
    hold = threading.Event()

    def update_top35_with_progress(client, data_dir, market, on_progress=None):
        on_progress(1, 2, "005930")
        progress_seen.set()
        hold.wait(timeout=2.0)  # 메인 스레드가 중간 상태를 확인할 시간을 줌
        on_progress(2, 2, "000660")
        return pd.DataFrame([{"stock_code": "005930", "name": "삼성전자", "status": "ok"}, {"stock_code": "000660", "name": "SK하이닉스", "status": "ok"}])

    monkeypatch.setattr(top35_job, "update_top35", update_top35_with_progress)

    start_job("key", "secret", True)

    assert progress_seen.wait(timeout=2.0)
    status = get_status()
    assert status["processed"] == 1
    assert status["total"] == 2
    assert status["current_code"] == "005930"

    hold.set()
    assert _wait_until(lambda: get_status()["status"] == "done")


def test_should_run_daily_update_true_when_time_passed_and_not_run_today():
    now = datetime(2026, 7, 24, 15, 40)      # 금요일
    assert _should_run_daily_update(now, last_success_date=None, hour=15, minute=40) is True


def test_should_run_daily_update_false_before_scheduled_time():
    now = datetime(2026, 7, 24, 15, 39)
    assert _should_run_daily_update(now, last_success_date=None, hour=15, minute=40) is False


def test_should_run_daily_update_false_when_already_run_today():
    now = datetime(2026, 7, 24, 16, 0)
    assert _should_run_daily_update(now, last_success_date="2026-07-24", hour=15, minute=40) is False


def test_should_run_daily_update_true_on_new_day_even_if_run_yesterday():
    now = datetime(2026, 7, 27, 15, 40)      # 월요일
    assert _should_run_daily_update(now, last_success_date="2026-07-24", hour=15, minute=40) is True


# ---- _finished_successfully_today: 실패 시 같은 날 재시도가 필요한지 판단의 근거 ----

def test_finished_successfully_today_true_when_done_and_finished_today():
    status = {"status": "done", "finished_at": "2026-07-25T15:41:00"}
    assert _finished_successfully_today(status, "2026-07-25") is True


def test_finished_successfully_today_false_when_status_is_error():
    # 실패한 날은 "성공한 적 없음"으로 취급돼야 스케줄러가 같은 날 안에서 재시도한다.
    status = {"status": "error", "finished_at": "2026-07-25T15:41:00"}
    assert _finished_successfully_today(status, "2026-07-25") is False


def test_finished_successfully_today_false_when_done_status_is_from_a_previous_day():
    # 모듈 전역 상태라 어제 성공한 "done"이 오늘 아직 갱신 전까지 남아있을 수 있다 —
    # status만 보고 오늘도 성공한 것으로 착각하면 안 된다.
    status = {"status": "done", "finished_at": "2026-07-24T15:41:00"}
    assert _finished_successfully_today(status, "2026-07-25") is False


def test_finished_successfully_today_false_when_idle():
    status = {"status": "idle", "finished_at": None}
    assert _finished_successfully_today(status, "2026-07-25") is False


# ---- 실패 알림 ----

def _summary_with_one_failure():
    return pd.DataFrame([
        {"stock_code": "000660", "name": "SK하이닉스", "status": "ok"},
        {"stock_code": "005930", "name": "삼성전자", "status": "실패: DNS 해석 실패"},
    ])


@pytest.fixture
def notify_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(top35_job, "notify_top35_failed",
                        lambda *args: calls.append(args) or True)
    monkeypatch.setattr(top35_job, "_bot_token", "token")
    monkeypatch.setattr(top35_job, "_chat_id", "chat")
    return calls


def test_partial_failure_sends_telegram_alert(monkeypatch, notify_calls):
    # 일부 종목만 실패한 날은 status가 "done"이라 스케줄러가 재시도하지 않는다 —
    # 알림이 유일한 발견 수단이라 반드시 나가야 한다.
    monkeypatch.setattr(top35_job, "update_top35",
                        lambda client, data_dir, market, on_progress=None: _summary_with_one_failure())

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "done")
    assert _wait_until(lambda: len(notify_calls) == 1)
    fail_count, total, failures, bot_token, chat_id = notify_calls[0]
    assert (fail_count, total, bot_token, chat_id) == (1, 2, "token", "chat")
    assert failures[0][0] == "005930" and "DNS" in failures[0][2]


def test_all_ok_sends_nothing(monkeypatch, notify_calls):
    monkeypatch.setattr(top35_job, "update_top35",
                        lambda client, data_dir, market, on_progress=None:
                        pd.DataFrame([{"stock_code": "000660", "name": "SK하이닉스", "status": "ok"}]))

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "done")
    assert notify_calls == []


def test_job_exception_sends_alert(monkeypatch, notify_calls):
    def blow_up(client, data_dir, market, on_progress=None):
        raise RuntimeError("토큰 발급 실패")

    monkeypatch.setattr(top35_job, "update_top35", blow_up)

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "error")
    assert _wait_until(lambda: len(notify_calls) == 1)
    assert "토큰 발급 실패" in notify_calls[0][2][0][2]


def test_no_alert_without_recipient(monkeypatch):
    calls = []
    monkeypatch.setattr(top35_job, "notify_top35_failed", lambda *args: calls.append(args))
    monkeypatch.setattr(top35_job, "_bot_token", "")
    monkeypatch.setattr(top35_job, "_chat_id", "")
    monkeypatch.setattr(top35_job, "update_top35",
                        lambda client, data_dir, market, on_progress=None: _summary_with_one_failure())

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "done")
    assert calls == []


def test_주말에는_돌지_않는다():
    """토요일엔 장도 없고 키움은 점검 페이지(HTML)를 준다 — 2026-09-12 에 1분마다 실패 알림."""
    assert _should_run_daily_update(datetime(2026, 9, 12, 15, 40), None, 15, 40) is False   # 토
    assert _should_run_daily_update(datetime(2026, 9, 13, 15, 40), None, 15, 40) is False   # 일


def test_전체_실패_직후엔_바로_다시_돌지_않는다():
    now = datetime(2026, 9, 14, 15, 45)
    just = {"status": "error", "finished_at": datetime(2026, 9, 14, 15, 44).isoformat()}
    old = {"status": "error", "finished_at": datetime(2026, 9, 14, 15, 10).isoformat()}
    assert _errored_recently(just, now) is True
    assert _errored_recently(old, now) is False
    assert _errored_recently({"status": "done", "finished_at": now.isoformat()}, now) is False


def test_같은_실패는_하루_한_번만_알린다(monkeypatch, notify_calls):
    monkeypatch.setattr(top35_job, "_last_error_alert", ("", ""))

    def blow_up(client, data_dir, market, on_progress=None):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(top35_job, "update_top35", blow_up)
    for _ in range(3):
        start_job("key", "secret", True)
        assert _wait_until(lambda: get_status()["status"] == "error")
    assert len(notify_calls) == 1
    assert "HTML" in notify_calls[0][2][0][2]
