import pytest

from backtesting import telegram_order_bot
from backtesting.telegram_order_bot import (
    USAGE_MESSAGE,
    _execute_order,
    _handle_update,
    parse_order_command,
    run_telegram_order_bot,
)


# --- parse_order_command ---

def test_parse_order_command_buy():
    assert parse_order_command("/buy 005930 10") == ("buy", "005930", 10)


def test_parse_order_command_sell():
    assert parse_order_command("/sell 000660 3") == ("sell", "000660", 3)


def test_parse_order_command_extra_whitespace():
    assert parse_order_command("  /buy 005930 10  ") == ("buy", "005930", 10)


@pytest.mark.parametrize("text", [
    "/buy 005930",
    "/buy 005930 10 20",
    "/hold 005930 10",
    "hello",
    "",
    "/buy 12345 10",  # 5자리 종목코드
    "/buy AAAAAA 10",  # 숫자가 아닌 종목코드
    "/buy 005930 0",  # 수량 0
    "/buy 005930 -1",  # 음수 수량
    "/buy 005930 abc",  # 수량이 숫자가 아님
])
def test_parse_order_command_rejects_invalid_formats(text):
    assert parse_order_command(text) is None


# --- _execute_order ---

class _StubKiwoomClient:
    def __init__(self, result):
        self._result = result
        self.calls = []
        self.call_kwargs = []

    def place_order(self, code, side, quantity, **kwargs):
        self.calls.append((code, side, quantity))
        self.call_kwargs.append(kwargs)
        return self._result


def test_execute_order_sends_success_message_and_invalidates_cache(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        telegram_order_bot, "KiwoomClient",
        lambda appkey, secretkey, is_mock: _StubKiwoomClient({"return_code": 0}),
    )
    monkeypatch.setattr(telegram_order_bot, "invalidate_cache", lambda: captured.setdefault("invalidated", True))
    monkeypatch.setattr(
        telegram_order_bot, "send_telegram",
        lambda message, bot_token, chat_id: captured.setdefault("message", message) or True,
    )

    _execute_order("buy", "005930", 10, "APPKEY", "SECRET", True, "TOKEN", "CHAT")

    assert captured.get("invalidated") is True
    assert "매수" in captured["message"]
    assert "005930" in captured["message"]


def test_execute_order_sends_failure_message_and_does_not_invalidate_cache(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        telegram_order_bot, "KiwoomClient",
        lambda appkey, secretkey, is_mock: _StubKiwoomClient({"return_code": 1, "return_msg": "잔고 부족"}),
    )
    monkeypatch.setattr(telegram_order_bot, "invalidate_cache", lambda: captured.setdefault("invalidated", True))
    monkeypatch.setattr(
        telegram_order_bot, "send_telegram",
        lambda message, bot_token, chat_id: captured.setdefault("message", message) or True,
    )

    _execute_order("sell", "005930", 10, "APPKEY", "SECRET", True, "TOKEN", "CHAT")

    assert "invalidated" not in captured
    assert "실패" in captured["message"]
    assert "잔고 부족" in captured["message"]


def test_execute_order_places_market_order_explicitly(monkeypatch):
    # kiwoom_client.place_order 기본값이 지정가로 바뀌었으므로, 텔레그램 명령이 원래
    # 의도한 시장가 주문을 유지하려면 order_type="3"을 명시적으로 넘겨야 한다.
    stub_client = _StubKiwoomClient({"return_code": 0})
    monkeypatch.setattr(telegram_order_bot, "KiwoomClient", lambda appkey, secretkey, is_mock: stub_client)
    monkeypatch.setattr(telegram_order_bot, "invalidate_cache", lambda: None)
    monkeypatch.setattr(telegram_order_bot, "send_telegram", lambda *a, **k: True)

    _execute_order("buy", "005930", 10, "APPKEY", "SECRET", True, "TOKEN", "CHAT")

    assert stub_client.call_kwargs == [{"order_type": "3"}]


# --- _handle_update (인가 필터링) ---

def _message_update(chat_id, text):
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


def test_handle_update_ignores_unauthorized_chat_id(monkeypatch):
    called = {"execute": False, "usage": False}
    monkeypatch.setattr(telegram_order_bot, "_execute_order", lambda *a, **k: called.__setitem__("execute", True))
    monkeypatch.setattr(telegram_order_bot, "send_telegram", lambda *a, **k: called.__setitem__("usage", True))

    _handle_update(_message_update(999, "/buy 005930 10"), "123", "APPKEY", "SECRET", True, "TOKEN")

    assert called["execute"] is False
    assert called["usage"] is False  # 무단 발신자에게는 응답조차 하지 않음


def test_handle_update_executes_order_for_authorized_chat_id(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        telegram_order_bot, "_execute_order",
        lambda side, code, quantity, appkey, secretkey, is_mock, bot_token, chat_id: captured.update(
            side=side, code=code, quantity=quantity, chat_id=chat_id,
        ),
    )

    _handle_update(_message_update(123, "/sell 005930 5"), "123", "APPKEY", "SECRET", True, "TOKEN")

    assert captured == {"side": "sell", "code": "005930", "quantity": 5, "chat_id": "123"}


def test_handle_update_sends_usage_for_authorized_chat_id_with_bad_command(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        telegram_order_bot, "send_telegram",
        lambda message, bot_token, chat_id: captured.update(message=message, chat_id=chat_id),
    )

    _handle_update(_message_update(123, "무슨 명령이지?"), "123", "APPKEY", "SECRET", True, "TOKEN")

    assert captured["message"] == USAGE_MESSAGE
    assert captured["chat_id"] == "123"


# --- run_telegram_order_bot ---

def test_run_telegram_order_bot_raises_without_bot_token():
    with pytest.raises(ValueError):
        run_telegram_order_bot(bot_token="", chat_id="123", appkey="A", secretkey="S")


def test_run_telegram_order_bot_raises_without_chat_id():
    with pytest.raises(ValueError):
        run_telegram_order_bot(bot_token="TOKEN", chat_id="", appkey="A", secretkey="S")
