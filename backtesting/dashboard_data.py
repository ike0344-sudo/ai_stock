"""trading-dashboard의 파싱 계층 — state/risk_state.json, signals.jsonl을 읽기 전용으로
파싱한다. HTTP를 전혀 모르는 순수 함수만 둬서 dashboard_server.py 없이도 단독 테스트
가능하게 유지한다 (Design §9.2 의존 규칙: 역방향 의존 금지).

trading_loop.py/risk_manager.py를 import하지 않는다 — 실주문 로직과 완전히 분리된
읽기 전용 소비자로 남기 위해서다 (Design §1.2, §2.3).
"""
import json
import os

EMPTY_STATE = {
    "trading_date": None,
    "realized_pnl_krw": 0.0,
    "kill_switch_active": False,
    "open_positions": [],
}


def load_dashboard_state(risk_state_path: str) -> dict:
    """risk_state.json을 읽어 대시보드 응답 형태로 반환한다.

    파일이 없거나(첫 실행 전) trading_loop.py가 쓰는 도중이라 JSON이 깨져 있어도
    예외를 올리지 않고 빈 상태를 반환한다 — 다음 폴링에서 정상 상태로 회복된다
    (Design §6.1).
    """
    if not os.path.exists(risk_state_path):
        return dict(EMPTY_STATE)

    try:
        with open(risk_state_path, encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(EMPTY_STATE)

    return {
        "trading_date": raw.get("trading_date"),
        "realized_pnl_krw": raw.get("realized_pnl_krw", 0.0),
        "kill_switch_active": raw.get("kill_switch_active", False),
        "open_positions": raw.get("open_positions", []),
    }


def _read_jsonl(path: str) -> list[dict]:
    """JSON Lines 파일을 읽어 dict 리스트로 반환. 파일이 없으면 빈 리스트, 손상된
    줄(쓰는 도중 읽힌 부분 줄 등)은 건너뛰고 나머지는 정상 반환한다."""
    if not os.path.exists(path):
        return []

    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_signal_history(signals_path: str, limit: int = 200) -> list[dict]:
    """signals.jsonl(한 줄에 신호 하나)을 읽어 signal_time 내림차순으로 최대 limit개
    반환한다."""
    signals = _read_jsonl(signals_path)
    signals.sort(key=lambda s: s.get("signal_time", ""), reverse=True)
    return signals[:limit]


def load_order_history(orders_path: str, limit: int = 200) -> list[dict]:
    """orders.jsonl(trading_loop.py가 씀, Cycle #2)을 읽어 order_time 내림차순으로
    최대 limit개 반환한다 — load_signal_history와 동일한 패턴(Design §12.4)."""
    orders = _read_jsonl(orders_path)
    orders.sort(key=lambda o: o.get("order_time", ""), reverse=True)
    return orders[:limit]


def load_strategy_config(config_path: str) -> dict:
    """run-trading이 시작 시 기록하는 config.json(전략의 실행 파라미터 스냅샷)을 읽는다.
    파일이 없으면(대시보드만 켜놓고 아직 run-trading을 시작 안 한 경우 등) 빈 dict —
    load_dashboard_state와 동일하게 예외 없이 조용히 빈 상태로 회복된다."""
    if not os.path.exists(config_path):
        return {}

    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def load_pnl_history(pnl_history_path: str) -> list[dict]:
    """pnl_history.jsonl(risk_manager.py가 씀, Cycle #2)을 읽어 날짜 오름차순으로
    반환한다 — 차트가 시간순으로 그려지도록(Design §12.4). 전체 이력이라 limit을
    두지 않는다(일 단위 데이터라 양이 크지 않음)."""
    entries = _read_jsonl(pnl_history_path)
    entries.sort(key=lambda e: e.get("date", ""))
    return entries
