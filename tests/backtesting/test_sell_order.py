from backtesting import account_status, sell_order
from backtesting.sell_order import sell_one


class _FakeClient:
    def __init__(self, order_result=None, order_error=None):
        self._order_result = order_result
        self._order_error = order_error
        self.calls = []

    def place_order(self, code, side, quantity):
        self.calls.append((code, side, quantity))
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
