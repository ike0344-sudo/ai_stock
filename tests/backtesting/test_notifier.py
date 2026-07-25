import json

import pytest

from backtesting import notifier
from backtesting.notifier import (
    notify_dashboard_down,
    notify_dashboard_recovered,
    notify_error,
    notify_kill_switch,
    notify_nasdaq_drop,
    notify_order_filled,
    notify_signal_detected,
    send_telegram,
)


class _StubResponse:
    def __init__(self, status_ok=True):
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise RuntimeError("HTTP 500")


def test_send_telegram_posts_correct_url_and_payload(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return _StubResponse()

    monkeypatch.setattr(notifier.requests, "post", fake_post)

    result = send_telegram("테스트 메시지", bot_token="TOKEN123", chat_id="CHAT456")

    assert result is True
    assert captured["url"] == "https://api.telegram.org/botTOKEN123/sendMessage"
    assert captured["json"] == {"chat_id": "CHAT456", "text": "테스트 메시지"}


def test_send_telegram_returns_false_when_bot_token_missing():
    assert send_telegram("메시지", bot_token="", chat_id="CHAT456") is False


def test_send_telegram_returns_false_when_chat_id_missing():
    assert send_telegram("메시지", bot_token="TOKEN123", chat_id="") is False


def test_send_telegram_returns_false_on_network_exception_without_raising(monkeypatch):
    def fake_post(url, json, timeout):
        raise ConnectionError("네트워크 오류")

    monkeypatch.setattr(notifier.requests, "post", fake_post)

    result = send_telegram("메시지", bot_token="TOKEN123", chat_id="CHAT456")

    assert result is False  # 예외가 밖으로 전파되지 않아야 함


def test_send_telegram_returns_false_on_http_error_status(monkeypatch):
    monkeypatch.setattr(notifier.requests, "post", lambda url, json, timeout: _StubResponse(status_ok=False))

    result = send_telegram("메시지", bot_token="TOKEN123", chat_id="CHAT456")

    assert result is False


def _capturing_send_telegram(captured):
    def fake(message, bot_token, chat_id, level=notifier.INFO, **kwargs):
        captured["message"] = message
        captured["level"] = level
        return True
    return fake


def test_notify_order_filled_formats_buy_message(monkeypatch):
    captured = {}
    monkeypatch.setattr(notifier, "send_telegram", _capturing_send_telegram(captured))

    notify_order_filled("strategy_1", "buy", "005930", 10, 70000, "TOKEN", "CHAT")

    assert "[strategy_1]" in captured["message"]
    assert "매수" in captured["message"]
    assert "005930" in captured["message"]
    assert "10" in captured["message"]
    assert captured["level"] == notifier.INFO


def test_notify_order_filled_formats_sell_message(monkeypatch):
    captured = {}
    monkeypatch.setattr(notifier, "send_telegram", _capturing_send_telegram(captured))

    notify_order_filled("strategy_1", "sell", "005930", 10, 71000, "TOKEN", "CHAT")

    assert "매도" in captured["message"]


def test_notify_error_includes_context_and_exception_message(monkeypatch):
    captured = {}
    monkeypatch.setattr(notifier, "send_telegram", _capturing_send_telegram(captured))

    notify_error("strategy_1", "주문 실행 실패", ValueError("잔고 부족"), "TOKEN", "CHAT")

    assert "[strategy_1]" in captured["message"]
    assert "주문 실행 실패" in captured["message"]
    assert "잔고 부족" in captured["message"]
    assert captured["level"] == notifier.WARNING


def test_notify_signal_detected_includes_strategy_name_code_price_and_proba(monkeypatch):
    captured = {}
    monkeypatch.setattr(notifier, "send_telegram", _capturing_send_telegram(captured))

    notify_signal_detected("strategy_1", "005930", "삼성전자", 70000, 0.732, "TOKEN", "CHAT")

    assert "[strategy_1]" in captured["message"]
    assert "삼성전자" in captured["message"]
    assert "005930" in captured["message"]
    assert "70,000" in captured["message"]
    assert "73%" in captured["message"]
    assert captured["level"] == notifier.INFO


def test_notify_signal_detected_falls_back_to_code_only_when_name_unknown(monkeypatch):
    # watchlist에 없던 코드 등 이름을 못 찾은 경우 — 이름 조회 실패로 알림 자체가
    # 막히면 안 되므로 코드만이라도 표시한다.
    captured = {}
    monkeypatch.setattr(notifier, "send_telegram", _capturing_send_telegram(captured))

    notify_signal_detected("strategy_1", "005930", "", 70000, 0.732, "TOKEN", "CHAT")

    assert "005930" in captured["message"]
    assert "()" not in captured["message"]


def test_notify_signal_detected_omits_proba_clause_when_none(monkeypatch):
    # strategy3_scalp처럼 ML 게이트가 없는 전략은 진입확률 개념이 없어 proba=None을
    # 넘긴다 — 이때 메시지에 "진입확률" 문구 자체가 없어야 한다.
    captured = {}
    monkeypatch.setattr(notifier, "send_telegram", _capturing_send_telegram(captured))

    notify_signal_detected("strategy_3", "005930", "삼성전자", 70000, None, "TOKEN", "CHAT")

    assert "005930" in captured["message"]
    assert "70,000" in captured["message"]
    assert "진입확률" not in captured["message"]


def test_notify_kill_switch_includes_strategy_pnl_and_threshold(monkeypatch):
    captured = {}
    monkeypatch.setattr(notifier, "send_telegram", _capturing_send_telegram(captured))

    notify_kill_switch("strategy_1", -550_000, 500_000, "TOKEN", "CHAT")

    assert "[strategy_1]" in captured["message"]
    assert "550,000" in captured["message"] or "-550000" in captured["message"].replace(",", "")
    assert "500,000" in captured["message"] or "500000" in captured["message"].replace(",", "")
    assert captured["level"] == notifier.CRITICAL


def test_notify_nasdaq_drop_includes_change_pct_price_and_headlines(monkeypatch):
    captured = {}
    monkeypatch.setattr(notifier, "send_telegram", _capturing_send_telegram(captured))

    notify_nasdaq_drop(-1.23, 18000.5, ["Fed 발언 관련 헤드라인", "지정학 리스크 헤드라인"], "TOKEN", "CHAT")

    assert "-1.23" in captured["message"]
    assert "18,000.5" in captured["message"] or "18000.5" in captured["message"]
    assert "Fed 발언 관련 헤드라인" in captured["message"]
    assert "지정학 리스크 헤드라인" in captured["message"]
    assert captured["level"] == notifier.WARNING


def test_notify_nasdaq_drop_handles_empty_headlines(monkeypatch):
    captured = {}
    monkeypatch.setattr(notifier, "send_telegram", _capturing_send_telegram(captured))

    notify_nasdaq_drop(-1.5, 17800.0, [], "TOKEN", "CHAT")

    assert "가져오지 못했습니다" in captured["message"]


def test_notify_dashboard_down_includes_reason(monkeypatch):
    captured = {}
    monkeypatch.setattr(notifier, "send_telegram", _capturing_send_telegram(captured))

    notify_dashboard_down("Connection refused", "TOKEN", "CHAT")

    assert "대시보드" in captured["message"]
    assert "Connection refused" in captured["message"]
    assert captured["level"] == notifier.WARNING


def test_notify_dashboard_recovered_sends_message(monkeypatch):
    captured = {}
    monkeypatch.setattr(notifier, "send_telegram", _capturing_send_telegram(captured))

    notify_dashboard_recovered("TOKEN", "CHAT")

    assert "대시보드" in captured["message"]
    assert "복구" in captured["message"]
    assert captured["level"] == notifier.INFO


def test_send_telegram_repeats_for_critical_level(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)
        return _StubResponse()

    monkeypatch.setattr(notifier.requests, "post", fake_post)

    result = send_telegram("긴급", bot_token="TOKEN123", chat_id="CHAT456", level=notifier.CRITICAL)

    assert result is True
    assert len(calls) == notifier.CRITICAL_REPEAT_COUNT


def test_send_telegram_sends_once_for_non_critical_level(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)
        return _StubResponse()

    monkeypatch.setattr(notifier.requests, "post", fake_post)

    send_telegram("일반", bot_token="TOKEN123", chat_id="CHAT456", level=notifier.WARNING)

    assert len(calls) == 1


def test_send_telegram_logs_failure_on_network_exception(monkeypatch, tmp_path):
    def fake_post(url, json, timeout):
        raise ConnectionError("네트워크 오류")

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    log_path = str(tmp_path / "notifier_failures.jsonl")

    result = send_telegram(
        "메시지", bot_token="TOKEN123", chat_id="CHAT456", level=notifier.WARNING, failure_log_path=log_path,
    )

    assert result is False
    lines = (tmp_path / "notifier_failures.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["level"] == notifier.WARNING
    assert entry["event"] == "telegram_send_failed"
    assert "네트워크 오류" in entry["detail"]


def test_send_telegram_logs_failure_when_bot_token_missing(tmp_path):
    log_path = str(tmp_path / "notifier_failures.jsonl")

    result = send_telegram("메시지", bot_token="", chat_id="CHAT456", failure_log_path=log_path)

    assert result is False
    lines = (tmp_path / "notifier_failures.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["detail"] == "bot_token/chat_id 미설정"
