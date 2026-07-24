"""대시보드의 "중지" 버튼이 요청하는 우아한 종료 플래그 — kill_switch_control.py와
같은 패턴(dashboard→루프 방향의 상태 파일 기반 단방향 통신).

kill switch(신규 진입만 막고 프로세스는 계속 돎)와 달리 이건 프로세스 자체를 끝낸다.
강제로 kill하지 않는 이유: 루프는 매 폴링 사이클 시작 시 이 파일을 확인해 요청이
있으면 while 조건에서 자연스럽게 빠져나가므로, finally 블록(RealtimeFeed.stop() 등)과
그 사이클의 state 저장이 항상 정상적으로 끝난다 — Windows에서 외부 프로세스를
Popen.terminate()로 강제 종료하면 Python의 finally가 실행을 보장받지 못한다.

안전 기본값: 파일이 없거나 손상돼 있으면 "요청 없음"(False)으로 취급한다 — 이 파일이
사라졌다고 거래가 멈추면 안 된다(kill_switch_control.py와 동일한 가용성 우선 원칙).
"""
import os

DEFAULT_STOP_FLAG_FILENAME = "stop_requested.json"


def request_stop(path: str) -> None:
    """대시보드가 호출 — 우아한 종료를 요청한다."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{}")


def clear_stop_flag(path: str) -> None:
    """루프가 시작 시 호출 — 이전 실행이 남긴 정지 요청이 새 실행을 즉시 끝내버리지
    않도록 자기 시작 시점에 스스로 지운다."""
    if os.path.exists(path):
        os.remove(path)


def is_stop_requested(path: str) -> bool:
    """매매/감시 루프가 매 사이클 호출 — 파일 존재 여부만 확인(kill_switch_override.json과
    달리 내용은 의미 없음, 존재 자체가 신호)."""
    return os.path.exists(path)
