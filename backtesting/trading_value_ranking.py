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
import csv
import functools
import json
import logging
import math
import os
import threading
import time
from datetime import datetime
from datetime import time as clock_time

from kiwoom_client import KiwoomClient

from .orderbook_collector import MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE, is_market_open
from .screener import top_by_trading_value

THEME_CACHE = "data/themes.csv"     # fetch_themes.py가 네이버 금융에서 받아둔 종목->테마 표
MIN_THEME_SIZE = 6                 # 3~4종목짜리는 "S7(삼성전자/SK하이닉스 등)" 같은 자투리라 건너뛴다

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


@functools.lru_cache(maxsize=1)
def _theme_map() -> dict[str, str]:
    """종목코드 -> 대표 테마 하나.

    종목:테마는 1:N이라(삼성전자는 31개) 표에 넣을 하나를 골라야 한다. 구성종목이
    적은 테마일수록 구체적이므로 작은 쪽을 쓰되, MIN_THEME_SIZE 미만은 자투리라
    후보에서 뺀다. 전부 그보다 작으면 그중 가장 작은 것을 쓴다."""
    try:                                     # utf-8-sig: fetch_themes가 BOM 포함으로 저장한다
        with open(THEME_CACHE, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return {}
    by_code: dict[str, list[tuple[int, str]]] = {}
    for r in rows:
        by_code.setdefault(r["stock_code"], []).append((int(r["theme_size"]), r["theme"]))
    return {code: min([t for t in themes if t[0] >= MIN_THEME_SIZE] or themes)[1]
            for code, themes in by_code.items()}


_HIGH120: dict = {}
_HIGH120_MTIME: float | None = None


def _high120_map() -> dict:
    """data/high120.csv 를 mtime이 바뀔 때만 다시 읽는다(폴링마다 파일을 열지 않는다).
    파일이 없으면 빈 dict — 별표만 안 붙고 랭킹 화면은 그대로 동작한다."""
    global _HIGH120, _HIGH120_MTIME
    path = os.path.join("data", "high120.csv")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if mtime != _HIGH120_MTIME:
        from build_high120 import load
        _HIGH120, _HIGH120_MTIME = load(path), mtime
    return _HIGH120


_SESSION_HIGH: dict[str, float] = {}
_SESSION_DATE: str | None = None


def _mark_high120(rows: list[dict], now: datetime | None = None) -> list[dict]:
    """'직전 120거래일 최고가'를 **당일 고가 포함**으로 넘었는지.

    ka10032는 당일 고가를 안 주므로 폴러가 보는 현재가의 당일 최댓값을 직접 누적한다
    (10초 폴링 해상도). 그래서 장중에 한 번이라도 넘겼으면 이후 눌려도 별표가 유지된다
    — "지금 이 순간 최고가인가"보다 "오늘 신고가를 냈는가"가 쓸모 있다.

    한계: 상위 20에 들어와 있는 동안만 관측하므로, 순위 밖에서 찍은 고가는 놓칠 수 있다.
    """
    global _SESSION_HIGH, _SESSION_DATE
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    if _SESSION_DATE != today:                      # 날짜가 바뀌면 당일 고가 누적을 비운다
        _SESSION_HIGH, _SESSION_DATE = {}, today

    m = _high120_map()
    for row in rows:
        code, price = row.get("stock_code"), row.get("current_price")
        if code and price:
            _SESSION_HIGH[code] = max(_SESSION_HIGH.get(code, 0.0), float(price))
        hit = m.get(code)
        today_high = _SESSION_HIGH.get(code, price or 0.0)
        row["is_high_120"] = bool(hit and today_high > hit[0])
        row["high_120"] = hit[0] if hit else None
        row["session_high"] = _SESSION_HIGH.get(code)
    return rows


def _fetch_rows(appkey: str, secretkey: str, is_mock: bool, top_n: int,
                exclude_spac: bool = True) -> list[dict]:
    client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
    df = top_by_trading_value(client, top_n=top_n, exclude_spac=exclude_spac)
    # screener.py는 volume_vs_prev_day_pct=None(전일 거래량 0, 오늘 상장 등)으로 채우지만,
    # pd.DataFrame이 float 컬럼에 None을 섞으면 NaN으로 바꿔버린다 — json.dumps는 기본적으로
    # NaN을 리터럴 NaN으로 직렬화하는데 이건 표준 JSON이 아니라 브라우저 JSON.parse가
    # 파싱에 실패한다. 그 종목이 top_n 안에 있는 한 프론트의 거래대금 랭킹 폴링이 매번
    # 조용히 실패해(app.js pollRanking의 catch) 화면이 "멈춘 것"처럼 보였다(실측).
    themes = _theme_map()
    return [
        {**{key: (None if isinstance(value, float) and math.isnan(value) else value)
            for key, value in record.items()},
         "theme": themes.get(record.get("stock_code"), "미상")}
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
    today_str = now.date().isoformat()
    if _pre_market_snapshot_date != today_str:
        _pre_market_snapshot = {}
        _pre_market_snapshot_date = today_str
    # 통째로 덮어쓰지 않고 종목별로 **큰 값**을 남긴다. 누적값이라 큰 쪽이 09:00에 더
    # 가깝다는 뜻이라 "최신으로 갱신"이 그대로 지켜지고, 조회 폭이 다른 호출이 섞여도
    # 스냅샷이 좁아지지 않는다 — refresh_pre_market_snapshot(300종목) 직후 화면용
    # get_ranking(20종목)이 돌면서 300종목을 20종목으로 되돌리고 있었다.
    for row in rows:
        code = row["stock_code"]
        prev = _pre_market_snapshot.get(code)
        if prev is None or row["trading_value"] >= prev["trading_value"]:
            _pre_market_snapshot[code] = {
                "trading_value": row["trading_value"], "volume": row["volume"]}


BASELINE_TOP_N = 300   # 베이스라인 전용 조회 폭. 화면(20)과 따로 간다 — 아래 함수 참고.
WIDE_FETCH_SEC = 60.0                      # 평소 장전에는 1분에 한 번이면 충분하다
WIDE_FETCH_FINAL_SEC = 10.0                # 09:00 직전에는 폴러 주기대로 촘촘히
WIDE_FETCH_FINAL_FROM = clock_time(8, 55)
_last_wide_fetch: datetime | None = None


def refresh_pre_market_snapshot(
    appkey: str, secretkey: str, is_mock: bool, top_n: int = BASELINE_TOP_N,
    now: datetime | None = None,
) -> int:
    """장전 스냅샷만 넓게 채운다. 화면 캐시(_cache)는 건드리지 않는다.

    화면은 상위 20개만 보여주면 되지만, **베이스라인은 넓을수록 좋다**. 여기 없는 종목은
    장전 거래대금을 0으로 치고 정규장 순증분을 계산하므로, 20위 밖에서 장전에 거래된
    종목이 정규장 순위에서 그만큼 위로 뜬다.

    폭을 넓히려고 get_ranking(top_n=300)을 부르면 그 결과가 _cache 에 들어가 브라우저가
    받는 표까지 300줄이 된다 — 그래서 조회만 따로 한다. 09:00 이후에는 스냅샷이 더
    안 쌓이므로(_update_pre_market_snapshot 이 그 시각에 멈춘다) 그냥 돌아간다.

    돌려주는 값은 스냅샷에 담긴 종목 수 — 0이면 지금이 장전이 아니거나 조회가 비었다.
    """
    global _last_wide_fetch
    now = now or datetime.now()
    if now.time() >= MARKET_OPEN_TIME or now.time() < EXTENDED_HOURS_START:
        return 0
    # 폴러는 10초마다 도는데 300종목은 3~4페이지라 매번 받으면 08~09시 한 시간에
    # 1,000회 가까이 더 부른다 — 429가 나면 정작 베이스라인을 통째로 놓친다.
    # 스냅샷은 09:00에 가까울수록만 정확하면 되므로, 막판에만 촘촘히 받는다.
    gap = WIDE_FETCH_FINAL_SEC if now.time() >= WIDE_FETCH_FINAL_FROM else WIDE_FETCH_SEC
    if _last_wide_fetch and (now - _last_wide_fetch).total_seconds() < gap:
        return len(_pre_market_snapshot)
    # 스팩까지 담는다. 소피증권 순위는 스팩을 빼지 않으므로, 베이스라인에 스팩이
    # 없으면 그 종목만 장전 물량이 안 빠져 정규장 순위가 위로 뜬다.
    rows = _fetch_rows(appkey, secretkey, is_mock, top_n, exclude_spac=False)
    _last_wide_fetch = now
    _update_pre_market_snapshot(rows, now)
    return len(_pre_market_snapshot)


def _ensure_baseline(now: datetime) -> dict:
    """오늘자 베이스라인을 확정해 반환한다. 이미 확정돼 있으면(메모리 또는 파일) 그대로
    쓰고, 오늘 09:00을 넘겼는데 아직 없으면 지금까지 모인 장전 스냅샷을 그 순간 잠가서
    파일에 저장한다(대시보드 재시작에도 유지). 장전 스냅샷이 오늘 것이 아니면(어제
    이전 것이거나 아예 없으면) 빈 베이스라인(0 취급)으로 시작한다.

    빈 베이스라인은 "확정"으로 취급하지 않는다 — window="regular"만 조회하는 프로세스
    ("extended"를 안 불러 장전 스냅샷이 절대 안 쌓이는 프로세스)가
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
        _notify_baseline_locked(_baseline)
        return _baseline

    return {}


# 이 아래로 떨어지면 장중 순위가 조용히 부정확해진다 — 빠진 종목의 장전 물량이
# 통째로 "정규장 증가분"으로 잡히기 때문이다. 사람이 알아야 고칠 수 있어서 알린다.
BASELINE_ALERT_BELOW = 100


def _notify_baseline_locked(baseline: dict) -> None:
    """베이스라인이 확정된 순간 한 번. 09:00 은 하루에 한 번뿐이라 놓치면 그날은 끝이다.

    알림이 실패해도 순위 계산에는 아무 영향이 없어야 하므로 예외를 통째로 삼킨다.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    try:
        from .notifier import CRITICAL, INFO, send_telegram

        count = len(baseline)
        floor = min((v.get("trading_value", 0) for v in baseline.values()), default=0)
        thin = count < BASELINE_ALERT_BELOW
        head = "⚠️ 장중 순위 베이스라인이 얇습니다" if thin else "✅ 장중 순위 베이스라인 확정"
        lines = [
            head,
            f"종목 {count}개 · 최하위 장전 거래대금 {floor / 1e8:,.0f}억",
            "(빠진 종목의 장전 물량은 0으로 계산됩니다)",
        ]
        # **별도 스레드로 보낸다.** 이 함수는 get_ranking -> _ensure_baseline 경로,
        # 즉 대시보드 HTTP 요청을 처리하는 중에도 불린다. 텔레그램은 타임아웃 10초에
        # CRITICAL이면 3회 반복이라, 그대로 부르면 09:00 직후 첫 요청이 최대 30초
        # 멈춰 브라우저가 멎는다.
        threading.Thread(
            target=send_telegram, args=("\n".join(lines), token, chat),
            kwargs={"level": CRITICAL if thin else INFO},
            name="baseline-alert", daemon=True).start()
    except Exception:
        logging.debug("베이스라인 알림 실패", exc_info=True)


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

    # 비활성 시간대엔 값이 더 안 변하므로 마지막 스냅샷을 그대로 유지한다. 스냅샷이
    # 아예 없으면(서버가 그 시간대에 처음 뜬 경우) 한 번은 조회해 빈 화면을 피한다 -
    # 예전엔 여기서 바로 빈 표를 돌려줘, 20시 이후 재시작하면 순위가 통째로 사라졌다.
    if not active and cached:
        return {"rows": cached["rows"], "as_of": cached["as_of"], "active": False}

    if cached and (time.monotonic() - cached["fetched_at"]) < CACHE_TTL_SECONDS:
        return {"rows": cached["rows"], "as_of": cached["as_of"], "active": active}

    rows = None
    error = None if (appkey and secretkey) else ".env에 KIWOOM_APPKEY/KIWOOM_SECRETKEY가 없습니다"
    if appkey and secretkey:
        try:
            rows = _fetch_rows(appkey, secretkey, is_mock, top_n)
        except Exception as e:
            # 조회 실패를 그냥 삼키면 화면엔 "빈 표"만 남아, 콘솔 없는 exe로 배포된
            # 다른 PC에서는 원인을 알 방법이 아예 없었다(실측) — 로그와 응답 양쪽에 남긴다.
            error = f"{type(e).__name__}: {e}"
            logging.warning("거래대금상위 조회 실패(%s): %s", window, error)

    if rows is None:
        if cached:
            return {"rows": cached["rows"], "as_of": cached["as_of"], "active": active, "error": error}
        return {"rows": [], "as_of": None, "active": active, "error": error}

    rows = _mark_high120(rows, now)
    _update_pre_market_snapshot(rows, now)
    if window == "regular":
        rows = _apply_regular_session_baseline(rows, now)

    as_of = now.strftime("%H:%M:%S")
    with _lock:
        _cache[window] = {"rows": rows, "as_of": as_of, "fetched_at": time.monotonic()}
    return {"rows": rows, "as_of": as_of, "active": active}


def _poll_loop(appkey: str, secretkey: str, is_mock: bool, interval_seconds: float) -> None:
    while True:
        try:
            # 화면보다 먼저, 더 넓게. 장전에만 돌고 09:00 이후에는 바로 돌아간다.
            # 소피증권처럼 베이스라인 파일을 빌려 쓰는 쪽이 08:00 전에 안 떠 있어도
            # 정규장 순위를 제대로 내려면 이 폭이 필요하다.
            refresh_pre_market_snapshot(appkey, secretkey, is_mock)
            get_ranking(appkey, secretkey, is_mock, "extended")
            # "regular"도 같이 돌려야 09:00 직후 _ensure_baseline이 장전 스냅샷을 잠그고
            # 파일로 저장한다 — 이게 없으면 브라우저가 "장중" 탭을 한 번도 안 여는 날엔
            # 베이스라인 파일이 어제 날짜로 남고, "regular"만 조회하는 프로세스
            # 는 하루 종일 베이스라인 없이 누적 기준 순위를 보게 된다(실측: 2026-08-10,
            # 대시보드는 대한광통신 4위인데 순위 감시 쪽은 5위로 보여 승격 신호가 안 나갔다).
            get_ranking(appkey, secretkey, is_mock, "regular")
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
