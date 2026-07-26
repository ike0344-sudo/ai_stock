import json
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backtesting import live_monitor, trading_loop
from backtesting.ml_entry_filter import TrainedEntryFilterModel
from backtesting.risk_manager import RiskDecision, RiskState, can_open_new_position, record_position_opened
from backtesting.trading_loop import (
    ExitTrackingState,
    _log_order,
    _parse_quote_price,
    compute_sell_quantity,
    evaluate_exit,
    process_entries_once,
    process_exits_once,
    run_trading_loop,
)

TIERS = (0.025, 0.04, 0.055, 0.07)
STOP_LOSS = 0.025

# check_candidate 내부가 date.today()로 "오늘"을 계산하므로, 픽스처도 실제 오늘 날짜를
# 써야 top35_ok 등 날짜 매칭이 실제 코드와 어긋나지 않는다 (test_live_monitor.py와 동일 패턴).
TODAY_STR = date.today().isoformat()
PREV_STR = (date.today() - timedelta(days=3)).isoformat()


def _daily(dates: list[str], closes: list[float]) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * len(closes)}, index=index
    )


def _rising_minute(day: str, closes: list[float]) -> pd.DataFrame:
    index = pd.date_range(f"{day} 09:00", periods=len(closes), freq="1min")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [20_000_000] * len(closes)},
        index=index,
    )


class _StubProbaModel:
    def __init__(self, proba: float):
        self._proba = proba

    def predict_proba(self, X):
        return np.array([[1 - self._proba, self._proba]] * len(X))


def _write_daily_csv(tmp_path, code: str, dates: list[str], closes: list[float]) -> str:
    daily_dir = tmp_path / "stocks" / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    _daily(dates, closes).to_csv(daily_dir / f"{code}.csv")
    return str(tmp_path)


@pytest.fixture(autouse=True)
def stub_log_order(monkeypatch):
    """_log_order의 기본 경로(state/orders.jsonl)는 함수 정의 시점에 바인딩돼 있어
    모듈 상수를 패치해도 바뀌지 않는다 — 대신 _log_order 자체를 기본적으로 no-op으로
    바꿔, 이 파일의 기존(Cycle #1) 테스트가 실제 프로젝트 디렉터리에 파일을 만들지
    않게 한다. 로그 기록 자체를 검증하는 테스트는 이 패치를 test 내부에서 다시
    monkeypatch.setattr로 덮어써 원래 동작을 복원한다."""
    monkeypatch.setattr(trading_loop, "_log_order", lambda *a, **k: None)


# ---- _parse_quote_price ----

def test_parse_quote_price_strips_minus_sign_for_declining_stock():
    # 실API: 전일종가 대비 하락이면 "-255000"처럼 마이너스 부호가 붙어 온다.
    assert _parse_quote_price("-255000") == 255000.0


def test_parse_quote_price_strips_plus_sign_for_rising_stock():
    assert _parse_quote_price("+255000") == 255000.0


def test_parse_quote_price_handles_unsigned_value():
    assert _parse_quote_price("255000") == 255000.0


# ---- evaluate_exit ----

def test_evaluate_exit_stop_loss_when_not_armed():
    tracking = ExitTrackingState(tiers_remaining=list(TIERS))

    outcome = evaluate_exit(tracking, net_pct=-0.03, stop_loss_pct=STOP_LOSS, tiers=TIERS)

    assert outcome == ("stop_loss", 1.0)


def test_evaluate_exit_no_trigger_returns_none():
    tracking = ExitTrackingState(tiers_remaining=list(TIERS))

    outcome = evaluate_exit(tracking, net_pct=0.01, stop_loss_pct=STOP_LOSS, tiers=TIERS)

    assert outcome is None


def test_evaluate_exit_first_tier_arms_and_sells_quarter():
    tracking = ExitTrackingState(tiers_remaining=list(TIERS))

    outcome = evaluate_exit(tracking, net_pct=0.03, stop_loss_pct=STOP_LOSS, tiers=TIERS)

    assert outcome == ("take_profit_tier", 0.25)
    assert tracking.armed is True
    assert tracking.tiers_remaining == [0.04, 0.055, 0.07]


def test_evaluate_exit_gap_up_triggers_multiple_tiers_at_once():
    tracking = ExitTrackingState(tiers_remaining=list(TIERS))

    outcome = evaluate_exit(tracking, net_pct=0.08, stop_loss_pct=STOP_LOSS, tiers=TIERS)  # 4단계 전부 넘음

    assert outcome == ("take_profit_tier", 1.0)
    assert tracking.tiers_remaining == []


def test_evaluate_exit_stop_loss_does_not_fire_once_armed():
    tracking = ExitTrackingState(armed=True, tiers_remaining=[0.04, 0.055, 0.07])

    # 무장 후에는 큰 하락도 stop_loss가 아니라 breakeven(0% 이하) 로직만 적용
    outcome = evaluate_exit(tracking, net_pct=-0.03, stop_loss_pct=STOP_LOSS, tiers=TIERS)

    assert outcome == ("breakeven", 0.75)


def test_evaluate_exit_breakeven_only_when_armed_and_at_or_below_zero():
    tracking = ExitTrackingState(armed=False, tiers_remaining=list(TIERS))

    outcome = evaluate_exit(tracking, net_pct=0.0, stop_loss_pct=STOP_LOSS, tiers=TIERS)

    assert outcome is None  # 무장 전이라 손절선(-2.5%)까지는 아무 것도 안 함


def test_evaluate_exit_returns_none_after_fully_sold():
    tracking = ExitTrackingState(armed=True, tiers_remaining=[])  # 4단계 다 발동됨(전량 매도 완료 상태)

    outcome = evaluate_exit(tracking, net_pct=-0.5, stop_loss_pct=STOP_LOSS, tiers=TIERS)

    assert outcome is None  # remaining이 0이라 더 팔 게 없음


