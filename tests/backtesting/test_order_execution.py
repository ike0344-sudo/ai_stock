import json

import pytest
import requests

from backtesting import trading_loop
from backtesting.order_execution import (
    DEFAULT_ORDER_TRACKING_LOG_PATH,
    TrackedOrder,
    cancel_if_timed_out,
    check_fill,
    load_recent_orders,
    restore_pending_orders_from_broker,
    submit_order,
)
from backtesting.risk_manager import RiskState
from backtesting.trading_loop import process_entries_once
from kiwoom_client import KiwoomClient


def _client():
    return KiwoomClient("key", "secret")


# --- submit_order -----------------------------------------------------------

def test_submit_order_rejects_without_approval():
    client = _client()
    tracked = submit_order(
        client, stock_code="005930", side="buy", quantity=1, price=70000, approved=False, log_path=None,
    )
    assert tracked.status == "rejected"
    assert tracked.detail == "리스크 승인 없음"


def test_submit_order_success_marks_pending(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "place_order", lambda *a, **k: {"return_code": 0, "ord_no": "OID1"})

    tracked = submit_order(client, stock_code="005930", side="buy", quantity=1, price=70000, approved=True, log_path=None)

    assert tracked.status == "pending"
    assert tracked.ord_no == "OID1"


def test_submit_order_broker_rejection_does_not_retry(monkeypatch):
    client = _client()
    calls = {"n": 0}

    def fake_place_order(*a, **k):
        calls["n"] += 1
        return {"return_code": 20, "return_msg": "잔고부족"}

    monkeypatch.setattr(client, "place_order", fake_place_order)

    tracked = submit_order(client, stock_code="005930", side="buy", quantity=1, price=70000, approved=True, log_path=None)

    assert tracked.status == "rejected"
    assert calls["n"] == 1  # 재시도 없음


def test_submit_order_retries_network_error_then_succeeds(monkeypatch):
    client = _client()
    calls = {"n": 0}

    def fake_place_order(*a, **k):
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.exceptions.ConnectionError("boom")
        return {"return_code": 0, "ord_no": "OID2"}

    monkeypatch.setattr(client, "place_order", fake_place_order)
    monkeypatch.setattr(client, "get_pending_orders", lambda **k: {"return_code": 0, "list": []})
    monkeypatch.setattr("backtesting.order_execution.time.sleep", lambda s: None)

    tracked = submit_order(client, stock_code="005930", side="buy", quantity=1, price=70000, approved=True, log_path=None)

    assert calls["n"] == 2
    assert tracked.status == "pending"
    assert tracked.ord_no == "OID2"


def test_submit_order_aborts_retry_when_pending_orders_ambiguous(monkeypatch):
    client = _client()
    calls = {"n": 0}

    def fake_place_order(*a, **k):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(client, "place_order", fake_place_order)
    # 통신 오류 이후 조회했더니 그 종목에 미체결이 있다 -> 직전 시도가 실제로 접수됐을 수 있음
    monkeypatch.setattr(client, "get_pending_orders", lambda **k: {"return_code": 0, "list": [{"ord_no": "SOMETHING"}]})
    monkeypatch.setattr("backtesting.order_execution.time.sleep", lambda s: None)

    tracked = submit_order(
        client, stock_code="005930", side="buy", quantity=1, price=70000, approved=True, max_retries=3, log_path=None,
    )

    assert tracked.status == "ambiguous"
    assert calls["n"] == 1  # 두 번째 place_order는 나가지 않음 (중복 주문 방지)


def test_submit_order_exhausts_retries_stays_failed(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "place_order", lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.Timeout()))
    monkeypatch.setattr(client, "get_pending_orders", lambda **k: {"return_code": 0, "list": []})
    monkeypatch.setattr("backtesting.order_execution.time.sleep", lambda s: None)

    tracked = submit_order(client, stock_code="005930", side="buy", quantity=1, price=70000, approved=True, max_retries=2, log_path=None)

    assert tracked.status == "failed"


# --- check_fill ---------------------------------------------------------------

def test_check_fill_marks_filled_when_order_no_longer_pending(monkeypatch):
    client = _client()
    tracked = TrackedOrder(
        client_order_id="c1", stock_code="005930", side="buy", ordered_qty=10, price=70000,
        order_type="0", submitted_at=0.0, ord_no="OID1", status="pending",
    )
    monkeypatch.setattr(client, "get_pending_orders", lambda **k: {"return_code": 0, "list": []})

    result = check_fill(client, tracked)

    assert result.status == "filled"
    assert result.filled_qty == 10


