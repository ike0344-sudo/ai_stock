"""키움증권 REST API 클라이언트.

공식 가이드: https://openapi.kiwoom.com/guide/apiguide
- 실전 도메인: https://api.kiwoom.com
- 모의투자 도메인: https://mockapi.kiwoom.com
"""
import os
import threading
import time
import uuid
from datetime import date

import requests

INVALID_TOKEN_ERROR_CODE = "8005"


def batch_keys() -> tuple[str, str]:
    """배치·수집용 (앱키, 시크릿). KIWOOM_BATCH_* 가 있으면 그걸, 없으면 실시간용을 쓴다.

    **앱키 하나당 WebSocket 세션은 하나다.** 같은 앱키로 두 번째 연결을 열면 먼저
    있던 쪽이 즉시 Bye 로 끊긴다(2026-08-31 실측: 탐침 연결 시각과 소피증권 끊김
    시각이 밀리초까지 일치). 그래서 백필·분봉 수집·장전 배치처럼 뒤에서 도는 일은
    별도 앱키로 돌려 소피증권 실시간 구독을 건드리지 않는다.

    없으면 실시간용으로 돌아가므로, 배치키를 안 넣은 PC 에서도 그대로 동작한다.
    """
    key = os.environ.get("KIWOOM_BATCH_APPKEY", "").strip()
    sec = os.environ.get("KIWOOM_BATCH_SECRETKEY", "").strip()
    if key and sec:
        return key, sec
    return os.environ.get("KIWOOM_APPKEY", ""), os.environ.get("KIWOOM_SECRETKEY", "")


def _is_invalid_token_response(payload: dict) -> bool:
    """request_tr 응답이 "토큰이 유효하지 않습니다([8005])" 오류인지 판별 — 이 경우만
    토큰 재발급으로 회복 가능하다(다른 return_code!=0 오류는 재시도해도 소용없음)."""
    return payload.get("return_code") not in (0, None) and INVALID_TOKEN_ERROR_CODE in str(payload.get("return_msg", ""))


