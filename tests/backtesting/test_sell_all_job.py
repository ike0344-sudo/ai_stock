import threading
import time

import pytest

from backtesting import sell_all_job
from backtesting.risk_manager import RiskDecision
from backtesting.sell_all_job import SellAllJobState, get_status, start_job


@pytest.fixture(autouse=True)
def reset_job_state():
    sell_all_job._state = SellAllJobState()
    yield
    sell_all_job._state = SellAllJobState()


def _wait_until(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _FakeClient:
    def __init__(self, holdings=None, evaluation_error=None, order_results=None, order_errors=None, block=None):
        self._holdings = holdings or []
        self._evaluation_error = evaluation_error
        self._order_results = order_results or {}
        self._order_errors = order_errors or {}
        self._block = block
        self.orders_placed = []
        self.order_kwargs = []

    def get_account_evaluation(self):
        if self._block:
            self._block.wait(timeout=2.0)
        if self._evaluation_error:
            raise self._evaluation_error
        return {"stk_acnt_evlt_prst": self._holdings, "return_code": 0}

    def place_order(self, code, side, quantity, **kwargs):
        self.orders_placed.append((code, side, quantity))
        self.order_kwargs.append(kwargs)
        if code in self._order_errors:
            raise self._order_errors[code]
        return self._order_results.get(code, {"return_code": 0, "return_msg": "모의투자 매도주문완료"})


def _holding(code, name, qty):
    return {"stk_cd": f"A{code}", "stk_nm": name, "rmnd_qty": str(qty).zfill(12)}


def test_start_job_from_idle_returns_true_and_sets_running(monkeypatch):
    block = threading.Event()
    fake_client = _FakeClient(holdings=[_holding("005930", "삼성전자", 1)], block=block)
    monkeypatch.setattr(sell_all_job, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    started = start_job("key", "secret", True)

    assert started is True
    assert _wait_until(lambda: get_status()["status"] == "running")
    block.set()
    assert _wait_until(lambda: get_status()["status"] == "done")


def test_start_job_while_running_returns_false_and_does_not_restart(monkeypatch):
    block = threading.Event()
    fake_client = _FakeClient(holdings=[_holding("005930", "삼성전자", 1)], block=block)
    monkeypatch.setattr(sell_all_job, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    assert start_job("key", "secret", True) is True
    assert _wait_until(lambda: get_status()["status"] == "running")

    started_again = start_job("key", "secret", True)

    assert started_again is False
    block.set()
    assert _wait_until(lambda: get_status()["status"] == "done")


def test_job_sells_every_holding_at_market_price(monkeypatch):
    fake_client = _FakeClient(holdings=[
        _holding("005930", "삼성전자", 1),
        _holding("000660", "SK하이닉스", 3),
    ])
    monkeypatch.setattr(sell_all_job, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "done")
    assert fake_client.orders_placed == [("005930", "sell", 1), ("000660", "sell", 3)]


def test_job_skips_holdings_with_zero_quantity(monkeypatch):
    fake_client = _FakeClient(holdings=[_holding("005930", "삼성전자", 0)])
    monkeypatch.setattr(sell_all_job, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "done")
    assert fake_client.orders_placed == []
    assert get_status()["results"] == []


def test_job_records_ok_and_error_results_per_stock(monkeypatch):
    fake_client = _FakeClient(
        holdings=[_holding("005930", "삼성전자", 1), _holding("000660", "SK하이닉스", 2)],
        order_errors={"000660": RuntimeError("주문 거부")},
    )
    monkeypatch.setattr(sell_all_job, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "done")
    results = get_status()["results"]
    assert results[0]["code"] == "005930"
    assert results[0]["status"] == "ok"
    assert results[1]["code"] == "000660"
    assert results[1]["status"] == "error"
    assert "주문 거부" in results[1]["message"]


def test_job_records_error_status_when_order_rejected_without_exception(monkeypatch):
    # place_order가 예외 없이 return_code!=0으로 응답하는 경우(HTTP 200 + 거부) —
    # 이 체크가 없으면 실제로는 거부된 주문이 "ok"로 기록돼 매도된 것처럼 착각하게 된다.
    fake_client = _FakeClient(
        holdings=[_holding("005930", "삼성전자", 1)],
        order_results={"005930": {"return_code": 20, "return_msg": "모의투자에서는 해당업무가 제공되지 않습니다"}},
    )
    monkeypatch.setattr(sell_all_job, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "done")
    results = get_status()["results"]
    assert results[0]["code"] == "005930"
    assert results[0]["status"] == "error"
    assert "모의투자에서는" in results[0]["message"]


def test_job_records_error_status_when_evaluation_fails(monkeypatch):
    fake_client = _FakeClient(evaluation_error=RuntimeError("계좌 조회 실패"))
    monkeypatch.setattr(sell_all_job, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "error")
    assert "계좌 조회 실패" in get_status()["error_message"]


def test_job_results_empty_before_start():
    assert get_status()["results"] == []
    assert get_status()["status"] == "idle"


def test_job_places_market_order_explicitly(monkeypatch):
    # kiwoom_client.place_order 기본값이 지정가로 바뀌었으므로, 이 일괄매도가 원래
    # 의도한 시장가 청산을 유지하려면 order_type="3"을 명시적으로 넘겨야 한다.
    fake_client = _FakeClient(holdings=[_holding("005930", "삼성전자", 1)])
    monkeypatch.setattr(sell_all_job, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "done")
    assert fake_client.order_kwargs == [{"order_type": "3"}]


def test_job_skips_holding_when_risk_manager_rejects(monkeypatch):
    fake_client = _FakeClient(holdings=[
        _holding("005930", "삼성전자", 1),
        _holding("000660", "SK하이닉스", 2),
    ])
    monkeypatch.setattr(sell_all_job, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    def fake_check_order(order, portfolio):
        if order.code == "005930":
            return RiskDecision(approved=False, reason="테스트 거부", rule_id="test_rule")
        return RiskDecision(approved=True, reason="승인", rule_id="approved")

    monkeypatch.setattr(sell_all_job, "check_order", fake_check_order)

    start_job("key", "secret", True)

    assert _wait_until(lambda: get_status()["status"] == "done")
    assert fake_client.orders_placed == [("000660", "sell", 2)]
    results = get_status()["results"]
    assert results[0]["code"] == "005930"
    assert results[0]["status"] == "error"
    assert "테스트 거부" in results[0]["message"]
    assert results[1]["code"] == "000660"
    assert results[1]["status"] == "ok"
