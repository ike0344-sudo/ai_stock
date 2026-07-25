from backtesting import account_status, sell_order
from backtesting.risk_manager import RiskDecision
from backtesting.sell_order import sell_one


class _FakeClient:
    def __init__(self, order_result=None, order_error=None):
        self._order_result = order_result
        self._order_error = order_error
        self.calls = []
        self.call_kwargs = []

    def place_order(self, code, side, quantity, **kwargs):
        self.calls.append((code, side, quantity))
        self.call_kwargs.append(kwargs)
        if self._order_error:
            raise self._order_error
        return self._order_result


def test_sell_one_places_market_sell_order_for_full_quantity(monkeypatch):
    fake_client = _FakeClient(order_result={"return_code": 0, "return_msg": "모의투자 매도주문완료"})
    monkeypatch.setattr(sell_order, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    result = sell_one("appkey", "secretkey", True, "005930", 3)

    assert fake_client.calls == [("005930", "sell", 3)]
    assert result == {"return_code": 0, "return_msg": "모의투자 매도주문완료"}


def test_sell_one_invalidates_account_cache_on_success(monkeypatch):
    fake_client = _FakeClient(order_result={"return_code": 0, "return_msg": "ok"})
    monkeypatch.setattr(sell_order, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)
    invalidated = []
    monkeypatch.setattr(sell_order, "invalidate_cache", lambda: invalidated.append(True))

    sell_one("appkey", "secretkey", True, "005930", 1)

    assert invalidated == [True]


def test_sell_one_does_not_invalidate_cache_on_failure(monkeypatch):
    fake_client = _FakeClient(order_result={"return_code": 5, "return_msg": "주문 실패"})
    monkeypatch.setattr(sell_order, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)
    invalidated = []
    monkeypatch.setattr(sell_order, "invalidate_cache", lambda: invalidated.append(True))

    result = sell_one("appkey", "secretkey", True, "005930", 1)

    assert result["return_code"] == 5
    assert invalidated == []


def test_sell_one_propagates_exceptions(monkeypatch):
    fake_client = _FakeClient(order_error=RuntimeError("네트워크 오류"))
    monkeypatch.setattr(sell_order, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    try:
        sell_one("appkey", "secretkey", True, "005930", 1)
        assert False, "예외가 나야 한다"
    except RuntimeError as exc:
        assert "네트워크 오류" in str(exc)


def test_sell_one_calls_check_order_before_placing(monkeypatch):
    fake_client = _FakeClient(order_result={"return_code": 0, "return_msg": "ok"})
    monkeypatch.setattr(sell_order, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)
    captured = {}

    def fake_check_order(order, portfolio):
        captured["order"] = order
        return RiskDecision(approved=True, reason="테스트 통과", rule_id="test_rule")

    monkeypatch.setattr(sell_order, "check_order", fake_check_order)

    sell_one("appkey", "secretkey", True, "005930", 3)

    assert captured["order"].code == "005930"
    assert captured["order"].side == "sell"
    assert captured["order"].quantity == 3
    assert fake_client.calls == [("005930", "sell", 3)]


def test_sell_one_skips_order_when_risk_manager_rejects(monkeypatch):
    fake_client = _FakeClient(order_result={"return_code": 0, "return_msg": "ok"})
    monkeypatch.setattr(sell_order, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)
    monkeypatch.setattr(
        sell_order, "check_order",
        lambda order, portfolio: RiskDecision(approved=False, reason="테스트 거부", rule_id="test_rule"),
    )

    result = sell_one("appkey", "secretkey", True, "005930", 3)

    assert fake_client.calls == []
    assert result["return_code"] != 0
    assert "테스트 거부" in result["return_msg"]


def test_sell_one_places_market_order_explicitly(monkeypatch):
    # kiwoom_client.place_order 기본값이 지정가로 바뀌었으므로, 이 버튼이 원래
    # 의도한 시장가 매도를 유지하려면 order_type="3"을 명시적으로 넘겨야 한다.
    fake_client = _FakeClient(order_result={"return_code": 0, "return_msg": "ok"})
    monkeypatch.setattr(sell_order, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    sell_one("appkey", "secretkey", True, "005930", 3)

    assert fake_client.call_kwargs == [{"order_type": "3"}]
