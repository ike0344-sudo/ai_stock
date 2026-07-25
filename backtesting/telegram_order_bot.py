"""텔레그램에서 /buy, /sell 명령으로 시장가 주문 — getUpdates 롱폴링으로 메시지를
받아 Kiwoom API에 그대로 전달한다. 실제 계좌에 주문이 나가는 기능이라 .env의
TELEGRAM_CHAT_ID(알림 수신용으로 이미 쓰는 값)와 정확히 일치하는 발신자의 메시지만
처리하고, 그 외 chat_id는 응답 없이 조용히 무시한다(봇 존재 자체를 노출하지 않음).

dashboard_server.py와 마찬가지로 trading_loop.py를 import하지 않는 완전히 분리된
프로세스다.

명령 형식:
    /buy <종목코드6자리> <수량>
    /sell <종목코드6자리> <수량>
"""
import time

import requests

from kiwoom_client import KiwoomClient

from .account_status import invalidate_cache
from .notifier import send_telegram

TELEGRAM_API_BASE = "https://api.telegram.org"
POLL_TIMEOUT_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = POLL_TIMEOUT_SECONDS + 10
RETRY_DELAY_SECONDS = 5

USAGE_MESSAGE = "사용법: /buy <종목코드> <수량> 또는 /sell <종목코드> <수량> (예: /buy 005930 10)"


def _get_updates(bot_token: str, offset: int | None) -> list[dict]:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/getUpdates"
    params = {"timeout": POLL_TIMEOUT_SECONDS}
    if offset is not None:
        params["offset"] = offset
    res = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    res.raise_for_status()
    return res.json().get("result", [])


def parse_order_command(text: str) -> tuple[str, str, int] | None:
    """"/buy 005930 10" -> ("buy", "005930", 10). 형식이 안 맞으면 None."""
    parts = text.strip().split()
    if len(parts) != 3:
        return None
    cmd, code, qty_str = parts
    side = {"/buy": "buy", "/sell": "sell"}.get(cmd)
    if side is None:
        return None
    if not (code.isdigit() and len(code) == 6):
        return None
    try:
        quantity = int(qty_str)
    except ValueError:
        return None
    if quantity <= 0:
        return None
    return side, code, quantity


def _execute_order(
    side: str, code: str, quantity: int,
    appkey: str, secretkey: str, is_mock: bool,
    bot_token: str, chat_id: str,
) -> None:
    client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
    result = client.place_order(code, side, quantity, order_type="3")
    ok = result.get("return_code") == 0
    if ok:
        invalidate_cache()
    label = "매수" if side == "buy" else "매도"
    mode = "모의" if is_mock else "실전"
    if ok:
        message = f"[{mode}][{label} 접수] {code} {quantity}주 (시장가)"
    else:
        message = f"[{mode}][{label} 실패] {code} {quantity}주 — {result.get('return_msg', '')}"
    print(message, flush=True)
    send_telegram(message, bot_token, chat_id)


def _handle_update(
    update: dict,
    allowed_chat_id: str,
    appkey: str, secretkey: str, is_mock: bool,
    bot_token: str,
) -> None:
    message = update.get("message") or {}
    sender_chat_id = str(message.get("chat", {}).get("id", ""))
    if sender_chat_id != allowed_chat_id:
        print(f"무단 발신자 무시: chat_id={sender_chat_id}", flush=True)
        return  # 허용되지 않은 발신자 — 응답 없이 무시
    text = message.get("text", "")
    print(f"명령 수신: {text!r}", flush=True)
    parsed = parse_order_command(text)
    if parsed is None:
        print("형식 오류 — 사용법 안내 회신", flush=True)
        send_telegram(USAGE_MESSAGE, bot_token, allowed_chat_id)
        return
    side, code, quantity = parsed
    _execute_order(side, code, quantity, appkey, secretkey, is_mock, bot_token, allowed_chat_id)


def run_telegram_order_bot(
    bot_token: str, chat_id: str,
    appkey: str, secretkey: str, is_mock: bool = True,
) -> None:
    """블로킹 롱폴링 루프. Ctrl+C로 중단."""
    if not bot_token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID가 .env에 설정되어야 합니다")

    allowed_chat_id = str(chat_id)
    mode = "모의" if is_mock else "실전"
    print(f"텔레그램 주문 봇 시작 ({mode}투자, chat_id={allowed_chat_id}만 허용) — Ctrl+C로 중단", flush=True)

    offset = None
    try:
        while True:
            try:
                updates = _get_updates(bot_token, offset)
            except Exception as exc:
                print(f"업데이트 조회 실패, {RETRY_DELAY_SECONDS}초 후 재시도: {exc}", flush=True)
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                _handle_update(update, allowed_chat_id, appkey, secretkey, is_mock, bot_token)
    except KeyboardInterrupt:
        pass
