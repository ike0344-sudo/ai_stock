"""과거 시세 로딩 + 로컬 CSV 캐시.

Design: docs/02-design/features/strategy-backtesting.design.md §4.1, §6.1
"""
import os
import time
from datetime import date

import pandas as pd

from fetch_chart import DAILY_COLUMN_MAP, MINUTE_COLUMN_MAP, find_records, to_dataframe
from kiwoom_client import KiwoomClient

CACHE_DIR = os.environ.get("BACKTEST_CACHE_DIR", ".cache/backtest")

# "API가 보유한 최대치까지" 요청 시 무한루프 방지용 안전 상한. cont-yn이 먼저
# 끊기면 이 값에 도달하기 전에 멈춘다.
FULL_HISTORY_MAX_PAGES = 300


class DataLoadError(RuntimeError):
    pass


def _cache_path(key: str, interval: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}_{interval}.csv")


def _is_cache_valid(cached: pd.DataFrame, start: date, end: date) -> bool:
    """캐시가 요청 구간 [start, end]를 커버하는지 확인하는 순수 함수 (단위 테스트 대상)."""
    if cached.empty:
        return False
    return cached.index.min().date() <= start and cached.index.max().date() >= end


def _clean_candles(df: pd.DataFrame) -> pd.DataFrame:
    """결측치·거래정지(거래량 0 이하) 등 성과 지표를 왜곡할 수 있는 구간을 제거.

    Design: docs/02-design/features/strategy-backtesting.design.md §6.1, Plan Risks
    """
    cleaned = df.dropna(subset=["open", "high", "low", "close", "volume"])
    cleaned = cleaned[(cleaned["close"] > 0) & (cleaned["volume"] > 0)]
    return cleaned


def _minute_pages_needed(tic_scope: str, start: date, end: date) -> int:
    """요청 구간을 커버하기 위한 대략적인 페이지 수 추정 (단위 테스트 대상).

    실측 기준 1페이지 ≈ 900행이고, 하루 거래시간(6.5시간)을 tic_scope(분)로 나눈
    봉 수만큼 하루치를 차지한다. 정확한 수치가 아니라 상한 추정치이며, 실제로는
    cont-yn 응답이 끊기면 더 일찍 멈춘다 (KiwoomClient.get_minute_chart_pages).
    """
    try:
        tic_minutes = max(1, int(tic_scope))
    except ValueError:
        tic_minutes = 1
    business_days = max(1, len(pd.bdate_range(start, end)))
    trading_days_per_page = max(1.0, 2.3 * tic_minutes)
    return min(50, int(business_days / trading_days_per_page) + 2)


def _daily_pages_needed(start: date, end: date) -> int:
    """일봉 요청 구간을 커버하기 위한 대략적인 페이지 수 추정 (단위 테스트 대상).

    실측 기준 1페이지 ≈ 600행 ≈ 2.4년(영업일 약 600일).
    """
    business_days = max(1, len(pd.bdate_range(start, end)))
    return min(20, int(business_days / 600) + 2)


