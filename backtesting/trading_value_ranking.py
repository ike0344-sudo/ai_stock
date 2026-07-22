"""거래대금 상위 순위를 실시간으로 보여주는 대시보드 패널용 — 확장시간(08:00~20:00)
동안만 재조회한다. 비활성 시간대 밖에서는 마지막으로 성공한 스냅샷을 그대로
유지해("OO시 XX분 기준" 식으로) 새로고침해도 화면이 비지 않게 한다.

top_by_trading_value(screener.py)를 그대로 재사용한다 — ETF/ETN/스팩·관리종목 제외
로직을 여기서 중복 구현하지 않는다. run-trading의 watchlist 선정에도 같은 함수를
쓰지만, 여기서 만드는 캐시(_cache)는 별개 — 이 모듈은 순수 조회 전용이라 서로의
상태에 영향을 주지 않는다.
"""
import threading
import time
from datetime import datetime
from datetime import time as clock_time

from kiwoom_client import KiwoomClient

from .screener import top_by_trading_value

EXTENDED_HOURS_START = clock_time(8, 0)
EXTENDED_HOURS_END = clock_time(20, 0)
CACHE_TTL_SECONDS = 10.0

_lock = threading.Lock()
_cache: dict[str, dict] = {}  # "extended" -> {"rows", "as_of", "fetched_at"}


def is_extended_hours(now: datetime) -> bool:
    """평일 08:00~20:00(KST)만. 공휴일 캘린더는 반영하지 않는다."""
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=EXTENDED_HOURS_START.hour, minute=EXTENDED_HOURS_START.minute, second=0, microsecond=0)
    end = now.replace(hour=EXTENDED_HOURS_END.hour, minute=EXTENDED_HOURS_END.minute, second=0, microsecond=0)
    return start <= now <= end


WINDOW_CHECKS = {"extended": is_extended_hours}


def _fetch_rows(appkey: str, secretkey: str, is_mock: bool, top_n: int) -> list[dict]:
    client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
    df = top_by_trading_value(client, top_n=top_n)
    return df.to_dict("records")


def get_ranking(
    appkey: str, secretkey: str, is_mock: bool, window: str, top_n: int = 20, now: datetime | None = None
) -> dict:
    """window: "extended"(08:00~20:00, 현재 유일하게 지원하는 값).

    반환: {"rows": [...], "as_of": "HH:MM:SS" | None, "active": bool}. active=False면
    지금이 활성 시간대가 아니라는 뜻 — 프론트가 "활성 시간대에만 갱신됩니다" 같은
    안내를 보여줄 수 있게 한다. active=True인데 rows가 이전과 동일할 수도 있다
    (CACHE_TTL_SECONDS 이내 재호출, 혹은 이번 조회가 실패해 마지막 스냅샷을 유지한
    경우 — 둘 다 화면을 비우는 것보다 낫다).
    """
    now = now or datetime.now()
    check = WINDOW_CHECKS.get(window)
    if check is None:
        raise ValueError(f"알 수 없는 window: {window} (extended만 허용)")
    active = check(now)

    with _lock:
        cached = _cache.get(window)

    if not active:
        if cached:
            return {"rows": cached["rows"], "as_of": cached["as_of"], "active": False}
        return {"rows": [], "as_of": None, "active": False}

    if cached and (time.monotonic() - cached["fetched_at"]) < CACHE_TTL_SECONDS:
        return {"rows": cached["rows"], "as_of": cached["as_of"], "active": True}

    rows = None
    if appkey and secretkey:
        try:
            rows = _fetch_rows(appkey, secretkey, is_mock, top_n)
        except Exception:
            rows = None

    if rows is None:
        if cached:
            return {"rows": cached["rows"], "as_of": cached["as_of"], "active": True}
        return {"rows": [], "as_of": None, "active": True}

    as_of = now.strftime("%H:%M:%S")
    with _lock:
        _cache[window] = {"rows": rows, "as_of": as_of, "fetched_at": time.monotonic()}
    return {"rows": rows, "as_of": as_of, "active": True}
