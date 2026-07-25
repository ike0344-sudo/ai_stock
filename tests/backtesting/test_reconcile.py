import pytest

from backtesting.reconcile import reconcile
from backtesting.risk_manager import OpenPosition, RiskState


def _holding(code, qty):
    return {"stk_cd": f"A{code}", "stk_nm": "", "rmnd_qty": str(qty).zfill(12)}


class _FakeClient:
    def __init__(self, holdings=None, return_code=0):
        self._holdings = holdings or []
        self._return_code = return_code

    def get_account_evaluation(self):
        return {"stk_acnt_evlt_prst": self._holdings, "return_code": self._return_code}


def _position(code, quantity):
    return OpenPosition(code=code, entry_time="t", allocated_capital=1.0, entry_price=1.0, total_quantity=quantity)


def test_reconcile_reports_matched_when_quantities_agree():
    client = _FakeClient(holdings=[_holding("005930", 10)])
    risk_state = RiskState(trading_date="2026-07-20", open_positions=[_position("005930", 10)])

    report = reconcile(client, risk_state)

    assert report.matched == ["005930"]
    assert report.is_clean is True


def test_reconcile_reports_quantity_mismatch():
    client = _FakeClient(holdings=[_holding("005930", 7)])
    risk_state = RiskState(trading_date="2026-07-20", open_positions=[_position("005930", 10)])

    report = reconcile(client, risk_state)

    assert report.quantity_mismatches == [{"code": "005930", "internal_qty": 10, "broker_qty": 7}]
    assert report.is_clean is False


def test_reconcile_reports_broker_only_position():
    client = _FakeClient(holdings=[_holding("005930", 5)])
    risk_state = RiskState(trading_date="2026-07-20")

    report = reconcile(client, risk_state)

    assert report.broker_only == ["005930"]
    assert report.is_clean is False


def test_reconcile_reports_internal_only_position():
    client = _FakeClient(holdings=[])
    risk_state = RiskState(trading_date="2026-07-20", open_positions=[_position("005930", 10)])

    report = reconcile(client, risk_state)

    assert report.internal_only == ["005930"]
    assert report.is_clean is False


def test_reconcile_raises_when_broker_query_fails():
    client = _FakeClient(return_code=20)
    risk_state = RiskState(trading_date="2026-07-20")

    with pytest.raises(RuntimeError):
        reconcile(client, risk_state)
