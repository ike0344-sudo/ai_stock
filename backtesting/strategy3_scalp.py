"""전략 3번 — 테스트 모드 신호 포착 전용 규칙. 3분 거래대금 40억원 이상 AND 3분
수익률 1% 이상, 이 두 조건만 확인한다(breakout_reversal.detect_entries 그대로
재사용 — final_strategy.py처럼 ML 게이트/코스피 레짐/일간 등락폭/신고가/무손절이력
등을 더 얹지 않은 최소 버전). 사용자가 "테스트 모드로 조건만 보고 싶다"고 명시적으로
요청해 청산 로직과 주문 실행 자체가 없다 — 조건 충족 시 텔레그램 알림/신호 로그만
남긴다(live_monitor.run_monitor_loop과 같은 관찰전용 계열이지만 그쪽은 ML+레짐 게이트가
있어 이 단순 규칙에는 안 맞아 별도 모듈로 분리).

거래소 기준: 워치리스트 선정(top_by_trading_value)과 3분 거래대금/수익률 계산에 쓰는
분봉(fetch_today_candles, live_monitor.py 재사용) 모두 통합(KRX+NXT) 기준 — 전략1과
동일한 결정이다(전략2만 60이평선 계산에 한해 KRX 단독 기준 유지).
"""
import json
import os
import time
from datetime import datetime, timedelta

import pandas as pd
from kiwoom_client import KiwoomClient

from .breakout_reversal import detect_entries
from .heartbeat import write_heartbeat
from .live_monitor import fetch_today_candles, log_signal
from .notifier import notify_signal_detected
from .orderbook_collector import is_extended_market_open
from .realtime_feed import RealtimeFeed
from .screener import top_by_trading_value
from .stop_control import clear_stop_flag, is_stop_requested

WINDOW_MINUTES = 3
MIN_TRADE_VALUE = 4_000_000_000
MIN_RETURN_PCT = 0.01
STRATEGY_NAME = "strategy_3"  # 이 모듈은 항상 전략3 전용 — 텔레그램 알림 구분용

DEFAULT_SIGNAL_LOG_PATH = "state/strategy_3/signals.jsonl"


def describe_strategy_3() -> dict:
    """대시보드 등 조회용 — strategy_catalog.py에 등록되어 실제 상수값으로 문구를
    만든다(describe_strategy_1/2와 동일 패턴)."""
    return {
        "entry": [
            f"{WINDOW_MINUTES}분 거래대금 {MIN_TRADE_VALUE / 1e8:.0f}억원 이상",
            f"{WINDOW_MINUTES}분 수익률 {MIN_RETURN_PCT:.1%} 이상",
        ],
        "exit": ["청산 로직 없음 — 신호 포착/알림 전용(테스트 모드, 주문 미실행)"],
        "operation": ["ML 진입확률 게이트 없음", "코스피 레짐/일간 등락폭 등 다른 필터 없음"],
        "exchange_basis": [
            "워치리스트 선정(거래대금 상위): 통합(KRX+NXT)",
            f"{WINDOW_MINUTES}분 거래대금/수익률 계산용 분봉: 통합(KRX+NXT)",
        ],
    }


