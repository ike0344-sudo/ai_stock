"""코스피/코스닥/나스닥100 선물의 "지금 이 순간" 현재값·등락률 스냅샷 — 대시보드
헤더 티커용. 코스피/코스닥은 키움 REST API(ka20006, 종목 일봉 차트와 동일한
필드로 응답)를 재사용하고, 나스닥은 키움이 지원하지 않는 해외지수라 인증이
필요없는 Yahoo Finance 차트 API(query1.finance.yahoo.com)로 별도 조회한다 —
stooq는 최근 봇 차단(JS 프루프오브워크 챌린지)이 걸려 requests로는 더 이상
CSV를 받을 수 없어서 채택하지 않았다. User-Agent 헤더 없이 호출하면 429가
나서(브라우저 UA 없는 요청을 봇으로 간주하는 듯) 브라우저 UA를 명시한다.

나스닥 "지수"(^IXIC)가 아니라 나스닥100 선물(NQ=F, CME)을 쓴다 — 현물지수는
미국 정규장(한국시간 밤~새벽)에만 움직여서 한국 장중엔 전날 종가로 멈춰 있는
반면, 선물은 거의 24시간 거래돼 한국 장중에도 실시간에 가깝게 움직인다(실측:
NQ=F가 instrumentType=FUTURE, exchangeName=CME로 응답, meta 필드 구조는
지수와 동일해 기존 파싱 로직 그대로 재사용 가능).

대시보드가 짧은 간격으로 폴링하는데 그때마다 외부 API를 때리면 과다호출/속도
저하로 이어지므로, CACHE_TTL_SECONDS 동안은 마지막 조회 결과를 그대로 재사용한다
(top35_job.py처럼 백그라운드 스레드로 미리 갱신하지 않고, 캐시 만료 시점의 폴링
요청 하나가 동기적으로 다시 채워 넣는 단순한 방식). 코스피/코스닥/나스닥 중 하나가
실패해도 그 지수만 None으로 두고 나머지는 정상 반환한다(부분 실패 허용,
trading_loop.py/risk_manager.py 등 실주문 로직과는 무관한 읽기 전용 조회).

KiwoomClient는 kiwoom_session.get_client()로 대시보드 프로세스 전체가 공유하는
인스턴스를 그대로 쓴다(모듈별로 따로 만들지 않음) — 매번 새로 만들면 매 호출마다
OAuth 토큰을 재발급받는 문제도 있지만(issue_token()은 _throttle() 페이싱 대상이
아님), 더 중요한 건 account_status.py 등 다른 패널이 "각자 페이싱하는 별도
클라이언트"를 쓰면 서로의 호출 타이밍을 몰라서 계정 단위 rate limit을 함께
넘길 수 있다는 점이다(실측: market_snapshot 폴링을 1~2초로 당긴 뒤 account_status를
동시에 돌리면 토큰 발급 자체가 429). 클라이언트를 공유하면 프로세스 안의 모든
키움 호출이 하나의 페이싱 상태를 따르게 된다.
"""
import threading
import time

import requests
from kiwoom_client import KiwoomClient

from fetch_chart import DAILY_COLUMN_MAP, find_records, to_dataframe
from .kiwoom_session import get_client

KOSPI_INDEX_CODE = "001"
KOSDAQ_INDEX_CODE = "101"
CACHE_TTL_SECONDS = 1.0
NASDAQ_YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/NQ=F?interval=15m&range=5d"
NASDAQ_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0"}
ROLLING_CHANGE_WINDOW_SECONDS = 24 * 60 * 60

_lock = threading.Lock()
_cached_snapshot: dict | None = None
_cached_at = 0.0


def _index_change(latest: float, previous: float | None) -> float | None:
    if not previous:
        return None
    return (latest - previous) / previous * 100


def _kiwoom_index_snapshot(client: KiwoomClient, index_code: str) -> dict | None:
    """ka20006(업종 일봉) 오늘자 응답의 마지막 두 행(전일/당일 종가)으로 현재값·등락률을
    계산한다. dt/cur_prc 등 필드명은 개별 종목 일봉과 동일해 fetch_chart의 파싱 유틸을
    그대로 재사용할 수 있다(data_loader.load_index_history와 같은 근거)."""
    try:
        payload = client.get_index_daily_chart(index_code)
        df = to_dataframe(find_records(payload), DAILY_COLUMN_MAP, "%Y%m%d")
    except Exception:
        return None
    if df.empty:
        return None
    latest = float(df["close"].iloc[-1])
    previous = float(df["close"].iloc[-2]) if len(df) >= 2 else None
    return {"value": latest, "change_pct": _index_change(latest, previous)}


