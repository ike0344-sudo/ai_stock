"""보유종목 중 하나만 골라 매도(시장가) — sell_all_job.py(일괄 매도)와 달리 주문이
1건뿐이라 백그라운드 잡/상태 폴링 없이 동기 호출로 처리한다. dashboard_server.py의
세 번째 쓰기 트리거(top35 갱신, 일괄 매도에 이어) — 대시보드 보유종목 테이블의
행별 "매도" 버튼에서만 호출된다(프론트에서 확인 다이얼로그를 거친 뒤).
"""
from kiwoom_client import KiwoomClient

from .account_status import invalidate_cache


def sell_one(appkey: str, secretkey: str, is_mock: bool, code: str, quantity: int) -> dict:
    """지정한 종목 quantity 전량을 시장가로 매도하고 키움 응답을 그대로 반환한다.
    성공 시 계좌 스냅샷 캐시를 무효화해, 다음 대시보드 폴링이 방금 매도한 낡은
    보유수량을 최대 60초까지 계속 보여주지 않게 한다."""
    client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
    result = client.place_order(code, "sell", quantity)
    if result.get("return_code") == 0:
        invalidate_cache()
    return result