def check_candidate(
    client: KiwoomClient, stock_code: str, feed: RealtimeFeed | None = None, exchange: str = "3"
) -> dict | None:
    """당일 마지막(=지금) 분봉이 막 두 조건(거래대금/수익률)을 동시에 충족했으면
    신호 정보 dict를, 아니면 None을 반환한다.

    exchange 기본값 "3"(통합, KRX+NXT) — 전략1과 동일한 결정(선정 기준과 신호 계산
    기준을 통합으로 통일)을 전략3에도 적용한다."""
    minute_df = fetch_today_candles(client, stock_code, feed=feed, exchange=exchange)
    if minute_df.empty:
        return None
    entries = detect_entries(minute_df, WINDOW_MINUTES, MIN_TRADE_VALUE, MIN_RETURN_PCT)
    if not bool(entries.iloc[-1]):
        return None
    # signal_time은 관례상 롤링 윈도우의 끝(지금) 대신 시작 시각으로 남긴다 — "거래대금/
    # 수익률 조건을 충족시킨 3분 구간이 언제부터인지"가 사용자에게 더 자연스러운 기준
    # (실측: 특정 신호를 두고 "거래대금은 18분에 충족됐는데 왜..."처럼 시작 시각으로
    # 되짚어 확인하는 경우가 있었음 — 끝 시각 라벨과 2분 어긋나 혼선이 있었다).
    window_start = minute_df.index[-1] - timedelta(minutes=WINDOW_MINUTES - 1)
    return {
        "stock_code": stock_code,
        "signal_time": window_start.isoformat(),
        "price": float(minute_df["close"].iloc[-1]),
    }


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Strategy 프로토콜 어댑터 — check_candidate가 내부에서 쓰는 detect_entries를
    그대로 재사용해 signal 컬럼(1/0)으로 매핑만 한다(check_candidate 자체는 실시간
    client 조회가 필요해 df 하나만으로 재현할 수 없음)."""
    entries = detect_entries(df, WINDOW_MINUTES, MIN_TRADE_VALUE, MIN_RETURN_PCT)
    out = df.copy()
    out["signal"] = entries.astype(int)
    return out


generate_signals.name = "strategy_3"
generate_signals.params = {
    "window_minutes": WINDOW_MINUTES,
    "min_trade_value": MIN_TRADE_VALUE,
    "min_return_pct": MIN_RETURN_PCT,
}


def scan_watchlist_once(
    client: KiwoomClient,
    today_top35: set,
    seen_signals: set | None = None,
    feed: RealtimeFeed | None = None,
    exchange: str = "3",
) -> list[dict]:
    """watchlist 전 종목을 1바퀴 확인해 새로 발생한 신호 목록을 반환.

    seen_signals: (stock_code, signal_time) 조합을 기록해 같은 신호를 반복 알림하지
    않게 한다 — 호출자가 세션 내내 같은 set을 넘겨 누적해야 한다(live_monitor.
    scan_watchlist_once와 동일 규칙)."""
    if seen_signals is None:
        seen_signals = set()

    new_signals = []
    for code in today_top35:
        try:
            signal = check_candidate(client, code, feed=feed, exchange=exchange)
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


def _write_scalp_config(output_path: str, top_n: int, poll_interval_seconds: float, is_mock: bool) -> None:
    """대시보드가 GET /api/strategies에서 state_root 밑 서브폴더 존재 여부로 "실행된
    적 있는 전략" 목록을 만든다(dashboard_server.list_strategies) — 이 전략은 신호가
    한 번도 안 뜨면 log_signal이 폴더를 아예 안 만들어서 대시보드에 영영 안 보이는
    문제가 있었다. run-trading의 _write_strategy_config와 같은 이유로, 시작하자마자
    config.json을 써서 신호 발생 여부와 무관하게 즉시 목록에 뜨게 한다."""
    directory = os.path.dirname(output_path) or "."
    os.makedirs(directory, exist_ok=True)
    config = {
        "strategy": "strategy_3",
        "top_n": top_n,
        "interval_seconds": poll_interval_seconds,
        "is_mock": is_mock,
        "mode": "signal_only",
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(os.path.join(directory, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def run_scalp_monitor_loop(
    client: KiwoomClient,
    bot_token: str,
    chat_id: str,
    output_path: str = DEFAULT_SIGNAL_LOG_PATH,
    top_n: int = 35,
    poll_interval_seconds: float = 30.0,
    use_realtime_feed: bool = True,
    stop_flag_path: str | None = None,
) -> None:
    """정규장 동안 오늘의 top-N 종목을 반복 감시해, 신호가 뜨면 텔레그램 알림과
    신호 로그만 남긴다. 주문은 절대 내지 않는다(risk_manager/포지션 상태 자체가
    없음) — run_trading_loop과 달리 이 함수가 이 전략의 유일한 실행 경로다.

    stop_flag_path: 대시보드 "중지" 버튼의 우아한 종료 플래그(stop_control.py) — trading_loop.
    run_trading_loop과 동일한 규칙(미지정 시 output_path와 같은 폴더, 시작 시 자동 clear)."""
    stop_flag_path = stop_flag_path or os.path.join(os.path.dirname(output_path) or ".", "stop_requested.json")
    clear_stop_flag(stop_flag_path)
    write_heartbeat(os.path.dirname(output_path) or ".")  # 백필 완료 전에도 "실행 중"으로 즉시 보이게(trading_loop.py와 동일 이유)
    _write_scalp_config(output_path, top_n, poll_interval_seconds, client.is_mock)
    watchlist_df = top_by_trading_value(client, top_n=top_n)
    today_top35 = set(watchlist_df["stock_code"])
    code_to_name = dict(zip(watchlist_df["stock_code"], watchlist_df["name"]))
    print(
        f"전략3(테스트모드) 감시 시작 — {len(today_top35)}종목, "
        f"{WINDOW_MINUTES}분거래대금≥{MIN_TRADE_VALUE / 1e8:.0f}억원, {WINDOW_MINUTES}분수익률≥{MIN_RETURN_PCT:.1%}. "
        "주문 없음, 포착 시 알림만. 중단하려면 Ctrl+C.",
        flush=True,
    )

    feed = None
    if use_realtime_feed:
        feed = RealtimeFeed(client.appkey, client.secretkey, client.is_mock, sorted(today_top35))
        print(f"실시간 시세 백필 중... ({len(today_top35)}종목, REST 1회씩)", flush=True)
        for code in today_top35:
            try:
                feed.seed_from_dataframe(code, fetch_today_candles(client, code, exchange="3"))
            except Exception as exc:
                print(f"{code}: 백필 실패(실시간 구독 후 자동 회복) - {exc}", flush=True)
        connected = feed.start()
        print(
            "실시간 시세 구독 " + ("성공 — 이후 REST 없이 실시간으로 스캔합니다" if connected else "실패 — REST 폴백으로 동작합니다"),
            flush=True,
        )

    try:
        seen_signals: set = set()
        while is_extended_market_open(datetime.now()) and not is_stop_requested(stop_flag_path):
            # 워치리스트를 매 사이클(poll_interval_seconds, 기본 30초)마다 다시 뽑는다 —
            # 시작 시 한 번만 고정해두면 장중에 새로 거래대금 top_n 안으로 들어온 종목은
            # (예: 삼성E&A가 12시엔 top35 밖이었다가 13시대 랠리로 진입) 재시작 전까지
            # 영영 감시 대상이 아니게 되는 문제가 실측으로 확인됐다. 새로 들어온 종목은
            # 실시간피드 구독 목록엔 없어도 fetch_today_candles가 자동으로 REST 폴백하므로
            # 이 갱신만으로 바로 감시 대상에 들어간다.
            try:
                watchlist_df = top_by_trading_value(client, top_n=top_n)
                today_top35 = set(watchlist_df["stock_code"])
                code_to_name = dict(zip(watchlist_df["stock_code"], watchlist_df["name"]))
            except Exception as exc:
                print(f"워치리스트 갱신 실패(기존 목록 유지) - {exc}", flush=True)

            new_signals = scan_watchlist_once(client, today_top35, seen_signals, feed=feed)
            for signal in new_signals:
                log_signal(signal, output_path)
                code = signal["stock_code"]
                notify_signal_detected(STRATEGY_NAME, code, code_to_name.get(code, ""), signal["price"], None, bot_token, chat_id)
            write_heartbeat(os.path.dirname(output_path) or ".")
            time.sleep(poll_interval_seconds)
    finally:
        if feed is not None:
            feed.stop()
