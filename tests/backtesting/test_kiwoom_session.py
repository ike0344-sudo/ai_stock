import pytest

from backtesting import kiwoom_session
from backtesting.kiwoom_session import get_client


@pytest.fixture(autouse=True)
def reset_client():
    kiwoom_session._client = None
    yield
    kiwoom_session._client = None


def test_get_client_constructs_once(monkeypatch):
    construction_calls = []
    monkeypatch.setattr(
        kiwoom_session, "KiwoomClient",
        lambda appkey, secretkey, is_mock: construction_calls.append((appkey, secretkey, is_mock)) or "fake-client",
    )

    first = get_client("appkey", "secretkey", True)
    second = get_client("appkey", "secretkey", True)

    assert first is second == "fake-client"
    assert construction_calls == [("appkey", "secretkey", True)]


def test_get_client_shared_across_different_callers(monkeypatch):
    # market_snapshot.py/account_status.py처럼 서로 다른 모듈이 각자 get_client를
    # 불러도 같은 인스턴스를 받아야 한다(그래야 요청 간격 페이싱이 프로세스 전역으로
    # 이어진다) — 두 "모듈"을 흉내내기 위해 그냥 두 번 다른 인자로 호출해본다.
    monkeypatch.setattr(kiwoom_session, "KiwoomClient", lambda appkey, secretkey, is_mock: object())

    from_market = get_client("appkey", "secretkey", True)
    from_account = get_client("appkey", "secretkey", True)

    assert from_market is from_account
