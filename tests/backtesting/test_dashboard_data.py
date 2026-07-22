import json

from backtesting.dashboard_data import (
    load_dashboard_state,
    load_order_history,
    load_pnl_history,
    load_signal_history,
    load_strategy_config,
)


# ---- load_dashboard_state ----

def test_load_dashboard_state_returns_empty_state_when_file_missing(tmp_path):
    state = load_dashboard_state(str(tmp_path / "nonexistent.json"))

    assert state == {
        "trading_date": None,
        "realized_pnl_krw": 0.0,
        "kill_switch_active": False,
        "open_positions": [],
    }


def test_load_dashboard_state_returns_parsed_fields_from_valid_file(tmp_path):
    path = tmp_path / "risk_state.json"
    path.write_text(
        json.dumps(
            {
                "trading_date": "2026-07-20",
                "realized_pnl_krw": -40000.0,
                "kill_switch_active": False,
                "open_positions": [
                    {
                        "code": "005930", "entry_time": "2026-07-20T09:31:00",
                        "allocated_capital": 2_000_000.0, "entry_price": 70000.0,
                        "remaining_fraction": 0.75, "total_quantity": 28,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    state = load_dashboard_state(str(path))

    assert state["trading_date"] == "2026-07-20"
    assert state["realized_pnl_krw"] == -40000.0
    assert state["kill_switch_active"] is False
    assert len(state["open_positions"]) == 1
    assert state["open_positions"][0]["code"] == "005930"


def test_load_dashboard_state_returns_empty_state_when_json_corrupted(tmp_path):
    path = tmp_path / "risk_state.json"
    path.write_text('{"trading_date": "2026-07-20", "realized_pnl_kr', encoding="utf-8")  # 쓰다 만 상태

    state = load_dashboard_state(str(path))

    assert state == {
        "trading_date": None,
        "realized_pnl_krw": 0.0,
        "kill_switch_active": False,
        "open_positions": [],
    }


# ---- load_strategy_config ----

def test_load_strategy_config_returns_empty_dict_when_file_missing(tmp_path):
    config = load_strategy_config(str(tmp_path / "nonexistent.json"))

    assert config == {}


def test_load_strategy_config_returns_parsed_fields_from_valid_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"strategy": "strategy_1", "top_n": 35, "proba_threshold": 0.6}),
        encoding="utf-8",
    )

    config = load_strategy_config(str(path))

    assert config == {"strategy": "strategy_1", "top_n": 35, "proba_threshold": 0.6}


def test_load_strategy_config_returns_empty_dict_when_json_corrupted(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"strategy": "strategy_1", "top_n"', encoding="utf-8")

    config = load_strategy_config(str(path))

    assert config == {}


# ---- load_signal_history ----

def test_load_signal_history_returns_empty_list_when_file_missing(tmp_path):
    signals = load_signal_history(str(tmp_path / "nonexistent.jsonl"))

    assert signals == []


def test_load_signal_history_sorts_by_signal_time_descending(tmp_path):
    path = tmp_path / "signals.jsonl"
    lines = [
        {"stock_code": "005930", "signal_time": "2026-07-20T09:00:00", "price": 70000.0, "proba": 0.55},
        {"stock_code": "000660", "signal_time": "2026-07-20T10:15:00", "price": 215000.0, "proba": 0.62},
        {"stock_code": "035420", "signal_time": "2026-07-20T09:30:00", "price": 180000.0, "proba": 0.58},
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

    signals = load_signal_history(str(path))

    assert [s["stock_code"] for s in signals] == ["000660", "035420", "005930"]


def test_load_signal_history_skips_corrupted_lines(tmp_path):
    path = tmp_path / "signals.jsonl"
    good1 = json.dumps({"stock_code": "005930", "signal_time": "2026-07-20T09:00:00", "price": 70000.0, "proba": 0.55})
    good2 = json.dumps({"stock_code": "000660", "signal_time": "2026-07-20T10:15:00", "price": 215000.0, "proba": 0.62})
    corrupted = '{"stock_code": "035420", "signal_time": "2026-07-20T09:3'  # 쓰다 만 줄
    path.write_text("\n".join([good1, corrupted, good2]), encoding="utf-8")

    signals = load_signal_history(str(path))

    assert len(signals) == 2
    assert {s["stock_code"] for s in signals} == {"005930", "000660"}


def test_load_signal_history_respects_limit(tmp_path):
    path = tmp_path / "signals.jsonl"
    lines = [
        {"stock_code": f"{i:06d}", "signal_time": f"2026-07-20T09:{i:02d}:00", "price": 1000.0, "proba": 0.5}
        for i in range(10)
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

    signals = load_signal_history(str(path), limit=3)

    assert len(signals) == 3
    # 최신순(signal_time 내림차순) 상위 3개
    assert [s["stock_code"] for s in signals] == ["000009", "000008", "000007"]


# ---- load_order_history ----

def test_load_order_history_returns_empty_list_when_file_missing(tmp_path):
    orders = load_order_history(str(tmp_path / "nonexistent.jsonl"))

    assert orders == []


def test_load_order_history_sorts_by_order_time_descending(tmp_path):
    path = tmp_path / "orders.jsonl"
    lines = [
        {"side": "buy", "code": "005930", "quantity": 28, "price": 70000.0, "reason": "entry", "order_time": "2026-07-20T09:31:00"},
        {"side": "sell", "code": "005930", "quantity": 7, "price": 71750.0, "reason": "take_profit_tier", "order_time": "2026-07-20T10:05:00"},
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

    orders = load_order_history(str(path))

    assert [o["order_time"] for o in orders] == ["2026-07-20T10:05:00", "2026-07-20T09:31:00"]


def test_load_order_history_skips_corrupted_lines(tmp_path):
    path = tmp_path / "orders.jsonl"
    good = json.dumps({"side": "buy", "code": "005930", "quantity": 28, "price": 70000.0, "reason": "entry", "order_time": "2026-07-20T09:31:00"})
    corrupted = '{"side": "sell", "code": "0059'
    path.write_text("\n".join([good, corrupted]), encoding="utf-8")

    orders = load_order_history(str(path))

    assert len(orders) == 1


# ---- load_pnl_history ----

def test_load_pnl_history_returns_empty_list_when_file_missing(tmp_path):
    history = load_pnl_history(str(tmp_path / "nonexistent.jsonl"))

    assert history == []


def test_load_pnl_history_sorts_by_date_ascending(tmp_path):
    path = tmp_path / "pnl_history.jsonl"
    lines = [
        {"date": "2026-07-19", "realized_pnl_krw": -12000.0},
        {"date": "2026-07-18", "realized_pnl_krw": 35000.0},
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

    history = load_pnl_history(str(path))

    assert [h["date"] for h in history] == ["2026-07-18", "2026-07-19"]


def test_load_pnl_history_skips_corrupted_lines(tmp_path):
    path = tmp_path / "pnl_history.jsonl"
    good = json.dumps({"date": "2026-07-18", "realized_pnl_krw": 35000.0})
    corrupted = '{"date": "2026-07-19", "realized_pnl_k'
    path.write_text("\n".join([good, corrupted]), encoding="utf-8")

    history = load_pnl_history(str(path))

    assert len(history) == 1