def _fetch_pages_with_retry(fetch_pages_fn, entity_label: str, max_retries: int) -> list[dict]:
    """fetch_pages_fn()을 재시도 백오프와 함께 실행해 페이지 리스트를 반환.

    fetch_pages_fn: () -> list[dict] (KiwoomClient의 *_pages 메서드를 이미 바인딩한 콜러블)
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fetch_pages_fn()
        except Exception as exc:
            last_exc = exc
            # 재시도 없이 바로 다시 호출하면 레이트리밋(429)에 또 걸리기 쉬움 (실제로
            # 겪음). 점점 늘어나는 대기시간을 둔다. 마지막 시도 실패 후에는 대기 불필요.
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    raise DataLoadError(f"{entity_label} 조회 실패 ({max_retries}회 재시도): {last_exc}") from last_exc


def _pages_to_dataframe(pages: list[dict], is_minute: bool) -> pd.DataFrame:
    records = []
    for payload in pages:
        records.extend(find_records(payload))

    column_map = MINUTE_COLUMN_MAP if is_minute else DAILY_COLUMN_MAP
    date_format = "%Y%m%d%H%M%S" if is_minute else "%Y%m%d"
    df = to_dataframe(records, column_map, date_format)
    df = df[~df.index.duplicated(keep="first")]
    return _clean_candles(df)


def _resample_minute(df: pd.DataFrame, target_minutes: int) -> pd.DataFrame:
    """1분봉 df를 target_minutes 단위로 재표본화. 거래일 경계를 넘어 합쳐지지
    않도록 날짜별로 나눠서 처리한다 (예: 15:29+다음날 09:00이 한 버킷이 되지 않게)."""
    if df.empty or target_minutes <= 1:
        return df

    parts = []
    for _, day_df in df.groupby(df.index.normalize()):
        resampled = day_df.resample(f"{target_minutes}min", origin=day_df.index[0]).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        )
        parts.append(resampled.dropna(subset=["open"]))
    return pd.concat(parts).sort_index()


def _load_local_series(code: str, interval: str, data_dir: str, subdir: str) -> pd.DataFrame | None:
    """download-universe/update-top35가 저장한 로컬 CSV를 읽는다.

    분봉은 항상 1분봉으로 저장되어 있으므로, interval이 그보다 성긴 분 단위면
    로컬 1분봉을 재표본화해 맞춘다. 로컬 파일이 없으면 None (호출자가 API로 폴백).
    """
    if interval == "day":
        path = os.path.join(data_dir, subdir, "daily", f"{code}.csv")
        if not os.path.exists(path):
            return None
        return pd.read_csv(path, index_col=0, parse_dates=True)

    path = os.path.join(data_dir, subdir, "minute", f"{code}.csv")
    if not os.path.exists(path):
        return None
    try:
        target_minutes = int(interval)
    except ValueError:
        return None

    base = pd.read_csv(path, index_col=0, parse_dates=True)
    return _resample_minute(base, target_minutes)


def load_history(
    client: KiwoomClient,
    stock_code: str,
    start: date,
    end: date,
    interval: str = "day",
    use_cache: bool = True,
    max_retries: int = 3,
    use_local_data: bool = False,
    data_dir: str = "data",
    exchange: str | None = None,
) -> pd.DataFrame:
    """stock_code의 [start, end] 구간 OHLCV를 반환.

    exchange: 분봉 조회(interval이 "day"가 아닐 때)에만 적용 — kiwoom_client.
    get_minute_chart_pages와 같은 의미("1"=KRX, "3"=통합, 미지정 시 필드 자체를 안
    보내 KRX와 사실상 동일하게 동작). 일봉 조회(interval="day")에는 적용되지 않는다.

    interval="day" 또는 분 단위 문자열(예: "15"). 일봉/분봉 모두 1회 호출로는 제한된
    기간만 반환되는 것을 실제 API로 확인해(일봉 ≈ 2.4년/페이지, 분봉 ≈ 12거래일/페이지),
    cont-yn/next-key로 여러 페이지를 이어 받아 병합한다. 그래도 API가 커버하는 과거
    이력에는 한계가 있을 수 있어, 조회 후 [start, end]로 다시 슬라이스한다.

    use_local_data=True면 download-universe/update-top35가 미리 받아둔
    data_dir/stocks/{daily,minute}/{code}.csv를 API보다 먼저 확인한다 — 백테스팅을
    빠르게/오프라인으로 돌리기 위함. 기본값은 False (opt-in) — 이 함수를 쓰는 기존
    호출부와 테스트가 실제 로컬 data/ 폴더의 존재 여부에 영향받지 않도록 보수적으로
    잡음. 로컬 데이터가 없거나 요청 구간을 못 채우면 그대로 API 경로로 폴백한다.
    """
    if use_local_data:
        local = _load_local_series(stock_code, interval, data_dir, "stocks")
        if local is not None and _is_cache_valid(local, start, end):
            return local.loc[str(start):str(end)]

    cache_path = _cache_path(stock_code, interval)

    if use_cache and os.path.exists(cache_path):
        cached = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        if _is_cache_valid(cached, start, end):
            return cached.loc[str(start):str(end)]

    is_minute = interval != "day"
    if is_minute:
        max_pages = _minute_pages_needed(interval, start, end)
        fetch = lambda: client.get_minute_chart_pages(stock_code, tic_scope=interval, max_pages=max_pages, exchange=exchange)
    else:
        max_pages = _daily_pages_needed(start, end)
        fetch = lambda: client.get_daily_chart_pages(stock_code, base_date=end.strftime("%Y%m%d"), max_pages=max_pages)

    pages = _fetch_pages_with_retry(fetch, stock_code, max_retries)
    df = _pages_to_dataframe(pages, is_minute)

    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        df.to_csv(cache_path)

    return df.loc[str(start):str(end)]


def load_full_minute_history(
    client: KiwoomClient,
    stock_code: str,
    tic_scope: str = "1",
    max_pages: int = FULL_HISTORY_MAX_PAGES,
    use_cache: bool = True,
    max_retries: int = 3,
) -> pd.DataFrame:
    """API가 cont-yn으로 제공하는 한 가장 먼 과거까지 분봉을 받는다 (날짜 범위 미지정).

    "얼마나 과거까지 있는지" 자체를 미리 알 수 없어 load_history와 달리 start/end가
    없다. max_pages는 무한루프 방지용 안전장치일 뿐, 실제로는 cont-yn이 끊기는
    시점(API가 더 이상 과거 데이터를 주지 않는 시점)에 먼저 멈춘다.
    """
    cache_path = _cache_path(f"{stock_code}_full", tic_scope)

    if use_cache and os.path.exists(cache_path):
        return pd.read_csv(cache_path, index_col=0, parse_dates=True)

    fetch = lambda: client.get_minute_chart_pages(stock_code, tic_scope=tic_scope, max_pages=max_pages)
    pages = _fetch_pages_with_retry(fetch, stock_code, max_retries)
    df = _pages_to_dataframe(pages, is_minute=True)

    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        df.to_csv(cache_path)

    return df


def load_index_history(
    client: KiwoomClient,
    index_code: str,
    start: date,
    end: date,
    interval: str = "day",
    use_cache: bool = True,
    max_retries: int = 3,
    use_local_data: bool = False,
    data_dir: str = "data",
) -> pd.DataFrame:
    """업종(지수) 일봉/분봉 이력. index_code: "001"=코스피종합, "101"=코스닥종합.

    응답 필드명이 개별 종목과 동일해(dt/open_pric/high_pric/low_pric/cur_prc/trde_qty)
    load_history와 같은 파싱 경로(_pages_to_dataframe)를 재사용한다.

    use_local_data 동작은 load_history와 동일 (기본 False, opt-in).
    """
    if use_local_data:
        local = _load_local_series(index_code, interval, data_dir, "index")
        if local is not None and _is_cache_valid(local, start, end):
            return local.loc[str(start):str(end)]

    cache_key = f"idx_{index_code}"
    cache_path = _cache_path(cache_key, interval)

    if use_cache and os.path.exists(cache_path):
        cached = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        if _is_cache_valid(cached, start, end):
            return cached.loc[str(start):str(end)]

    is_minute = interval != "day"
    if is_minute:
        max_pages = _minute_pages_needed(interval, start, end)
        fetch = lambda: client.get_index_minute_chart_pages(index_code, tic_scope=interval, max_pages=max_pages)
    else:
        max_pages = _daily_pages_needed(start, end)
        fetch = lambda: client.get_index_daily_chart_pages(index_code, base_date=end.strftime("%Y%m%d"), max_pages=max_pages)

    pages = _fetch_pages_with_retry(fetch, cache_key, max_retries)
    df = _pages_to_dataframe(pages, is_minute)

    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        df.to_csv(cache_path)

    return df.loc[str(start):str(end)]


def load_full_index_minute_history(
    client: KiwoomClient,
    index_code: str,
    tic_scope: str = "1",
    max_pages: int = FULL_HISTORY_MAX_PAGES,
    use_cache: bool = True,
    max_retries: int = 3,
) -> pd.DataFrame:
    cache_path = _cache_path(f"idx_{index_code}_full", tic_scope)

    if use_cache and os.path.exists(cache_path):
        return pd.read_csv(cache_path, index_col=0, parse_dates=True)

    fetch = lambda: client.get_index_minute_chart_pages(index_code, tic_scope=tic_scope, max_pages=max_pages)
    pages = _fetch_pages_with_retry(fetch, f"idx_{index_code}", max_retries)
    df = _pages_to_dataframe(pages, is_minute=True)

    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        df.to_csv(cache_path)

    return df