# ---- compute_sell_quantity ----

class _Position:
    def __init__(self, total_quantity, remaining_fraction):
        self.total_quantity = total_quantity
        self.remaining_fraction = remaining_fraction


def test_compute_sell_quantity_partial_leg_rounds():
    position = _Position(total_quantity=13, remaining_fraction=1.0)

    qty = compute_sell_quantity(position, sell_fraction=0.25)

    assert qty == round(13 * 0.25)  # 3


def test_compute_sell_quantity_final_leg_sells_exact_remainder_avoiding_rounding_dust():
    # 13주를 25%씩 3번 판 뒤(반올림 누적: 3+3+3=9), 마지막 25%는 남은 4주 전부 팔아야 함
    position = _Position(total_quantity=13, remaining_fraction=0.25)

    qty = compute_sell_quantity(position, sell_fraction=0.25)

    assert qty == 13 - round(13 * 0.75)  # 13 - 10 = 3... already_sold 계산 확인
    already_sold = round(13 * (1.0 - 0.25))
    assert qty == 13 - already_sold


# ---- process_entries_once ----

class _StubOrderClient:
    def __init__(self, raise_on_order=False, reject_order=False):
        self.orders = []
        self.order_kwargs = []
        self.raise_on_order = raise_on_order
        self.reject_order = reject_order

    def place_order(self, stock_code, side, quantity, **kwargs):
        if self.raise_on_order:
            raise RuntimeError("주문 실패")
        self.orders.append({"code": stock_code, "side": side, "quantity": quantity})
        self.order_kwargs.append(kwargs)
        if self.reject_order:
            return {"ord_no": "", "return_code": 20, "return_msg": "주문 거부"}
        return {"ord_no": "1", "return_code": 0}


def test_process_entries_once_places_buy_order_and_updates_risk_state(monkeypatch):
    client = _StubOrderClient()
    monkeypatch.setattr(
        trading_loop, "scan_watchlist_once",
        lambda *a, **k: [{"stock_code": "005930", "signal_time": "t1", "price": 70000, "proba": 0.7}],
    )
    risk_state = RiskState(trading_date="2026-07-20")

    executed = process_entries_once(
        client, trained=None, today_top35={"005930"}, regime_ok=True, risk_state=risk_state,
        exit_tracking={}, data_dir="data", proba_threshold=0.5, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="", chat_id="", seen_signals=set(), total_capital_krw=10_000_000,
    )

    assert len(executed) == 1
    assert client.orders == [{"code": "005930", "side": "buy", "quantity": 28}]  # 2,000,000 // 70000
    assert client.order_kwargs == [{"price": 70000, "order_type": "0"}]  # 지정가(슬리피지 통제)
    assert len(risk_state.open_positions) == 1
    assert risk_state.open_positions[0].total_quantity == 28


def test_process_entries_once_skips_when_no_free_slot(monkeypatch):
    client = _StubOrderClient()
    monkeypatch.setattr(
        trading_loop, "scan_watchlist_once",
        lambda *a, **k: [{"stock_code": "005930", "signal_time": "t1", "price": 70000, "proba": 0.7}],
    )
    risk_state = RiskState(trading_date="2026-07-20")
    for i in range(5):
        record_position_opened(risk_state, f"00000{i}", "t0", 2_000_000, 100.0)

    executed = process_entries_once(
        client, trained=None, today_top35={"005930"}, regime_ok=True, risk_state=risk_state,
        exit_tracking={}, data_dir="data", proba_threshold=0.5, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="", chat_id="", seen_signals=set(), total_capital_krw=10_000_000,
    )

    assert executed == []
    assert client.orders == []


def test_process_entries_once_sends_capture_notification_when_regime_bullish(tmp_path, monkeypatch):
    """scan_watchlist_once를 목으로 대체하지 않고 실제 check_candidate/detect_final_entries
    경로를 그대로 태워, "레짐이 상승으로 바뀌면 포착 알림이 오는지"를 end-to-end로 검증."""
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    monkeypatch.setattr(live_monitor, "load_history", lambda *a, **k: rising)
    data_dir = _write_daily_csv(tmp_path, "000001", [PREV_STR, TODAY_STR], [100, 999])
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.9))
    client = _StubOrderClient()
    detected = []
    monkeypatch.setattr(trading_loop, "notify_signal_detected", lambda *a, **k: detected.append(a))
    risk_state = RiskState(trading_date="2026-07-20")

    executed = process_entries_once(
        client, trained=trained, today_top35={"000001"}, regime_ok=True, risk_state=risk_state,
        exit_tracking={}, data_dir=data_dir, proba_threshold=0.6, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="TOKEN", chat_id="CHAT", seen_signals=set(), total_capital_krw=10_000_000,
    )

    assert len(detected) == 1
    assert detected[0][1] == "000001"
    assert len(executed) == 1  # 레짐 상승 + 조건 충족이면 실제 매수까지 이어짐


def test_process_entries_once_sends_no_capture_notification_when_regime_bearish(tmp_path, monkeypatch):
    """지금 실서비스 상황(코스피 레짐=하락)과 동일한 조건 재현 — 다른 진입조건은 전부
    충족해도 레짐 필터 하나 때문에 포착 알림이 아예 안 오는 게 맞는 동작임을 확인."""
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    monkeypatch.setattr(live_monitor, "load_history", lambda *a, **k: rising)
    data_dir = _write_daily_csv(tmp_path, "000001", [PREV_STR, TODAY_STR], [100, 999])
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.9))
    client = _StubOrderClient()
    detected = []
    monkeypatch.setattr(trading_loop, "notify_signal_detected", lambda *a, **k: detected.append(a))
    risk_state = RiskState(trading_date="2026-07-20")

    executed = process_entries_once(
        client, trained=trained, today_top35={"000001"}, regime_ok=False, risk_state=risk_state,
        exit_tracking={}, data_dir=data_dir, proba_threshold=0.6, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="TOKEN", chat_id="CHAT", seen_signals=set(), total_capital_krw=10_000_000,
    )

    assert detected == []
    assert executed == []


