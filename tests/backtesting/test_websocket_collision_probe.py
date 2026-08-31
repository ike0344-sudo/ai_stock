import json
from datetime import datetime
from zoneinfo import ZoneInfo

from backtesting.websocket_collision_probe import CollisionProbe, resolve_hard_stop

SEOUL = ZoneInfo("Asia/Seoul")


class _FakeWs:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, msg):
        self.sent.append(msg)

    def close(self):
        self.closed = True


# ---- resolve_hard_stop ----

def test_resolve_hard_stop_same_day_when_still_ahead():
    now = datetime(2026, 8, 31, 8, 0, tzinfo=SEOUL)
    result = resolve_hard_stop("0850", now=now)
    assert result == datetime(2026, 8, 31, 8, 50, tzinfo=SEOUL)


def test_resolve_hard_stop_rolls_to_next_day_when_already_past():
    now = datetime(2026, 8, 31, 9, 0, tzinfo=SEOUL)
    result = resolve_hard_stop("0850", now=now)
    assert result == datetime(2026, 9, 1, 8, 50, tzinfo=SEOUL)


# ---- CollisionProbe._on_message ----

def _probe(tmp_path):
    return CollisionProbe(token="TOK", codes=["005930"], exchange="AL", log_path=str(tmp_path / "log.jsonl"))


def test_on_message_ping_echoes_raw_message_unchanged(tmp_path):
    probe = _probe(tmp_path)
    ws = _FakeWs()
    raw = json.dumps({"trnm": "PING", "extra": "x"})

    probe._on_message(ws, raw)

    assert ws.sent == [raw]  # 가공 없이 그대로 echo — feed.py와 같은 이유


def test_on_message_login_success_sends_reg(tmp_path):
    probe = _probe(tmp_path)
    ws = _FakeWs()

    probe._on_message(ws, json.dumps({"trnm": "LOGIN", "return_code": 0}))

    assert len(ws.sent) == 1
    reg = json.loads(ws.sent[0])
    assert reg["trnm"] == "REG"
    assert reg["data"][0]["item"] == ["005930_AL"]
    assert reg["data"][0]["type"] == ["0B"]


def test_on_message_login_failure_closes_without_reg(tmp_path):
    probe = _probe(tmp_path)
    ws = _FakeWs()

    probe._on_message(ws, json.dumps({"trnm": "LOGIN", "return_code": 3, "return_msg": "실패"}))

    assert ws.sent == []
    assert ws.closed is True


def test_on_message_push_increments_count_and_logs(tmp_path):
    probe = _probe(tmp_path)
    ws = _FakeWs()

    probe._on_message(ws, json.dumps({"trnm": "REAL", "data": [{"item": "005930_AL", "values": {"10": "70000"}}]}))

    assert probe.push_count == 1

    with open(probe.log_path, encoding="utf-8") as f:
        lines = f.readlines()
    last = json.loads(lines[-1])
    assert last["event"] == "push"


def test_on_message_reg_response_does_not_count_as_push(tmp_path):
    probe = _probe(tmp_path)
    ws = _FakeWs()

    probe._on_message(ws, json.dumps({"trnm": "REG", "return_code": 0}))

    assert probe.push_count == 0
    assert ws.sent == []  # REG 응답 자체는 아무것도 되돌려 보내지 않는다


def test_on_close_sets_event_and_records_push_count(tmp_path):
    probe = _probe(tmp_path)
    probe.push_count = 5

    probe._on_close(None, 1006, "abnormal")

    assert probe.closed_event.is_set()
