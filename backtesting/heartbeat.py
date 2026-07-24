"""각 전략 루프(run_trading_loop/run_oversold_trading_loop/run_scalp_monitor_loop)가
폴링 사이클마다 자기 상태 폴더에 남기는 생존 신호.

dashboard_server.py는 trading_loop.py 등을 import하지 않는 완전히 분리된 프로세스라
(Design §1.2) PID로 "지금 이 전략이 살아있는지"를 알 방법이 없다 — 그래서 이 프로젝트가
이미 쓰는 방식(config.json, risk_state.json 같은 상태 파일 기반 통신)을 그대로 따라,
하트비트 파일 하나를 매 사이클 갱신하고 대시보드가 그 나이(age)를 기준 임계값과
비교해 "실행중" 여부를 판단한다."""
import json
import os
import time

HEARTBEAT_FILENAME = "heartbeat.json"


def write_heartbeat(state_dir: str) -> None:
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, HEARTBEAT_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time()}, f)


def read_heartbeat_age_seconds(state_dir: str) -> float | None:
    """마지막 하트비트 이후 경과 시간(초). 파일이 없거나 손상됐으면 None(=알 수 없음
    — 호출부에서 "실행중 아님"으로 취급하면 된다)."""
    path = os.path.join(state_dir, HEARTBEAT_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return time.time() - float(data["updated_at"])
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None
