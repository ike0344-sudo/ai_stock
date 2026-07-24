import json

import pytest

from backtesting.risk_manager import (
    OpenPosition,
    RiskState,
    can_open_new_position,
    load_state,
    record_partial_exit,
    record_position_added_to,
    record_position_closed,
    record_position_opened,
    roll_to_new_day_if_needed,
    save_state,
)


def _state_with_positions(n: int, trading_date: str = "2026-07-20") -> RiskState:
    positions = [
        OpenPosition(code=f"00000{i}", entry_time="2026-07-20T09:0" + str(i), allocated_capital=2_000_000, entry_price=100.0)
        for i in range(n)
    ]
    return RiskState(trading_date=trading_date, open_positions=positions)


def test_can_open_new_position_true_when_slot_available():
    state = _state_with_positions(3)

    assert can_open_new_position(state, max_concurrent=5) is True


def test_can_open_new_position_false_when_all_slots_full():
    state = _state_with_positions(5)

    assert can_open_new_position(state, max_concurrent=5) is False


def test_can_open_new_position_false_when_kill_switch_active_even_with_free_slots():
    state = _state_with_positions(0)
    state.kill_switch_active = True

    assert can_open_new_position(state, max_concurrent=5) is False


def test_record_position_opened_appends_position():
    state = RiskState(trading_date="2026-07-20")

    record_position_opened(state, "005930", "2026-07-20T09:05", allocated_capital=2_000_000, entry_price=70000)

    assert len(state.open_positions) == 1
    assert state.open_positions[0].code == "005930"


def test_record_position_added_to_averages_entry_price_and_accumulates_quantity():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(
        state, "000660", "2026-07-20T09:05", allocated_capital=1_000_000, entry_price=100.0, total_quantity=10,
    )

    record_position_added_to(state, "000660", additional_capital=1_000_000, fill_price=88.0, additional_quantity=12)

    position = state.open_positions[0]
    assert position.total_quantity == 22
    assert position.allocated_capital == 2_000_000
    # (100*10 + 88*12) / 22
    assert position.entry_price == pytest.approx((100.0 * 10 + 88.0 * 12) / 22)


def test_record_position_added_to_raises_when_no_open_position():
    state = RiskState(trading_date="2026-07-20")

    with pytest.raises(ValueError):
        record_position_added_to(state, "000660", additional_capital=1_000_000, fill_price=88.0, additional_quantity=12)


def test_record_position_added_to_keeps_single_position_closeable_by_code():
    # 같은 code로 여러 OpenPosition을 만들지 않고 이 함수로 갱신하면, record_position_closed가
    # 평단가 전체를 한 번에 정확히 청산할 수 있다(반대로 여러 개를 만들면 첫 번째만
    # 청산되고 나머지는 손익 반영 없이 사라진다 — 이 함수가 막으려는 상황).
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(
        state, "000660", "2026-07-20T09:05", allocated_capital=1_000_000, entry_price=100.0, total_quantity=10,
    )
    record_position_added_to(state, "000660", additional_capital=1_000_000, fill_price=88.0, additional_quantity=12)

    assert len(state.open_positions) == 1  # 포지션이 여전히 하나 — 청산 시 전량 정확히 처리됨
    record_position_closed(state, "000660", exit_price=95.0, max_daily_loss_krw=10_000_000)
    assert state.open_positions == []


def test_record_position_closed_updates_realized_pnl_and_removes_position():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "2026-07-20T09:05", allocated_capital=2_000_000, entry_price=70000)

    record_position_closed(state, "005930", exit_price=71400, max_daily_loss_krw=1_000_000)  # +2%

    assert state.open_positions == []
    assert state.realized_pnl_krw == pytest.approx(40_000)  # 2,000,000 * 0.02
    assert state.kill_switch_active is False


def test_record_position_closed_triggers_kill_switch_when_loss_exceeds_threshold():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "2026-07-20T09:05", allocated_capital=2_000_000, entry_price=70000)

    # -3% * 2,000,000 = -60,000, 한도 50,000 초과
    record_position_closed(state, "005930", exit_price=67900, max_daily_loss_krw=50_000)

    assert state.kill_switch_active is True
    assert can_open_new_position(state, max_concurrent=5) is False


def test_record_position_closed_accumulates_across_multiple_trades():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "t1", allocated_capital=1_000_000, entry_price=100)
    record_position_opened(state, "000660", "t2", allocated_capital=1_000_000, entry_price=200)

    record_position_closed(state, "005930", exit_price=90, max_daily_loss_krw=1_000_000)  # -10% -> -100,000
    record_position_closed(state, "000660", exit_price=180, max_daily_loss_krw=1_000_000)  # -10% -> -100,000

    assert state.realized_pnl_krw == pytest.approx(-200_000)
    assert state.kill_switch_active is False  # 아직 한도(1,000,000) 안 넘음


def test_record_position_closed_raises_when_position_not_open():
    state = RiskState(trading_date="2026-07-20")

    with pytest.raises(ValueError):
        record_position_closed(state, "005930", exit_price=100, max_daily_loss_krw=1_000_000)


def test_record_partial_exit_keeps_slot_occupied_until_fully_closed():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "t1", allocated_capital=4_000_000, entry_price=100)

    record_partial_exit(state, "005930", exit_price=103, sold_fraction=0.25, max_daily_loss_krw=1_000_000)

    assert len(state.open_positions) == 1  # 슬롯 계속 점유
    assert state.open_positions[0].remaining_fraction == pytest.approx(0.75)
    assert state.realized_pnl_krw == pytest.approx(4_000_000 * 0.25 * 0.03)
    assert can_open_new_position(state, max_concurrent=1) is False  # 슬롯 1개 다 참


