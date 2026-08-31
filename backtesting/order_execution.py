"""주문 실행 계층 — 체결확인/부분체결추적/미체결 타임아웃/재시도.

execution-agent.md 담당 업무 §2~4 구현. place_order 이후의 흐름만 다룬다 —
리스크 심사(check_order)는 risk_manager.py의 단일 책임이라 여기서 다시 하지
않는다. 호출자는 이미 승인된 신호에서만 submit_order를 불러야 하며,
submit_order의 approved 체크는 그 위의 마지막 방어선일 뿐이다
(execution-agent.md §핵심원칙 1 — 리스크 승인 없는 주문은 존재하지 않는다).

trading_loop.py가 이 모듈의 함수들을 호출한다(2026-08-29 배선 완료).
"""
import json
import os
import time
import uuid
from dataclasses import dataclass

import requests

from kiwoom_client import KiwoomClient

# risk_state_lock은 이름과 달리 risk_state 전용이 아니라 "여러 프로세스가 공유하는
# 파일 하나를 O_CREAT|O_EXCL로 상호배제"하는 범용 유틸이다(risk_manager.py) — 여기서는
# risk 판단이 아니라 그 락만 재사용한다(새 락 구현 금지 지시, 2026-08-29).
from .risk_manager import risk_state_lock

DEFAULT_ORDER_TRACKING_LOG_PATH = "state/order_tracking.jsonl"


def _order_rejected(response: dict) -> RuntimeError | None:
    """place_order 응답이 거부(return_code!=0)면 RuntimeError로, 정상 체결이면
    None을 반환한다. request_tr()은 HTTP 레벨 오류만 예외로 던지고, 주문 거부는
    HTTP 200 + return_code!=0으로 응답에 실려 온다 — 이 체크 없이 응답을 무조건
    성공으로 취급하면 실제로는 거부된 주문이 risk_state에 "체결"로 기록되는
    phantom position이 생긴다.

    trading_loop.py/oversold_trading_loop.py에 있던 동일 함수를 이곳으로 옮겼다 —
    order_execution이 trading_loop을 import하면(원래 위치) trading_loop이
    order_execution을 import하는 것과 순환참조가 생긴다. 두 모듈 다 이 함수를
    trading_loop 이름으로 계속 쓸 수 있도록 trading_loop.py에서 재수출한다."""
    return_code = response.get("return_code")
    if return_code == 0:
        return None
    return RuntimeError(f"return_code={return_code} {response.get('return_msg', '')}".strip())

# 통신 오류(RequestException)만 재시도 대상이다. 잔고부족/호가오류 등 브로커가 명시
# 거부한 응답은 HTTP 200 + return_code!=0으로 오므로 예외가 아니라 _order_rejected로
# 갈라진다 — 재시도해도 소용없어 즉시 반환한다(execution-agent.md §4).
RETRYABLE_EXCEPTIONS = (requests.exceptions.RequestException,)

_ORD_NO_KEYS = ("ord_no",)
# ka10075(미체결요청) 응답의 잔량 필드명은 실계좌로 검증된 바 없다(reconcile.py:5-8과
# 같은 사유) — 후보 키를 순서대로 시도하고, 전부 없으면 "unknown"으로 남겨 잘못된
# 값을 체결로 오인하지 않는다. 실계좌 첫 응답을 받으면 여기를 확정 키 하나로 좁힐 것.
_REMAINING_QTY_KEYS = ("oso_qty", "rmn_qty", "rmnd_qty", "ord_rmnd_qty", "unfilled_qty")


@dataclass
class TrackedOrder:
    client_order_id: str
    stock_code: str
    side: str
    ordered_qty: int
    price: float
    order_type: str
    submitted_at: float  # time.time()
    ord_no: str | None = None
    filled_qty: int = 0
    # filled_qty 중 이미 risk_state에 반영된(record_position_opened/added_to,
    # record_partial_exit로 처리한) 수량 — 호출자(trading_loop)가 여러 사이클에 걸쳐
    # 갱신한다. order_execution 자체는 risk_state를 모르므로 이 필드를 쓰지 않는다.
    applied_qty: int = 0
    # failed(통신오류로 미확정) / rejected(브로커 거부) / ambiguous(재시도 보류,
    # 수동확인 필요) / pending / partial / filled / cancelled / unknown(잔량 파싱 불가)
    status: str = "failed"
    detail: str = ""


