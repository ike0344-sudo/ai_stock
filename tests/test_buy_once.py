import sys

import pytest

import buy_once


class _FakeClient:
    def __init__(self, quote_price=70000, deposit_krw=100_000_000, order_result=None):
        self._quote_price = quote_price
        self._deposit_krw = deposit_krw
        self._order_result = order_result or {"return_code": 0, "return_msg": "ok"}
        self.orders = []
        self.order_kwargs = []

    def get_stock_quote(self, stock_code):
        return {"buy_fpr_bid": f"-{self._quote_price}"}

    def get_deposit_detail(self):
        return {"entr": str(self._deposit_krw)}

    def place_order(self, code, side, quantity, **kwargs):
        self.orders.append((code, side, quantity))
        self.order_kwargs.append(kwargs)
        return self._order_result


def _run_main(monkeypatch, argv, fake_client):
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(buy_once, "load_dotenv", lambda: None)
    monkeypatch.setenv("KIWOOM_APPKEY", "key")
    monkeypatch.setenv("KIWOOM_SECRETKEY", "secret")
    monkeypatch.setenv("KIWOOM_IS_MOCK", "true")
    monkeypatch.setattr(buy_once, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)


def test_main_places_market_order_when_stop_loss_given(monkeypatch, capsys):
    fake_client = _FakeClient(quote_price=70000, deposit_krw=100_000_000)
    _run_main(monkeypatch, ["buy_once.py", "005930", "10", "65000"], fake_client)

    buy_once.main()

    assert fake_client.orders == [("005930", "buy", 10)]
    assert fake_client.order_kwargs == [{"order_type": "3"}]
    assert "매수 주문" in capsys.readouterr().out


def test_main_rejects_without_placing_order_when_risk_manager_denies(monkeypatch, capsys):
    from backtesting.risk_manager import RiskDecision

    fake_client = _FakeClient(quote_price=70000, deposit_krw=100_000_000)
    _run_main(monkeypatch, ["buy_once.py", "005930", "10", "65000"], fake_client)
    monkeypatch.setattr(
        buy_once, "check_order",
        lambda order, portfolio: RiskDecision(approved=False, reason="테스트 거부", rule_id="test_rule"),
    )

    with pytest.raises(SystemExit) as exc_info:
        buy_once.main()

    assert exc_info.value.code == 1
    assert fake_client.orders == []
    assert "리스크 심사 거부" in capsys.readouterr().out


def test_main_exits_with_usage_when_args_missing(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["buy_once.py", "005930", "10"])

    with pytest.raises(SystemExit) as exc_info:
        buy_once.main()

    assert exc_info.value.code == 1
    assert "사용법" in capsys.readouterr().out
