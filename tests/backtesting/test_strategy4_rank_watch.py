import json
from types import SimpleNamespace

import pandas as pd
import pytest

from backtesting import strategy4_rank_watch
from backtesting.strategy4_rank_watch import (
    check_rank_promotion,
    describe_strategy_4,
    run_rank_watch_loop,
)


def test_describe_strategy_4_lists_only_rank_promotion_condition_and_no_exit_logic():
    description = describe_strategy_4()

    assert set(description.keys()) == {"entry", "exit", "operation", "exchange_basis"}
    assert "4위" in description["entry"][0] and "3위" in description["entry"][0]
    assert "청산" in description["exit"][0]


def test_check_rank_promotion_fires_when_prev_4th_becomes_3rd():
    previous_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}
    current_ranks = {"AAA": 1, "BBB": 2, "DDD": 3, "CCC": 4}  # DDD(4위) <-> CCC(3위) 자리 교환

    assert check_rank_promotion(previous_ranks, current_ranks) == "DDD"


def test_check_rank_promotion_none_when_prev_4th_stays_at_4th():
    previous_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}
    current_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}  # 변동 없음

    assert check_rank_promotion(previous_ranks, current_ranks) is None


def test_check_rank_promotion_none_when_prev_4th_drops_out_of_ranking():
    previous_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}
    current_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "EEE": 4}  # DDD가 순위 밖으로 밀려남

    assert check_rank_promotion(previous_ranks, current_ranks) is None


def test_check_rank_promotion_none_when_a_different_stock_becomes_3rd():
    # 3위 자리 자체는 바뀌었지만, 그게 "직전에 4위였던 종목"이 아니면 알림 대상이 아니다
    # (사용자가 명시적으로 확정한 트리거: "지금 4등인 종목이 3등으로 올라설 때").
    previous_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}
    current_ranks = {"AAA": 1, "EEE": 2, "BBB": 3, "CCC": 4}  # 새 종목 EEE가 끼어들며 재배열, DDD는 관련 없음

    assert check_rank_promotion(previous_ranks, current_ranks) is None


def test_check_rank_promotion_none_on_first_cycle_with_no_previous_data():
    assert check_rank_promotion({}, {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}) is None


def test_run_rank_watch_loop_notifies_and_logs_on_promotion_without_placing_orders(monkeypatch, tmp_path):
    rankings = iter([
        pd.DataFrame([
            {"stock_code": "AAA", "name": "가상1", "rank": 3},
            {"stock_code": "DDD", "name": "가상4", "rank": 4},
        ]),
        pd.DataFrame([
            {"stock_code": "DDD", "name": "가상4", "rank": 3},
            {"stock_code": "AAA", "name": "가상1", "rank": 4},
        ]),
    ])
    monkeypatch.setattr(strategy4_rank_watch, "top_by_trading_value", lambda client, top_n: next(rankings))

    calls_state = {"iterations": 0}

    def fake_is_market_open(now):
        calls_state["iterations"] += 1
        return calls_state["iterations"] <= 2  # 두 바퀴 돌고 종료(승격이 두 번째 사이클에 감지됨)

    monkeypatch.setattr(strategy4_rank_watch, "is_extended_market_open", fake_is_market_open)
    monkeypatch.setattr(strategy4_rank_watch, "time", SimpleNamespace(sleep=lambda s: None))

    notified = []
    monkeypatch.setattr(strategy4_rank_watch, "send_telegram", lambda message, bot_token, chat_id: notified.append(message))

    output_path = str(tmp_path / "strategy_4" / "signals.jsonl")
    client = SimpleNamespace(appkey="a", secretkey="b", is_mock=True)
    run_rank_watch_loop(client, "TOKEN", "CHAT", output_path=output_path, poll_interval_seconds=0)

    assert len(notified) == 1
    assert "DDD" in notified[0] and "4위" in notified[0] and "3위" in notified[0]

    logged_lines = (tmp_path / "strategy_4" / "signals.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(logged_lines) == 1
    entry = json.loads(logged_lines[0])
    assert entry["stock_code"] == "DDD"
    assert entry["from_rank"] == 4
    assert entry["to_rank"] == 3


def test_run_rank_watch_loop_writes_config_immediately_so_dashboard_lists_it(monkeypatch, tmp_path):
    monkeypatch.setattr(strategy4_rank_watch, "top_by_trading_value", lambda client, top_n: pd.DataFrame({"stock_code": [], "name": [], "rank": []}))
    monkeypatch.setattr(strategy4_rank_watch, "is_extended_market_open", lambda now: False)  # 조회 없이 바로 종료

    output_path = str(tmp_path / "strategy_4" / "signals.jsonl")
    client = SimpleNamespace(appkey="a", secretkey="b", is_mock=True)
    run_rank_watch_loop(client, "TOKEN", "CHAT", output_path=output_path, top_n=10, poll_interval_seconds=10.0)

    config_path = tmp_path / "strategy_4" / "config.json"
    assert config_path.exists()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["strategy"] == "strategy_4"
    assert config["mode"] == "signal_only"


def test_run_rank_watch_loop_stops_when_stop_flag_requested_mid_run(monkeypatch, tmp_path):
    from backtesting.stop_control import request_stop

    monkeypatch.setattr(strategy4_rank_watch, "is_extended_market_open", lambda now: True)  # 장은 계속 열려 있다고 가정
    monkeypatch.setattr(strategy4_rank_watch, "time", SimpleNamespace(sleep=lambda s: None))
    monkeypatch.setattr(strategy4_rank_watch, "send_telegram", lambda *a, **k: None)

    output_path = str(tmp_path / "signals.jsonl")
    stop_flag_path = str(tmp_path / "stop_requested.json")
    fetch_calls = []

    def fake_fetch(client, top_n):
        fetch_calls.append(1)
        if len(fetch_calls) == 2:
            request_stop(stop_flag_path)  # 두 번째 조회 도중 중지 요청이 온 상황 재현
        return pd.DataFrame({"stock_code": [], "name": [], "rank": []})

    monkeypatch.setattr(strategy4_rank_watch, "top_by_trading_value", fake_fetch)

    client = SimpleNamespace(appkey="a", secretkey="b", is_mock=True)
    run_rank_watch_loop(client, "TOKEN", "CHAT", output_path=output_path, stop_flag_path=stop_flag_path)

    assert len(fetch_calls) == 2  # 세 번째 조회로 안 넘어감


def test_run_rank_watch_loop_continues_after_ranking_fetch_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(strategy4_rank_watch, "time", SimpleNamespace(sleep=lambda s: None))
    monkeypatch.setattr(strategy4_rank_watch, "send_telegram", lambda *a, **k: None)

    calls_state = {"iterations": 0}

    def fake_is_market_open(now):
        calls_state["iterations"] += 1
        return calls_state["iterations"] <= 1

    monkeypatch.setattr(strategy4_rank_watch, "is_extended_market_open", fake_is_market_open)

    def fake_fetch(client, top_n):
        raise RuntimeError("조회 실패")

    monkeypatch.setattr(strategy4_rank_watch, "top_by_trading_value", fake_fetch)

    output_path = str(tmp_path / "signals.jsonl")
    client = SimpleNamespace(appkey="a", secretkey="b", is_mock=True)
    run_rank_watch_loop(client, "TOKEN", "CHAT", output_path=output_path)  # 예외 없이 정상 종료돼야 함
