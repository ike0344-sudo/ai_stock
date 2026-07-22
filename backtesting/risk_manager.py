"""동시보유 포지션 한도 + 일일 손실 kill switch — 상태를 파일로 영속화해 프로세스
재시작에도 당일 손실 누계/보유 포지션이 유지되게 한다.

의도적으로 kiwoom_client/notifier를 import하지 않는다 — 주문·알림 성패와 무관하게
리스크 판단 로직만 독립적으로 테스트할 수 있어야 한다 (Design §9.2 의존 규칙).

portfolio_sim.py의 "슬롯 N개, 없으면 스킵" 개념을 백테스트에서 실거래 상태로
그대로 이식했다 — 다만 여기서는 슬롯 크기가 아니라 "슬롯 수(동시보유 종목수)"만
관리하고, 실제 배정 금액(allocated_capital)은 호출자가 정해서 넘긴다.
"""
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class OpenPosition:
    code: str
    entry_time: str
    allocated_capital: float
    entry_price: float
    remaining_fraction: float = 1.0  # 분할매도로 일부만 청산됐을 때 남은 비중
    total_quantity: int = 0  # 최초 매수 주식수 — 분할매도 시 실제 정수 수량 계산용(trading_loop.py)


@dataclass
class RiskState:
    trading_date: str
    realized_pnl_krw: float = 0.0
    open_positions: list = field(default_factory=list)
    kill_switch_active: bool = False


def load_state(path: str) -> RiskState:
    """상태 파일이 없으면 오늘 날짜의 빈 상태로 시작 (최초 실행)."""
    if not os.path.exists(path):
        return RiskState(trading_date=date.today().isoformat())
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    positions = [OpenPosition(**p) for p in raw.get("open_positions", [])]
    return RiskState(
        trading_date=raw["trading_date"],
        realized_pnl_krw=raw.get("realized_pnl_krw", 0.0),
        open_positions=positions,
        kill_switch_active=raw.get("kill_switch_active", False),
    )


def save_state(state: RiskState, path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f, ensure_ascii=False, indent=2)


def roll_to_new_day_if_needed(
    state: RiskState, today: str | None = None, pnl_history_path: str | None = None
) -> RiskState:
    """거래일이 바뀌면 당일 손실 누계와 kill switch를 리셋한다. open_positions는
    보존한다(정상적으로는 데이트레이딩 특성상 당일 마감 전 이미 청산되어 비어있어야
    하지만, 비정상 종료 등으로 남아있을 경우 실제 계좌 상태와 대조하는 건 이 모듈이
    아니라 trading_loop.py의 책임).

    pnl_history_path가 주어지면 리셋 직전에 그날의 최종 realized_pnl_krw를 그 파일에
    적재한다(trading-dashboard Cycle #2, Design §12.3) — 생략 시(기존 호출부와
    하위호환) 이력 적재를 하지 않는다. 적재 실패는 조용히 무시하고 리셋은 그대로
    진행한다(Design §12.7 — 이력 적재 실패가 새 거래일 시작을 막으면 안 됨).
    """
    today = today or date.today().isoformat()
    if state.trading_date == today:
        return state

    if pnl_history_path is not None:
        try:
            _append_pnl_history(pnl_history_path, state.trading_date, state.realized_pnl_krw)
        except OSError:
            pass

    return RiskState(
        trading_date=today,
        realized_pnl_krw=0.0,
        open_positions=state.open_positions,
        kill_switch_active=False,
    )


def _append_pnl_history(path: str, trading_date: str, realized_pnl_krw: float) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": trading_date, "realized_pnl_krw": realized_pnl_krw}, ensure_ascii=False) + "\n")


def can_open_new_position(state: RiskState, max_concurrent: int) -> bool:
    """kill switch가 발동 중이면 무조건 False. 아니면 슬롯 여유가 있을 때만 True.

    주의: 같은 종목에 대한 중복 진입은 별도로 막지 않는다(슬롯 수만 확인) — 이
    전략은 종목당 1포지션을 전제하므로 실제로는 거의 발생하지 않지만, 완전히
    배제되지는 않는 단순화임을 기록해둔다.
    """
    if state.kill_switch_active:
        return False
    return len(state.open_positions) < max_concurrent


def record_position_opened(
    state: RiskState, code: str, entry_time: str, allocated_capital: float, entry_price: float,
    total_quantity: int = 0,
) -> RiskState:
    state.open_positions.append(
        OpenPosition(
            code=code, entry_time=entry_time, allocated_capital=allocated_capital, entry_price=entry_price,
            total_quantity=total_quantity,
        )
    )
    return state


def record_partial_exit(
    state: RiskState, code: str, exit_price: float, sold_fraction: float, max_daily_loss_krw: float
) -> RiskState:
    """포지션의 일부(또는 전부)를 매도했을 때 호출. 전략 1번은 4단계 분할매도라
    한 포지션이 여러 번에 걸쳐 청산될 수 있다 — remaining_fraction이 0이 될 때까지
    슬롯을 계속 점유하고(다른 신규 진입이 그 슬롯을 못 씀), 완전히 청산돼야 슬롯이
    빈다(백테스트의 evaluate_tiered_exit_from_path_with_exit_idx와 동일한 "마지막
    leg에서만 종료" 규칙을 실거래 상태로 이식).
    """
    position = next((p for p in state.open_positions if p.code == code), None)
    if position is None:
        raise ValueError(f"열려있는 포지션이 아닙니다: {code}")

    pnl_pct = (exit_price - position.entry_price) / position.entry_price
    pnl_krw = position.allocated_capital * sold_fraction * pnl_pct
    state.realized_pnl_krw += pnl_krw
    position.remaining_fraction -= sold_fraction

    if position.remaining_fraction <= 1e-9:
        state.open_positions = [p for p in state.open_positions if p.code != code]

    if state.realized_pnl_krw <= -max_daily_loss_krw:
        state.kill_switch_active = True

    return state


def record_position_closed(state: RiskState, code: str, exit_price: float, max_daily_loss_krw: float) -> RiskState:
    """포지션을 한 번에 전량 청산(sold_fraction=1.0)하는 record_partial_exit의 별칭.
    분할매도 없이 단순 손절/전량청산되는 경우에 사용."""
    return record_partial_exit(state, code, exit_price, sold_fraction=1.0, max_daily_loss_krw=max_daily_loss_krw)
