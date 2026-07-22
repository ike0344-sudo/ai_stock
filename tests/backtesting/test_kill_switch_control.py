import json

from backtesting.kill_switch_control import (
    clear_kill_switch,
    get_override_status,
    is_kill_switch_requested,
    request_kill_switch,
)


def test_get_override_status_returns_safe_default_when_file_missing(tmp_path):
    path = str(tmp_path / "kill_switch_override.json")

    status = get_override_status(path)

    assert status == {"requested": False, "requested_at": None}


def test_is_kill_switch_requested_false_when_file_missing(tmp_path):
    path = str(tmp_path / "kill_switch_override.json")

    assert is_kill_switch_requested(path) is False


def test_is_kill_switch_requested_false_when_file_corrupted(tmp_path):
    path = tmp_path / "kill_switch_override.json"
    path.write_text('{"requested": tr', encoding="utf-8")  # 쓰다 만 상태

    assert is_kill_switch_requested(str(path)) is False


def test_request_kill_switch_sets_requested_true(tmp_path):
    path = str(tmp_path / "state" / "kill_switch_override.json")  # 하위 디렉터리 자동 생성 확인

    request_kill_switch(path)

    status = get_override_status(path)
    assert status["requested"] is True
    assert status["requested_at"] is not None
    assert is_kill_switch_requested(path) is True


def test_clear_kill_switch_sets_requested_false(tmp_path):
    path = str(tmp_path / "kill_switch_override.json")
    request_kill_switch(path)
    assert is_kill_switch_requested(path) is True

    clear_kill_switch(path)

    status = get_override_status(path)
    assert status["requested"] is False
    assert status["requested_at"] is None


def test_request_then_clear_round_trip_via_raw_file(tmp_path):
    path = tmp_path / "kill_switch_override.json"
    request_kill_switch(str(path))

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["requested"] is True

    clear_kill_switch(str(path))

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["requested"] is False