def test_process_entries_once_notifies_signal_detected_even_without_free_slot(monkeypatch):
    client = _StubOrderClient()
    monkeypatch.setattr(
        trading_loop, "scan_watchlist_once",
        lambda *a, **k: [{"stock_code": "005930", "signal_time": "t1", "price": 70000, "proba": 0.7}],
    )
    detected = []
    monkeypatch.setattr(trading_loop, "notify_signal_detected", lambda *a, **k: detected.append(a))
    risk_state = RiskState(trading_date="2026-07-20")
    for i in range(5):
        record_position_opened(risk_state, f"00000{i}", "t0", 2_000_000, 100.0)

    executed = process_entries_once(
        client, trained=None, today_top35={"005930"}, regime_ok=True, risk_state=risk_state,
        exit_tracking={}, data_dir="data", proba_threshold=0.5, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="", chat_id="", seen_signals=set(), total_capital_krw=10_000_000,
    )

    assert executed == []
    assert detected == [("strategy_1", "005930", "", 70000, 0.7, "", "")]


def test_process_entries_once_includes_stock_name_from_code_to_name_in_notification(monkeypatch):
    client = _StubOrderClient()
    monkeypatch.setattr(
        trading_loop, "scan_watchlist_once",
        lambda *a, **k: [{"stock_code": "005930", "signal_time": "t1", "price": 70000, "proba": 0.7}],
    )
    detected = []
    monkeypatch.setattr(trading_loop, "notify_signal_detected", lambda *a, **k: detected.append(a))
    risk_state = RiskState(trading_date="2026-07-20")

    process_entries_once(
        client, trained=None, today_top35={"005930"}, regime_ok=True, risk_state=risk_state,
        exit_tracking={}, data_dir="data", proba_threshold=0.5, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="", chat_id="", seen_signals=set(), total_capital_krw=10_000_000,
        code_to_name={"005930": "삼성전자"},
    )

    assert detected == [("strategy_1", "005930", "삼성전자", 70000, 0.7, "", "")]


def test_process_entries_once_notifies_and_continues_on_order_failure(monkeypatch):
    client = _StubOrderClient(raise_on_order=True)
    monkeypatch.setattr(
        trading_loop, "scan_watchlist_once",
        lambda *a, **k: [{"stock_code": "005930", "signal_time": "t1", "price": 70000, "proba": 0.7}],
    )
    notified = []
    monkeypatch.setattr(trading_loop, "notify_error", lambda *a, **k: notified.append(a))
    risk_state = RiskState(trading_date="2026-07-20")

    executed = process_entries_once(
        client, trained=None, today_top35={"005930"}, regime_ok=True, risk_state=risk_state,
        exit_tracking={}, data_dir="data", proba_threshold=0.5, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="", chat_id="", seen_signals=set(), total_capital_krw=10_000_000,
    )

    assert executed == []
    assert len(notified) == 1
    assert risk_state.open_positions == []


def test_process_entries_once_notifies_and_continues_on_order_rejected(monkeypatch):
    # request_tr()은 HTTP 레벨 오류만 예외로 던지고, 주문 거부는 HTTP 200 +
    # return_code!=0으로 온다 — 이 케이스에서도 예외와 마찬가지로 포지션을 기록하면
    # 안 된다(phantom position).
    client = _StubOrderClient(reject_order=True)
    monkeypatch.setattr(
        trading_loop, "scan_watchlist_once",
        lambda *a, **k: [{"stock_code": "005930", "signal_time": "t1", "price": 70000, "proba": 0.7}],
    )
    notified = []
    monkeypatch.setattr(trading_loop, "notify_error", lambda *a, **k: notified.append(a))
    risk_state = RiskState(trading_date="2026-07-20")

    executed = process_entries_once(
        client, trained=None, today_top35={"005930"}, regime_ok=True, risk_state=risk_state,
        exit_tracking={}, data_dir="data", proba_threshold=0.5, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="", chat_id="", seen_signals=set(), total_capital_krw=10_000_000,
    )

    assert executed == []
    assert len(notified) == 1
    assert risk_state.open_positions == []


def test_process_entries_once_rejects_order_when_risk_check_disapproves(monkeypatch):
    """2026-07-26 risk-agent 감사 지적: 예전엔 can_open_new_position(동시보유 슬롯)만
    확인하고 바로 place_order를 불러, risk_manager.check_order의 나머지 한도(단일주문
    금액/종목당 비중/재진입 쿨다운/연속손절 한도)가 전혀 적용되지 않았다. 이제
    check_order가 거부하면 실제로 주문을 안 내는지 확인한다."""
    client = _StubOrderClient()
    monkeypatch.setattr(
        trading_loop, "scan_watchlist_once",
        lambda *a, **k: [{"stock_code": "005930", "signal_time": "t1", "price": 70000, "proba": 0.7}],
    )
    notified = []
    monkeypatch.setattr(trading_loop, "notify_error", lambda *a, **k: notified.append(a))
    monkeypatch.setattr(
        trading_loop, "check_order",
        lambda order, portfolio: RiskDecision(approved=False, reason="테스트 거부", rule_id="test_rule"),
    )
    risk_state = RiskState(trading_date="2026-07-20")

    executed = process_entries_once(
        client, trained=None, today_top35={"005930"}, regime_ok=True, risk_state=risk_state,
        exit_tracking={}, data_dir="data", proba_threshold=0.5, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="", chat_id="", seen_signals=set(), total_capital_krw=10_000_000,
    )

    assert executed == []
    assert client.orders == []  # place_order 자체가 호출되면 안 됨
    assert len(notified) == 1
    assert risk_state.open_positions == []


