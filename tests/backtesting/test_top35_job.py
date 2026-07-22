import threading
import time

import pandas as pd
import pytest

from backtesting import top35_job
from backtesting.top35_job import Top35JobState, get_status, start_job


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
        {"stock_code": "005930", "name": "삼성전자", "status": "ok"},
        {"stock_code": "035420", "name": "NAVER", "status": "실패: API error"},
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
