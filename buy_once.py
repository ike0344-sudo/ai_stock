"""수동 매수 1회 실행용 — 반드시 사용자가 직접 실행할 것.

사용법:
    python buy_once.py <종목코드> <수량> <손절가>
    python buy_once.py 000660 1 195000   # SK하이닉스 1주 시장가 매수, 손절가 195000원

.env의 KIWOOM_APPKEY/KIWOOM_SECRETKEY/KIWOOM_IS_MOCK을 그대로 쓴다(dashboard/
run-trading과 동일 계좌). 시장가(주문구분 3) 매수만 지원 — 지정가가 필요하면
kiwoom_client.place_order()의 price/order_type 인자를 직접 조정해서 쓸 것.

risk_manager.check_order() 승인을 거쳐야 주문이 나간다(손절가 없는 진입은 거부,
execution-agent.md §1) — 그래서 손절가가 필수 인자다. trading_loop.py가 쓰는
공유 상태(state/risk_state.json)는 추적하지 않는 독립된 심사라 동시보유/연속손절
한도는 적용되지 않고, 그 시점의 실제 예수금 기준 팻핑거/비중 한도만 걸린다.
"""
import os
import sys
from datetime import date

from dotenv import load_dotenv

from backtesting.risk_manager import OrderRequest, PortfolioState, RiskState, check_order
from kiwoom_client import KiwoomClient


def main() -> None:
    if len(sys.argv) != 4:
        print("사용법: python buy_once.py <종목코드> <수량> <손절가>")
        sys.exit(1)

    stock_code = sys.argv[1]
    quantity = int(sys.argv[2])
    stop = float(sys.argv[3])

    load_dotenv()
    appkey = os.environ["KIWOOM_APPKEY"]
    secretkey = os.environ["KIWOOM_SECRETKEY"]
    is_mock = os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true"

    client = KiwoomClient(appkey, secretkey, is_mock=is_mock)

    quote = client.get_stock_quote(stock_code)
    price = abs(float(quote["buy_fpr_bid"]))  # ka10004 부호는 등락방향 표시일 뿐 가격 부호가 아님
    deposit = client.get_deposit_detail()
    total_capital_krw = float(deposit.get("entr") or 0)

    order = OrderRequest(code=stock_code, side="buy", quantity=quantity, price=price, stop=stop)
    portfolio = PortfolioState(risk_state=RiskState(trading_date=date.today().isoformat()), total_capital_krw=total_capital_krw)
    decision = check_order(order, portfolio)
    if not decision.approved:
        print(f"리스크 심사 거부[{decision.rule_id}]: {decision.reason}")
        sys.exit(1)

    result = client.place_order(stock_code, "buy", quantity, order_type="3")

    print(f"{'모의투자' if is_mock else '실전투자'} 매수 주문: {stock_code} {quantity}주 (시장가, 승인 rule_id={decision.rule_id})")
    print(result)


if __name__ == "__main__":
    main()
