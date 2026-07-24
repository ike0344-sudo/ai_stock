from backtesting.stop_control import clear_stop_flag, is_stop_requested, request_stop


def test_is_stop_requested_false_when_file_missing(tmp_path):
    path = str(tmp_path / "stop_requested.json")

    assert is_stop_requested(path) is False


def test_request_stop_creates_file_and_flags_requested(tmp_path):
    path = str(tmp_path / "state" / "stop_requested.json")  # 하위 디렉터리 자동 생성 확인

    request_stop(path)

    assert is_stop_requested(path) is True


def test_clear_stop_flag_removes_file(tmp_path):
    path = str(tmp_path / "stop_requested.json")
    request_stop(path)
    assert is_stop_requested(path) is True

    clear_stop_flag(path)

    assert is_stop_requested(path) is False


def test_clear_stop_flag_is_noop_when_file_missing(tmp_path):
    path = str(tmp_path / "stop_requested.json")

    clear_stop_flag(path)  # 예외 없이 조용히 통과해야 함

    assert is_stop_requested(path) is False