def test_process_entries_once_uses_adjusted_qty_from_risk_check(monkeypatch):
    client = _StubOrderClient()
    monkeypatch.setattr(
        trading_loop, "scan_watchlist_once",
        lambda *a, **k: [{"stock_code": "005930", "signal_time": "t1", "price": 70000, "proba": 0.7}],
    )
    monkeypatch.setattr(
        trading_loop, "check_order",
        lambda order, portfolio: RiskDecision(approved=True, reason="조정 승인", rule_id="test_rule", adjusted_qty=5),
    )
    risk_state = RiskState(trading_date="2026-07-20")

    executed = process_entries_once(
        client, trained=None, today_top35={"005930"}, regime_ok=True, risk_state=risk_state,
        exit_tracking={}, data_dir="data", proba_threshold=0.5, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="", chat_id="", seen_signals=set(), total_capital_krw=10_000_000,
    )

    assert len(executed) == 1
    assert client.orders == [{"code": "005930", "side": "buy", "quantity": 5}]
    assert risk_state.open_positions[0].total_quantity == 5


# ---- process_exits_once ----

class _StubQuoteClient:
    def __init__(self, price, raise_on_quote=False, raise_on_order=False, reject_order=False):
        self.price = price
        self.orders = []
        self.order_kwargs = []
        self.raise_on_quote = raise_on_quote
        self.raise_on_order = raise_on_order
        self.reject_order = reject_order

    def get_stock_quote(self, stock_code):
        if self.raise_on_quote:
            raise RuntimeError("조회 실패")
        # 실제 ka10004 응답처럼 부호를 붙여서 반환 — abs() 처리(부호 제거) 로직 검증용.
        return {"buy_fpr_bid": f"-{self.price}"}

    def place_order(self, stock_code, side, quantity, **kwargs):
        if self.raise_on_order:
            raise RuntimeError("주문 실패")
        self.orders.append({"code": stock_code, "side": side, "quantity": quantity})
        self.order_kwargs.append(kwargs)
        if self.reject_order:
            return {"ord_no": "", "return_code": 20, "return_msg": "주문 거부"}
        return {"ord_no": "1", "return_code": 0}


def test_process_exits_once_sells_all_on_stop_loss(monkeypatch):
    client = _StubQuoteClient(price=97.5)  # entry=100 -> net_pct 약 -3.6%(수수료 포함) -> 손절선 이하
    risk_state = RiskState(trading_date="2026-07-20")
    record_position_opened(risk_state, "005930", "t1", 2_000_000, 100.0, total_quantity=20)

    executed = process_exits_once(client, risk_state, exit_tracking={}, max_daily_loss_krw=1_000_000, bot_token="", chat_id="")

    assert len(executed) == 1
    assert executed[0]["reason"] == "stop_loss"
    assert client.orders == [{"code": "005930", "side": "sell", "quantity": 20}]
    assert client.order_kwargs == [{"price": 97.5, "order_type": "3"}]  # 시장가(체결확인 인프라 없어 되돌림)
    assert risk_state.open_positions == []  # 전량 청산 -> 슬롯 해제


def test_process_exits_once_partial_sell_keeps_slot_occupied(monkeypatch):
    client = _StubQuoteClient(price=103.5)  # entry=100 -> +3.5%대, 1단계(2.5%) 발동
    risk_state = RiskState(trading_date="2026-07-20")
    record_position_opened(risk_state, "005930", "t1", 2_000_000, 100.0, total_quantity=20)

    executed = process_exits_once(client, risk_state, exit_tracking={}, max_daily_loss_krw=1_000_000, bot_token="", chat_id="")

    assert len(executed) == 1
    assert executed[0]["reason"] == "take_profit_tier"
    assert client.orders[0]["quantity"] == 5  # 20주의 25%
    assert len(risk_state.open_positions) == 1  # 슬롯 계속 점유
    assert risk_state.open_positions[0].remaining_fraction == pytest.approx(0.75)


def test_process_exits_once_no_action_when_no_condition_met():
    client = _StubQuoteClient(price=100.5)  # entry=100 -> 거의 변화 없음
    risk_state = RiskState(trading_date="2026-07-20")
    record_position_opened(risk_state, "005930", "t1", 2_000_000, 100.0, total_quantity=20)

    executed = process_exits_once(client, risk_state, exit_tracking={}, max_daily_loss_krw=1_000_000, bot_token="", chat_id="")

    assert executed == []
    assert client.orders == []
    assert len(risk_state.open_positions) == 1


def test_process_exits_once_notifies_and_skips_on_quote_failure(monkeypatch):
    client = _StubQuoteClient(price=0, raise_on_quote=True)
    notified = []
    monkeypatch.setattr(trading_loop, "notify_error", lambda *a, **k: notified.append(a))
    risk_state = RiskState(trading_date="2026-07-20")
    record_position_opened(risk_state, "005930", "t1", 2_000_000, 100.0, total_quantity=20)

    executed = process_exits_once(client, risk_state, exit_tracking={}, max_daily_loss_krw=1_000_000, bot_token="", chat_id="")

    assert executed == []
    assert len(notified) == 1
    assert len(risk_state.open_positions) == 1  # 상태 변화 없음


