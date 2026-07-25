"""보유종목 일괄 매도(시장가) — top35_job.py와 동일한 패턴(백그라운드 스레드 + 스레드
세이프 상태 노출)을 따르는, dashboard_server.py의 두 번째 쓰기 트리거.

dashboard_server.py는 원래 read-only 원칙이지만(top35 갱신만 유일한 예외), 사용자가
대시보드에서 명시적으로 누른 "일괄 매도" 버튼에 한해서만 실제 매도 주문을 낸다 —
프론트에서 확인 다이얼로그를 거친 뒤에만 호출되도록 되어 있다(app.js).

trading_loop.py(전략별 실거래 루프)는 여전히 import하지 않는다 — 어느 전략이 관리
중인 포지션인지와 무관하게 계좌 전체를 대상으로 하는 청산이라 특정 전략의
risk_state에 묶을 수 없다(설계상 알려진 위험: 자동매매 루프가 관리 중인 포지션과
이 일괄매도가 서로의 존재를 모르는 채로 동시에 주문을 낼 수 있음, 그대로 남겨둠).
다만 risk_manager.check_order는 각 매도 주문마다 거친다(모니터링 감사 지적사항 —
대시보드가 리스크 심사를 우회하던 문제) — sell 주문은 항상 승인되도록 설계돼 있어
게이트라기보단 "조용한 결정"을 남기지 않기 위한 기록용이다.
"""
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime

from kiwoom_client import KiwoomClient

from .account_status import invalidate_cache
from .risk_manager import OrderRequest, PortfolioState, RiskState, check_order


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
            decision = check_order(
                OrderRequest(code=code, side="sell", quantity=quantity, price=0.0),
                PortfolioState(risk_state=RiskState(trading_date=""), total_capital_krw=0.0),
            )
            print(f"[risk] 매도 심사: {code} x{quantity} - {decision.rule_id}: {decision.reason}", flush=True)
            if not decision.approved:
                results.append({
                    "code": code, "name": name, "quantity": quantity,
                    "status": "error", "message": f"리스크 심사 거부: {decision.reason}",
                })
                continue
            try:
                order = client.place_order(code, "sell", quantity, order_type="3")
                # return_code!=0(주문 거부)도 HTTP 200으로 응답에 실려 오므로, 이 체크
                # 없이는 실제로는 거부된 주문이 "ok"로 기록돼 사용자가 매도된 줄 착각한다.
                if order.get("return_code") == 0:
                    results.append({
                        "code": code, "name": name, "quantity": quantity,
                        "status": "ok", "message": order.get("return_msg", ""),
                    })
                else:
                    results.append({
                        "code": code, "name": name, "quantity": quantity,
                        "status": "error", "message": order.get("return_msg", f"return_code={order.get('return_code')}"),
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
