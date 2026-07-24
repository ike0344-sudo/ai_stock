"""확정된 최종 규칙(final_strategy.py)의 조건 1~6을 실시간으로 감지하고, 조건 7
(ML 확률 게이트)까지 통과한 신호를 로그로 남긴다.

이 모듈은 신호 감지·기록까지만 한다 — 실제 매수 주문은 내지 않는다. 주문 실행은
키움 주문 API 구현과 별도의 리스크 검토(포지션 사이징, 최대손실한도, 킬스위치 등)가
필요한 이후 단계의 작업이라 의도적으로 범위에서 뺐다.
"""
import json
import os
import time
from datetime import date, datetime, timedelta

import pandas as pd

from kiwoom_client import KiwoomClient
from .data_loader import load_history, load_index_history
from .entry_filters import compute_index_regime_by_day
from .final_strategy import (
    KOSPI_INDEX_CODE,
    MIN_TRADE_VALUE,
    N_DAY_HIGH,
    REGIME_MA_PERIOD,
    REGIME_RESAMPLE_MINUTES,
    RECOMMENDED_PROBA_THRESHOLD,
    WINDOW_MINUTES,
    detect_final_entries,
)
from .ml_entry_filter import TrainedEntryFilterModel, extract_entry_features, predict_quality_proba
from .orderbook_collector import is_extended_market_open
from .realtime_feed import RealtimeFeed
from .screener import top_by_trading_value


def fetch_today_candles(
    client: KiwoomClient, stock_code: str, feed: RealtimeFeed | None = None, exchange: str = "1"
) -> pd.DataFrame:
    """당일 1분봉을 조회한다. feed(RealtimeFeed)가 주어지고 이미 데이터가 쌓여 있으면
    REST 호출 없이 그걸 그대로 쓴다 — WebSocket 실시간체결로 조립한 분봉이라 REST보다
    최신이고, 무엇보다 종목당 매번 REST 왕복(키움 rate limit로 1종목≈1.1초)이 사라져
    35종목 스캔이 초 단위로 끝난다(realtime_feed.py 참고). feed가 없거나 아직 그
    종목의 틱을 한 번도 못 받았으면(장 시작 직후, 거래 없는 종목 등) 기존처럼 REST로
    폴백한다 — get_minute_chart(_pages)가 한 번에 최근 ~12거래일을 반환하므로(실측)
    오늘 하루는 페이지네이션 없이 항상 커버된다.

    exchange: 기본값 "1"(KRX) — strategy3_scalp.py가 이 기본값 그대로 쓴다.
    trading_loop.py(전략1)는 "3"(통합)을 명시적으로 넘긴다(전략1은 진입 조건 기준을
    통합으로 바꾸기로 결정)."""
    if feed is not None:
        live_df = feed.get_minute_df(stock_code)
        if not live_df.empty:
            return live_df
    today = date.today()
    return load_history(client, stock_code, today, today, interval="1", use_cache=False, exchange=exchange)


def fetch_today_regime(client: KiwoomClient, data_dir: str = "data") -> bool:
    """코스피 지수 로컬 이력 + 당일 실시간 데이터를 합쳐 오늘의 레짐(15분봉 60이평선
    위/아래)을 판단한다. 60기간 이평선은 여러 거래일에 걸쳐 계산돼야 하므로 로컬
    이력이 필요하고, 로컬 데이터만으로는 당일 봉이 아직 없을 수 있어 실시간 조회로
    보완한다. 장 시작 시 한 번만 계산해 그날 내내 재사용하는 용도(장중 재평가 없음).

    로컬 이력의 마지막 날짜와 오늘 사이에 갭(며칠간 update가 안 돌아 비어있는 거래일)이
    있으면 60기간 이평선이 그 갭을 건너뛰고 훨씬 과거 봉으로 이어붙어 계산돼 레짐
    판정이 왜곡된다(실측: 로컬 이력이 4거래일 밀려 있던 상태에서 하락으로 잘못
    판정 — 갭을 메우니 상승으로 뒤집힘). 그래서 갭이 있으면 그 구간만 추가로
    조회해 로컬 파일에도 병합 저장해 둔다(updater.py의 증분 갱신과 동일한 패턴)."""
    today = date.today()
    local_path = os.path.join(data_dir, "index", "minute", f"{KOSPI_INDEX_CODE}.csv")
    local_df = pd.read_csv(local_path, index_col=0, parse_dates=True) if os.path.exists(local_path) else pd.DataFrame()

    gap_df = pd.DataFrame()
    if not local_df.empty:
        gap_start = local_df.index.max().date() + timedelta(days=1)
        if gap_start < today:
            try:
                gap_df = load_index_history(client, KOSPI_INDEX_CODE, gap_start, today - timedelta(days=1), interval="1", use_cache=False)
            except Exception:
                gap_df = pd.DataFrame()

    try:
        live_df = load_index_history(client, KOSPI_INDEX_CODE, today, today, interval="1", use_cache=False)
    except Exception:
        live_df = pd.DataFrame()

    combined = pd.concat([local_df, gap_df, live_df])
    if combined.empty:
        return False
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()

    if not gap_df.empty:
        merged_local = pd.concat([local_df, gap_df])
        merged_local = merged_local[~merged_local.index.duplicated(keep="last")].sort_index()
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        merged_local.to_csv(local_path)

    regime_by_day = compute_index_regime_by_day(combined, ma_period=REGIME_MA_PERIOD, resample_minutes=REGIME_RESAMPLE_MINUTES)
    return regime_by_day.get(pd.Timestamp(today), False)