def test_process_exits_once_notifies_and_skips_on_order_rejected(monkeypatch):
    client = _StubQuoteClient(price=97.5, reject_order=True)  # 손절 조건 충족 -> 매도 시도하지만 거부됨
    notified = []
    monkeypatch.setattr(trading_loop, "notify_error", lambda *a, **k: notified.append(a))
    risk_state = RiskState(trading_date="2026-07-20")
    record_position_opened(risk_state, "005930", "t1", 2_000_000, 100.0, total_quantity=20)

    executed = process_exits_once(client, risk_state, exit_tracking={}, max_daily_loss_krw=1_000_000, bot_token="", chat_id="")

    assert executed == []
    assert len(notified) == 1
    assert len(risk_state.open_positions) == 1  # 거부된 주문은 청산 처리되면 안 됨


def test_process_exits_once_notifies_kill_switch_when_triggered(monkeypatch):
    client = _StubQuoteClient(price=90.0)  # entry=100 -> -10%, 큰 손절
    notified_kill = []
    monkeypatch.setattr(trading_loop, "notify_kill_switch", lambda *a, **k: notified_kill.append(a))
    risk_state = RiskState(trading_date="2026-07-20")
    record_position_opened(risk_state, "005930", "t1", 2_000_000, 100.0, total_quantity=20)

    process_exits_once(client, risk_state, exit_tracking={}, max_daily_loss_krw=100_000, bot_token="", chat_id="")

    assert risk_state.kill_switch_active is True
    assert len(notified_kill) == 1


# ---- run_trading_loop (thin wrapper) ----

def test_run_trading_loop_polls_until_market_closes_and_saves_state(monkeypatch, tmp_path):
    import pandas as pd

    watchlist = pd.DataFrame([{"stock_code": "005930", "name": "A"}])
    monkeypatch.setattr(trading_loop, "top_by_trading_value", lambda client, top_n: watchlist)
    monkeypatch.setattr(trading_loop, "fetch_today_regime", lambda client, data_dir: True)
    open_flags = iter([True, True, False])
    monkeypatch.setattr(trading_loop, "is_extended_market_open", lambda now: next(open_flags))
    monkeypatch.setattr(trading_loop.time, "sleep", lambda s: None)

    exit_calls, entry_calls = [], []
    monkeypatch.setattr(trading_loop, "process_exits_once", lambda *a, **k: exit_calls.append(1) or [])
    monkeypatch.setattr(trading_loop, "process_entries_once", lambda *a, **k: entry_calls.append(1) or [])

    state_path = str(tmp_path / "risk_state.json")
    run_trading_loop(
        object(), trained=None, bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0, use_realtime_feed=False,
    )

    assert len(exit_calls) == 2
    assert len(entry_calls) == 2
    assert __import__("os").path.exists(state_path)


def test_run_trading_loop_refreshes_watchlist_each_cycle_and_picks_up_new_entrant(monkeypatch, tmp_path):
    # strategy3_scalp에서 실측된 것과 같은 문제(장중 새로 top_n 진입한 종목이 재시작
    # 전까진 영영 감시 대상이 아니었던 것) — 전략1도 같은 구조라 동일하게 겪는다.
    import pandas as pd

    watchlists = iter([
        pd.DataFrame([{"stock_code": "005930", "name": "A"}]),  # 시작 시 최초 조회
        pd.DataFrame([{"stock_code": "005930", "name": "A"}]),  # 1사이클 갱신: 신규종목 아직 없음
        pd.DataFrame([{"stock_code": "005930", "name": "A"}, {"stock_code": "000660", "name": "B"}]),  # 2사이클 갱신: 신규종목 진입
    ])
    monkeypatch.setattr(trading_loop, "top_by_trading_value", lambda client, top_n: next(watchlists))
    monkeypatch.setattr(trading_loop, "fetch_today_regime", lambda client, data_dir: True)
    open_flags = iter([True, True, False])
    monkeypatch.setattr(trading_loop, "is_extended_market_open", lambda now: next(open_flags))
    monkeypatch.setattr(trading_loop.time, "sleep", lambda s: None)
    monkeypatch.setattr(trading_loop, "process_exits_once", lambda *a, **k: [])

    seen_watchlists = []
    monkeypatch.setattr(
        trading_loop, "process_entries_once",
        lambda client, trained, today_top35, *a, **k: seen_watchlists.append(set(today_top35)) or [],
    )

    state_path = str(tmp_path / "risk_state.json")
    run_trading_loop(
        object(), trained=None, bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0, use_realtime_feed=False,
    )

    assert seen_watchlists == [{"005930"}, {"005930", "000660"}]


def test_run_trading_loop_keeps_previous_watchlist_when_refresh_fails(monkeypatch, tmp_path):
    import pandas as pd

    calls_state = {"n": 0}

    def fake_fetch(client, top_n):
        calls_state["n"] += 1
        if calls_state["n"] == 1:
            return pd.DataFrame([{"stock_code": "005930", "name": "A"}])
        raise RuntimeError("일시적 API 오류")

    monkeypatch.setattr(trading_loop, "top_by_trading_value", fake_fetch)
    monkeypatch.setattr(trading_loop, "fetch_today_regime", lambda client, data_dir: True)
    open_flags = iter([True, True, False])
    monkeypatch.setattr(trading_loop, "is_extended_market_open", lambda now: next(open_flags))
    monkeypatch.setattr(trading_loop.time, "sleep", lambda s: None)
    monkeypatch.setattr(trading_loop, "process_exits_once", lambda *a, **k: [])

    seen_watchlists = []
    monkeypatch.setattr(
        trading_loop, "process_entries_once",
        lambda client, trained, today_top35, *a, **k: seen_watchlists.append(set(today_top35)) or [],
    )

    state_path = str(tmp_path / "risk_state.json")
    run_trading_loop(
        object(), trained=None, bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0, use_realtime_feed=False,
    )

    assert seen_watchlists == [{"005930"}, {"005930"}]  # 갱신 실패 시 기존 목록 유지