def test_record_partial_exit_frees_slot_only_on_final_leg():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "t1", allocated_capital=4_000_000, entry_price=100)

    record_partial_exit(state, "005930", exit_price=103, sold_fraction=0.25, max_daily_loss_krw=1_000_000)
    record_partial_exit(state, "005930", exit_price=105, sold_fraction=0.25, max_daily_loss_krw=1_000_000)
    record_partial_exit(state, "005930", exit_price=107, sold_fraction=0.25, max_daily_loss_krw=1_000_000)
    assert len(state.open_positions) == 1  # 아직 25% 남음

    record_partial_exit(state, "005930", exit_price=110, sold_fraction=0.25, max_daily_loss_krw=1_000_000)

    assert state.open_positions == []  # 마지막 leg에서 완전히 비워짐
    assert can_open_new_position(state, max_concurrent=1) is True


def test_record_partial_exit_accumulates_pnl_across_legs():
    state = RiskState(trading_date="2026-07-20")
    record_position_opened(state, "005930", "t1", allocated_capital=4_000_000, entry_price=100)

    record_partial_exit(state, "005930", exit_price=102.5, sold_fraction=0.25, max_daily_loss_krw=1_000_000)
    record_partial_exit(state, "005930", exit_price=104, sold_fraction=0.75, max_daily_loss_krw=1_000_000)

    expected = 4_000_000 * 0.25 * 0.025 + 4_000_000 * 0.75 * 0.04
    assert state.realized_pnl_krw == pytest.approx(expected)


def test_record_partial_exit_raises_when_position_not_open():
    state = RiskState(trading_date="2026-07-20")

    with pytest.raises(ValueError):
        record_partial_exit(state, "005930", exit_price=100, sold_fraction=0.25, max_daily_loss_krw=1_000_000)


def test_roll_to_new_day_if_needed_resets_pnl_and_kill_switch_but_keeps_positions():
    state = _state_with_positions(2, trading_date="2026-07-19")
    state.realized_pnl_krw = -500_000
    state.kill_switch_active = True

    rolled = roll_to_new_day_if_needed(state, today="2026-07-20")

    assert rolled.trading_date == "2026-07-20"
    assert rolled.realized_pnl_krw == 0.0
    assert rolled.kill_switch_active is False
    assert len(rolled.open_positions) == 2  # 포지션은 보존


def test_roll_to_new_day_if_needed_noop_when_same_day():
    state = _state_with_positions(1, trading_date="2026-07-20")
    state.realized_pnl_krw = -500_000

    rolled = roll_to_new_day_if_needed(state, today="2026-07-20")

    assert rolled.realized_pnl_krw == -500_000  # 변화 없음


def test_load_state_returns_fresh_state_when_file_missing(tmp_path):
    state = load_state(str(tmp_path / "nonexistent.json"))

    assert state.open_positions == []
    assert state.kill_switch_active is False


def test_save_and_load_state_round_trip_preserves_kill_switch(tmp_path):
    path = str(tmp_path / "risk_state.json")
    state = _state_with_positions(2, trading_date="2026-07-20")
    state.realized_pnl_krw = -300_000
    state.kill_switch_active = True

    save_state(state, path)
    restored = load_state(path)

    assert restored.trading_date == "2026-07-20"
    assert restored.realized_pnl_krw == pytest.approx(-300_000)
    assert restored.kill_switch_active is True
    assert len(restored.open_positions) == 2
    assert restored.open_positions[0].code == "000000"
    assert can_open_new_position(restored, max_concurrent=5) is False  # 재시작해도 여전히 차단


def test_roll_to_new_day_appends_previous_day_pnl_to_history(tmp_path):
    history_path = str(tmp_path / "pnl_history.jsonl")
    state = RiskState(trading_date="2026-07-19", realized_pnl_krw=35_000.0)

    roll_to_new_day_if_needed(state, today="2026-07-20", pnl_history_path=history_path)

    lines = (tmp_path / "pnl_history.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry == {"date": "2026-07-19", "realized_pnl_krw": 35_000.0}


def test_roll_to_new_day_does_not_append_when_same_day(tmp_path):
    history_path = str(tmp_path / "pnl_history.jsonl")
    state = RiskState(trading_date="2026-07-20", realized_pnl_krw=35_000.0)

    roll_to_new_day_if_needed(state, today="2026-07-20", pnl_history_path=history_path)

    assert not (tmp_path / "pnl_history.jsonl").exists()


def test_roll_to_new_day_skips_history_append_when_path_not_given(tmp_path, monkeypatch):
    """하위호환: pnl_history_path를 넘기지 않는 기존 호출부(trading_loop.py 등)가
    그대로 동작해야 함 — 이력 적재를 그냥 건너뛴다."""
    monkeypatch.chdir(tmp_path)
    state = RiskState(trading_date="2026-07-19", realized_pnl_krw=35_000.0)

    rolled = roll_to_new_day_if_needed(state, today="2026-07-20")

    assert rolled.trading_date == "2026-07-20"
    assert not (tmp_path / "pnl_history.jsonl").exists()


def test_roll_to_new_day_appends_multiple_days_across_calls(tmp_path):
    history_path = str(tmp_path / "pnl_history.jsonl")
    day1 = RiskState(trading_date="2026-07-18", realized_pnl_krw=10_000.0)
    rolled1 = roll_to_new_day_if_needed(day1, today="2026-07-19", pnl_history_path=history_path)
    rolled1.realized_pnl_krw = -5_000.0

    roll_to_new_day_if_needed(rolled1, today="2026-07-20", pnl_history_path=history_path)

    lines = (tmp_path / "pnl_history.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"date": "2026-07-18", "realized_pnl_krw": 10_000.0}
    assert json.loads(lines[1]) == {"date": "2026-07-19", "realized_pnl_krw": -5_000.0}