def raise_if_error(payload: dict) -> None:
    """return_code!=0인 응답을 그대로 흘려보내면, "페이지가 끝났다"고 해석하는 곳
    (아래 _paginate, 또는 수동으로 cont-yn/next-key를 도는 호출부)에서 진짜 오류를
    "더 이상 과거 데이터가 없다"와 구분 못 한다(실측: 2026-08-30 ka10079 79종목이
    이렇게 빈 채로 "완료"로 잘못 처리됨 — tick_collect_803_828.py).

    request_tr 자체에는 이 체크를 넣지 않는다 — kt00005(계좌평가)가 모의투자에서
    return_code=20("RC9000:모의투자에서는 지원하지 않는 기능")을 정상적으로 돌려주고
    호출부가 그 값을 보고 직접 분기하는 게 이미 의도된 동작이자 회귀 테스트로
    고정돼 있다(test_request_tr_does_not_reissue_token_on_other_api_errors). 반면
    상장폐지·존재하지 않는 종목코드는 return_code=0 그대로 오고 목록에 빈 값 한 줄이
    들어오는 방식이라(실측: 999999, 309710) 이 체크와 충돌하지 않는다 — "데이터 없음"과
    "API 오류"는 애초에 다른 신호로 구분된다.

    호출부에서 직접 페이지네이션을 도는 경우(예: 틱 수집처럼 _paginate를 안 쓰는
    경우)도 이 함수를 그대로 재사용해 같은 기준을 쓴다."""
    rc = payload.get("return_code")
    if rc is not None and rc != 0:
        raise RuntimeError(f"API 오류 - return_code={rc} {payload.get('return_msg', '')}".strip())


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
        # 대시보드처럼 여러 패널이 하나의 KiwoomClient 인스턴스를 공유하면(kiwoom_session.py)
        # ThreadingHTTPServer가 요청마다 스레드를 새로 띄우기 때문에 같은 인스턴스에 동시
        # 접근할 수 있다 — _throttle()의 "확인 후 대기" 로직 자체가 락 없이는 원자적이지
        # 않아서, 두 스레드가 거의 동시에 들어오면 둘 다 대기 시간을 짧게 계산해 거의 동시에
        # 실제 요청을 쏴버릴 수 있다(실측: 토큰 발급 엔드포인트 자체가 429). request_tr()
        # 전체(토큰 발급~요청~응답 헤더 반영)를 이 락으로 감싸 인스턴스당 완전히 직렬화한다.
        self._request_lock = threading.Lock()
        # client_order_id -> place_order 응답. 같은 client_order_id로 place_order가 다시
        # 호출되면(재시도 등) 실제 API를 다시 부르지 않고 이전 응답을 그대로 돌려준다
        # (execution-agent.md §핵심원칙 2 — 멱등성). 프로세스 재시작까지 살아남을
        # 필요는 없어서 in-memory로만 추적한다.
        # ponytail: 프로세스 수명 내내 무한정 쌓이는 dict(전역 락 없음) — 하루 거래량
        # 규모에선 무해하지만, 초장기 상주 프로세스에서 메모리가 문제되면 TTL/만료를 추가.
        self._submitted_orders: dict[str, dict] = {}

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
                # 대기했다면 now를 요청 직전 시각으로 다시 잰다 — 대기 전 시각을 그대로
                # 쓰면 실제 요청 간격이 min_request_interval보다 짧게 기록돼, 바로 다음
                # 요청의 대기시간이 과소 계산된다(연속 호출이 촘촘할수록 누적돼 결국
                # 페이싱이 무너진다 — 실측: 락으로 스레드를 직렬화해도 이 버그 때문에
                # 세 번째 요청부터 대기시간이 0으로 계산됐다).
                now = time.monotonic()
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

        토큰 발급~페이싱~요청 전체를 _request_lock으로 감싸 인스턴스당 직렬화한다 —
        여러 스레드가 같은 인스턴스를 동시에 쓸 수 있는 환경(dashboard의 kiwoom_session
        공유 클라이언트)에서, 락 없이는 두 스레드가 거의 동시에 페이싱 검사를 통과해
        실제 요청을 겹쳐 쏠 수 있다.

        토큰이 무효화된 응답(return_code!=0, [8005:Token이 유효하지 않습니다])이 오면
        한 번 재발급받아 재시도한다 — RealtimeFeed(realtime_feed.py)가 WebSocket
        재연결마다 같은 appkey로 새 토큰을 발급받는데, 그러면 이 인스턴스가 들고 있던
        토큰이 서버 쪽에서 무효화된다(실측). 재발급 로직이 없던 예전엔 그 순간부터
        이 인스턴스의 모든 요청이 세션이 끝날 때까지 계속 실패했다(전략1 실계좌
        로그에서 89,877회 반복된 "워치리스트 갱신 실패"의 근본 원인으로 실측 확인).
        """
        with self._request_lock:
            if not self.token:
                self.issue_token()

            payload = self._post_tr(api_id, body, path, cont_yn, next_key)
            if _is_invalid_token_response(payload):
                self.issue_token()
                payload = self._post_tr(api_id, body, path, cont_yn, next_key)

        return payload

    def _post_tr(self, api_id: str, body: dict, path: str, cont_yn: str, next_key: str) -> dict:
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
            raise_if_error(payload)
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

    def get_monthly_chart_pages(self, stock_code: str, base_date: str = "", max_pages: int = 2) -> list[dict]:
        """주식월봉차트조회요청 (ka10083). 역사적 신고가처럼 **상장 이후 전체**가 필요할 때 쓴다.

        실측 1페이지 = 240행 = 20년. 일봉으로 같은 기간을 받으려면 종목당 10페이지가
        필요해 전 종목이면 몇 시간이 걸린다 — 월봉은 1~2페이지로 끝난다.
        upd_stkpc_tp="1"이라 액면분할이 반영된 수정주가다(옛 고가와 그대로 비교 가능).
        """
        base_date = base_date or date.today().strftime("%Y%m%d")
        body = {"stk_cd": stock_code, "base_dt": base_date, "upd_stkpc_tp": "1"}
        return self._paginate("ka10083", body, path="/api/dostk/chart", max_pages=max_pages)

    def get_minute_chart(self, stock_code: str, tic_scope: str = "1", exchange: str | None = None) -> dict:
        """주식분봉차트조회요청 (ka10080). tic_scope: 1/3/5/10/15/30/45/60분. 첫 페이지만 반환.

        ⚠️ **stex_tp 는 이 TR 에서 무시된다. 거래소는 종목코드 접미사로 고른다.**
        실측 2026-09-21 삼성전자 하루 거래대금(= 09:00~20:00 분봉 합):

            stex_tp="1" / "2" / "3"  -> 전부 6.04조 (KRX 전용, 값이 완전히 동일)
            코드 "005930"            -> 6.04조  KRX
            코드 "005930_NX"         -> 3.16조  NXT
            코드 "005930_AL"         -> 9.20조  통합(KRX+NXT)

        같은 사실을 kospi-theme-engine/scripts/fetch_minute.py:89 가 2026-08-13 에
        이미 적어뒀다("stex_tp 파라미터로는 바뀌지 않는다"). 통합 분봉이 필요하면
        **코드에 _AL 을 붙여서** 부를 것 — exchange="3" 을 넘겨봐야 KRX 가 온다.

        exchange 인자는 하위호환으로 남겨둔다(넘기면 body 에 실리기는 한다). 지우면
        호출부가 전부 깨지는데, 지금 그 호출부들(live_monitor/trading_loop)이 이 값에
        의존해 "통합을 쓰고 있다"고 믿고 있어 별도 정리가 필요하다 —
        state/agent_reports/data-agent_20260921-2006_afterhours_top35.md 참고."""
        body = {"stk_cd": stock_code, "tic_scope": tic_scope, "upd_stkpc_tp": "1"}
        if exchange is not None:
            body["stex_tp"] = exchange
        return self.request_tr("ka10080", body)

    def get_minute_chart_pages(
        self, stock_code: str, tic_scope: str = "1", max_pages: int = 20, exchange: str | None = None
    ) -> list[dict]:
        """분봉 데이터를 cont-yn/next-key로 여러 페이지 이어받아 반환 (더 긴 과거 이력 확보용).
        exchange 의미는 get_minute_chart와 동일."""
        body = {"stk_cd": stock_code, "tic_scope": tic_scope, "upd_stkpc_tp": "1"}
        if exchange is not None:
            body["stex_tp"] = exchange
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

    def get_stock_quote(self, stock_code: str, exchange: str | None = None) -> dict:
        """주식호가요청 (ka10004). 호출 시점 기준 매도/매수 호가·잔량 스냅샷 1건.

        차트류(ka10081 등)와 달리 과거 이력을 조회하는 API가 아니다 — 호가는
        브로커 쪽에도 보관되지 않는 데이터라, 매 호출은 "지금 이 순간"만 반환한다.

        exchange 미지정 시 place_order와 같은 규칙(모의투자="1"=KRX, 실전="3"=통합)을
        쓴다 — trading_loop.py/oversold_trading_loop.py가 청산 판단 시 실시간피드에
        아직 틱이 없으면 이 호출로 폴백하는데, 넥스트레이드(NXT) 거래시간대(~20:00)에
        KRX 호가만 보면 그 시간대 실제 체결 가능 가격과 어긋날 수 있어 place_order와
        같은 기준(통합)으로 맞춘다. 필드명(stex_tp)과 값("1"/"3")은 place_order의
        dmst_stex_tp("KRX"/"SOR")와 다른 이 TR 고유의 표기라 그대로 매핑한다."""
        if exchange is None:
            exchange = "1" if self.is_mock else "3"
        return self.request_tr("ka10004", {"stk_cd": stock_code, "stex_tp": exchange}, path="/api/dostk/mrkcond")

    def place_order(
        self,
        stock_code: str,
        side: str,
        quantity: int,
        price: int = 0,
        order_type: str = "0",
        exchange: str | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        """주식 매수(kt10000)/매도(kt10001) 주문.

        side: "buy" 또는 "sell".
        order_type(매매구분, trde_tp): "0"=보통(지정가, 기본값 — 슬리피지 통제를 위해
        시장가를 기본으로 두지 않는다, execution-agent.md §1), "3"=시장가 등. 시장가로
        내려면 order_type="3"을 명시적으로 넘겨야 하며, 이때 price는 무시되고
        주문단가(ord_uv)는 빈 문자열로 전송된다.
        응답에 주문번호(ord_no)가 포함되어야 취소/체결확인에 사용할 수 있다.

        client_order_id: 같은 값으로 다시 호출되면(재시도) 실제 API를 다시 부르지 않고
        직전 응답을 그대로 돌려준다(멱등성 가드, execution-agent.md §2) — 미지정 시
        매 호출마다 새 uuid를 발급하므로 중복 차단은 호출자가 재시도 시 같은 id를
        재사용할 때만 의미가 있다.

        exchange 미지정 시 실전은 "SOR"(통합), 모의투자는 "KRX"로 기본값이 갈린다.
        실전에서 "KRX" 고정이면 정규장(09:00~15:30) 밖, 즉 넥스트레이드(NXT)
        시간대(08:00~20:00)에 주문을 넣어도 체결/거부 여부가 불확실해서 "SOR"(그
        순간 체결 가능한 거래소로 자동 라우팅)을 쓴다. 반면 모의투자 계좌는 SOR
        주문 자체가 막혀 있어서(실측: return_code=20, "RC9000:모의투자에서는
        해당업무가 제공되지 않습니다") "KRX"로 보내야 주문이 들어간다 — 조회용
        TR(kt00004 등)은 모의투자에서도 SOR이 되는 것과 다르다.
        """
        order_id = client_order_id or uuid.uuid4().hex
        if order_id in self._submitted_orders:
            return self._submitted_orders[order_id]

        if exchange is None:
            exchange = "KRX" if self.is_mock else "SOR"
        api_id = "kt10000" if side == "buy" else "kt10001"
        body = {
            "dmst_stex_tp": exchange,
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
            # int(price)로 정수화 — 호출부(oversold_trading_loop.py 등)가 현재가를
            # float으로 넘기면 str(93000.0) == "93000.0"이 되어 ord_uv가 "정수만
            # 입력가능합니다"로 거부된다(실측: return_code=2, [1517]).
            "ord_uv": str(int(price)) if order_type != "3" and price else "",
            "trde_tp": order_type,
            "cond_uv": "",
        }
        result = self.request_tr(api_id, body, path="/api/dostk/ordr")
        self._submitted_orders[order_id] = result
        return result

    def seed_submitted_order(self, client_order_id: str, response: dict) -> None:
        """멱등성 캐시(_submitted_orders)에 과거 place_order 응답을 재주입한다.
        이 캐시는 프로세스 메모리뿐이라 재시작하면 비는데(위 주석), order_execution.
        load_recent_orders()가 디스크 로그로 재시작 후 복원할 때 쓴다."""
        self._submitted_orders[client_order_id] = response

    def cancel_order(self, order_no: str, stock_code: str, quantity: int, exchange: str | None = None) -> dict:
        """주식 취소주문 (kt10003). quantity=0이면 잔량 전부 취소.

        exchange 기본값은 place_order와 동일한 규칙(모의투자="KRX", 실전="SOR") —
        주문을 넣은 거래소와 다른 값으로 취소를 보내면 거부될 수 있어 둘의
        기본값을 맞춰둔다."""
        if exchange is None:
            exchange = "KRX" if self.is_mock else "SOR"
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
