"""호가(ka10004)를 REST로 주기적 폴링해 로컬에 원본 그대로 기록.

호가는 과거 이력을 조회하는 API가 없다 — 조회 시점의 스냅샷만 존재하는 데이터라
지금부터 직접 쌓아야 나중에 백테스트에 쓸 수 있다. WebSocket 실시간 피드 대신 REST
폴링을 쓴 이유: 공식 WebSocket 프로토콜(로그인/PING-PONG/구독 메시지 형식)을 신뢰할
수 있는 소스로 확인하지 못했고, 검토했던 커뮤니티 오픈소스 래퍼도 실제로는 실시간
기능이 구현돼 있지 않아(직접 설치해 소스 확인) 이미 검증된 kiwoom_client.request_tr
패턴을 그대로 재사용하는 쪽을 택했다.

ka10004 응답의 정확한 전체 필드 스키마가 공개돼 있지 않으므로, 파싱을 시도하지 않고
원본 dict를 그대로 JSONL로 저장한다 — 실제 수신 데이터를 보고 나중에 분석/파싱한다.
"""
import json
import os
import time
from datetime import datetime

from kiwoom_client import KiwoomClient

MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE = 9, 0
MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE = 15, 30
EXTENDED_OPEN_HOUR, EXTENDED_OPEN_MINUTE = 8, 0
EXTENDED_CLOSE_HOUR, EXTENDED_CLOSE_MINUTE = 20, 0


def is_market_open(now: datetime) -> bool:
    """평일 09:00~15:30(KST)만 정규장으로 취급 — 공휴일 캘린더는 반영하지 않음."""
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    end = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)
    return start <= now <= end


def is_extended_market_open(now: datetime) -> bool:
    """평일 08:00~20:00(KST) — NXT(넥스트레이드) 장전/장후 시간외까지 포함하는 통합장
    창구. 전략1~4가 정규장 전용 is_market_open 대신 이걸로 운영 시간을 넓혀 통합장에서도
    감시/매매하도록 쓴다. 공휴일 캘린더는 반영하지 않음(is_market_open과 동일)."""
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=EXTENDED_OPEN_HOUR, minute=EXTENDED_OPEN_MINUTE, second=0, microsecond=0)
    end = now.replace(hour=EXTENDED_CLOSE_HOUR, minute=EXTENDED_CLOSE_MINUTE, second=0, microsecond=0)
    return start <= now <= end


def collect_once(client: KiwoomClient, stock_code: str, now: datetime | None = None) -> dict:
    """호가 1회 폴링, 수신시각·종목코드를 붙여 반환. 실패해도 예외를 올리지 않고
    error 필드를 채워 반환 — 폴링 루프가 한 종목 실패로 멈추지 않게 하기 위함."""
    now = now or datetime.now()
    try:
        payload = client.get_stock_quote(stock_code)
        return {"received_at": now.isoformat(), "stock_code": stock_code, **payload}
    except Exception as exc:
        return {"received_at": now.isoformat(), "stock_code": stock_code, "error": str(exc)}


def append_jsonl(record: dict, path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def poll_all_once(
    client: KiwoomClient,
    stock_codes: list[str],
    output_dir: str,
    now: datetime | None = None,
) -> list[dict]:
    """watchlist 전 종목을 1바퀴 폴링해 data/orderbook/{YYYYMMDD}/{code}.jsonl에 append."""
    now = now or datetime.now()
    day_dir = os.path.join(output_dir, now.strftime("%Y%m%d"))
    records = []
    for code in stock_codes:
        record = collect_once(client, code, now)
        append_jsonl(record, os.path.join(day_dir, f"{code}.jsonl"))
        records.append(record)
    return records


def run_collection_loop(
    client: KiwoomClient,
    stock_codes: list[str],
    output_dir: str = "data/orderbook",
    interval_seconds: float = 3.0,
) -> None:
    """정규장 동안 stock_codes를 반복 폴링. 종목수 x 요청간격만큼 한 바퀴가 걸리므로
    interval_seconds는 그 이후의 추가 대기 시간이다 (client._throttle이 요청 간
    최소 간격을 이미 보장).
    """
    while is_market_open(datetime.now()):
        poll_all_once(client, stock_codes, output_dir)
        time.sleep(interval_seconds)