def _nasdaq_snapshot() -> dict | None:
    """Yahoo Finance 차트 API(NQ=F, 나스닥100 선물)의 meta에서 현재가/전일종가를 받아
    등락률을 계산한다. API 키가 필요 없는 공개 엔드포인트라 실패하면(네트워크 차단,
    형식 변경 등) 조용히 None을 반환한다 — 나스닥 하나 실패했다고 코스피/코스닥까지
    못 보여줄 이유는 없다.

    전일종가는 일봉 종가 배열이 아니라 15분봉으로 "지금으로부터 정확히 24시간 전에
    가장 가까운" 시점의 가격을 쓴다. 예전엔 일봉 배열의 뒤에서 두 번째 값을 썼는데,
    NQ=F(선물)는 그 자리가 통째로 비어(None) 나오는 세션이 실측으로 확인됐고, 그럴 때
    None을 걸러내고 그다음(2세션 전) 값을 대신 쓰면 며칠치 변동이 하루치 등락률에
    섞여 실제(-0.04%~+0.07%, investing.com/Yahoo 웹페이지 실측 대조)와 동떨어진 큰
    값(-1.8%대)이 나왔다(실측). 15분봉은 하루에 ~96개 표본이 있어 특정 봉 하나가
    비어도 바로 옆(최대 ±15분 오차) 봉으로 대체되므로 같은 문제가 재발하지 않는다.

    meta.regularMarketTime을 "지금" 기준시각으로 쓴다(요청·응답 왕복 시간만큼 실제
    현재시각과 아주 약간 다를 수 있지만 15분봉 오차 범위 안이라 무시 가능). 24시간
    전과 12시간 넘게 떨어진 봉은 후보에서 아예 제외한다 — 그래야 조회 범위가
    짧아 24시간 전 근방 데이터가 하나도 없는 경우(예: 5일치 요청이 실패해 최근
    몇 개 봉만 온 경우) "지금과 거의 같은 시각" 봉을 엉뚱하게 전일가로 써서
    등락률이 0%에 가깝게 잘못 나오는 걸 막는다 — 그럴 땐 그냥 None."""
    try:
        res = requests.get(NASDAQ_YAHOO_URL, headers=NASDAQ_REQUEST_HEADERS, timeout=10)
        res.raise_for_status()
        result = res.json()["chart"]["result"][0]
        latest = float(result["meta"]["regularMarketPrice"])
        latest_ts = result["meta"]["regularMarketTime"]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        target_ts = latest_ts - ROLLING_CHANGE_WINDOW_SECONDS
        candidates = [
            (abs(ts - target_ts), c) for ts, c in zip(timestamps, closes)
            if c is not None and abs(ts - target_ts) <= ROLLING_CHANGE_WINDOW_SECONDS / 2
        ]
        previous = min(candidates, key=lambda pair: pair[0])[1] if candidates else None
    except Exception:
        return None
    return {"value": latest, "change_pct": _index_change(latest, float(previous) if previous else None)}


def fetch_nasdaq_futures_snapshot() -> dict | None:
    """나스닥100 선물(NQ=F) 현재가/전일종가 대비 등락률 스냅샷 — 대시보드 티커 외에도
    nasdaq_drop_monitor.py의 3분 급락 감지가 실시간가 소스로 재사용하는 공개 래퍼."""
    return _nasdaq_snapshot()


def get_market_snapshot(appkey: str, secretkey: str, is_mock: bool) -> dict:
    """{"kospi": {"value", "change_pct"} | None, "kosdaq": ..., "nasdaq": ...} 반환.

    CACHE_TTL_SECONDS 이내 재호출은 마지막 결과를 그대로 돌려준다. appkey/secretkey가
    비어 있으면(대시보드만 켜두고 .env를 아직 안 채운 경우 등) 코스피/코스닥 조회를
    아예 시도하지 않고 None으로 둔다 — 나스닥은 키움 자격증명과 무관하므로 계속 시도한다.

    지수별로 조회 실패 시 이전 성공값을 유지한다(account_status.py와 동일한 패턴) —
    안 그러면 장 마감 직후처럼 일시적으로 조회가 안 되는 순간에 티커가 바로 "-"로
    사라져서, 마치 장이 끝나면 지수 표시 자체가 없어지는 것처럼 보인다.
    """
    global _cached_snapshot, _cached_at
    with _lock:
        if _cached_snapshot is not None and (time.monotonic() - _cached_at) < CACHE_TTL_SECONDS:
            return _cached_snapshot
        previous = _cached_snapshot

    kospi = kosdaq = None
    if appkey and secretkey:
        client = get_client(appkey, secretkey, is_mock)
        kospi = _kiwoom_index_snapshot(client, KOSPI_INDEX_CODE)
        kosdaq = _kiwoom_index_snapshot(client, KOSDAQ_INDEX_CODE)
    nasdaq = _nasdaq_snapshot()

    if kospi is None and previous:
        kospi = previous["kospi"]
    if kosdaq is None and previous:
        kosdaq = previous["kosdaq"]
    if nasdaq is None and previous:
        nasdaq = previous["nasdaq"]

    snapshot = {"kospi": kospi, "kosdaq": kosdaq, "nasdaq": nasdaq}
    with _lock:
        _cached_snapshot = snapshot
        _cached_at = time.monotonic()
    return snapshot
