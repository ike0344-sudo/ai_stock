import json
import os

from backtesting.heartbeat import read_heartbeat_age_seconds, write_heartbeat


def test_write_heartbeat_creates_directory_and_file(tmp_path):
    state_dir = str(tmp_path / "strategy_1")

    write_heartbeat(state_dir)

    path = os.path.join(state_dir, "heartbeat.json")
    assert os.path.exists(path)
    data = json.loads(open(path, encoding="utf-8").read())
    assert "updated_at" in data


def test_read_heartbeat_age_seconds_is_small_right_after_write(tmp_path):
    state_dir = str(tmp_path / "strategy_1")
    write_heartbeat(state_dir)

    age = read_heartbeat_age_seconds(state_dir)

    assert age is not None
    assert 0 <= age < 5


def test_read_heartbeat_age_seconds_returns_none_when_no_file(tmp_path):
    age = read_heartbeat_age_seconds(str(tmp_path / "never_started"))

    assert age is None


def test_read_heartbeat_age_seconds_returns_none_when_file_corrupted(tmp_path):
    state_dir = tmp_path / "strategy_1"
    state_dir.mkdir()
    (state_dir / "heartbeat.json").write_text("{not json", encoding="utf-8")

    age = read_heartbeat_age_seconds(str(state_dir))

    assert age is None


def test_write_heartbeat_overwrites_previous_value(tmp_path):
    state_dir = str(tmp_path / "strategy_1")
    write_heartbeat(state_dir)
    first = json.loads(open(os.path.join(state_dir, "heartbeat.json"), encoding="utf-8").read())

    write_heartbeat(state_dir)
    second = json.loads(open(os.path.join(state_dir, "heartbeat.json"), encoding="utf-8").read())

    assert second["updated_at"] >= first["updated_at"]
