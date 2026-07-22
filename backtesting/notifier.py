"""텔레그램 알림 — 실계좌 자동매매의 체결/오류/kill switch 이벤트를 즉시 통지.

알림 발송 실패가 매매 루프를 막으면 안 되므로, 모든 함수는 예외를 밖으로 던지지
않고 성공 여부(bool)만 반환한다. 이메일 채널은 이 세션 범위 밖 — 필요해지면
send_telegram과 같은 형태의 send_email을 추가하고 notify_* 함수들이 두 채널을
모두 호출하도록 확장하면 된다 (Design §1.2).
"""
import requests

TELEGRAM_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 10


def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    """텔레그램 Bot API로 메시지 1건 전송. 실패해도 예외를 올리지 않는다."""
    if not bot_token or not chat_id:
        return False
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        res = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=REQUEST_TIMEOUT_SECONDS)
        res.raise_for_status()
        return True
    except Exception:
        return False


def notify_order_filled(side: str, code: str, quantity: int, price: float, bot_token: str, chat_id: str) -> bool:
    label = "매수" if side == "buy" else "매도"
    message = f"[체결] {label} {code} {quantity}주 @ {price:,.0f}원"
    return send_telegram(message, bot_token, chat_id)


def notify_error(context: str, exc: Exception, bot_token: str, chat_id: str) -> bool:
    message = f"[오류] {context}: {exc}"
    return send_telegram(message, bot_token, chat_id)


def notify_kill_switch(realized_pnl_krw: float, threshold_krw: float, bot_token: str, chat_id: str) -> bool:
    message = (
        f"[KILL SWITCH 발동] 당일 실현손익 {realized_pnl_krw:,.0f}원 "
        f"(한도 -{threshold_krw:,.0f}원) — 신규 진입 중단"
    )
    return send_telegram(message, bot_token, chat_id)
