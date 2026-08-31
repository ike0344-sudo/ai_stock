"""텔레그램 알림 — 실계좌 자동매매의 체결/오류/kill switch 이벤트를 즉시 통지.

알림 발송 실패가 매매 루프를 막으면 안 되므로, 모든 함수는 예외를 밖으로 던지지
않고 성공 여부(bool)만 반환한다. 이메일 채널은 이 세션 범위 밖 — 필요해지면
send_telegram과 같은 형태의 send_email을 추가하고 notify_* 함수들이 두 채널을
모두 호출하도록 확장하면 된다 (Design §1.2).

전략1/2/3이 동시에 돌 때 같은 텔레그램 채팅방으로 알림이 섞여 들어와 어느 전략이
보낸 건지 구분이 안 되는 문제가 있었다 — 모든 notify_* 함수가 strategy(예: "strategy_1")를
필수로 받아 메시지 맨 앞에 `[strategy_1]`처럼 붙인다(cli.py의 시작 로그 `[{mode_label}]
[{strategy}]`와 같은 표기 방식).

알림 등급(monitoring-agent.md §알림 등급): CRITICAL/WARNING/INFO 3단계. notify_* 함수마다
이벤트 성격에 맞는 등급을 고정으로 넘긴다(호출부가 등급을 매번 고를 필요 없음).
CRITICAL은 놓치면 안 되므로 send_telegram이 같은 호출 안에서 CRITICAL_REPEAT_COUNT회
반복 발송한다(재시도 스케줄러 등은 과설계이므로 두지 않음). send_telegram 실패는
호출부에서 조용히 삼키지 않도록 매 실패마다 FAILURE_LOG_PATH에 구조화 로그(JSON
lines)를 남긴다.
"""
import json
import os
from datetime import datetime

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 10

CRITICAL = "critical"
WARNING = "warning"
INFO = "info"

CRITICAL_REPEAT_COUNT = 3

FAILURE_LOG_PATH = "state/notifier_failures.jsonl"


