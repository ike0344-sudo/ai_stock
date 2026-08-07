"""거래대금 상위 순위를 실시간으로 보여주는 대시보드 패널용 — 정규장(09:00~15:30)과
확장시간(08:00~20:00) 두 창구로 나눠서 각자 자기 활성시간대에만 재조회한다. 활성
시간대 밖에서는 마지막으로 성공한 스냅샷을 그대로 유지해("OO시 XX분 기준" 식으로)
새로고침해도 화면이 비지 않게 한다.

ka10032(거래대금상위요청)는 세션(장중/시간외)별로 분리된 수치를 주는 요청 파라미터가
없다(라이브 테스트로 여러 후보 필드명을 다 확인함, 관련 TR ka10030의 공식 예제 필드
목록에도 없음) — API가 주는 값은 항상 "지금 이 순간까지의 전체 누적" 하나뿐이다.
그래서 "regular"(장중)는 직접 계산한다: 09:00 장 시작 직전(장전시간외 마지막) 누적
거래대금/거래량을 베이스라인으로 저장해두고, 그 이후 매 조회 시점의 누적값에서
베이스라인을 빼서 "정규장 시간 동안만의" 순수 증가분을 구한다. 이 증가분 기준으로
순위도 다시 매긴다(원본 순위는 확장시간 누적 기준이라 그대로 쓰면 순서가 다를 수
있음). 베이스라인은 state/regular_session_baseline.json에 저장해 대시보드가
장중에 재시작돼도 그날 베이스라인을 잃지 않게 한다.

베이스라인은 "extended" 창구가 09:00 이전(장전시간외, 08:00~09:00)에 최소 한 번은
조회돼야 잡힌다 — 브라우저 탭이 그 시간에 열려 있어야만 잡히면 사용자가 깜빡하고
놓치기 쉬우므로, start_background_poller()가 대시보드 서버 프로세스 자체 안에서
주기적으로(브라우저 유무와 무관하게) "extended"를 스스로 조회해 이 조건을 채운다
(cli.py의 dashboard 커맨드가 서버 시작 시 자동으로 돌림). 그래도 놓치면(대시보드
프로세스 자체가 그 시간에 안 떠 있었으면) "regular"가 그날 첫 조회 시점 값을 0으로
잡고 시작한다 — API 자체에 과거 시점 조회가 없어 불가피한 한계.

top_by_trading_value(screener.py)를 그대로 재사용한다 — ETF/ETN/스팩·관리종목 제외
로직을 여기서 중복 구현하지 않는다. run-trading의 watchlist 선정에도 같은 함수를
쓰지만, 여기서 만드는 캐시(_cache)는 별개 — 이 모듈은 순수 조회 전용이라 서로의
상태에 영향을 주지 않는다.
"""
import json
import math
import os
import threading
import time
from datetime import datetime
from datetime import time as clock_time

from kiwoom_client import KiwoomClient

from .orderbook_collector import MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE, is_market_open
from .screener import top_by_trading_value

EXTENDED_HOURS_START = clock_time(8, 0)
EXTENDED_HOURS_END = clock_time(20, 0)
MARKET_OPEN_TIME = clock_time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)
CACHE_TTL_SECONDS = 3.0
BASELINE_PATH = "state/regular_session_baseline.json"

_lock = threading.Lock()
_cache: dict[str, dict] = {}  # "regular" | "extended" -> {"rows", "as_of", "fetched_at"}
_pre_market_snapshot: dict[str, dict] = {}  # stock_code -> {"trading_value", "volume"} — 장 시작 전 마지막 조회값
_pre_market_snapshot_date: str | None = None  # 위 스냅샷이 찍힌 날짜 — 날짜 안 맞으면 베이스라인으로 안 씀
_baseline: dict[str, dict] | None = None  # 오늘자로 확정된 베이스라인(장 시작 시 잠금)
_baseline_date: str | None = None


def is_extended_hours(now: datetime) -> bool:
    """평일 08:00~20:00(KST)만 — 정규장(09:00~15:30) 전후 시간외 거래까지 포함해 보고
    싶을 때 쓰는 더 넓은 창구. is_market_open과 동일하게 공휴일 캘린더는 반영하지
    않는다."""
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=EXTENDED_HOURS_START.hour, minute=EXTENDED_HOURS_START.minute, second=0, microsecond=0)
    end = now.replace(hour=EXTENDED_HOURS_END.hour, minute=EXTENDED_HOURS_END.minute, second=0, microsecond=0)
    return start <= now <= end