def test_check_fill_marks_partial_using_remaining_qty_field(monkeypatch):
    client = _client()
    tracked = TrackedOrder(
        client_order_id="c1", stock_code="005930", side="buy", ordered_qty=10, price=70000,
        order_type="0", submitted_at=0.0, ord_no="OID1", status="pending",
    )
    monkeypatch.setattr(
        client, "get_pending_orders", lambda **k: {"return_code": 0, "list": [{"ord_no": "OID1", "rmn_qty": "4"}]},
    )

    result = check_fill(client, tracked)

    assert result.status == "partial"
    assert result.filled_qty == 6


def test_check_fill_unknown_when_remaining_field_missing(monkeypatch):
    client = _client()
    tracked = TrackedOrder(
        client_order_id="c1", stock_code="005930", side="buy", ordered_qty=10, price=70000,
        order_type="0", submitted_at=0.0, ord_no="OID1", status="pending",
    )
    monkeypatch.setattr(
        client, "get_pending_orders", lambda **k: {"return_code": 0, "list": [{"ord_no": "OID1"}]},
    )

    result = check_fill(client, tracked)

    assert result.status == "unknown"
    assert result.filled_qty == 0  # 잘못된 값으로 체결 처리하지 않는다


# --- cancel_if_timed_out --------------------------------------------------------

def test_cancel_if_timed_out_skips_when_not_yet_timed_out(monkeypatch):
    client = _client()
    tracked = TrackedOrder(
        client_order_id="c1", stock_code="005930", side="buy", ordered_qty=10, price=70000,
        order_type="0", submitted_at=1_000_000.0, ord_no="OID1", status="pending",
    )
    monkeypatch.setattr("backtesting.order_execution.time.time", lambda: 1_000_001.0)

    result = cancel_if_timed_out(client, tracked, timeout_seconds=30, log_path=None)

    assert result.status == "pending"


def test_cancel_if_timed_out_cancels_after_timeout(monkeypatch):
    client = _client()
    tracked = TrackedOrder(
        client_order_id="c1", stock_code="005930", side="buy", ordered_qty=10, price=70000,
        order_type="0", submitted_at=1_000_000.0, ord_no="OID1", status="pending",
    )
    monkeypatch.setattr("backtesting.order_execution.time.time", lambda: 1_000_100.0)

    captured = {}

    def fake_cancel_order(order_no, stock_code, quantity, exchange=None):
        captured["args"] = (order_no, stock_code, quantity)
        return {"return_code": 0}

    monkeypatch.setattr(client, "cancel_order", fake_cancel_order)

    result = cancel_if_timed_out(client, tracked, timeout_seconds=30, log_path=None)

    assert result.status == "cancelled"
    assert captured["args"] == ("OID1", "005930", 0)  # quantity=0 -> 잔량 전부 취소


# --- idempotency persistence across restart ------------------------------------

def test_load_recent_orders_restores_dedup_cache(tmp_path):
    log_path = tmp_path / "orders.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"event": "submitted", "client_order_id": "retry-1", "response": {"ord_no": "OID1", "return_code": 0}}) + "\n")
        f.write(json.dumps({"event": "attempt_failed", "client_order_id": "retry-2"}) + "\n")  # response 없음 -> 무시

    client = _client()
    n = load_recent_orders(client, log_path=str(log_path))

    assert n == 1
    assert client._submitted_orders["retry-1"] == {"ord_no": "OID1", "return_code": 0}


def test_load_recent_orders_missing_file_returns_zero(tmp_path):
    client = _client()
    assert load_recent_orders(client, log_path=str(tmp_path / "nope.jsonl")) == 0


def test_default_log_path_is_state_dir():
    assert DEFAULT_ORDER_TRACKING_LOG_PATH == "state/order_tracking.jsonl"


# --- restore_pending_orders_from_broker (재시작 후 브로커 조회로 복원) --------------

def test_restore_pending_orders_from_broker_only_restores_our_own_orders(tmp_path, monkeypatch):
    """우리가 제출 로그에 남긴 ord_no만 복원한다 — 같은 계좌의 다른 미체결(수동 주문
    등)은 소유권을 확인할 수 없으므로 손대지 않는다."""
    log_path = str(tmp_path / "orders.jsonl")
    client = _client()
    monkeypatch.setattr(client, "place_order", lambda *a, **k: {"return_code": 0, "ord_no": "OID-OURS"})
    submit_order(client, stock_code="005930", side="buy", quantity=10, price=70000, approved=True, log_path=log_path)

    monkeypatch.setattr(client, "get_pending_orders", lambda **k: {
        "return_code": 0,
        "list": [
            {"ord_no": "OID-OURS", "rmn_qty": "10"},
            {"ord_no": "OID-MANUAL-ORDER", "rmn_qty": "5"},  # 우리 로그엔 없음 -> 남의 주문
        ],
    })

    pending_orders: dict = {}
    restored = restore_pending_orders_from_broker(client, pending_orders, log_path=log_path)

    assert restored == 1
    assert list(pending_orders.keys()) == ["buy:005930"]
    assert pending_orders["buy:005930"].ord_no == "OID-OURS"
    assert pending_orders["buy:005930"].ordered_qty == 10
    assert pending_orders["buy:005930"].price == 70000


