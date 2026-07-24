"""텔레그램 알림 — 실계좌 자동매매의 체결/오류/kill switch 이벤트를 즉시 통지.

알림 발송 실패가 매매 루프를 막으면 안 되므로, 모든 함수는 예외를 밖으로 던지지
않고 성공 여부(bool)만 반환한다. 이메일 채널은 이 세션 범위 밖 — 필요해지면
send_telegram과 같은 형태의 send_email을 추가하고 notify_* 함수들이 두 채널을
모두 호출하도록 확장하면 된다 (Design §1.2).

전략1/2/3이 동시에 돌 때 같은 텔레그램 채팅방으로 알림이 섞여 들어와 어느 전략이
보낸 건지 구분이 안 되는 문제가 있었다 — 모든 notify_* 함수가 strategy(예: "strategy_1")를
필수로 받아 메시지 맨 앞에 `[strategy_1]`처럼 붙인다(cli.py의 시작 로그 `[{mode_label}]
[{strategy}]`와 같은 표기 방식).
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


def notify_order_filled(strategy: str, side: str, code: str, quantity: int, price: float, bot_token: str, chat_id: str) -> bool:
    label = "매수" if side == "buy" else "매도"
    message = f"[{strategy}] [체결] {label} {code} {quantity}주 @ {price:,.0f}원"
    return send_telegram(message, bot_token, chat_id)


def notify_signal_detected(strategy: str, code: str, name: str, price: float, proba: float | None, bot_token: str, chat_id: str) -> bool:
    """scan_watchlist_once가 신규 진입 신호를 찾은 즉시(매수 주문 성공 여부와 무관하게)
    통지 — 슬롯 부족 등으로 매수가 스킵되는 신호도 놓치지 않도록 notify_order_filled보다
    먼저, 별도로 호출된다.

    name이 빈 문자열/None이면(watchlist에 없던 코드 등 이름을 못 찾은 경우) 종목코드만
    표시한다 — 알림 자체가 실패하면 안 되므로 이름 조회 실패를 이유로 메시지를 막지 않음.

    proba=None은 ML 게이트가 없는 전략(예: strategy3_scalp — 조건만으로 포착, 진입확률
    개념 자체가 없음)에서 쓴다 — 이 경우 진입확률 문구를 아예 생략한다."""
    label = f"{name}({code})" if name else code
    proba_part = f" (진입확률 {proba:.0%})" if proba is not None else ""
    message = f"[{strategy}] [포착] {label} @ {price:,.0f}원{proba_part}"
    return send_telegram(message, bot_token, chat_id)


def notify_error(strategy: str, context: str, exc: Exception, bot_token: str, chat_id: str) -> bool:
    message = f"[{strategy}] [오류] {context}: {exc}"
    return send_telegram(message, bot_token, chat_id)


def notify_nasdaq_drop(change_pct: float, price: float, headlines: list[str], bot_token: str, chat_id: str) -> bool:
    """나스닥100 선물이 짧은 시간 안에 급락했을 때 통지. 가격 데이터만으로는 원인을
    확정할 수 없으므로, 그 시점 관련 뉴스 헤드라인(자동 검색 — 인과관계 보장 없음,
    참고자료일 뿐)을 같이 보낸다."""
    lines = [f"[나스닥100 선물] 급락 감지: {change_pct:+.2f}% (현재 {price:,.2f})"]
    if headlines:
        lines.append("관련 뉴스(참고용 — 원인 확정 아님):")
        lines.extend(f"- {h}" for h in headlines)
    else:
        lines.append("관련 뉴스를 가져오지 못했습니다.")
    return send_telegram("\n".join(lines), bot_token, chat_id)


def notify_kill_switch(strategy: str, realized_pnl_krw: float, threshold_krw: float, bot_token: str, chat_id: str) -> bool:
    message = (
        f"[{strategy}] [KILL SWITCH 발동] 당일 실현손익 {realized_pnl_krw:,.0f}원 "
        f"(한도 -{threshold_krw:,.0f}원) — 신규 진입 중단"
    )
    return send_telegram(message, bot_token, chat_id)
