"""키움 계좌 잔고(예수금)·보유종목 스냅샷 — 대시보드 잔고조회/보유종목 패널용.

get_positions()(kt00005, 체결잔고요청)는 모의투자 계좌에서 막혀 있어서(실측: return_code=20,
"RC9000:모의투자에서는 해당업무가 제공되지 않습니다") kt00001(예수금상세현황요청)과
kt00004(계좌평가현황요청, 보유종목 리스트 포함)를 대신 쓴다 — 실전/모의 모두 이 두 TR로
동작 확인됨(kiwoom_client.KiwoomClient.get_deposit_detail/get_account_evaluation).

market_snapshot.py와 같은 이유로 캐시를 둔다 — 대시보드가 5초마다 폴링하는데 그때마다
키움 API를 호출하면(게다가 매 호출마다 토큰도 새로 발급됨) 과다호출이 되므로,
CACHE_TTL_SECONDS 동안은 마지막 조회 결과를 재사용한다.
"""
import threading
import time

from kiwoom_client import KiwoomClient

CACHE_TTL_SECONDS = 60.0

_lock = threading.Lock()
_cached_snapshot: dict | None = None
_cached_at = 0.0


def _parse_amount(raw) -> int:
    """키움 응답의 금액 필드는 0으로 패딩된 고정폭 문자열(부호 포함 가능) — 정수로 변환.
    필드가 없거나 파싱 불가능하면 0(조회 자체 실패는 호출부에서 이미 None으로 처리)."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _deposit_snapshot(client: KiwoomClient) -> dict | None:
    try:
        payload = client.get_deposit_detail()
    except Exception:
        return None
    if payload.get("return_code") != 0:
        return None
    return {
        "deposit_krw": _parse_amount(payload.get("entr")),
        "order_available_krw": _parse_amount(payload.get("ord_alow_amt")),
        "withdrawable_krw": _parse_amount(payload.get("pymn_alow_amt")),
        "d2_deposit_krw": _parse_amount(payload.get("d2_entra")),
    }


def _holdings_snapshot(client: KiwoomClient) -> list[dict] | None:
    try:
        payload = client.get_account_evaluation()
    except Exception:
        return None
    if payload.get("return_code") != 0:
        return None
    return [
        {
            "code": row.get("stk_cd", "").removeprefix("A"),
            "name": row.get("stk_nm", ""),
            "quantity": _parse_amount(row.get("rmnd_qty")),
            "avg_price": _parse_amount(row.get("avg_prc")),
            "current_price": _parse_amount(row.get("cur_prc")),
            "eval_amount": _parse_amount(row.get("evlt_amt")),
            "pl_amount": _parse_amount(row.get("pl_amt")),
            "pl_pct": float(row.get("pl_rt") or 0),
        }
        for row in payload.get("stk_acnt_evlt_prst", [])
    ]


def get_account_snapshot(appkey: str, secretkey: str, is_mock: bool) -> dict:
    """{"deposit": {...} | None, "holdings": [...] | None} 반환.

    CACHE_TTL_SECONDS 이내 재호출은 마지막 결과를 그대로 돌려준다. appkey/secretkey가
    비어 있으면(대시보드만 켜두고 .env를 아직 안 채운 경우 등) 조회를 시도하지 않는다.
    예수금 조회와 보유종목 조회 중 하나가 실패해도 나머지는 정상 반환한다.
    """
    global _cached_snapshot, _cached_at
    with _lock:
        if _cached_snapshot is not None and (time.monotonic() - _cached_at) < CACHE_TTL_SECONDS:
            return _cached_snapshot

    deposit = holdings = None
    if appkey and secretkey:
        client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
        deposit = _deposit_snapshot(client)
        holdings = _holdings_snapshot(client)

    snapshot = {"deposit": deposit, "holdings": holdings}
    with _lock:
        _cached_snapshot = snapshot
        _cached_at = time.monotonic()
    return snapshot


def invalidate_cache() -> None:
    """매도 등 주문 체결로 계좌 상태가 바뀐 직후 호출 — 다음 조회가 최대
    CACHE_TTL_SECONDS(60초)까지 낡은 캐시를 돌려주지 않고 바로 최신 상태를 다시
    가져오게 강제한다(sell_order.py/sell_all_job.py가 주문 처리 후 호출)."""
    global _cached_snapshot, _cached_at
    with _lock:
        _cached_snapshot = None
        _cached_at = 0.0
