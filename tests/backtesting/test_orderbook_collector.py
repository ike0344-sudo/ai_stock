import json
from datetime import datetime

import pytest

from backtesting import orderbook_collector
from backtesting.orderbook_collector import (
    append_jsonl,
    collect_once,
    is_market_open,
    poll_all_once,
    run_collection_loop,
    wait_until_extended_market_open,
)


class _StubClient:
    def __init__(self, quote_by_code: dict | None = None, raise_for: set | None = None):
        self._quote_by_code = quote_by_code or {}
        self._raise_for = raise_for or set()

    def get_stock_quote(self, stock_code):
        if stock_code in self._raise_for:
            raise RuntimeError("API error")
        return self._quote_by_code.get(stock_code, {"sel_1bid": "100", "buy_1bid": "99"})


def test_is_market_open_true_within_regular_hours_on_weekday():
    now = datetime(2026, 7, 20, 10, 30)  # 월요일

    assert is_market_open(now) is True


def test_is_market_open_false_before_open_and_after_close():
    assert is_market_open(datetime(2026, 7, 20, 8, 59)) is False
    assert is_market_open(datetime(2026, 7, 20, 15, 31)) is False


def test_is_market_open_false_on_weekend():
    saturday = datetime(2026, 7, 18, 10, 0)  # 토요일

    assert is_market_open(saturday) is False


def test_collect_once_merges_payload_with_metadata():
    client = _StubClient({"005930": {"sel_1bid": "70100"}})
    now = datetime(2026, 7, 20, 9, 5)

    record = collect_once(client, "005930", now)

    assert record["stock_code"] == "005930"
    assert record["received_at"] == now.isoformat()
    assert record["sel_1bid"] == "70100"


def test_collect_once_captures_error_instead_of_raising():
    client = _StubClient(raise_for={"005930"})

    record = collect_once(client, "005930", datetime(2026, 7, 20, 9, 5))

    assert record["stock_code"] == "005930"
    assert "API error" in record["error"]


def test_append_jsonl_appends_one_line_per_call(tmp_path):
    path = tmp_path / "sub" / "005930.jsonl"

    append_jsonl({"a": 1}, str(path))
    append_jsonl({"a": 2}, str(path))

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert [json.loads(line)["a"] for line in lines] == [1, 2]


def test_poll_all_once_writes_one_file_per_code_under_date_dir(tmp_path):
    client = _StubClient({"005930": {"sel_1bid": "70100"}, "000660": {"sel_1bid": "200000"}})
    now = datetime(2026, 7, 20, 9, 5)

    records = poll_all_once(client, ["005930", "000660"], str(tmp_path), now=now)

    assert len(records) == 2
    day_dir = tmp_path / "20260720"
    assert (day_dir / "005930.jsonl").exists()
    assert (day_dir / "000660.jsonl").exists()
    saved = json.loads((day_dir / "005930.jsonl").read_text(encoding="utf-8").strip())
    assert saved["sel_1bid"] == "70100"


def test_poll_all_once_appends_across_multiple_calls_same_day(tmp_path):
    client = _StubClient()
    now = datetime(2026, 7, 20, 9, 5)

    poll_all_once(client, ["005930"], str(tmp_path), now=now)
    poll_all_once(client, ["005930"], str(tmp_path), now=now)

    lines = (tmp_path / "20260720" / "005930.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


def test_wait_until_extended_market_open_returns_immediately_when_already_open(monkeypatch):
    monkeypatch.setattr(orderbook_collector.time, "sleep", lambda s: pytest.fail("should not sleep"))
    now = datetime(2026, 7, 24, 10, 30)  # 금요일, 이미 통합장 시간

    assert wait_until_extended_market_open(now_fn=lambda: now) is True


def test_wait_until_extended_market_open_returns_false_immediately_on_weekend(monkeypatch):
    monkeypatch.setattr(orderbook_collector.time, "sleep", lambda s: pytest.fail("should not sleep"))
    saturday = datetime(2026, 7, 18, 7, 0)  # 토요일, 8시 이전이지만 주말이라 대기하지 않음

    assert wait_until_extended_market_open(now_fn=lambda: saturday) is False


def test_wait_until_extended_market_open_returns_false_immediately_after_close(monkeypatch):
    monkeypatch.setattr(orderbook_collector.time, "sleep", lambda s: pytest.fail("should not sleep"))
    now = datetime(2026, 7, 24, 21, 0)  # 금요일 20시 마감 이후

    assert wait_until_extended_market_open(now_fn=lambda: now) is False


def test_wait_until_extended_market_open_waits_then_starts_at_8am(monkeypatch):
    times = iter([
        datetime(2026, 7, 24, 7, 59, 30),  # 최초 확인 - 8시 전이라 대기 시작
        datetime(2026, 7, 24, 7, 59, 45),  # while 조건 - 아직 8시 전
        datetime(2026, 7, 24, 8, 0, 0),  # while 조건 - 8시 도달, 루프 종료
    ])
    sleeps = []
    monkeypatch.setattr(orderbook_collector.time, "sleep", lambda s: sleeps.append(s))

    result = wait_until_extended_market_open(now_fn=lambda: next(times))

    assert result is True
    assert sleeps == [15.0]


def test_run_collection_loop_polls_until_market_closes(monkeypatch):
    client = _StubClient()
    open_flags = iter([True, True, False])  # 두 번 폴링 후 종료
    monkeypatch.setattr(orderbook_collector, "is_market_open", lambda now: next(open_flags))
    sleeps = []
    monkeypatch.setattr(orderbook_collector.time, "sleep", lambda s: sleeps.append(s))
    poll_calls = []
    monkeypatch.setattr(
        orderbook_collector, "poll_all_once",
        lambda client, codes, output_dir: poll_calls.append(codes),
    )

    run_collection_loop(client, ["005930"], output_dir="unused", interval_seconds=1.0)

    assert len(poll_calls) == 2
    assert sleeps == [1.0, 1.0]
