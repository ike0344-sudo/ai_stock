"""코스피/코스닥/나스닥 지수의 "지금 이 순간" 현재값·등락률 스냅샷 — 대시보드
헤더 티커용. 코스피/코스닥은 키움 REST API(ka20006, 종목 일봉 차트와 동일한
필드로 응답)를 재사용하고, 나스닥은 키움이 지원하지 않는 해외지수라 인증이
필요없는 Yahoo Finance 차트 API(query1.finance.yahoo.com)로 별도 조회한다 —
stooq는 최근 봇 차단(JS 프루프오브워크 챌린지)이 걸려 requests로는 더 이상
CSV를 받을 수 없어서 채택하지 않았다. User-Agent 헤더 없이 호출하면 429가
나서(브라우저 UA 없는 요청을 봇으로 간주하는 듯) 브라우저 UA를 명시한다.

대시보드가 5초 간격으로 폴링하는데 그때마다 외부 API를 때리면 과다호출/속도
저하로 이어지므로, CACHE_TTL_SECONDS 동안은 마지막 조회 결과를 그대로 재사용한다
(top35_job.py처럼 백그라운드 스레드로 미리 갱신하지 않고, 캐시 만료 시점의 폴링
요청 하나가 동기적으로 다시 채워 넣는 단순한 방식 — 개인용 로컬 대시보드 규모에서는
그 정도 지연이면 충분하다). 코스피/코스닥/나스닥 중 하나가 실패해도 그 지수만
None으로 두고 나머지는 정상 반환한다(부분 실패 허용, trading_loop.py/risk_manager.py
등 실주문 로직과는 무관한 읽기 전용 조회).
"""
import threading
import time

import requests
from kiwoom_client import KiwoomClient

from fetch_chart import DAILY_COLUMN_MAP, find_records, to_dataframe

KOSPI_INDEX_CODE = "001"
KOSDAQ_INDEX_CODE = "101"
CACHE_TTL_SECONDS = 60.0
NASDAQ_YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EIXIC?interval=1d&range=5d"
NASDAQ_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0"}

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
    """Yahoo Finance 차트 API(^IXIC, 나스닥종합)의 meta에서 현재가/전일종가를 받아
    등락률을 계산한다. API 키가 필요 없는 공개 엔드포인트라 실패하면(네트워크 차단,
    형식 변경 등) 조용히 None을 반환한다 — 나스닥 하나 실패했다고 코스피/코스닥까지
    못 보여줄 이유는 없다."""
    try:
        res = requests.get(NASDAQ_YAHOO_URL, headers=NASDAQ_REQUEST_HEADERS, timeout=10)
        res.raise_for_status()
        meta = res.json()["chart"]["result"][0]["meta"]
        latest = float(meta["regularMarketPrice"])
        previous = meta.get("chartPreviousClose")
    except Exception:
        return None
    return {"value": latest, "change_pct": _index_change(latest, float(previous) if previous else None)}


def get_market_snapshot(appkey: str, secretkey: str, is_mock: bool) -> dict:
    """{"kospi": {"value", "change_pct"} | None, "kosdaq": ..., "nasdaq": ...} 반환.

    CACHE_TTL_SECONDS 이내 재호출은 마지막 결과를 그대로 돌려준다. appkey/secretkey가
    비어 있으면(대시보드만 켜두고 .env를 아직 안 채운 경우 등) 코스피/코스닥 조회를
    아예 시도하지 않고 None으로 둔다 — 나스닥은 키움 자격증명과 무관하므로 계속 시도한다.
    """
    global _cached_snapshot, _cached_at
    with _lock:
        if _cached_snapshot is not None and (time.monotonic() - _cached_at) < CACHE_TTL_SECONDS:
            return _cached_snapshot

    kospi = kosdaq = None
    if appkey and secretkey:
        client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
        kospi = _kiwoom_index_snapshot(client, KOSPI_INDEX_CODE)
        kosdaq = _kiwoom_index_snapshot(client, KOSDAQ_INDEX_CODE)
    nasdaq = _nasdaq_snapshot()

    snapshot = {"kospi": kospi, "kosdaq": kosdaq, "nasdaq": nasdaq}
    with _lock:
        _cached_snapshot = snapshot
        _cached_at = time.monotonic()
    return snapshot
