"""나스닥100 선물(NQ=F)이 짧은 시간 안에 급락하면 텔레그램으로 알린다.

"왜 하락하는지"는 가격 데이터만으로는 확정할 수 없다 — 대신 그 시점 전후의 관련
뉴스 헤드라인을 자동으로 붙여서 참고자료로 같이 보낸다(인과관계를 보장하지 않는
"이 근처에 이런 뉴스가 있었다" 수준). 헤드라인은 API 키가 필요 없는 Google News
RSS(공개 엔드포인트)에서 가져온다 — market_snapshot.py가 나스닥 가격을 Yahoo
Finance 무인증 API로 가져오는 것과 같은 이유(별도 자격증명/설정 없이 바로 동작).

한국 주식 전략(전략1~4)과 달리 정규장/통합장 시간 제한을 두지 않는다 — NQ=F는
CME에서 평일 거의 24시간 거래되므로 시간 게이트 자체가 의미가 없다.
"""
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

from .heartbeat import write_heartbeat
from .market_snapshot import fetch_nasdaq_futures_snapshot
from .notifier import notify_nasdaq_drop
from .stop_control import clear_stop_flag, is_stop_requested
from .telegram_news_source import DEFAULT_CHANNEL as NEWS_TELEGRAM_CHANNEL
from .telegram_news_source import fetch_telegram_channel_posts

WINDOW_SECONDS = 180.0  # 3분
DROP_THRESHOLD_PCT = -1.0
REARM_THRESHOLD_PCT = DROP_THRESHOLD_PCT / 2  # 급락 후 이 선까지 회복해야 다음 알림이 다시 무장됨
HISTORY_RETENTION_MULTIPLIER = 2  # window_seconds의 몇 배까지 과거 샘플을 보관할지

NEWS_RSS_URL_TEMPLATE = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
NEWS_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0"}
NEWS_QUERY = "nasdaq"
NEWS_HEADLINE_LIMIT = 5

DEFAULT_STATE_DIR = "state/nasdaq_drop_monitor"
DEFAULT_STOP_FLAG_PATH = "state/nasdaq_drop_monitor/stop_requested.json"


def _now() -> float:
    """time.time()의 얇은 래퍼 — heartbeat.py도 별도로 time.time()을 호출하므로
    (같은 time 모듈 객체) 테스트에서 time.time 자체를 패치하면 heartbeat 호출까지
    같이 소비돼버린다. 이 함수만 패치하면 가격 샘플링용 시계만 제어할 수 있다."""
    return time.time()


def compute_window_change_pct(
    history: list[tuple[float, float]], now_ts: float, window_seconds: float = WINDOW_SECONDS
) -> float | None:
    """history: [(epoch초, 가격), ...] 오래된 순으로 쌓인 샘플들. now_ts 기준
    window_seconds 이전에 가장 가까운(그 이전 중 가장 최신) 샘플을 기준가로 삼아
    최신 샘플 대비 등락률(%)을 반환한다. 기준가로 쓸 만큼 오래된 샘플이 아직 없으면
    (감시 시작 직후 등) None."""
    if not history:
        return None
    latest_price = history[-1][1]
    cutoff = now_ts - window_seconds
    baseline_price = None
    for ts, price in history:
        if ts <= cutoff:
            baseline_price = price
        else:
            break
    if baseline_price is None or baseline_price == 0:
        return None
    return (latest_price - baseline_price) / baseline_price * 100


def fetch_related_news_headlines(query: str = NEWS_QUERY, limit: int = NEWS_HEADLINE_LIMIT) -> list[str]:
    """Google News RSS(공개, API 키 불필요)에서 query 관련 최신 헤드라인을 가져온다.
    실패하면 빈 리스트를 반환한다 — 뉴스 조회 실패가 급락 알림 자체를 막으면 안 된다
    (market_snapshot.py의 나스닥 조회 실패 처리와 같은 원칙)."""
    url = NEWS_RSS_URL_TEMPLATE.format(query=quote(query))
    try:
        res = requests.get(url, headers=NEWS_REQUEST_HEADERS, timeout=10)
        res.raise_for_status()
        root = ET.fromstring(res.content)
        titles = [item.findtext("title") for item in root.iter("item")]
        return [t for t in titles if t][:limit]
    except Exception:
        return []


def fetch_combined_headlines() -> list[str]:
    """Google News + 텔레그램 First Squawk 채널(속보 헤드라인 특화) 두 소스를 합쳐
    반환한다. First Squawk을 먼저 배치한다 — 시황 급변 원인 파악용으로는 종합 뉴스
    검색보다 몇 분 단위로 올라오는 속보 채널 쪽이 시간적으로 더 근접한 경우가 많다.
    두 소스 다 각자 실패해도 예외 없이 빈 리스트로 처리되므로 한쪽이 죽어도 나머지는
    그대로 나간다."""
    return fetch_telegram_channel_posts(NEWS_TELEGRAM_CHANNEL) + fetch_related_news_headlines()


def run_nasdaq_drop_monitor(
    bot_token: str,
    chat_id: str,
    poll_interval_seconds: float = 15.0,
    window_seconds: float = WINDOW_SECONDS,
    threshold_pct: float = DROP_THRESHOLD_PCT,
    state_dir: str = DEFAULT_STATE_DIR,
    stop_flag_path: str | None = None,
) -> None:
    """polling으로 NQ=F 현재가를 쌓아가며 window_seconds 내 등락률이 threshold_pct
    이하로 떨어지면 알림 + 관련 뉴스 헤드라인을 보낸다.

    같은 급락 국면에서 알림이 매 사이클 반복되지 않도록, 한 번 알린 뒤에는
    REARM_THRESHOLD_PCT(기본 threshold_pct의 절반)까지 회복해야 다음 알림이 다시
    무장된다(breakout_reversal.py의 armed 패턴과 같은 발상 — 무장 전엔 재발동 안 함)."""
    stop_flag_path = stop_flag_path or DEFAULT_STOP_FLAG_PATH
    clear_stop_flag(stop_flag_path)
    write_heartbeat(state_dir)

    history: list[tuple[float, float]] = []
    armed = True
    while not is_stop_requested(stop_flag_path):
        # "항상 켜져 있어야 하는" 상시 감시라 사이클 하나에서 예상 못 한 예외가 나도
        # (가격 파싱 변경 등 개별 함수가 이미 방어 못 한 버그) 루프 전체가 죽어서
        # 감시가 멈추면 안 된다 — 로그만 남기고 다음 사이클에서 계속한다. 이 사이클도
        # write_heartbeat까지는 도달해야 대시보드가 "실행중"을 계속 정확히 보여준다.
        try:
            snapshot = fetch_nasdaq_futures_snapshot()
            now_ts = _now()
            if snapshot is not None and snapshot.get("value") is not None:
                history.append((now_ts, snapshot["value"]))
                retention_cutoff = now_ts - window_seconds * HISTORY_RETENTION_MULTIPLIER
                history = [(ts, price) for ts, price in history if ts >= retention_cutoff]

                change_pct = compute_window_change_pct(history, now_ts, window_seconds)
                if change_pct is not None:
                    if armed and change_pct <= threshold_pct:
                        headlines = fetch_combined_headlines()
                        notify_nasdaq_drop(change_pct, snapshot["value"], headlines, bot_token, chat_id)
                        armed = False
                    elif not armed and change_pct > REARM_THRESHOLD_PCT:
                        armed = True
        except Exception as exc:
            print(f"나스닥 급락 감시 사이클 오류(계속 진행): {exc}", flush=True)

        write_heartbeat(state_dir)
        time.sleep(poll_interval_seconds)
