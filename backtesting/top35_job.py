"""backtest-dashboard의 유일한 쓰기 지점 — top35 갱신을 백그라운드 스레드로 실행하고
진행상황을 스레드 안전하게 노출한다(Design §1.1/§9.1).

기존 backtesting.updater.update_top35()를 그대로 재사용한다(로직 복제 금지, Design
§1.2) — 이 모듈이 새로 하는 일은 "언제 시작할지/중복 실행 방지/진행률 기록"뿐이다.
trading_loop.py/risk_manager.py 등 실주문 로직은 전혀 import하지 않는다 — top35
갱신은 데이터 수집이지 주문이 아니다(Design §9.2).
"""
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

from kiwoom_client import KiwoomClient

from .updater import update_top35

# 장 마감(15:30) 이후라 그날 거래대금 top35 순위가 확정되는 15:40을 기본값으로 삼는다.
DAILY_UPDATE_HOUR = 15
DAILY_UPDATE_MINUTE = 40
SCHEDULER_POLL_SECONDS = 60.0


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
        # reindex: update_top35은 항상 daily_range/minute_range를 채워 반환하지만,
        # 테스트가 monkeypatch로 넘기는 요약 DataFrame엔 없을 수 있어 fill_value로 방어.
        results = summary.reindex(
            columns=["stock_code", "name", "status", "daily_range", "minute_range"], fill_value=""
        ).to_dict("records")
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


_last_auto_success_date: str | None = None  # 스케줄러 전용 스레드 하나만 읽고 쓰므로 잠금 불필요


def _should_run_daily_update(now: datetime, last_success_date: str | None, hour: int, minute: int) -> bool:
    """hour:minute를 지났고 오늘 아직 성공한 적 없으면 True (단위 테스트 대상 순수 함수).

    "실행한 적 있는지"가 아니라 "성공한 적 있는지"를 본다 — 그래야 실패(status="error")한
    날은 오늘 안에서 계속 재시도된다(대시보드의 수동 "top35 업데이트" 버튼을 없앤 대신,
    실패 시 사람이 다시 눌러줄 필요 없이 스케줄러가 스스로 다시 시도해야 한다)."""
    if last_success_date == now.date().isoformat():
        return False
    return (now.hour, now.minute) >= (hour, minute)


def _finished_successfully_today(status: dict, today: str) -> bool:
    """오늘 이미 성공적으로 끝났는지 — status가 "done"이어도 finished_at이 어제
    이전의 낡은 상태일 수 있어(모듈 전역 상태라 재시작 전까지 남아있음) 날짜까지 확인한다."""
    return (
        status["status"] == "done"
        and status["finished_at"] is not None
        and status["finished_at"][:10] == today
    )


def _daily_scheduler_loop(
    appkey: str, secretkey: str, is_mock: bool, data_dir: str, market: str, hour: int, minute: int
) -> None:
    global _last_auto_success_date
    while True:
        try:
            now = datetime.now()
            today = now.date().isoformat()
            status = get_status()
            if _finished_successfully_today(status, today):
                _last_auto_success_date = today
            elif _should_run_daily_update(now, _last_auto_success_date, hour, minute) and status["status"] != "running":
                # 실패(error)했거나 아직 안 돌았으면 시도 — start_job은 이미 running 중이면
                # 스스로 거부하므로 여기서 막지 않아도 안전하지만, 불필요한 스레드 생성을 줄인다.
                start_job(appkey, secretkey, is_mock, data_dir, market)
        except Exception:
            pass  # 상시 스케줄러 — 한 사이클 실패해도 다음 사이클에 계속
        time.sleep(SCHEDULER_POLL_SECONDS)


def start_daily_scheduler(
    appkey: str,
    secretkey: str,
    is_mock: bool,
    data_dir: str = "data",
    market: str = "000",
    hour: int = DAILY_UPDATE_HOUR,
    minute: int = DAILY_UPDATE_MINUTE,
) -> threading.Thread:
    """대시보드 서버가 켜져 있는 동안 매일 hour:minute가 지나면 top35 업데이트를 스스로
    1회 트리거하는 데몬 스레드. 이 PC는 Windows 작업 스케줄러 등록이 UAC로 막혀 있어
    (관리자 토큰 제한), 이미 상시 실행 중인 대시보드 서버 프로세스 안에서 자체
    스케줄링한다 — trading_value_ranking.start_background_poller와 같은 패턴."""
    thread = threading.Thread(
        target=_daily_scheduler_loop, args=(appkey, secretkey, is_mock, data_dir, market, hour, minute), daemon=True
    )
    thread.start()
    return thread
