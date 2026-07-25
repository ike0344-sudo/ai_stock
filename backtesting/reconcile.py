"""브로커(키움) 실제 보유수량 vs 내부 리스크 상태(risk_manager.RiskState.open_positions)
대사 — execution-agent.md §핵심원칙 3("상태는 브로커가 진실")에 따라 장 시작 전/재접속
후 호출해 phantom position(주문은 거부됐는데 내부엔 체결로 기록된 경우 등)을 잡아낸다.

미체결(ka10075) 대사는 포함하지 않는다 — 이 시스템은 애초에 내부적으로 "미체결" 개념을
추적하지 않고(place_order가 동기 응답만 처리), ka10075 응답 필드명도 실계좌로 확인된 바
없어 잘못된 필드명을 추측해 넣느니 비워두는 게 안전하다(CLAUDE.md 원칙 — 필드명 불확실한
API 응답을 함부로 단정하지 않는다).
"""
from dataclasses import dataclass, field

from kiwoom_client import KiwoomClient

from .risk_manager import RiskState


@dataclass
class ReconcileReport:
    matched: list = field(default_factory=list)  # 코드 리스트 — 내부/브로커 수량 일치
    quantity_mismatches: list = field(default_factory=list)  # [{"code", "internal_qty", "broker_qty"}]
    broker_only: list = field(default_factory=list)  # 브로커엔 있는데 내부 상태엔 없는 종목코드
    internal_only: list = field(default_factory=list)  # 내부 상태엔 있는데 브로커엔 없는 종목코드

    @property
    def is_clean(self) -> bool:
        return not (self.quantity_mismatches or self.broker_only or self.internal_only)


def reconcile(client: KiwoomClient, risk_state: RiskState) -> ReconcileReport:
    """client.get_account_evaluation()으로 받은 실제 보유수량과 risk_state.open_positions를
    종목코드 기준으로 비교한다. 브로커 조회 자체가 실패하면(return_code!=0) 예외를 던진다 —
    이 경우 내부 상태를 그대로 신뢰하는 건 §핵심원칙 3 위반이므로, 호출자가 재시도하거나
    거래를 중단하도록 명확히 알려야 한다."""
    payload = client.get_account_evaluation()
    if payload.get("return_code") != 0:
        raise RuntimeError(payload.get("return_msg", "계좌평가 조회 실패"))

    broker_qty: dict[str, int] = {}
    for row in payload.get("stk_acnt_evlt_prst", []):
        code = row.get("stk_cd", "").removeprefix("A")
        try:
            qty = int(row.get("rmnd_qty", "0"))
        except ValueError:
            qty = 0
        if qty > 0:
            broker_qty[code] = qty

    internal_qty = {p.code: p.total_quantity for p in risk_state.open_positions}

    report = ReconcileReport()
    for code in sorted(set(internal_qty) | set(broker_qty)):
        i_qty, b_qty = internal_qty.get(code), broker_qty.get(code)
        if i_qty is None:
            report.broker_only.append(code)
        elif b_qty is None:
            report.internal_only.append(code)
        elif i_qty != b_qty:
            report.quantity_mismatches.append({"code": code, "internal_qty": i_qty, "broker_qty": b_qty})
        else:
            report.matched.append(code)

    return report