def load_recent_daily(stock_code: str, data_dir: str = "data", lookback_days: int = 10) -> pd.DataFrame:
    """day_return/n_day_high 참조용 로컬 일봉 최근분 (update-top35가 갱신해둔 것을 사용)."""
    path = os.path.join(data_dir, "stocks", "daily", f"{stock_code}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, index_col=0, parse_dates=True).tail(lookback_days)


def check_candidate(
    client: KiwoomClient,
    stock_code: str,
    trained: TrainedEntryFilterModel,
    today_top35: set,
    regime_ok: bool,
    data_dir: str = "data",
    proba_threshold: float = RECOMMENDED_PROBA_THRESHOLD,
    feed: RealtimeFeed | None = None,
    exchange: str = "1",
) -> dict | None:
    """1~8번 조건(레짐 포함)을 모두 확인해, 당일 마지막(=지금) 캔들이 막 신호를
    냈으면 신호 정보 dict를, 아니면 None을 반환한다."""
    minute_df = fetch_today_candles(client, stock_code, feed=feed, exchange=exchange)
    if minute_df.empty:
        return None
    daily_df = load_recent_daily(stock_code, data_dir)
    if daily_df.empty:
        return None

    today = pd.Timestamp(date.today())
    entries = detect_final_entries(minute_df, daily_df, stock_code, {today: today_top35}, {today: regime_ok})
    if not bool(entries.iloc[-1]):
        return None

    last_idx = len(minute_df) - 1
    features = extract_entry_features(minute_df, last_idx, WINDOW_MINUTES, MIN_TRADE_VALUE, daily_df, N_DAY_HIGH)
    proba = predict_quality_proba(trained, pd.DataFrame([features])).iloc[0]
    if proba < proba_threshold:
        return None

    return {
        "stock_code": stock_code,
        "signal_time": minute_df.index[-1].isoformat(),
        "price": float(minute_df["close"].iloc[-1]),
        "proba": float(proba),
    }


def scan_watchlist_once(
    client: KiwoomClient,
    trained: TrainedEntryFilterModel,
    today_top35: set,
    regime_ok: bool,
    data_dir: str = "data",
    proba_threshold: float = RECOMMENDED_PROBA_THRESHOLD,
    seen_signals: set | None = None,
    feed: RealtimeFeed | None = None,
    exchange: str = "1",
) -> list[dict]:
    """watchlist 전 종목을 1바퀴 확인해 새로 발생한 신호 목록을 반환.

    seen_signals: (stock_code, signal_time) 조합을 기록해 같은 신호를 반복 알림하지
    않게 한다 — 호출자가 세션 내내 같은 set을 넘겨 누적해야 한다.
    feed가 주어지면 종목별 REST 왕복 없이 실시간체결로 조립된 분봉을 쓴다(35종목
    스캔이 초 단위로 끝남 — fetch_today_candles/realtime_feed.py 참고).
    """
    if seen_signals is None:
        seen_signals = set()

    new_signals = []
    for code in today_top35:
        try:
            signal = check_candidate(
                client, code, trained, today_top35, regime_ok, data_dir, proba_threshold, feed=feed, exchange=exchange
            )
        except Exception as exc:
            print(f"{code}: 확인 중 오류 - {exc}", flush=True)
            continue
        if signal is None:
            continue
        key = (signal["stock_code"], signal["signal_time"])
        if key in seen_signals:
            continue
        seen_signals.add(key)
        new_signals.append(signal)
    return new_signals


def log_signal(signal: dict, output_path: str) -> None:
    print(f"[신호] {signal}", flush=True)
    directory = os.path.dirname(output_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(signal, ensure_ascii=False) + "\n")


def run_monitor_loop(
    client: KiwoomClient,
    trained: TrainedEntryFilterModel,
    output_path: str = "signals.jsonl",
    data_dir: str = "data",
    top_n: int = 35,
    proba_threshold: float = RECOMMENDED_PROBA_THRESHOLD,
    poll_interval_seconds: float = 30.0,
) -> None:
    """정규장 동안 오늘의 top35를 반복 감시하며 신호를 로그로 남긴다. 주문 없음.

    레짐(코스피 지수 60이평선 위/아래)은 장 시작 시 한 번만 계산해 그날 내내 쓴다."""
    watchlist_df = top_by_trading_value(client, top_n=top_n)
    today_top35 = set(watchlist_df["stock_code"])
    regime_ok = fetch_today_regime(client, data_dir)
    print(f"감시 대상 {len(today_top35)}종목 (코스피 레짐={'상승' if regime_ok else '하락'}): {sorted(today_top35)}", flush=True)

    seen_signals: set = set()
    while is_extended_market_open(datetime.now()):
        new_signals = scan_watchlist_once(client, trained, today_top35, regime_ok, data_dir, proba_threshold, seen_signals)
        for signal in new_signals:
            log_signal(signal, output_path)
        time.sleep(poll_interval_seconds)