def test_run_trading_loop_writes_heartbeat_before_backfill_completes(monkeypatch, tmp_path):
    """35종목 백필(최대 40초 가까이)이 끝나기 전에도 대시보드가 "실행 중"으로 볼 수
    있어야 한다 — 그렇지 않으면 그 사이 오래된 하트비트가 만료돼 "중지됨"으로 잘못
    보이는 틈에 대시보드 "시작" 버튼이 똑같은 전략을 중복 실행시킬 수 있다(실측 사고)."""
    import pandas as pd

    from backtesting.heartbeat import read_heartbeat_age_seconds

    watchlist = pd.DataFrame([{"stock_code": "005930", "name": "A"}])
    monkeypatch.setattr(trading_loop, "top_by_trading_value", lambda client, top_n: watchlist)
    monkeypatch.setattr(trading_loop, "fetch_today_regime", lambda client, data_dir: True)
    monkeypatch.setattr(trading_loop, "is_extended_market_open", lambda now: False)  # 루프 진입 전 확인이 목적, 사이클은 0번이어도 됨

    state_path = str(tmp_path / "risk_state.json")
    run_trading_loop(
        object(), trained=None, bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0, use_realtime_feed=False,
    )

    age = read_heartbeat_age_seconds(str(tmp_path))
    assert age is not None and age < 5


def test_run_trading_loop_stops_when_stop_flag_requested_mid_run(monkeypatch, tmp_path):
    import pandas as pd

    from backtesting.stop_control import request_stop

    watchlist = pd.DataFrame([{"stock_code": "005930", "name": "A"}])
    monkeypatch.setattr(trading_loop, "top_by_trading_value", lambda client, top_n: watchlist)
    monkeypatch.setattr(trading_loop, "fetch_today_regime", lambda client, data_dir: True)
    monkeypatch.setattr(trading_loop, "is_extended_market_open", lambda now: True)  # 장은 계속 열려 있다고 가정
    monkeypatch.setattr(trading_loop.time, "sleep", lambda s: None)
    monkeypatch.setattr(trading_loop, "process_exits_once", lambda *a, **k: [])

    state_path = str(tmp_path / "risk_state.json")
    stop_flag_path = str(tmp_path / "stop_requested.json")
    entry_calls = []

    def fake_process_entries_once(*a, **k):
        entry_calls.append(1)
        if len(entry_calls) == 2:
            request_stop(stop_flag_path)  # 두 번째 사이클 도중 대시보드에서 중지 요청이 온 상황 재현
        return []

    monkeypatch.setattr(trading_loop, "process_entries_once", fake_process_entries_once)

    run_trading_loop(
        object(), trained=None, bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0, use_realtime_feed=False,
        stop_flag_path=stop_flag_path,
    )

    assert len(entry_calls) == 2  # 세 번째 사이클로 안 넘어가고 그 자리에서 멈춤 (market_open은 계속 True인데도)


def test_run_trading_loop_clears_stale_stop_flag_from_previous_run_at_startup(monkeypatch, tmp_path):
    import pandas as pd

    from backtesting.stop_control import request_stop

    watchlist = pd.DataFrame([{"stock_code": "005930", "name": "A"}])
    monkeypatch.setattr(trading_loop, "top_by_trading_value", lambda client, top_n: watchlist)
    monkeypatch.setattr(trading_loop, "fetch_today_regime", lambda client, data_dir: True)
    open_flags = iter([True, False])
    monkeypatch.setattr(trading_loop, "is_extended_market_open", lambda now: next(open_flags))
    monkeypatch.setattr(trading_loop.time, "sleep", lambda s: None)
    monkeypatch.setattr(trading_loop, "process_exits_once", lambda *a, **k: [])
    entry_calls = []
    monkeypatch.setattr(trading_loop, "process_entries_once", lambda *a, **k: entry_calls.append(1) or [])

    state_path = str(tmp_path / "risk_state.json")
    stop_flag_path = str(tmp_path / "stop_requested.json")
    request_stop(stop_flag_path)  # 이전 실행이 남긴 정지 요청 시뮬레이션

    run_trading_loop(
        object(), trained=None, bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0, use_realtime_feed=False,
        stop_flag_path=stop_flag_path,
    )

    assert len(entry_calls) == 1  # 과거 정지 요청 때문에 즉시 끝나지 않고 정상적으로 한 사이클 돎


# ---- _log_order ----

