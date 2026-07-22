"""backtest-dashboard의 유일한 쓰기 지점 — top35 갱신을 백그라운드 스레드로 실행하고
진행상황을 스레드 안전하게 노출한다(Design §1.1/§9.1).

기존 backtesting.updater.update_top35()를 그대로 재사용한다(로직 복제 금지, Design
§1.2) — 이 모듈이 새로 하는 일은 "언제 시작할지/중복 실행 방지/진행률 기록"뿐이다.
trading_loop.py/risk_manager.py 등 실주문 로직은 전혀 import하지 않는다 — top35
갱신은 데이터 수집이지 주문이 아니다(Design §9.2).
"""
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime

from kiwoom_client import KiwoomClient

from .updater import update_top35


@dataclass
class Top35JobState:
    status: str = "idle"  # idle | running | done | error
    processed: int = 0
    total: int = 0
    current_code: str = ""
    success_count: int = 0
    fail_count: int = 0
    error_message: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    results: list = field(default_factory=list)  # [{"stock_code", "name", "status"}, ...] — 완료 후 종목별 결과


_state = Top35JobState()
_lock = threading.Lock()


def get_status() -> dict:
    with _lock:
        return asdict(_state)


def start_job(
    appkey: str,
    secretkey: str,
    is_mock: bool,
    data_dir: str = "data",
    market: str = "000",
) -> bool:
    """이미 실행 중이면 아무 것도 하지 않고 False를 반환한다(중복 트리거 방지,
    Design §6.1 — 키움 API 과다호출을 막는 안전장치이기도 함). 새로 시작했으면 True."""
    global _state
    with _lock:
        if _state.status == "running":
            return False
        _state = Top35JobState(status="running", started_at=datetime.now().isoformat())

    thread = threading.Thread(
        target=_run_job, args=(appkey, secretkey, is_mock, data_dir, market), daemon=True
    )
    thread.start()
    return True


def _on_progress(processed: int, total: int, stock_code: str) -> None:
    with _lock:
        _state.processed = processed
        _state.total = total
        _state.current_code = stock_code


def _run_job(appkey: str, secretkey: str, is_mock: bool, data_dir: str, market: str) -> None:
    try:
        client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
        summary = update_top35(client, data_dir=data_dir, market=market, on_progress=_on_progress)
        success_count = int((summary["status"] == "ok").sum())
        results = summary[["stock_code", "name", "status"]].to_dict("records")
        with _lock:
            _state.status = "done"
            _state.success_count = success_count
            _state.fail_count = len(summary) - success_count
            _state.results = results
            _state.finished_at = datetime.now().isoformat()
    except Exception as exc:
        with _lock:
            _state.status = "error"
            _state.error_message = str(exc)
            _state.finished_at = datetime.now().isoformat()
