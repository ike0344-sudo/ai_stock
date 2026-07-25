"""매일 거래대금 top35(순위는 매일 바뀜)를 대상으로 일봉/1분봉을 증분 업데이트.

download-universe(cli.py)가 한 번에 넓은 유니버스를 부트스트랩하는 것과 달리,
이 모듈은 매일 실행되어 "오늘 기준 top35" 종목의 데이터만 최신 상태로 유지한다.
이미 저장된 종목은 마지막 저장 시점 이후분만 추가 조회해 병합하고, 처음 보는
종목(오늘 처음 top35에 진입)은 전체 이력을 새로 받는다.
"""
import os
from datetime import date, timedelta
from typing import Callable

import pandas as pd

from kiwoom_client import KiwoomClient
from .data_loader import _atomic_to_csv, load_full_minute_history, load_history
from .screener import top_by_trading_value


def _load_existing(path: str) -> pd.DataFrame:
    if os.path.exists(path):
        return pd.read_csv(path, index_col=0, parse_dates=True)
    return pd.DataFrame()


def _merge_dedupe_save(existing: pd.DataFrame, fresh: pd.DataFrame, path: str) -> pd.DataFrame:
    """겹치는 시점은 새로 받은(fresh) 값으로 덮어쓴다 (정정된 시세 반영)."""
    merged = pd.concat([existing, fresh]) if not existing.empty else fresh
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    _atomic_to_csv(merged, path)
    return merged


def update_daily(
    client: KiwoomClient,
    stock_code: str,
    path: str,
    years_if_new: float = 5,
    overlap_days: int = 5,
) -> pd.DataFrame:
    """일봉을 증분 업데이트. 신규 종목은 years_if_new년치를 새로 받는다.

    overlap_days: 기존 데이터가 있어도 마지막 저장일 기준 며칠 전부터 다시 조회해
    겹쳐받는다 (정정된 시세나 결측 보정 반영용).
    """
    existing = _load_existing(path)
    if existing.empty:
        start = date.today() - timedelta(days=int(years_if_new * 365.25))
    else:
        start = existing.index.max().date() - timedelta(days=overlap_days)

    fresh = load_history(client, stock_code, start, date.today(), interval="day", use_cache=False)
    return _merge_dedupe_save(existing, fresh, path)


def update_minute(
    client: KiwoomClient,
    stock_code: str,
    path: str,
    tic_scope: str = "1",
    overlap_days: int = 5,
) -> pd.DataFrame:
    """1분봉을 증분 업데이트. 신규 종목은 API가 보유한 전체 이력을 새로 받는다.

    기존 종목은 load_full_minute_history(전체 재조회)가 아니라 최근 overlap_days만
    조회하는 load_history를 사용 — 매일 전체 이력을 다시 받으면 비용이 크다.
    """
    existing = _load_existing(path)
    if existing.empty:
        fresh = load_full_minute_history(client, stock_code, tic_scope=tic_scope, use_cache=False)
    else:
        start = existing.index.max().date() - timedelta(days=overlap_days)
        fresh = load_history(client, stock_code, start, date.today(), interval=tic_scope, use_cache=False)

    return _merge_dedupe_save(existing, fresh, path)


def _date_range_str(df: pd.DataFrame) -> str:
    """대시보드 top35 결과 표의 "실제로 받아온 데이터 범위" 열에 쓰인다 — 빈 데이터는
    빈 문자열(프론트엔드가 "-"로 표시)."""
    if df.empty:
        return ""
    return f"{df.index.min().strftime('%Y-%m-%d')} ~ {df.index.max().strftime('%Y-%m-%d')}"


def update_top35(
    client: KiwoomClient,
    data_dir: str = "data",
    market: str = "000",
    daily_years_if_new: float = 5,
    minute_tic_scope: str = "1",
    overlap_days: int = 5,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> pd.DataFrame:
    """오늘 기준 거래대금 top35를 재산정해 일봉/1분봉을 증분 업데이트.

    on_progress(processed, total, stock_code): 종목 하나(성공/실패 무관) 처리를
    마칠 때마다 호출된다 — backtest-dashboard의 top35_job.py가 진행률을 폴링
    API로 노출하는 데 사용(Design §2.3). 하위호환을 위해 선택적 파라미터로 둠,
    기존 CLI(update-top35)는 넘기지 않아도 그대로 동작.

    반환: stock_code, name, daily_rows, minute_rows, status 컬럼을 가진 요약 DataFrame.
    """
    today_top35 = top_by_trading_value(client, top_n=35, market=market)
    total = len(today_top35)

    daily_dir = os.path.join(data_dir, "stocks", "daily")
    minute_dir = os.path.join(data_dir, "stocks", "minute")
    os.makedirs(daily_dir, exist_ok=True)
    os.makedirs(minute_dir, exist_ok=True)

    rows = []
    for i, (_, row) in enumerate(today_top35.iterrows()):
        stock_code, name = row["stock_code"], row["name"]
        try:
            daily_path = os.path.join(daily_dir, f"{stock_code}.csv")
            daily_df = update_daily(client, stock_code, daily_path, years_if_new=daily_years_if_new, overlap_days=overlap_days)

            minute_path = os.path.join(minute_dir, f"{stock_code}.csv")
            minute_df = update_minute(client, stock_code, minute_path, tic_scope=minute_tic_scope, overlap_days=overlap_days)

            rows.append(
                {
                    "stock_code": stock_code, "name": name,
                    "daily_rows": len(daily_df), "minute_rows": len(minute_df), "status": "ok",
                    "daily_range": _date_range_str(daily_df), "minute_range": _date_range_str(minute_df),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "stock_code": stock_code, "name": name,
                    "daily_rows": None, "minute_rows": None, "status": f"실패: {exc}",
                    "daily_range": "", "minute_range": "",
                }
            )

        if on_progress is not None:
            on_progress(i + 1, total, stock_code)

    return pd.DataFrame(rows)
