"""trading-dashboard Cycle #2의 유일한 dashboard→trading_loop 쓰기 통로.

state/kill_switch_override.json 하나만 다루며, 기존 risk_state.json 읽기/쓰기 경로
(risk_manager.load_state/save_state)는 전혀 건드리지 않는다(Design §12.1/§12.2) —
trading_loop.py는 매 사이클 is_kill_switch_requested() 하나만 호출해 이 파일을 확인한다.

안전 기본값: 파일이 없거나 손상돼 있으면 "요청 없음"(False)으로 취급한다 — 이 파일이
사라졌다고 거래가 멈추면 안 된다(가용성 우선, Design §12.7).
"""
import json
import os
from datetime import datetime

DEFAULT_OVERRIDE_PATH = "state/kill_switch_override.json"


def request_kill_switch(override_path: str = DEFAULT_OVERRIDE_PATH) -> None:
    """대시보드가 호출 — 수동 중단을 요청한다."""
    _write(override_path, {"requested": True, "requested_at": datetime.now().isoformat()})


def clear_kill_switch(override_path: str = DEFAULT_OVERRIDE_PATH) -> None:
    """대시보드가 호출 — 수동 중단 요청을 해제(재개)한다."""
    _write(override_path, {"requested": False, "requested_at": None})


def get_override_status(override_path: str = DEFAULT_OVERRIDE_PATH) -> dict:
    """대시보드 조회용. 파일 없음/손상 시 안전 기본값(요청 없음) 반환."""
    if not os.path.exists(override_path):
        return {"requested": False, "requested_at": None}
    try:
        with open(override_path, encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"requested": False, "requested_at": None}
    return {"requested": bool(raw.get("requested", False)), "requested_at": raw.get("requested_at")}


def is_kill_switch_requested(override_path: str = DEFAULT_OVERRIDE_PATH) -> bool:
    """trading_loop.py가 매 사이클 호출 — 실주문 루프가 확인하는 유일한 함수."""
    return get_override_status(override_path)["requested"]


def _write(override_path: str, payload: dict) -> None:
    directory = os.path.dirname(override_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(override_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
