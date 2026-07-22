"""보유종목 일괄 매도(시장가) — top35_job.py와 동일한 패턴(백그라운드 스레드 + 스레드
세이프 상태 노출)을 따르는, dashboard_server.py의 두 번째 쓰기 트리거.

dashboard_server.py는 원래 read-only 원칙이지만(top35 갱신만 유일한 예외), 사용자가
대시보드에서 명시적으로 누른 "일괄 매도" 버튼에 한해서만 실제 매도 주문을 낸다 —
프론트에서 확인 다이얼로그를 거친 뒤에만 호출되도록 되어 있다(app.js).

trading_loop.py/risk_manager.py는 import하지 않는다 — 자동매매 루프가 별도 프로세스로
관리 중인 포지션과 이 일괄매도가 서로의 존재를 모르는 채로 같은 계좌에 동시에 주문을
낼 수 있다는 점은 설계상 알려진 위험으로 남겨둔다(완전히 분리된 프로세스 원칙 유지).
"""
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime

from kiwoom_client import KiwoomClient

from .account_status import invalidate_cache


@dataclass
class SellAllJobState:
    status: str = "idle"  # idle | running | done | error
    results: list = field(default_factory=list)  # [{"code","name","quantity","status","message"}, ...]
    error_message: str = ""
    started_at: str | None = None
    finished_at: str | None = None


_state = SellAllJobState()
_lock = threading.Lock()


def get_status() -> dict:
    with _lock:
        return asdict(_state)


def start_job(appkey: str, secretkey: str, is_mock: bool) -> bool:
    """이미 실행 중이면 아무 것도 하지 않고 False(중복 클릭 방지). 새로 시작했으면 True."""
    global _state
    with _lock:
        if _state.status == "running":
            return False
        _state = SellAllJobState(status="running", started_at=datetime.now().isoformat())

    thread = threading.Thread(target=_run_job, args=(appkey, secretkey, is_mock), daemon=True)
    thread.start()
    return True


def _run_job(appkey: str, secretkey: str, is_mock: bool) -> None:
    try:
        client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
        payload = client.get_account_evaluation()
        if payload.get("return_code") != 0:
            raise RuntimeError(payload.get("return_msg", "계좌평가 조회 실패"))

        results = []
        for row in payload.get("stk_acnt_evlt_prst", []):
            code = row.get("stk_cd", "").removeprefix("A")
            name = row.get("stk_nm", "")
            try:
                quantity = int(row.get("rmnd_qty", "0"))
            except ValueError:
                quantity = 0
            if quantity <= 0:
                continue
            try:
                order = client.place_order(code, "sell", quantity)
                results.append({
                    "code": code, "name": name, "quantity": quantity,
                    "status": "ok", "message": order.get("return_msg", ""),
                })
            except Exception as exc:
                results.append({
                    "code": code, "name": name, "quantity": quantity,
                    "status": "error", "message": str(exc),
                })

        invalidate_cache()  # 매도 체결 반영 — 다음 대시보드 폴링이 낡은 잔고를 안 보여주게
        with _lock:
            _state.status = "done"
            _state.results = results
            _state.finished_at = datetime.now().isoformat()
    except Exception as exc:
        with _lock:
            _state.status = "error"
            _state.error_message = str(exc)
            _state.finished_at = datetime.now().isoformat()
