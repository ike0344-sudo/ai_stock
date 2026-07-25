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
from datetime import date, datetime

import yaml

DEFAULT_RISK_LIMITS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "risk_limits.yaml")


def load_risk_limits(path: str = DEFAULT_RISK_LIMITS_PATH) -> dict:
    """risk_limits.yaml을 읽는다. 한도 변경은 코드가 아니라 이 파일에서만 한다
    (risk-agent.md §핵심원칙 4) — check_order/get_position_size는 이 함수가 반환한
    값만 참조하고, 전략 모듈(final_strategy.py 등)을 import하지 않는다."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


_LIMITS = load_risk_limits()
# trading_loop.py 등 실거래 코드가 참조하는 상수 — final_strategy.py(전략 모듈) 대신
# 여기서 가져오게 하여 전략과 리스크 모듈의 독립성을 지킨다(감사 지적사항 #2).
STOP_LOSS_PCT = _LIMITS["stop_loss_pct"]
TIERS = tuple(_LIMITS["tiers"])
RECOMMENDED_MAX_CONCURRENT_POSITIONS = _LIMITS["max_concurrent_positions"]


@dataclass
class OpenPosition:
    code: str
    entry_time: str
    allocated_capital: float
    entry_price: float
    remaining_fraction: float = 1.0  # 분할매도로 일부만 청산됐을 때 남은 비중
    total_quantity: int = 0  # 최초 매수 주식수 — 분할매도 시 실제 정수 수량 계산용(trading_loop.py)
    pnl_krw: float = 0.0  # 이 포지션의 누적 실현손익(분할매도 legs 합산) — 연속손절 판정용


@dataclass
class RiskState:
    trading_date: str
    realized_pnl_krw: float = 0.0
    open_positions: list = field(default_factory=list)
    kill_switch_active: bool = False
    consecutive_losses: int = 0
    last_exit: dict = field(default_factory=dict)  # code -> {"time": iso, "was_loss": bool} (재진입 쿨다운용)


@dataclass
class OrderRequest:
    code: str
    side: str  # "buy" | "sell"
    quantity: int
    price: float
    stop: float | None = None  # 손절가 — None이면 check_order가 무조건 거부


@dataclass
class PortfolioState:
    risk_state: RiskState
    total_capital_krw: float


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    rule_id: str
    adjusted_qty: int | None = None


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
        consecutive_losses=raw.get("consecutive_losses", 0),
        last_exit=raw.get("last_exit", {}),
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
        consecutive_losses=0,  # 연속손절 한도는 당일 기준(risk-agent.md §3)
        last_exit={},
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


def record_position_added_to(
    state: RiskState, code: str, additional_capital: float, fill_price: float, additional_quantity: int,
) -> RiskState:
    """이미 열려있는 포지션에 분할매수로 추가 체결됐을 때 호출 — 진입가를 수량가중
    평균으로 갱신하고 배정자금/수량을 누적한다(과대낙폭 3분할매수처럼 한 종목을
    여러 번에 걸쳐 매수하는 전략용).

    record_partial_exit/record_position_closed는 code로 포지션을 하나만 찾아 그
    하나를 청산하는데, 같은 code로 OpenPosition을 여러 개 만들면 청산 시 첫 번째
    것만 청산되고 나머지는 손익 반영 없이 그냥 목록에서 사라진다(제거 조건이
    "코드가 일치하는 전부"라서). 그래서 같은 종목은 항상 이 함수로 기존 포지션
    하나를 갱신해야지, record_position_opened로 새 포지션을 추가로 만들면 안 된다.
    """
    position = next((p for p in state.open_positions if p.code == code), None)
    if position is None:
        raise ValueError(f"열려있는 포지션이 아닙니다: {code}")

    new_quantity = position.total_quantity + additional_quantity
    position.entry_price = (
        (position.entry_price * position.total_quantity) + (fill_price * additional_quantity)
    ) / new_quantity
    position.total_quantity = new_quantity
    position.allocated_capital += additional_capital
    return state


def record_partial_exit(
    state: RiskState, code: str, exit_price: float, sold_fraction: float, max_daily_loss_krw: float,
    exit_time: str | None = None,
) -> RiskState:
    """포지션의 일부(또는 전부)를 매도했을 때 호출. 전략 1번은 4단계 분할매도라
    한 포지션이 여러 번에 걸쳐 청산될 수 있다 — remaining_fraction이 0이 될 때까지
    슬롯을 계속 점유하고(다른 신규 진입이 그 슬롯을 못 씀), 완전히 청산돼야 슬롯이
    빈다(백테스트의 evaluate_tiered_exit_from_path_with_exit_idx와 동일한 "마지막
    leg에서만 종료" 규칙을 실거래 상태로 이식).

    exit_time: 완전청산 시 state.last_exit[code]에 기록되는 시각(재진입 쿨다운
    판정용, check_order 참고) — 미지정 시 현재 시각을 쓴다.
    """
    position = next((p for p in state.open_positions if p.code == code), None)
    if position is None:
        raise ValueError(f"열려있는 포지션이 아닙니다: {code}")

    pnl_pct = (exit_price - position.entry_price) / position.entry_price
    pnl_krw = position.allocated_capital * sold_fraction * pnl_pct
    state.realized_pnl_krw += pnl_krw
    position.remaining_fraction -= sold_fraction
    position.pnl_krw += pnl_krw

    if position.remaining_fraction <= 1e-9:
        state.open_positions = [p for p in state.open_positions if p.code != code]
        was_loss = position.pnl_krw < 0
        state.last_exit[code] = {"time": exit_time or datetime.now().isoformat(), "was_loss": was_loss}
        state.consecutive_losses = state.consecutive_losses + 1 if was_loss else 0

    if state.realized_pnl_krw <= -max_daily_loss_krw:
        state.kill_switch_active = True

    return state


def record_position_closed(
    state: RiskState, code: str, exit_price: float, max_daily_loss_krw: float, exit_time: str | None = None,
) -> RiskState:
    """포지션을 한 번에 전량 청산(sold_fraction=1.0)하는 record_partial_exit의 별칭.
    분할매도 없이 단순 손절/전량청산되는 경우에 사용."""
    return record_partial_exit(
        state, code, exit_price, sold_fraction=1.0, max_daily_loss_krw=max_daily_loss_krw, exit_time=exit_time,
    )


def get_position_size(code: str, entry: float, stop: float, portfolio: PortfolioState, limits: dict | None = None) -> int:
    """손절 거리 기반 포지션 사이징 (리스크 금액 고정 방식, risk-agent.md §1):
    수량 = (계좌 x 트레이드당 리스크%) / (진입가 - 손절가).

    entry == stop(손절거리 0)이면 나눗셈이 불가능하므로 0을 반환한다 — 호출자가
    check_order를 거치므로 정상 흐름에서는 도달하지 않는다.
    """
    limits = limits if limits is not None else _LIMITS
    per_share_risk = abs(entry - stop)
    if per_share_risk == 0:
        return 0
    risk_amount_krw = portfolio.total_capital_krw * limits["risk_pct_per_trade"]
    return max(0, int(risk_amount_krw // per_share_risk))


def check_order(
    order: OrderRequest, portfolio: PortfolioState, limits: dict | None = None, now: str | None = None,
) -> RiskDecision:
    """모든 주문은 이 심사를 통과해야 실행 에이전트로 전달된다(risk-agent.md §핵심원칙
    1) — 전략 코드는 import하지 않고 order/portfolio와 risk_limits.yaml만으로 판단한다.
    승인/거부 어느 쪽이든 reason/rule_id를 채워 조용한 결정이 없게 한다(§핵심원칙 3).

    now: reentry_cooldown_sec 판정 기준 시각(테스트 주입용) — 미지정 시 현재 시각.
    """
    limits = limits if limits is not None else _LIMITS
    risk_state = portfolio.risk_state

    if order.side == "sell":
        return RiskDecision(approved=True, reason="청산 주문은 리스크 심사 대상이 아님", rule_id="sell_always_allowed")

    if order.stop is None:
        return RiskDecision(approved=False, reason="손절가 없는 진입 요청은 거부", rule_id="no_stop_loss")

    if risk_state.kill_switch_active:
        return RiskDecision(approved=False, reason="킬 스위치 발동 중 — 신규 진입 전면 차단", rule_id="kill_switch_active")

    max_consecutive_losses = limits.get("max_consecutive_losses")
    if max_consecutive_losses is not None and risk_state.consecutive_losses >= max_consecutive_losses:
        return RiskDecision(
            approved=False,
            reason=f"연속손절 {risk_state.consecutive_losses}회로 한도 {max_consecutive_losses}회 도달 — 당일 거래 중단",
            rule_id="max_consecutive_losses",
        )

    max_concurrent = limits.get("max_concurrent_positions")
    if max_concurrent is not None and not can_open_new_position(risk_state, max_concurrent):
        return RiskDecision(
            approved=False, reason=f"동시보유 한도 {max_concurrent}종목 초과", rule_id="max_concurrent_positions",
        )

    notional = order.quantity * order.price
    max_order_notional = limits.get("max_order_notional")
    if max_order_notional is not None and notional > max_order_notional:
        return RiskDecision(
            approved=False,
            reason=f"단일주문 금액 {notional:,.0f}원이 한도 {max_order_notional:,.0f}원 초과(팻핑거 방지)",
            rule_id="max_order_notional",
        )

    max_symbol_weight_pct = limits.get("max_symbol_weight_pct")
    if max_symbol_weight_pct is not None:
        existing_capital = sum(p.allocated_capital for p in risk_state.open_positions if p.code == order.code)
        weight = (existing_capital + notional) / portfolio.total_capital_krw
        if weight > max_symbol_weight_pct:
            return RiskDecision(
                approved=False,
                reason=f"{order.code} 비중 {weight:.1%}가 한도 {max_symbol_weight_pct:.1%} 초과",
                rule_id="max_symbol_weight_pct",
            )

    reentry_cooldown_sec = limits.get("reentry_cooldown_sec")
    if reentry_cooldown_sec is not None:
        last = risk_state.last_exit.get(order.code)
        if last is not None and last["was_loss"]:
            now_dt = datetime.fromisoformat(now) if now is not None else datetime.now()
            elapsed = (now_dt - datetime.fromisoformat(last["time"])).total_seconds()
            if elapsed < reentry_cooldown_sec:
                return RiskDecision(
                    approved=False,
                    reason=f"{order.code} 손절 후 재진입 쿨다운 {reentry_cooldown_sec}초 미경과(경과 {elapsed:.0f}초)",
                    rule_id="reentry_cooldown",
                )

    return RiskDecision(approved=True, reason="리스크 심사 통과", rule_id="approved")
