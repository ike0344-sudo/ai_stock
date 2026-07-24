"""트레이딩 대시보드(dashboard_server.py)가 응답하는지 주기적으로 확인해, 응답이
끊기면(다운/멈춤) 텔레그램으로 알리고 복구되면 다시 알린다.

대시보드 자체와 완전히 분리된 프로세스다 — 대시보드가 죽거나(프로세스 종료) 응답
없이 멈춰도(서버 스레드 교착 등) 이 감시는 영향받지 않고 계속 확인할 수 있다.
확인 대상은 정적 파일을 서빙하는 "/"(index.html) 하나뿐이다 — /api/account-snapshot
등 다른 라우트는 매 사이클 키움 API를 실제로 호출하므로, 단순 생존 확인 목적으로
쓰면 불필요한 API 부하가 된다(정적 라우트는 로컬 파일 읽기뿐이라 그런 부담이 없다).
"""
import time

import requests

from .heartbeat import write_heartbeat
from .notifier import notify_dashboard_down, notify_dashboard_recovered
from .stop_control import clear_stop_flag, is_stop_requested

HEALTH_CHECK_TIMEOUT_SECONDS = 5.0

DEFAULT_STATE_DIR = "state/dashboard_monitor"
DEFAULT_STOP_FLAG_PATH = "state/dashboard_monitor/stop_requested.json"


def check_dashboard_health(url: str) -> tuple[bool, str]:
    """url에 GET 요청 1회. 정상 응답이면 (True, ""), 실패하면 (False, 실패 사유)."""
    try:
        res = requests.get(url, timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        if res.status_code >= 500:
            return False, f"HTTP {res.status_code}"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def run_dashboard_monitor_loop(
    bot_token: str,
    chat_id: str,
    url: str = "http://127.0.0.1:8765/",
    poll_interval_seconds: float = 30.0,
    state_dir: str = DEFAULT_STATE_DIR,
    stop_flag_path: str | None = None,
) -> None:
    """polling으로 대시보드 응답 여부를 확인한다. 매 사이클 알리면 다운된 동안 계속
    스팸이 되므로, 상태가 바뀔 때(정상→다운, 다운→정상)만 알린다 — nasdaq_drop_monitor.py의
    armed/rearm 패턴과 같은 발상."""
    stop_flag_path = stop_flag_path or DEFAULT_STOP_FLAG_PATH
    clear_stop_flag(stop_flag_path)
    write_heartbeat(state_dir)

    healthy = True
    while not is_stop_requested(stop_flag_path):
        # "항상 켜져 있어야 하는" 상시 감시라 사이클 하나에서 예상 못 한 예외가 나도
        # 로그만 남기고 다음 사이클에서 계속한다 — nasdaq_drop_monitor.py와 같은 이유.
        try:
            ok, reason = check_dashboard_health(url)
            if healthy and not ok:
                notify_dashboard_down(reason, bot_token, chat_id)
                healthy = False
            elif not healthy and ok:
                notify_dashboard_recovered(bot_token, chat_id)
                healthy = True
        except Exception as exc:
            print(f"대시보드 감시 사이클 오류(계속 진행): {exc}", flush=True)

        write_heartbeat(state_dir)
        time.sleep(poll_interval_seconds)