def _append_log(log_path: str | None, record: dict) -> None:
    """trading_loop._log_order와 같은 관용구 — 기록 실패가 매매 흐름을 막으면
    안 되므로 조용히 무시한다."""
    if not log_path:
        return
    try:
        directory = os.path.dirname(log_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({**record, "ts": time.time()}, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def load_recent_orders(client: KiwoomClient, log_path: str = DEFAULT_ORDER_TRACKING_LOG_PATH) -> int:
    """재시작 후 place_order의 멱등성 캐시(_submitted_orders)를 디스크 로그로
    복원한다. 그 캐시는 프로세스 메모리뿐이라 재시작하면 비는데(kiwoom_client.py:47-53
    자체 주석), 복원 없이 재시작 직후 재시도가 들어오면 같은 client_order_id라도
    캐시가 비어있어 API를 다시 부를 수 있다. 반환값: 복원한 건수."""
    if not os.path.exists(log_path):
        return 0
    n = 0
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("event") == "submitted" and record.get("client_order_id") and record.get("response"):
                client.seed_submitted_order(record["client_order_id"], record["response"])
                n += 1
    return n


def restore_pending_orders_from_broker(
    client: KiwoomClient, pending_orders: dict, log_path: str = DEFAULT_ORDER_TRACKING_LOG_PATH,
) -> int:
    """재시작 직후 한 번 호출한다. "이 종목에 우리가 낸 주문이 아직 안 끝났는지"는
    로컬 상태가 아니라 브로커(get_pending_orders, ka10075)에게 직접 물어 확인한다 —
    로컬 파일은 재시작 사이에 언제든 실제와 어긋날 수 있고, 미체결의 진실은 브로커만
    갖고 있다(2026-08-29 지시).

    다만 브로커 응답만으로는 그 미체결 주문이 "우리 봇이 낸 것"인지 아니면 같은
    계좌를 쓰는 수동 주문(영웅문 등)인지 구분할 수 없다 — ord_no만으로는 소유권을
    모른다. 그래서 log_path(JSONL)에 남긴 우리 자신의 제출 기록(ord_no·side·수량·
    가격 포함, submit_order가 이미 기록)과 대조해서, 우리가 낸 것으로 "확인된" 주문만
    pending_orders에 복원한다. 확인 안 되는(남이 낸) 미체결은 절대 건드리지 않는다 —
    cancel_if_timed_out이 나중에 그 주문을 취소하면 사용자의 수동 주문을 봇이
    지워버리는 사고가 된다.

    복원된 항목은 side/quantity/price를 로그(=우리가 직접 낸 값)에서 그대로 가져오므로
    ka10075 응답에서 새로 추측해야 하는 필드는 ord_no뿐이다(place_order/cancel_order
    요청 바디에서 이미 쓰는 필드명과 동일 — 새로운 추측이 아니다). 이후 체결/타임아웃
    추적은 이미 있는 check_fill/cancel_if_timed_out을 그대로 탄다(잔량 필드 추측은
    거기 한 곳에만 있다).

    log_path 읽기는 risk_state_lock으로 감싼다 — 여러 전략 프로세스가 같은 계좌를
    공유하면 이 로그 파일도 공유될 수 있어, 다른 프로세스가 쓰는 도중 읽으면 마지막
    줄이 깨질 수 있다(어차피 파손된 줄은 아래에서 JSONDecodeError로 건너뛰지만, 락으로
    애초에 덜 겹치게 한다). 반환값: 복원한 건수."""
    lines: list[str] = []
    try:
        with risk_state_lock(log_path):
            if os.path.exists(log_path):
                with open(log_path, encoding="utf-8") as f:
                    lines = f.readlines()
    except OSError:
        return 0

    known_by_ord_no: dict[str, dict] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") != "submitted":
            continue
        response = record.get("response") or {}
        ord_no = response.get("ord_no")
        if not ord_no or response.get("return_code") != 0:
            continue
        known_by_ord_no[str(ord_no)] = record

    if not known_by_ord_no:
        return 0

    try:
        payload = client.get_pending_orders()
    except Exception:
        return 0  # 조회 실패 — 복원 없이 시작(중복 위험보다, 아무 것도 안 하는 쪽이 안전)

    restored = 0
    for row in _pending_rows(payload):
        ord_no = _first_present(row, _ORD_NO_KEYS)
        record = known_by_ord_no.get(str(ord_no)) if ord_no is not None else None
        if record is None:
            continue  # 우리가 낸 게 확인 안 됨(수동 주문 등) -> 손대지 않는다
        code = record["stock_code"]
        key = f"{record['side']}:{code}"
        if key in pending_orders:
            continue
        pending_orders[key] = TrackedOrder(
            client_order_id=record["client_order_id"], stock_code=code, side=record["side"],
            ordered_qty=record["quantity"], price=record.get("price", 0.0), order_type="0",
            submitted_at=time.time(), ord_no=str(ord_no), status="pending",
        )
        restored += 1
    return restored


def _pending_rows(payload: dict) -> list[dict]:
    """ka10075 응답의 미체결 목록 wrapper 키 이름도 검증된 바 없다 — return_code/
    return_msg/cont-yn 등 나머지 필드는 전부 스칼라이므로, 응답 안에서 list 타입인
    첫 값을 그대로 목록으로 쓰는 편이 키 이름을 추측하는 것보다 안전하다."""
    for value in payload.values():
        if isinstance(value, list):
            return value
    return []


def _first_present(row: dict, keys: tuple) -> object:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _pending_orders_ambiguous(client: KiwoomClient, stock_code: str) -> bool:
    """재시도 전 중복 주문 여부 확인(execution-agent.md §4). ord_no를 모르는 상태
    (place_order가 응답 없이 예외를 던졌으므로)라 개별 주문을 골라낼 수 없다 —
    그 종목에 미체결이 하나라도 잡히면 "직전 시도가 실제로는 접수됐을 수 있다"고
    보수적으로 판단해 재시도를 보류한다. 조회 자체가 실패해도 같은 이유로 보류."""
    try:
        payload = client.get_pending_orders(stock_code=stock_code)
    except Exception:
        return True
    return len(_pending_rows(payload)) > 0


def submit_order(
    client: KiwoomClient,
    *,
    stock_code: str,
    side: str,
    quantity: int,
    price: float,
    approved: bool,
    order_type: str = "0",
    client_order_id: str | None = None,
    max_retries: int = 3,
    backoff_base_seconds: float = 1.0,
    log_path: str | None = DEFAULT_ORDER_TRACKING_LOG_PATH,
) -> TrackedOrder:
    """place_order를 감싸 재시도(지수 백오프) + 멱등성 + 감사로그를 붙인다.

    approved=False면 즉시 거부한다(execution-agent.md §핵심원칙 1). 호출자
    (risk_manager.check_order를 통과시킨 쪽)가 이미 승인했어야 하며, 이건 그 위의
    마지막 방어선일 뿐 리스크 심사를 여기서 다시 하지 않는다.
    """
    order_id = client_order_id or uuid.uuid4().hex
    tracked = TrackedOrder(
        client_order_id=order_id, stock_code=stock_code, side=side, ordered_qty=quantity,
        price=price, order_type=order_type, submitted_at=time.time(),
    )

    if not approved:
        tracked.status = "rejected"
        tracked.detail = "리스크 승인 없음"
        _append_log(log_path, {"event": "rejected_no_approval", "client_order_id": order_id, "stock_code": stock_code})
        return tracked

    for attempt in range(max_retries + 1):
        if attempt > 0:
            if _pending_orders_ambiguous(client, stock_code):
                tracked.status = "ambiguous"
                tracked.detail = f"attempt {attempt}: {stock_code} 미체결 존재 — 중복 위험으로 재시도 중단, 수동 확인 필요"
                _append_log(log_path, {"event": "retry_aborted_ambiguous", "client_order_id": order_id, "stock_code": stock_code})
                return tracked
            time.sleep(backoff_base_seconds * (2 ** (attempt - 1)))

        try:
            response = client.place_order(
                stock_code, side=side, quantity=quantity, price=price, order_type=order_type, client_order_id=order_id,
            )
        except Exception as exc:
            tracked.status = "failed"
            tracked.detail = str(exc)
            _append_log(log_path, {"event": "attempt_failed", "client_order_id": order_id, "attempt": attempt, "error": str(exc)})
            if not isinstance(exc, RETRYABLE_EXCEPTIONS):
                # 통신 오류가 아니면(잘못된 인자, 버그 등 브로커 응답과 무관한 예외)
                # 재시도해도 소용없다 — 바로 반환한다.
                return tracked
            continue

        _append_log(log_path, {
            "event": "submitted", "client_order_id": order_id, "stock_code": stock_code,
            "side": side, "quantity": quantity, "price": price, "response": response,
        })

        rejected = _order_rejected(response)
        if rejected is not None:
            tracked.status = "rejected"
            tracked.detail = str(rejected)
            return tracked

        tracked.ord_no = response.get("ord_no")
        tracked.status = "pending"
        return tracked

    tracked.status = "failed"
    tracked.detail = f"{max_retries}회 재시도 후에도 통신 실패"
    return tracked


def check_fill(client: KiwoomClient, tracked: TrackedOrder) -> TrackedOrder:
    """get_pending_orders(ka10075)로 실제 체결 수량을 확인한다 — place_order 응답만
    보고 바로 "체결 완료"로 기록하던 기존 방식(trading_loop.py:298-302 주석 참고)을
    대체한다.

    ord_no가 미체결 목록에서 사라졌으면 전량 체결로 간주한다 — 거부는 place_order
    응답 단계에서 이미 걸러지므로(_order_rejected), 여기까지 pending으로 들어온
    주문이 목록에서 사라졌다는 건 체결 종결을 뜻한다. 남아있으면 잔량 필드를 읽어
    부분체결 여부를 판단한다."""
    if tracked.ord_no is None or tracked.status not in ("pending", "partial"):
        return tracked
    try:
        payload = client.get_pending_orders(stock_code=tracked.stock_code)
    except Exception as exc:
        tracked.detail = f"체결확인 조회 실패: {exc}"
        return tracked

    rows = _pending_rows(payload)
    row = next((r for r in rows if _first_present(r, _ORD_NO_KEYS) == tracked.ord_no), None)
    if row is None:
        tracked.filled_qty = tracked.ordered_qty
        tracked.status = "filled"
        return tracked

    remaining_raw = _first_present(row, _REMAINING_QTY_KEYS)
    if remaining_raw is None:
        tracked.status = "unknown"
        tracked.detail = f"미체결 응답에서 잔량 필드를 찾지 못함(keys={sorted(row.keys())})"
        return tracked

    try:
        remaining = int(remaining_raw)
    except (TypeError, ValueError):
        tracked.status = "unknown"
        tracked.detail = f"잔량 값 파싱 실패: {remaining_raw!r}"
        return tracked

    tracked.filled_qty = max(0, tracked.ordered_qty - remaining)
    tracked.status = "partial" if tracked.filled_qty > 0 else "pending"
    return tracked


def cancel_if_timed_out(
    client: KiwoomClient,
    tracked: TrackedOrder,
    timeout_seconds: float,
    log_path: str | None = DEFAULT_ORDER_TRACKING_LOG_PATH,
) -> TrackedOrder:
    """timeout_seconds 안에 체결이 끝나지 않은 pending/partial 주문의 잔량을 취소한다.

    정정(추격)이 아니라 취소만 한다: kiwoom_client.py에 정정(modify) TR이 아예 없고,
    설령 있어도 추격가를 다시 정하는 건 진입/청산 판단(전략 로직)이라 execution-agent가
    손댈 영역이 아니다(execution-agent.md 금지사항 — 전략 판단 코드 삽입 금지). 재주문이
    필요하면 호출자가 취소 결과를 보고 새 신호로 다시 리스크 승인을 받아야 한다."""
    if tracked.status not in ("pending", "partial"):
        return tracked
    if time.time() - tracked.submitted_at < timeout_seconds:
        return tracked
    if tracked.ord_no is None:
        return tracked

    remaining = tracked.ordered_qty - tracked.filled_qty
    try:
        response = client.cancel_order(tracked.ord_no, tracked.stock_code, quantity=0)
    except Exception as exc:
        tracked.detail = f"타임아웃 취소 요청 실패: {exc}"
        return tracked

    _append_log(log_path, {
        "event": "timeout_cancel", "client_order_id": tracked.client_order_id,
        "ord_no": tracked.ord_no, "remaining_before_cancel": remaining, "response": response,
    })

    if response.get("return_code") == 0:
        tracked.status = "cancelled"
    else:
        tracked.detail = f"취소 거부: return_code={response.get('return_code')} {response.get('return_msg', '')}"
    return tracked
