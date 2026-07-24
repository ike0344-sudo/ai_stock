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

    def get_account_evaluation(self, exchange="KRX"):
        self.calls.append("holdings")
        self.last_exchange = exchange
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


def test_holdings_snapshot_requests_sor_combined_exchange_for_nxt_hours():
    # NXT(08:00~20:00)는 KRX 정규장(09:00~15:30) 밖에서도 거래되므로, 그 시간대에도
    # 평가손익이 갱신되려면 KRX 단독이 아니라 통합(SOR) 시세로 조회해야 한다.
    client = _FakeClient(holdings_payload=HOLDINGS_PAYLOAD)

    _holdings_snapshot(client)

    assert client.last_exchange == "SOR"


def test_holdings_snapshot_returns_empty_list_when_no_holdings():
    client = _FakeClient(holdings_payload={"stk_acnt_evlt_prst": [], "return_code": 0})

    assert _holdings_snapshot(client) == []


def test_holdings_snapshot_returns_none_when_client_raises():
    client = _FakeClient(holdings_error=RuntimeError("network down"))

    assert _holdings_snapshot(client) is None


# ---- get_account_snapshot ----

def test_get_account_snapshot_combines_deposit_and_holdings(monkeypatch):
    fake_client = _FakeClient(deposit_payload=DEPOSIT_PAYLOAD, holdings_payload=HOLDINGS_PAYLOAD)
    monkeypatch.setattr(account_status, "get_client", lambda appkey, secretkey, is_mock: fake_client)

    snapshot = get_account_snapshot("appkey", "secretkey", True)

    assert snapshot["deposit"]["deposit_krw"] == 10_000_000
    assert snapshot["holdings"][0]["code"] == "005930"
    assert fake_client.calls == ["deposit", "holdings"]


def test_get_account_snapshot_skips_kiwoom_when_credentials_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(account_status, "get_client", lambda *a, **k: calls.append(1))

    snapshot = get_account_snapshot("", "", True)

    assert snapshot == {"deposit": None, "holdings": None}
    assert calls == []


def test_get_account_snapshot_uses_cache_within_ttl(monkeypatch):
    fake_client = _FakeClient(deposit_payload=DEPOSIT_PAYLOAD, holdings_payload=HOLDINGS_PAYLOAD)
    monkeypatch.setattr(account_status, "get_client", lambda appkey, secretkey, is_mock: fake_client)

    first = get_account_snapshot("appkey", "secretkey", True)
    second = get_account_snapshot("appkey", "secretkey", True)

    assert first is second
    assert fake_client.calls == ["deposit", "holdings"]  # 두 번째 호출은 캐시로 응답, 재조회 없음


def test_get_account_snapshot_keeps_previous_deposit_when_refetch_fails(monkeypatch):
    # 예수금 조회만 일시적으로 실패해도, 화면이 60초간 "실패"로 고정되지 않고
    # 직전 성공값을 그대로 보여줘야 한다(보유종목은 이번 조회의 새 값으로 갱신).
    good_client = _FakeClient(deposit_payload=DEPOSIT_PAYLOAD, holdings_payload=HOLDINGS_PAYLOAD)
    monkeypatch.setattr(account_status, "get_client", lambda appkey, secretkey, is_mock: good_client)
    first = get_account_snapshot("appkey", "secretkey", True)
    account_status._cached_at = 0.0  # TTL 강제 만료

    failing_client = _FakeClient(deposit_error=RuntimeError("일시적 오류"), holdings_payload={"stk_acnt_evlt_prst": [], "return_code": 0})
    monkeypatch.setattr(account_status, "get_client", lambda appkey, secretkey, is_mock: failing_client)

    second = get_account_snapshot("appkey", "secretkey", True)

    assert second["deposit"] == first["deposit"]  # 실패한 필드는 직전 값 유지
    assert second["holdings"] == []  # 성공한 필드는 새 값으로 갱신(빈 보유종목)
