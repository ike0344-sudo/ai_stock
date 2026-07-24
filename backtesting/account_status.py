"""키움 계좌 잔고(예수금)·보유종목 스냅샷 — 대시보드 잔고조회/보유종목 패널용.

get_positions()(kt00005, 체결잔고요청)는 모의투자 계좌에서 막혀 있어서(실측: return_code=20,
"RC9000:모의투자에서는 해당업무가 제공되지 않습니다") kt00001(예수금상세현황요청)과
kt00004(계좌평가현황요청, 보유종목 리스트 포함)를 대신 쓴다 — 실전/모의 모두 이 두 TR로
동작 확인됨(kiwoom_client.KiwoomClient.get_deposit_detail/get_account_evaluation).

market_snapshot.py와 같은 이유로 캐시를 둔다 — 대시보드가 짧은 간격으로 폴링하는데
그때마다 키움 API를 호출하면 과다호출이 되므로, CACHE_TTL_SECONDS 동안은 마지막 조회
결과를 재사용한다. KiwoomClient는 kiwoom_session.get_client()로 대시보드 프로세스
전체가 공유하는 인스턴스를 그대로 쓴다 — 이 모듈만의 별도 클라이언트를 쓰면 market_
snapshot.py 등 다른 패널의 호출 타이밍을 모른 채 각자 페이싱하다가 계정 단위 rate
limit을 함께 넘길 수 있다(실측: market_snapshot 폴링을 1~2초로 당긴 뒤 이 모듈을
동시에 돌리면 토큰 발급 자체가 429 — "잔고 조회 실패"의 실제 원인이었다).

거기에 더해, 조회 실패 시 이전 성공값을 유지한다(deposit/holdings 필드별로 독립적으로) —
안 그러면 TTL(60초) 동안 화면이 "실패" 상태로 고정되는데, 그 시간이면 사용자가 계좌가
실제로 잘못됐다고 오해하기 충분히 길다.
"""
import threading
import time

from kiwoom_client import KiwoomClient

from .kiwoom_session import get_client

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
    # exchange 기본값("KRX")로 조회하면 cur_prc/evlt_amt/pl_amt가 KRX 정규장(09:00~15:30)
    # 가격만 반영해서, 장 마감 후~20:00까지 이어지는 넥스트레이드(NXT) 거래 시간대에는
    # 평가손익이 갱신되지 않고 마지막 KRX 종가에 고정된다. "SOR"(통합)로 조회하면
    # KRX+NXT를 통틀어 가장 최근 체결가를 반영하므로 별도 시간대 분기 없이 정규장·
    # NXT 시간대(08:00~20:00) 모두 실시간 평가손익이 나온다.
    try:
        payload = client.get_account_evaluation(exchange="SOR")
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
    예수금 조회와 보유종목 조회는 서로 독립적으로 실패를 허용한다 — 이번 조회에서
    한쪽만 실패하면(None) 그 필드만 직전 성공값을 그대로 유지하고, 나머지는 새 값으로
    갱신한다(둘 다 처음부터 실패였다면 그대로 None).
    """
    global _cached_snapshot, _cached_at
    with _lock:
        if _cached_snapshot is not None and (time.monotonic() - _cached_at) < CACHE_TTL_SECONDS:
            return _cached_snapshot
        previous = _cached_snapshot

    deposit = holdings = None
    if appkey and secretkey:
        client = get_client(appkey, secretkey, is_mock)
        deposit = _deposit_snapshot(client)
        holdings = _holdings_snapshot(client)

    if deposit is None and previous:
        deposit = previous["deposit"]
    if holdings is None and previous:
        holdings = previous["holdings"]

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
