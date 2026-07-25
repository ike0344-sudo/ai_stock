"""보유종목 중 하나만 골라 매도(시장가) — sell_all_job.py(일괄 매도)와 달리 주문이
1건뿐이라 백그라운드 잡/상태 폴링 없이 동기 호출로 처리한다. dashboard_server.py의
세 번째 쓰기 트리거(top35 갱신, 일괄 매도에 이어) — 대시보드 보유종목 테이블의
행별 "매도" 버튼에서만 호출된다(프론트에서 확인 다이얼로그를 거친 뒤).

주문 전 risk_manager.check_order를 거친다(모니터링 감사 지적사항 — 대시보드가
리스크 심사를 우회해 직접 주문을 내던 문제). check_order는 side="sell"이면 항상
승인하도록 설계돼 있어(계좌 전체 대상 청산이라 특정 전략의 risk_state에 묶을 수
없음) 오늘 시점엔 실질적인 게이트가 아니지만, 결정을 반드시 남겨(rule_id/reason이
있는 RiskDecision) "조용한 결정"이 없게 하고 향후 매도 쪽에 심사 규칙이 생겨도
이 한 곳만 바뀌면 되게 한다.
"""
from kiwoom_client import KiwoomClient

from .account_status import invalidate_cache
from .risk_manager import OrderRequest, PortfolioState, RiskState, check_order


def sell_one(appkey: str, secretkey: str, is_mock: bool, code: str, quantity: int) -> dict:
    """지정한 종목 quantity 전량을 시장가로 매도하고 키움 응답을 그대로 반환한다.
    성공 시 계좌 스냅샷 캐시를 무효화해, 다음 대시보드 폴링이 방금 매도한 낡은
    보유수량을 최대 60초까지 계속 보여주지 않게 한다."""
    decision = check_order(
        OrderRequest(code=code, side="sell", quantity=quantity, price=0.0),
        PortfolioState(risk_state=RiskState(trading_date=""), total_capital_krw=0.0),
    )
    print(f"[risk] 매도 심사: {code} x{quantity} - {decision.rule_id}: {decision.reason}", flush=True)
    if not decision.approved:
        return {"return_code": -1, "return_msg": f"리스크 심사 거부: {decision.reason}"}

    client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
    result = client.place_order(code, "sell", quantity, order_type="3")
    if result.get("return_code") == 0:
        invalidate_cache()
    return result