def test_restore_pending_orders_from_broker_skips_when_nothing_pending_there(tmp_path, monkeypatch):
    log_path = str(tmp_path / "orders.jsonl")
    client = _client()
    monkeypatch.setattr(client, "place_order", lambda *a, **k: {"return_code": 0, "ord_no": "OID-1"})
    submit_order(client, stock_code="005930", side="buy", quantity=10, price=70000, approved=True, log_path=log_path)

    # 브로커에는 더 이상 그 주문이 없다(재시작 전에 이미 체결/취소됨) -> 복원할 게 없다.
    monkeypatch.setattr(client, "get_pending_orders", lambda **k: {"return_code": 0, "list": []})

    pending_orders: dict = {}
    restored = restore_pending_orders_from_broker(client, pending_orders, log_path=log_path)

    assert restored == 0
    assert pending_orders == {}


def test_restore_pending_orders_from_broker_no_log_file_queries_nothing(tmp_path, monkeypatch):
    client = _client()
    called = []
    monkeypatch.setattr(client, "get_pending_orders", lambda **k: called.append(1) or {"return_code": 0, "list": []})

    pending_orders: dict = {}
    restored = restore_pending_orders_from_broker(client, pending_orders, log_path=str(tmp_path / "nope.jsonl"))

    assert restored == 0
    assert called == []  # 복원할 후보(로그)가 아예 없으니 브로커 조회조차 안 한다


# --- 핵심 시나리오: 재시작 후 이미 낸 주문이 다시 나가지 않는다 --------------------

def test_restart_does_not_resubmit_order_already_placed_at_broker(tmp_path, monkeypatch):
    """실행 에이전트 재시작 복원 기능의 핵심 시나리오.

    1) "이전 프로세스"가 매수 주문을 냈고 아직 미체결(로그에 ord_no 기록됨).
    2) "재시작" — 새 client, 새 pending_orders(메모리 전부 리셋). 브로커는 그 주문이
       여전히 미체결이라고 답한다.
    3) restore_pending_orders_from_broker로 복원한 뒤, process_entries_once가 같은
       종목에 대한 신호를 다시 감지해도 place_order를 다시 호출하면 안 된다.
    """
    log_path = str(tmp_path / "orders.jsonl")

    # 1) 이전 프로세스: 매수 제출
    old_client = _client()
    monkeypatch.setattr(old_client, "place_order", lambda *a, **k: {"return_code": 0, "ord_no": "OID-777"})
    tracked = submit_order(
        old_client, stock_code="005930", side="buy", quantity=10, price=70000, approved=True, log_path=log_path,
    )
    assert tracked.status == "pending"

    # 2) 재시작: 새 client(=새 프로세스의 새 인스턴스, place_order의 멱등성 캐시도 빔).
    # 브로커는 여전히 미체결이라고 답한다.
    new_client = _client()
    monkeypatch.setattr(
        new_client, "get_pending_orders",
        lambda **k: {"return_code": 0, "list": [{"ord_no": "OID-777", "rmn_qty": "10"}]},
    )
    pending_orders: dict = {}
    restored = restore_pending_orders_from_broker(new_client, pending_orders, log_path=log_path)
    assert restored == 1

    # 3) 재시작 후 첫 사이클 — 같은 신호가 다시 감지된다(seen_signals도 리셋됐다고 가정).
    place_order_calls = []
    monkeypatch.setattr(
        new_client, "place_order",
        lambda *a, **k: place_order_calls.append(1) or {"return_code": 0, "ord_no": "SHOULD-NOT-HAPPEN"},
    )
    monkeypatch.setattr(
        trading_loop, "scan_watchlist_once",
        lambda *a, **k: [{"stock_code": "005930", "signal_time": "t1", "price": 70000, "proba": 0.7}],
    )
    risk_state = RiskState(trading_date="2026-08-29")

    executed = process_entries_once(
        new_client, trained=None, today_top35={"005930"}, regime_ok=True, risk_state=risk_state,
        exit_tracking={}, data_dir="data", proba_threshold=0.5, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="", chat_id="", seen_signals=set(), total_capital_krw=10_000_000,
        pending_orders=pending_orders, order_tracking_log_path=log_path,
    )

    assert place_order_calls == []  # 핵심: 중복 주문이 나가지 않는다
    assert executed == []
    assert risk_state.open_positions == []  # 아직 체결 확인 전이므로 포지션도 새로 생기지 않는다
