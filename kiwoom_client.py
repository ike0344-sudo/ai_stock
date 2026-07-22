"""키움증권 REST API 클라이언트.

공식 가이드: https://openapi.kiwoom.com/guide/apiguide
- 실전 도메인: https://api.kiwoom.com
- 모의투자 도메인: https://mockapi.kiwoom.com
"""
import time
from datetime import date

import requests


class KiwoomClient:
    def __init__(self, appkey: str, secretkey: str, is_mock: bool = True, min_request_interval: float = 1.1):
        self.appkey = appkey
        self.secretkey = secretkey
        self.is_mock = is_mock
        self.base_url = "https://mockapi.kiwoom.com" if is_mock else "https://api.kiwoom.com"
        self.token: str | None = None
        # 마지막 request_tr 응답의 페이지네이션 정보 (cont-yn/next-key 응답 헤더)
        self.last_cont_yn: str = "N"
        self.last_next_key: str = ""
        # 여러 종목을 연속 조회할 때 429(rate limit)를 실제로 겪어서 추가한 최소 요청 간격(초).
        # 공식 문서에 정확한 한도가 없지만, 실측 보고로는 TR당 초당 1회(버스트 2) 수준 —
        # 0.5초였을 때는 이 한도의 2배 속도로 요청해 감시종목 35개 중 대부분이 429로
        # 실패하는 걸 실제로 겪었다(run-trading 라이브 로그로 확인). 1초보다 살짝 여유
        # 있게 잡는다.
        self.min_request_interval = min_request_interval
        self._last_request_at: float | None = None

    def issue_token(self) -> str:
        url = f"{self.base_url}/oauth2/token"
        headers = {"Content-Type": "application/json;charset=UTF-8"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.appkey,
            "secretkey": self.secretkey,
        }
        res = requests.post(url, headers=headers, json=body, timeout=10)
        res.raise_for_status()
        data = res.json()

        # 응답 필드명이 token / access_token 중 무엇인지 문서로 확정 못 해서 둘 다 대응
        token = data.get("token") or data.get("access_token")
        if not token:
            raise RuntimeError(f"토큰 발급 응답에서 토큰 필드를 찾지 못했습니다: {data}")

        self.token = token
        return token

    def _throttle(self) -> None:
        now = time.monotonic()
        if self._last_request_at is not None:
            wait = self.min_request_interval - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
        self._last_request_at = now

    def request_tr(
        self,
        api_id: str,
        body: dict,
        path: str = "/api/dostk/chart",
        cont_yn: str = "N",
        next_key: str = "",
    ) -> dict:
        """TR(api-id) 기반 요청 공통 함수. 차트 외 다른 TR도 이 함수로 호출 가능.

        cont_yn/next_key는 이전 응답의 cont-yn/next-key 헤더를 그대로 넘기면 다음
        페이지(더 과거 데이터)를 받을 수 있다 (실제 API로 검증됨). 응답을 받으면
        self.last_cont_yn/last_next_key를 갱신해 호출자가 다음 페이지 여부를 알 수 있다.
        """
        if not self.token:
            self.issue_token()

        self._throttle()

        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.token}",
            "api-id": api_id,
            "cont-yn": cont_yn,
            "next-key": next_key,
        }
        res = requests.post(url, headers=headers, json=body, timeout=10)
        res.raise_for_status()

        self.last_cont_yn = res.headers.get("cont-yn", "N")
        self.last_next_key = res.headers.get("next-key", "")

        return res.json()

    def _paginate(self, api_id: str, body: dict, path: str, max_pages: int) -> list[dict]:
        """cont-yn/next-key를 따라가며 최대 max_pages 페이지를 모아 반환하는 공통 루프.

        API가 더 이상 과거 데이터를 주지 않으면(cont-yn != "Y") max_pages 전이라도 멈춘다.
        """
        pages = []
        cont_yn, next_key = "N", ""

        for _ in range(max_pages):
            payload = self.request_tr(api_id, body, path=path, cont_yn=cont_yn, next_key=next_key)
            pages.append(payload)
            if self.last_cont_yn != "Y" or not self.last_next_key:
                break
            cont_yn, next_key = "Y", self.last_next_key

        return pages

    def get_daily_chart(self, stock_code: str, base_date: str = "") -> dict:
        """주식일봉차트조회요청 (ka10081). base_date 미지정 시 오늘 날짜 사용. 첫 페이지만 반환."""
        base_date = base_date or date.today().strftime("%Y%m%d")
        body = {"stk_cd": stock_code, "base_dt": base_date, "upd_stkpc_tp": "1"}
        return self.request_tr("ka10081", body)

    def get_daily_chart_pages(self, stock_code: str, base_date: str = "", max_pages: int = 10) -> list[dict]:
        """일봉 데이터를 cont-yn/next-key로 여러 페이지 이어받아 반환 (더 긴 과거 이력 확보용).

        실측 기준 1페이지 = 600행 ≈ 2.4년. max_pages=10이면 최대 약 24년치까지 시도.
        """
        base_date = base_date or date.today().strftime("%Y%m%d")
        body = {"stk_cd": stock_code, "base_dt": base_date, "upd_stkpc_tp": "1"}
        return self._paginate("ka10081", body, path="/api/dostk/chart", max_pages=max_pages)

    def get_minute_chart(self, stock_code: str, tic_scope: str = "1") -> dict:
        """주식분봉차트조회요청 (ka10080). tic_scope: 1/3/5/10/15/30/45/60분. 첫 페이지만 반환."""
        body = {"stk_cd": stock_code, "tic_scope": tic_scope, "upd_stkpc_tp": "1"}
        return self.request_tr("ka10080", body)

    def get_minute_chart_pages(self, stock_code: str, tic_scope: str = "1", max_pages: int = 20) -> list[dict]:
        """분봉 데이터를 cont-yn/next-key로 여러 페이지 이어받아 반환 (더 긴 과거 이력 확보용)."""
        body = {"stk_cd": stock_code, "tic_scope": tic_scope, "upd_stkpc_tp": "1"}
        return self._paginate("ka10080", body, path="/api/dostk/chart", max_pages=max_pages)

    def get_stock_list(self, market_type: str) -> list[dict]:
        """종목정보 리스트 (ka10099). market_type: "0"=거래소(코스피, ETF/ETN 등 포함),
        "10"=코스닥(개별종목만). 응답의 marketName 필드로 세부 구분 가능."""
        payload = self.request_tr("ka10099", {"mrkt_tp": market_type}, path="/api/dostk/stkinfo")
        return payload.get("list", [])

    def get_top_trading_value(self, body: dict, cont_yn: str = "N", next_key: str = "") -> dict:
        """거래대금상위요청 (ka10032)."""
        return self.request_tr("ka10032", body, path="/api/dostk/rkinfo", cont_yn=cont_yn, next_key=next_key)

    def get_index_daily_chart(self, index_code: str, base_date: str = "") -> dict:
        """업종(지수) 일봉 차트 (ka20006). index_code: "001"=코스피종합, "101"=코스닥종합."""
        base_date = base_date or date.today().strftime("%Y%m%d")
        body = {"inds_cd": index_code, "base_dt": base_date}
        return self.request_tr("ka20006", body)

    def get_index_daily_chart_pages(self, index_code: str, base_date: str = "", max_pages: int = 10) -> list[dict]:
        base_date = base_date or date.today().strftime("%Y%m%d")
        body = {"inds_cd": index_code, "base_dt": base_date}
        return self._paginate("ka20006", body, path="/api/dostk/chart", max_pages=max_pages)

    def get_index_minute_chart_pages(self, index_code: str, tic_scope: str = "1", max_pages: int = 20) -> list[dict]:
        """업종(지수) 분봉 차트 (ka20005)."""
        body = {"inds_cd": index_code, "tic_scope": tic_scope}
        return self._paginate("ka20005", body, path="/api/dostk/chart", max_pages=max_pages)

    def get_stock_quote(self, stock_code: str) -> dict:
        """주식호가요청 (ka10004). 호출 시점 기준 매도/매수 호가·잔량 스냅샷 1건.

        차트류(ka10081 등)와 달리 과거 이력을 조회하는 API가 아니다 — 호가는
        브로커 쪽에도 보관되지 않는 데이터라, 매 호출은 "지금 이 순간"만 반환한다.
        """
        return self.request_tr("ka10004", {"stk_cd": stock_code}, path="/api/dostk/mrkcond")

    def place_order(
        self,
        stock_code: str,
        side: str,
        quantity: int,
        price: int = 0,
        order_type: str = "3",
        exchange: str = "KRX",
    ) -> dict:
        """주식 매수(kt10000)/매도(kt10001) 주문.

        side: "buy" 또는 "sell".
        order_type(매매구분, trde_tp): "0"=보통(지정가), "3"=시장가(기본값) 등 —
        키움 매매구분 코드 전체 목록은 공식 가이드 참고. 시장가일 때 price는
        무시되고 주문단가(ord_uv)는 빈 문자열로 전송된다.
        응답에 주문번호(ord_no)가 포함되어야 취소/체결확인에 사용할 수 있다.
        """
        api_id = "kt10000" if side == "buy" else "kt10001"
        body = {
            "dmst_stex_tp": exchange,
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
            "ord_uv": str(price) if order_type != "3" and price else "",
            "trde_tp": order_type,
            "cond_uv": "",
        }
        return self.request_tr(api_id, body, path="/api/dostk/ordr")

    def cancel_order(self, order_no: str, stock_code: str, quantity: int, exchange: str = "KRX") -> dict:
        """주식 취소주문 (kt10003). quantity=0이면 잔량 전부 취소."""
        body = {
            "dmst_stex_tp": exchange,
            "orig_ord_no": order_no,
            "stk_cd": stock_code,
            "cncl_qty": str(quantity),
        }
        return self.request_tr("kt10003", body, path="/api/dostk/ordr")

    def get_pending_orders(self, stock_code: str | None = None, exchange_type: str = "0") -> dict:
        """미체결요청 (ka10075). stock_code 지정 시 해당 종목만, 미지정 시 전체."""
        body = {
            "all_stk_tp": "1" if stock_code else "0",
            "trde_tp": "0",
            "stex_tp": exchange_type,
        }
        if stock_code:
            body["stk_cd"] = stock_code
        return self.request_tr("ka10075", body, path="/api/dostk/acnt")

    def get_positions(self, exchange: str = "KRX") -> dict:
        """체결잔고요청 (kt00005). 예수금 + 보유종목별 평가손익(evltv_prft/pl_rt 등) 포함.

        모의투자 계좌에서는 이 TR 자체가 막혀 있다(실제로 호출하면 return_code=20,
        "RC9000:모의투자에서는 해당업무가 제공되지 않습니다") — 모의투자에서도 잔고를
        보려면 get_deposit_detail()/get_account_evaluation()을 대신 쓴다.
        """
        return self.request_tr("kt00005", {"dmst_stex_tp": exchange}, path="/api/dostk/acnt")

    def get_deposit_detail(self) -> dict:
        """예수금상세현황요청 (kt00001). 예수금/주문가능금액/출금가능금액 등 현금 잔고.
        get_positions(kt00005)와 달리 모의투자 계좌에서도 정상 동작한다(실측 확인됨)."""
        return self.request_tr("kt00001", {"qry_tp": "3"}, path="/api/dostk/acnt")

    def get_account_evaluation(self, exchange: str = "KRX") -> dict:
        """계좌평가현황요청 (kt00004). 계좌 평가금액 요약 + 보유종목 리스트
        (stk_acnt_evlt_prst: 종목코드/수량/평균단가/평가손익 등)를 함께 반환한다.
        get_positions(kt00005)와 달리 모의투자 계좌에서도 정상 동작한다(실측 확인됨) —
        모의투자에서 보유종목을 조회하려면 이걸 쓴다."""
        return self.request_tr("kt00004", {"qry_tp": "0", "dmst_stex_tp": exchange}, path="/api/dostk/acnt")
