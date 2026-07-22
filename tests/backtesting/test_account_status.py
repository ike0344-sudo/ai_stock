import pytest

from backtesting import account_status
from backtesting.account_status import _deposit_snapshot, _holdings_snapshot, get_account_snapshot


@pytest.fixture(autouse=True)
def reset_snapshot_cache():
    account_status._cached_snapshot = None
    account_status._cached_at = 0.0
    yield
    account_status._cached_snapshot = None
    account_status._cached_at = 0.0


class _FakeClient:
    def __init__(self, deposit_payload=None, holdings_payload=None, deposit_error=None, holdings_error=None):
        self._deposit_payload = deposit_payload
        self._holdings_payload = holdings_payload
        self._deposit_error = deposit_error
        self._holdings_error = holdings_error
        self.calls = []

    def get_deposit_detail(self):
        self.calls.append("deposit")
        if self._deposit_error:
            raise self._deposit_error
        return self._deposit_payload

    def get_account_evaluation(self):
        self.calls.append("holdings")
        if self._holdings_error:
            raise self._holdings_error
        return self._holdings_payload


DEPOSIT_PAYLOAD = {
    "entr": "000000010000000",
    "ord_alow_amt": "000000009725300",
    "pymn_alow_amt": "000000009917875",
    "d2_entra": "000000009725300",
    "return_code": 0,
}

HOLDINGS_PAYLOAD = {
    "stk_acnt_evlt_prst": [
        {
            "stk_cd": "A005930", "stk_nm": "삼성전자", "rmnd_qty": "000000000001",
            "avg_prc": "000000273750", "cur_prc": "000000273750", "evlt_amt": "000000271304",
            "pl_amt": "-00000002446", "pl_rt": "-0.8935",
        }
    ],
    "return_code": 0,
}


# ---- _deposit_snapshot ----

def test_deposit_snapshot_parses_padded_amount_fields():
    client = _FakeClient(deposit_payload=DEPOSIT_PAYLOAD)

    snapshot = _deposit_snapshot(client)

    assert snapshot == {
        "deposit_krw": 10_000_000, "order_available_krw": 9_725_300,
        "withdrawable_krw": 9_917_875, "d2_deposit_krw": 9_725_300,
    }


def test_deposit_snapshot_returns_none_when_client_raises():
    client = _FakeClient(deposit_error=RuntimeError("network down"))

    assert _deposit_snapshot(client) is None


def test_deposit_snapshot_returns_none_when_return_code_nonzero():
    client = _FakeClient(deposit_payload={"return_code": 20, "return_msg": "모의투자에서는 해당업무가 제공되지 않습니다"})

    assert _deposit_snapshot(client) is None


# ---- _holdings_snapshot ----

def test_holdings_snapshot_parses_rows_and_strips_exchange_prefix():
    client = _FakeClient(holdings_payload=HOLDINGS_PAYLOAD)

    holdings = _holdings_snapshot(client)

    assert holdings == [{
        "code": "005930", "name": "삼성전자", "quantity": 1, "avg_price": 273750,
        "current_price": 273750, "eval_amount": 271304, "pl_amount": -2446, "pl_pct": -0.8935,
    }]


def test_holdings_snapshot_returns_empty_list_when_no_holdings():
    client = _FakeClient(holdings_payload={"stk_acnt_evlt_prst": [], "return_code": 0})

    assert _holdings_snapshot(client) == []


def test_holdings_snapshot_returns_none_when_client_raises():
    client = _FakeClient(holdings_error=RuntimeError("network down"))

    assert _holdings_snapshot(client) is None


# ---- get_account_snapshot ----

def test_get_account_snapshot_combines_deposit_and_holdings(monkeypatch):
    fake_client = _FakeClient(deposit_payload=DEPOSIT_PAYLOAD, holdings_payload=HOLDINGS_PAYLOAD)
    monkeypatch.setattr(account_status, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    snapshot = get_account_snapshot("appkey", "secretkey", True)

    assert snapshot["deposit"]["deposit_krw"] == 10_000_000
    assert snapshot["holdings"][0]["code"] == "005930"
    assert fake_client.calls == ["deposit", "holdings"]


def test_get_account_snapshot_skips_kiwoom_when_credentials_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(account_status, "KiwoomClient", lambda *a, **k: calls.append(1))

    snapshot = get_account_snapshot("", "", True)

    assert snapshot == {"deposit": None, "holdings": None}
    assert calls == []


def test_get_account_snapshot_uses_cache_within_ttl(monkeypatch):
    fake_client = _FakeClient(deposit_payload=DEPOSIT_PAYLOAD, holdings_payload=HOLDINGS_PAYLOAD)
    monkeypatch.setattr(account_status, "KiwoomClient", lambda appkey, secretkey, is_mock: fake_client)

    first = get_account_snapshot("appkey", "secretkey", True)
    second = get_account_snapshot("appkey", "secretkey", True)

    assert first is second
    assert fake_client.calls == ["deposit", "holdings"]  # 두 번째 호출은 캐시로 응답, 재조회 없음