WINDOW_CHECKS = {"regular": is_market_open, "extended": is_extended_hours}


def _fetch_rows(appkey: str, secretkey: str, is_mock: bool, top_n: int) -> list[dict]:
    client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
    df = top_by_trading_value(client, top_n=top_n)
    # screener.py는 volume_vs_prev_day_pct=None(전일 거래량 0, 오늘 상장 등)으로 채우지만,
    # pd.DataFrame이 float 컬럼에 None을 섞으면 NaN으로 바꿔버린다 — json.dumps는 기본적으로
    # NaN을 리터럴 NaN으로 직렬화하는데 이건 표준 JSON이 아니라 브라우저 JSON.parse가
    # 파싱에 실패한다. 그 종목이 top_n 안에 있는 한 프론트의 거래대금 랭킹 폴링이 매번
    # 조용히 실패해(app.js pollRanking의 catch) 화면이 "멈춘 것"처럼 보였다(실측).
    return [
        {key: (None if isinstance(value, float) and math.isnan(value) else value) for key, value in record.items()}
        for record in df.to_dict("records")
    ]


def _load_baseline_file() -> dict | None:
    if not os.path.exists(BASELINE_PATH):
        return None
    try:
        with open(BASELINE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_baseline_file(date_str: str, baseline: dict) -> None:
    directory = os.path.dirname(BASELINE_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(BASELINE_PATH, "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "baseline": baseline}, f, ensure_ascii=False)


def _update_pre_market_snapshot(rows: list[dict], now: datetime) -> None:
    """장 시작 전(08:00~09:00, 장전시간외) 조회라면 최신 스냅샷으로 계속 덮어써서,
    09:00에 가장 가까운 시점의 누적값을 남긴다. 날짜를 같이 찍어두는 이유 —
    _ensure_baseline이 이 스냅샷을 베이스라인으로 잠글 때 "오늘 장전" 것인지 확인해야
    한다. 아니면 대시보드가 며칠째 안 꺼져서 어제 장전 스냅샷이 그대로 남아있는 경우,
    새 거래일에 어제 값을 오늘 베이스라인으로 잘못 잠가버린다(실측 발견)."""
    if now.time() >= MARKET_OPEN_TIME:
        return
    global _pre_market_snapshot, _pre_market_snapshot_date
    _pre_market_snapshot = {
        row["stock_code"]: {"trading_value": row["trading_value"], "volume": row["volume"]} for row in rows
    }
    _pre_market_snapshot_date = now.date().isoformat()


def _ensure_baseline(now: datetime) -> dict:
    """오늘자 베이스라인을 확정해 반환한다. 이미 확정돼 있으면(메모리 또는 파일) 그대로
    쓰고, 오늘 09:00을 넘겼는데 아직 없으면 지금까지 모인 장전 스냅샷을 그 순간 잠가서
    파일에 저장한다(대시보드 재시작에도 유지). 장전 스냅샷이 오늘 것이 아니면(어제
    이전 것이거나 아예 없으면) 빈 베이스라인(0 취급)으로 시작한다.

    빈 베이스라인은 "확정"으로 취급하지 않는다 — window="regular"만 조회하는 프로세스
    (strategy4_rank_watch.py 등, "extended"를 안 불러 장전 스냅샷이 절대 안 쌓임)가
    09:00 직후 이 함수를 먼저 호출하면 장전 스냅샷 없이 빈 베이스라인을 그 순간 파일에
    잠가버려, 그 뒤로 진짜 장전 스냅샷을 가진 다른 프로세스(대시보드 등)까지 파일만
    믿고 하루 종일 빈 베이스라인(=장중 증가분이 사실상 누적치 전체)을 쓰게 되는 문제가
    있었다(실측). 메모리/파일 모두 baseline이 비어 있으면 "아직 못 구함"으로 보고 계속
    재시도하되, 빈 값 자체는 파일에 저장하지 않아 다른 프로세스가 나중에 진짜 스냅샷으로
    덮어쓸 여지를 남긴다."""
    global _baseline, _baseline_date
    today_str = now.date().isoformat()

    if _baseline_date == today_str and _baseline:
        return _baseline

    loaded = _load_baseline_file()
    if loaded and loaded.get("date") == today_str and loaded.get("baseline"):
        _baseline = loaded["baseline"]
        _baseline_date = today_str
        return _baseline

    if now.time() >= MARKET_OPEN_TIME and _pre_market_snapshot_date == today_str:
        _baseline = dict(_pre_market_snapshot)
        _baseline_date = today_str
        _save_baseline_file(today_str, _baseline)
        return _baseline

    return {}


def _apply_regular_session_baseline(rows: list[dict], now: datetime) -> list[dict]:
    """각 종목의 누적 거래대금/거래량에서 장 시작 전 베이스라인을 빼 "정규장 동안만"의
    순수 증가분으로 바꾸고, 그 증가분 기준으로 다시 정렬·순위를 매긴다. 베이스라인이
    없는 종목(장전에 top_n 밖이었다가 장중에 새로 진입 등)은 0으로 취급 — 누적값을
    그대로 "장중 증가분"으로 본다."""
    baseline = _ensure_baseline(now)
    adjusted = []
    for row in rows:
        base = baseline.get(row["stock_code"], {})
        new_row = dict(row)
        new_row["trading_value"] = row["trading_value"] - base.get("trading_value", 0)
        new_row["volume"] = row["volume"] - base.get("volume", 0)
        if row.get("prev_day_volume"):
            new_row["volume_vs_prev_day_pct"] = new_row["volume"] / row["prev_day_volume"] * 100
        adjusted.append(new_row)

    adjusted.sort(key=lambda r: r["trading_value"], reverse=True)
    for i, row in enumerate(adjusted):
        row["rank"] = i + 1
    return adjusted


def get_ranking(
    appkey: str, secretkey: str, is_mock: bool, window: str, top_n: int = 20, now: datetime | None = None
) -> dict:
    """window: "regular"(09:00~15:30, 장중 순증가분만) | "extended"(08:00~20:00, 전체 누적).

    반환: {"rows": [...], "as_of": "HH:MM:SS" | None, "active": bool}. active=False면
    지금이 그 창구의 활성 시간대가 아니라는 뜻 — 프론트가 "정규장 시간에만 갱신됩니다"
    같은 안내를 보여줄 수 있게 한다. active=True인데 rows가 이전과 동일할 수도 있다
    (CACHE_TTL_SECONDS 이내 재호출, 혹은 이번 조회가 실패해 마지막 스냅샷을 유지한
    경우 — 둘 다 화면을 비우는 것보다 낫다).
    """
    now = now or datetime.now()
    check = WINDOW_CHECKS.get(window)
    if check is None:
        raise ValueError(f"알 수 없는 window: {window} (regular 또는 extended만 허용)")
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

    _update_pre_market_snapshot(rows, now)
    if window == "regular":
        rows = _apply_regular_session_baseline(rows, now)

    as_of = now.strftime("%H:%M:%S")
    with _lock:
        _cache[window] = {"rows": rows, "as_of": as_of, "fetched_at": time.monotonic()}
    return {"rows": rows, "as_of": as_of, "active": True}


def _poll_loop(appkey: str, secretkey: str, is_mock: bool, interval_seconds: float) -> None:
    while True:
        try:
            get_ranking(appkey, secretkey, is_mock, "extended")
        except Exception:
            pass  # 다음 주기에 자연히 재시도 — 백그라운드 폴러가 죽으면 안 됨
        time.sleep(interval_seconds)


def start_background_poller(appkey: str, secretkey: str, is_mock: bool, interval_seconds: float = 10.0) -> threading.Thread:
    """대시보드 서버 프로세스가 살아있는 동안 브라우저 탭 없이도 "extended" 창구를
    스스로 주기적으로 조회하는 데몬 스레드를 시작한다 — "regular"(장중) 베이스라인이
    08:00~09:00 사이에 사람이 브라우저를 열어봐야만 잡히는 문제를 없애기 위함
    (모듈 docstring 참고). cli.py의 dashboard 커맨드가 서버 시작 시 호출한다."""
    thread = threading.Thread(target=_poll_loop, args=(appkey, secretkey, is_mock, interval_seconds), daemon=True)
    thread.start()
    return thread
