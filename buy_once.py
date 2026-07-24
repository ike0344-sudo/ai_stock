"""수동 매수 1회 실행용 — 반드시 사용자가 직접 실행할 것.

사용법:
    python buy_once.py <종목코드> <수량>
    python buy_once.py 000660 1          # SK하이닉스 1주 시장가 매수

.env의 KIWOOM_APPKEY/KIWOOM_SECRETKEY/KIWOOM_IS_MOCK을 그대로 쓴다(dashboard/
run-trading과 동일 계좌). 시장가(주문구분 3) 매수만 지원 — 지정가가 필요하면
kiwoom_client.place_order()의 price/order_type 인자를 직접 조정해서 쓸 것.
"""
import os
import sys

from dotenv import load_dotenv

from kiwoom_client import KiwoomClient


def main() -> None:
    if len(sys.argv) != 3:
        print("사용법: python buy_once.py <종목코드> <수량>")
        sys.exit(1)

    stock_code = sys.argv[1]
    quantity = int(sys.argv[2])

    load_dotenv()
    appkey = os.environ["KIWOOM_APPKEY"]
    secretkey = os.environ["KIWOOM_SECRETKEY"]
    is_mock = os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true"

    client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
    result = client.place_order(stock_code, "buy", quantity)

    print(f"{'모의투자' if is_mock else '실전투자'} 매수 주문: {stock_code} {quantity}주 (시장가)")
    print(result)


if __name__ == "__main__":
    main()