def test_log_order_writes_json_line(tmp_path):
    path = str(tmp_path / "orders.jsonl")

    _log_order(path, "buy", "005930", 28, 70000.0, "entry")

    lines = (tmp_path / "orders.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["side"] == "buy"
    assert entry["code"] == "005930"
    assert entry["quantity"] == 28
    assert entry["price"] == 70000.0
    assert entry["reason"] == "entry"
    assert "order_time" in entry


def test_log_order_appends_multiple_lines(tmp_path):
    path = str(tmp_path / "orders.jsonl")

    _log_order(path, "buy", "005930", 28, 70000.0, "entry")
    _log_order(path, "sell", "005930", 7, 71750.0, "take_profit_tier")

    lines = (tmp_path / "orders.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


def test_log_order_silently_ignores_write_failure(monkeypatch, tmp_path):
    """Design §12.7 — 로그 기록 실패가 주문 처리 흐름을 막으면 안 됨."""
    def raise_oserror(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", raise_oserror)

    _log_order(str(tmp_path / "orders.jsonl"), "buy", "005930", 28, 70000.0, "entry")  # 예외 없이 통과해야 함


# ---- process_entries_once / process_exits_once order logging integration ----

def test_process_entries_once_logs_order_on_successful_buy(monkeypatch, tmp_path):
    client = _StubOrderClient()
    monkeypatch.setattr(
        trading_loop, "scan_watchlist_once",
        lambda *a, **k: [{"stock_code": "005930", "signal_time": "t1", "price": 70000, "proba": 0.7}],
    )
    logged = []
    monkeypatch.setattr(trading_loop, "_log_order", lambda *a: logged.append(a))
    risk_state = RiskState(trading_date="2026-07-20")

    process_entries_once(
        client, trained=None, today_top35={"005930"}, regime_ok=True, risk_state=risk_state,
        exit_tracking={}, data_dir="data", proba_threshold=0.5, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="", chat_id="", seen_signals=set(), total_capital_krw=10_000_000,
        order_log_path=str(tmp_path / "orders.jsonl"),
    )

    assert len(logged) == 1
    path_arg, side, code, quantity, price, reason = logged[0]
    assert side == "buy" and code == "005930" and reason == "entry"


def test_process_entries_once_does_not_log_when_order_fails(monkeypatch, tmp_path):
    client = _StubOrderClient(raise_on_order=True)
    monkeypatch.setattr(
        trading_loop, "scan_watchlist_once",
        lambda *a, **k: [{"stock_code": "005930", "signal_time": "t1", "price": 70000, "proba": 0.7}],
    )
    monkeypatch.setattr(trading_loop, "notify_error", lambda *a, **k: None)
    logged = []
    monkeypatch.setattr(trading_loop, "_log_order", lambda *a: logged.append(a))
    risk_state = RiskState(trading_date="2026-07-20")

    process_entries_once(
        client, trained=None, today_top35={"005930"}, regime_ok=True, risk_state=risk_state,
        exit_tracking={}, data_dir="data", proba_threshold=0.5, max_concurrent_positions=5,
        position_capital_krw=2_000_000, bot_token="", chat_id="", seen_signals=set(), total_capital_krw=10_000_000,
        order_log_path=str(tmp_path / "orders.jsonl"),
    )

    assert logged == []


def test_process_exits_once_logs_order_on_successful_sell(monkeypatch, tmp_path):
    client = _StubQuoteClient(price=103.5)  # entry=100 -> +3.5%대, 1단계(2.5%) 발동
    logged = []
    monkeypatch.setattr(trading_loop, "_log_order", lambda *a: logged.append(a))
    risk_state = RiskState(trading_date="2026-07-20")
    record_position_opened(risk_state, "005930", "t1", 2_000_000, 100.0, total_quantity=20)

    process_exits_once(
        client, risk_state, exit_tracking={}, max_daily_loss_krw=1_000_000, bot_token="", chat_id="",
        order_log_path=str(tmp_path / "orders.jsonl"),
    )

    assert len(logged) == 1
    path_arg, side, code, quantity, price, reason = logged[0]
    assert side == "sell" and code == "005930" and reason == "take_profit_tier"


# ---- run_trading_loop kill switch override integration ----

def test_run_trading_loop_activates_kill_switch_when_override_requested(monkeypatch, tmp_path):
    import pandas as pd

    watchlist = pd.DataFrame([{"stock_code": "005930", "name": "A"}])
    monkeypatch.setattr(trading_loop, "top_by_trading_value", lambda client, top_n: watchlist)
    monkeypatch.setattr(trading_loop, "fetch_today_regime", lambda client, data_dir: True)
    open_flags = iter([True, False])
    monkeypatch.setattr(trading_loop, "is_extended_market_open", lambda now: next(open_flags))
    monkeypatch.setattr(trading_loop.time, "sleep", lambda s: None)
    monkeypatch.setattr(trading_loop, "process_exits_once", lambda *a, **k: [])
    entry_calls = []
    monkeypatch.setattr(trading_loop, "process_entries_once", lambda *a, **k: entry_calls.append(1) or [])
    monkeypatch.setattr(trading_loop, "is_kill_switch_requested", lambda path: True)  # 수동 중단 요청된 상태로 모킹

    state_path = str(tmp_path / "risk_state.json")
    run_trading_loop(
        object(), trained=None, bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0,
        kill_switch_override_path=str(tmp_path / "kill_switch_override.json"), use_realtime_feed=False,
    )

    assert entry_calls == []  # kill switch가 켜져 있으니 진입 처리는 스킵됨

    with open(state_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["kill_switch_active"] is True


def test_run_trading_loop_does_not_activate_kill_switch_when_not_requested(monkeypatch, tmp_path):
    import pandas as pd

    watchlist = pd.DataFrame([{"stock_code": "005930", "name": "A"}])
    monkeypatch.setattr(trading_loop, "top_by_trading_value", lambda client, top_n: watchlist)
    monkeypatch.setattr(trading_loop, "fetch_today_regime", lambda client, data_dir: True)
    open_flags = iter([True, False])
    monkeypatch.setattr(trading_loop, "is_extended_market_open", lambda now: next(open_flags))
    monkeypatch.setattr(trading_loop.time, "sleep", lambda s: None)
    monkeypatch.setattr(trading_loop, "process_exits_once", lambda *a, **k: [])
    entry_calls = []
    monkeypatch.setattr(trading_loop, "process_entries_once", lambda *a, **k: entry_calls.append(1) or [])
    monkeypatch.setattr(trading_loop, "is_kill_switch_requested", lambda path: False)

    state_path = str(tmp_path / "risk_state.json")
    run_trading_loop(
        object(), trained=None, bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0,
        kill_switch_override_path=str(tmp_path / "kill_switch_override.json"), use_realtime_feed=False,
    )

    assert len(entry_calls) == 1
    with open(state_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["kill_switch_active"] is False


def test_run_trading_loop_appends_pnl_history_on_day_rollover(monkeypatch, tmp_path):
    import pandas as pd

    watchlist = pd.DataFrame([{"stock_code": "005930", "name": "A"}])
    monkeypatch.setattr(trading_loop, "top_by_trading_value", lambda client, top_n: watchlist)
    monkeypatch.setattr(trading_loop, "fetch_today_regime", lambda client, data_dir: True)
    open_flags = iter([False])  # 루프 진입 즉시 종료 -> 초기 load 시점의 롤오버만 확인
    monkeypatch.setattr(trading_loop, "is_extended_market_open", lambda now: next(open_flags))
    monkeypatch.setattr(trading_loop, "is_kill_switch_requested", lambda path: False)

    state_path = str(tmp_path / "risk_state.json")
    pnl_history_path = str(tmp_path / "pnl_history.jsonl")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"trading_date": "2026-07-19", "realized_pnl_krw": 12345.0, "open_positions": [], "kill_switch_active": False}, f)

    run_trading_loop(
        object(), trained=None, bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, pnl_history_path=pnl_history_path,
        kill_switch_override_path=str(tmp_path / "kill_switch_override.json"), use_realtime_feed=False,
    )

    with open(pnl_history_path, encoding="utf-8") as f:
        entry = json.loads(f.readline())
    assert entry["realized_pnl_krw"] == 12345.0


# ---- run_trading_loop: use_realtime_feed=True (default) ----

class _FakeRealtimeFeed:
    """실제 WebSocket을 열지 않는 RealtimeFeed 대역 — 생성자 인자와 호출 순서만 기록."""
    instances = []

    def __init__(self, appkey, secretkey, is_mock, stock_codes):
        self.appkey, self.secretkey, self.is_mock, self.stock_codes = appkey, secretkey, is_mock, stock_codes
        self.seeded = []
        self.started = False
        self.stopped = False
        _FakeRealtimeFeed.instances.append(self)

    def seed_from_dataframe(self, code, df):
        self.seeded.append(code)

    def start(self, wait_connected_seconds=10.0):
        self.started = True
        return True

    def stop(self):
        self.stopped = True

    def get_latest_bid(self, code):
        return None


def test_run_trading_loop_builds_and_starts_realtime_feed_by_default(monkeypatch, tmp_path):
    import pandas as pd

    _FakeRealtimeFeed.instances = []
    monkeypatch.setattr(trading_loop, "RealtimeFeed", _FakeRealtimeFeed)
    monkeypatch.setattr(trading_loop, "fetch_today_candles", lambda client, code, **k: pd.DataFrame())

    watchlist = pd.DataFrame([{"stock_code": "005930", "name": "A"}])
    monkeypatch.setattr(trading_loop, "top_by_trading_value", lambda client, top_n: watchlist)
    monkeypatch.setattr(trading_loop, "fetch_today_regime", lambda client, data_dir: True)
    open_flags = iter([True, False])
    monkeypatch.setattr(trading_loop, "is_extended_market_open", lambda now: next(open_flags))
    monkeypatch.setattr(trading_loop.time, "sleep", lambda s: None)

    entry_feed_kwargs, exit_feed_kwargs = [], []
    monkeypatch.setattr(trading_loop, "process_exits_once", lambda *a, **k: exit_feed_kwargs.append(k.get("feed")) or [])
    monkeypatch.setattr(trading_loop, "process_entries_once", lambda *a, **k: entry_feed_kwargs.append(k.get("feed")) or [])

    fake_client = SimpleNamespace(appkey="appkey123", secretkey="secret456", is_mock=True)
    state_path = str(tmp_path / "risk_state.json")

    run_trading_loop(
        fake_client, trained=None, bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0,
    )

    assert len(_FakeRealtimeFeed.instances) == 1
    feed = _FakeRealtimeFeed.instances[0]
    assert (feed.appkey, feed.secretkey, feed.is_mock) == ("appkey123", "secret456", True)
    assert feed.stock_codes == ["005930"]
    assert feed.seeded == ["005930"]
    assert feed.started is True
    assert feed.stopped is True  # 루프 종료(finally) 후 정리됨
    assert entry_feed_kwargs == [feed]
    assert exit_feed_kwargs == [feed]


def test_run_trading_loop_stops_feed_even_if_loop_raises(monkeypatch, tmp_path):
    import pandas as pd

    _FakeRealtimeFeed.instances = []
    monkeypatch.setattr(trading_loop, "RealtimeFeed", _FakeRealtimeFeed)
    monkeypatch.setattr(trading_loop, "fetch_today_candles", lambda client, code, **k: pd.DataFrame())

    watchlist = pd.DataFrame([{"stock_code": "005930", "name": "A"}])
    monkeypatch.setattr(trading_loop, "top_by_trading_value", lambda client, top_n: watchlist)
    monkeypatch.setattr(trading_loop, "fetch_today_regime", lambda client, data_dir: True)
    monkeypatch.setattr(trading_loop, "is_extended_market_open", lambda now: True)

    def boom(*a, **k):
        raise RuntimeError("의도된 테스트 예외")

    monkeypatch.setattr(trading_loop, "process_exits_once", boom)

    fake_client = SimpleNamespace(appkey="appkey123", secretkey="secret456", is_mock=True)
    state_path = str(tmp_path / "risk_state.json")

    with pytest.raises(RuntimeError, match="의도된 테스트 예외"):
        run_trading_loop(
            fake_client, trained=None, bot_token="", chat_id="", max_daily_loss_krw=500_000,
            risk_state_path=state_path, poll_interval_seconds=1.0,
        )

    assert _FakeRealtimeFeed.instances[0].stopped is True