def _log_send_failure(level: str, message: str, detail: str, path: str) -> None:
    """send_telegram 실패를 조용히 삼키지 않고 구조화 로그로 남긴다(monitoring-agent.md
    §금지사항 — 알림 실패를 조용히 삼키는 코드 금지). 로그 기록 자체가 실패해도(디스크
    문제 등) 더 할 수 있는 게 없으므로 조용히 무시한다 — 여기서 예외가 나면 알림 발송
    흐름까지 막힌다."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "agent": "monitoring-agent",
        "level": level,
        "event": "telegram_send_failed",
        "detail": detail,
        "message": message,
    }
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def send_telegram(
    message: str, bot_token: str, chat_id: str, level: str = INFO, failure_log_path: str = FAILURE_LOG_PATH,
) -> bool:
    """텔레그램 Bot API로 메시지 전송. 실패해도 예외를 올리지 않는다(대신 로그를 남김).

    level=CRITICAL이면 CRITICAL_REPEAT_COUNT회 반복 발송한다 — 알림 폭주를 막기 위한
    동일 이벤트 묶음 처리는 호출 빈도가 높은 상위 감시 루프(healthcheck 등)의 책임이고,
    여기서는 "한 번의 중요 이벤트를 놓치지 않는다"만 담당한다. repeat 중 한 번이라도
    성공하면 True(반복은 중복 확인용 안전장치일 뿐, 성공 판정은 1회 성공으로 충분)."""
    repeat = CRITICAL_REPEAT_COUNT if level == CRITICAL else 1
    if not bot_token or not chat_id:
        _log_send_failure(level, message, "bot_token/chat_id 미설정", failure_log_path)
        return False
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    any_ok = False
    for _ in range(repeat):
        try:
            res = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=REQUEST_TIMEOUT_SECONDS)
            res.raise_for_status()
            any_ok = True
        except Exception as exc:
            _log_send_failure(level, message, str(exc), failure_log_path)
    return any_ok


def notify_order_filled(strategy: str, side: str, code: str, quantity: int, price: float, bot_token: str, chat_id: str) -> bool:
    label = "매수" if side == "buy" else "매도"
    message = f"[{strategy}] [체결] {label} {code} {quantity}주 @ {price:,.0f}원"
    return send_telegram(message, bot_token, chat_id, level=INFO)


def notify_signal_detected(strategy: str, code: str, name: str, price: float, proba: float | None, bot_token: str, chat_id: str) -> bool:
    """scan_watchlist_once가 신규 진입 신호를 찾은 즉시(매수 주문 성공 여부와 무관하게)
    통지 — 슬롯 부족 등으로 매수가 스킵되는 신호도 놓치지 않도록 notify_order_filled보다
    먼저, 별도로 호출된다.

    name이 빈 문자열/None이면(watchlist에 없던 코드 등 이름을 못 찾은 경우) 종목코드만
    표시한다 — 알림 자체가 실패하면 안 되므로 이름 조회 실패를 이유로 메시지를 막지 않음.

    proba=None은 ML 게이트가 없는 전략(조건만으로 포착해 진입확률 개념 자체가
    없는 경우)에서 쓴다 — 이 경우 진입확률 문구를 아예 생략한다."""
    label = f"{name}({code})" if name else code
    proba_part = f" (진입확률 {proba:.0%})" if proba is not None else ""
    message = f"[{strategy}] [포착] {label} @ {price:,.0f}원{proba_part}"
    return send_telegram(message, bot_token, chat_id, level=INFO)


def notify_error(strategy: str, context: str, exc: Exception, bot_token: str, chat_id: str) -> bool:
    message = f"[{strategy}] [오류] {context}: {exc}"
    return send_telegram(message, bot_token, chat_id, level=WARNING)


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
    return send_telegram("\n".join(lines), bot_token, chat_id, level=WARNING)


def notify_dashboard_down(reason: str, bot_token: str, chat_id: str) -> bool:
    """대시보드 서버(dashboard_server.py)가 응답하지 않을 때 통지 — dashboard_monitor.py가
    호출한다. 원인(연결 실패/타임아웃/HTTP 5xx 등)을 그대로 붙여 어떤 종류의 장애인지
    바로 구분할 수 있게 한다."""
    return send_telegram(f"[대시보드] 응답 없음: {reason}", bot_token, chat_id, level=WARNING)


def notify_dashboard_recovered(bot_token: str, chat_id: str) -> bool:
    """다운으로 판단된 이후 다시 응답이 돌아왔을 때 통지 — 직접 대시보드를 열어보지
    않아도 복구를 알 수 있게 한다."""
    return send_telegram("[대시보드] 복구됨", bot_token, chat_id, level=INFO)


def notify_sophie_duplicate_process(count: int, bot_token: str, chat_id: str) -> bool:
    """소피증권(ai_stock.exe)이 논리적으로 2개 이상 떠 있을 때 통지 — sophie_feed_monitor.py가
    호출한다. 2026-08-30 실측: 중복 실행된 인스턴스가 8770 포트를 못 받고도(Windows
    ThreadingHTTPServer의 SO_REUSEADDR 특성상 바인드 자체는 예외 없이 "성공"으로 로그된다)
    엔진 루프는 계속 돌아 9시간 넘게 CPU를 낭비했는데 아무도 몰랐다 — 이 알림이 그 사고를
    막기 위한 것이다. 시간대 무관(장중 게이트 없음, CPU 낭비는 언제 나든 문제)."""
    return send_telegram(f"[소피증권] 중복 실행 감지: {count}개 인스턴스", bot_token, chat_id, level=WARNING)


def notify_sophie_duplicate_resolved(bot_token: str, chat_id: str) -> bool:
    """소피증권 중복 실행이 1개 이하로 정리됐을 때 통지."""
    return send_telegram("[소피증권] 중복 실행 정리됨", bot_token, chat_id, level=INFO)


def notify_sophie_feed_down(reason: str, bot_token: str, chat_id: str) -> bool:
    """소피증권(kospi-theme-engine) 실시간 체결 피드가 죽었을 때 통지 —
    sophie_feed_monitor.py가 호출한다. 8770 포트가 열려 있어도 웹소켓 피드가
    멈춰있을 수 있어(2026-08-30 실측 — 6일간 포트는 살아있었는데 알림이 없었다),
    프로세스 생존이 아니라 결과(엔진 틱 카운터·로그 갱신)로 판단한다."""
    return send_telegram(f"[소피증권] 실시간 피드 이상: {reason}", bot_token, chat_id, level=WARNING)


def notify_sophie_feed_recovered(bot_token: str, chat_id: str) -> bool:
    """소피증권 실시간 피드가 다시 정상(틱이 증가하거나 로그가 갱신)으로 돌아왔을 때 통지."""
    return send_telegram("[소피증권] 실시간 피드 정상화", bot_token, chat_id, level=INFO)


def notify_top35_failed(fail_count: int, total: int, failures: list[tuple[str, str, str]],
                        bot_token: str, chat_id: str) -> bool:
    """top35 일일 갱신에서 일부/전체 종목을 못 받았을 때 통지 — top35_job이 호출한다.
    데이터가 하루 비면 그날 백테스트/리포트가 조용히 낡은 채로 돌아가므로 WARNING.

    실패 사유를 종목별로 붙인다(DNS 실패인지 상장폐지인지에 따라 대응이 다름).
    사유가 길어 메시지가 잘리는 걸 막으려고 종목당 앞 120자만 싣는다."""
    lines = [f"{code} {name}: {reason[:120]}" for code, name, reason in failures[:5]]
    if len(failures) > 5:
        lines.append(f"... 외 {len(failures) - 5}종목")
    header = f"[top35 갱신] {total}종목 중 {fail_count}종목 실패"
    return send_telegram("\n".join([header] + lines), bot_token, chat_id, level=WARNING)


def notify_kill_switch(strategy: str, realized_pnl_krw: float, threshold_krw: float, bot_token: str, chat_id: str) -> bool:
    message = (
        f"[{strategy}] [KILL SWITCH 발동] 당일 실현손익 {realized_pnl_krw:,.0f}원 "
        f"(한도 -{threshold_krw:,.0f}원) — 신규 진입 중단"
    )
    return send_telegram(message, bot_token, chat_id, level=CRITICAL)


def notify_feed_stale(strategy: str, age_seconds: float, bot_token: str, chat_id: str) -> bool:
    """실시간 피드가 소켓은 열린 채 데이터만 끊겼을 때 통지 — trading_loop이
    get_feed_age_seconds()를 폴링해 호출한다. 피드가 끊겨도 fetch_today_candles가 REST로
    폴백하므로 매매가 멈추지는 않는다(그래서 CRITICAL이 아니다). 다만 REST 폴백은 느리고
    rate limit을 먹으므로 조용히 방치하면 안 된다."""
    message = f"[{strategy}] [실시간피드] {age_seconds:.0f}초째 틱 없음 — REST 폴백으로 동작 중"
    return send_telegram(message, bot_token, chat_id, level=WARNING)


def notify_feed_recovered(strategy: str, bot_token: str, chat_id: str) -> bool:
    """끊겼던 실시간 피드에 다시 틱이 들어왔을 때 통지."""
    return send_telegram(f"[{strategy}] [실시간피드] 복구됨", bot_token, chat_id, level=INFO)


def notify_reconcile_mismatch(strategy: str, report, bot_token: str, chat_id: str) -> bool:
    """계좌 대사(reconcile) 불일치 통지. 내부 상태를 믿을 수 없다는 뜻이라 CRITICAL이다 —
    특히 broker_only(브로커엔 있는데 내부엔 없는 종목)는 손절 감시가 안 붙은 채 방치되는
    포지션이므로 사람이 즉시 봐야 한다.

    report는 reconcile.ReconcileReport — 타입 힌트를 붙이면 notifier가 매매 모듈을
    import하게 되므로 덕타이핑으로 받는다(알림 모듈은 어느 도메인에도 의존하지 않는다)."""
    lines = [f"[{strategy}] [계좌 대사 불일치] 내부 상태와 브로커 보유가 어긋납니다 — 신규 진입 차단"]
    for m in report.quantity_mismatches[:5]:
        lines.append(f"- 수량 불일치 {m['code']}: 내부 {m['internal_qty']}주 / 브로커 {m['broker_qty']}주")
    if report.broker_only:
        lines.append(f"- 브로커에만 있음(손절 감시 없음): {', '.join(report.broker_only[:5])}")
    if report.internal_only:
        lines.append(f"- 내부에만 있음(유령 포지션): {', '.join(report.internal_only[:5])}")
    return send_telegram("\n".join(lines), bot_token, chat_id, level=CRITICAL)


def notify_reconcile_failed(strategy: str, exc: Exception, bot_token: str, chat_id: str) -> bool:
    """계좌 대사를 위한 브로커 조회 자체가 실패했을 때 통지. 조회 실패는 불일치의 증거가
    아니므로(토큰 만료·일시 장애 등) 매매를 막지 않고 WARNING만 남긴다."""
    return send_telegram(f"[{strategy}] [계좌 대사] 조회 실패로 확인 못 함: {exc}", bot_token, chat_id, level=WARNING)
