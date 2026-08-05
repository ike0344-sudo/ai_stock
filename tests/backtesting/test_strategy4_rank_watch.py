import json
from types import SimpleNamespace

import pandas as pd
import pytest

from backtesting import strategy4_rank_watch
from backtesting.strategy4_rank_watch import (
    WATCHED_RANK_PAIRS,
    check_rank_promotions,
    describe_strategy_4,
    generate_signals,
    run_rank_watch_loop,
)


def test_describe_strategy_4_lists_all_watched_pairs_and_no_exit_logic():
    description = describe_strategy_4()

    assert set(description.keys()) == {"entry", "exit", "operation", "exchange_basis"}
    for from_rank, to_rank in WATCHED_RANK_PAIRS:
        assert f"{from_rank}위→{to_rank}위" in description["entry"][0]
    assert "청산" in description["exit"][0]


def test_check_rank_promotions_fires_when_prev_4th_becomes_3rd():
    previous_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}
    current_ranks = {"AAA": 1, "BBB": 2, "DDD": 3, "CCC": 4}  # DDD(4위) <-> CCC(3위) 자리 교환

    assert check_rank_promotions(previous_ranks, current_ranks) == [("DDD", 4, 3)]


def test_check_rank_promotions_fires_for_multiple_pairs_in_same_cycle():
    # 4->3위, 5->4위가 같은 사이클에 동시에 감지되는 경우
    previous_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4, "EEE": 5}
    current_ranks = {"AAA": 1, "BBB": 2, "DDD": 3, "EEE": 4, "CCC": 5}

    promotions = check_rank_promotions(previous_ranks, current_ranks)

    assert ("DDD", 4, 3) in promotions
    assert ("EEE", 5, 4) in promotions
    assert len(promotions) == 2


def test_check_rank_promotions_detects_6th_to_5th():
    previous_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4, "EEE": 5, "FFF": 6}
    current_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4, "FFF": 5, "EEE": 6}

    assert check_rank_promotions(previous_ranks, current_ranks) == [("FFF", 6, 5)]


def test_check_rank_promotions_empty_when_prev_ranks_stay_put():
    previous_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}
    current_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}  # 변동 없음

    assert check_rank_promotions(previous_ranks, current_ranks) == []


def test_check_rank_promotions_empty_when_prev_4th_drops_out_of_ranking():
    previous_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}
    current_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "EEE": 4}  # DDD가 순위 밖으로 밀려남

    assert check_rank_promotions(previous_ranks, current_ranks) == []


def test_check_rank_promotions_empty_when_a_different_stock_becomes_3rd():
    # 3위 자리 자체는 바뀌었지만, 그게 "직전에 4위였던 종목"이 아니면 알림 대상이 아니다
    # (사용자가 명시적으로 확정한 트리거: "지금 N등인 종목이 N-1등으로 올라설 때").
    previous_ranks = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}
    current_ranks = {"AAA": 1, "EEE": 2, "BBB": 3, "CCC": 4}  # 새 종목 EEE가 끼어들며 재배열, DDD는 관련 없음

    assert check_rank_promotions(previous_ranks, current_ranks) == []


def test_check_rank_promotions_empty_on_first_cycle_with_no_previous_data():
    assert check_rank_promotions({}, {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}) == []


# ---- generate_signals (Strategy 프로토콜 어댑터) ----

def test_generate_signals_fires_on_rank_promotion_from_rank_column():
    df = pd.DataFrame({"rank": [6, 5, 4, 3, 3]})  # idx0->1: 6->5, idx1->2: 5->4, idx2->3: 4->3 연쇄 승격

    out = generate_signals(df)

    assert list(out["signal"]) == [0, 1, 1, 1, 0]


def test_generate_signals_fires_on_5_to_4_and_6_to_5_promotions_too():
    df = pd.DataFrame({"rank": [6, 5, 5, 4]})  # idx0->1: 6->5, idx2->3: 5->4

    out = generate_signals(df)

    assert list(out["signal"]) == [0, 1, 0, 1]


def test_generate_signals_all_zero_when_prev_4th_stays_at_4th():
    df = pd.DataFrame({"rank": [4, 4, 4]})

    out = generate_signals(df)

    assert (out["signal"] == 0).all()


def test_generate_signals_exposes_name_and_params():
    assert generate_signals.name == "strategy_4"
    assert generate_signals.params == {"watched_rank_pairs": WATCHED_RANK_PAIRS}


def test_run_rank_watch_loop_notifies_and_logs_on_promotion_without_placing_orders(monkeypatch, tmp_path):
    rankings = iter([
        [
            {"stock_code": "AAA", "name": "가상1", "rank": 3},
            {"stock_code": "DDD", "name": "가상4", "rank": 4},
        ],
        [
            {"stock_code": "DDD", "name": "가상4", "rank": 3},
            {"stock_code": "AAA", "name": "가상1", "rank": 4},
        ],
    ])
    monkeypatch.setattr(
        strategy4_rank_watch, "get_trading_value_ranking",
        lambda appkey, secretkey, is_mock, window, top_n: {"rows": next(rankings)},
    )

    calls_state = {"iterations": 0}

    def fake_is_market_open(now):
        calls_state["iterations"] += 1
        return calls_state["iterations"] <= 2  # 두 바퀴 돌고 종료(승격이 두 번째 사이클에 감지됨)

    monkeypatch.setattr(strategy4_rank_watch, "is_market_open", fake_is_market_open)
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


def test_run_rank_watch_loop_notifies_separately_for_each_simultaneous_promotion(monkeypatch, tmp_path):
    rankings = iter([
        [
            {"stock_code": "AAA", "name": "가상1", "rank": 3},
            {"stock_code": "DDD", "name": "가상4", "rank": 4},
            {"stock_code": "EEE", "name": "가상5", "rank": 5},
        ],
        [
            {"stock_code": "AAA", "name": "가상1", "rank": 2},
            {"stock_code": "DDD", "name": "가상4", "rank": 3},
            {"stock_code": "EEE", "name": "가상5", "rank": 4},
        ],
    ])
    monkeypatch.setattr(
        strategy4_rank_watch, "get_trading_value_ranking",
        lambda appkey, secretkey, is_mock, window, top_n: {"rows": next(rankings)},
    )

    calls_state = {"iterations": 0}

    def fake_is_market_open(now):
        calls_state["iterations"] += 1
        return calls_state["iterations"] <= 2

    monkeypatch.setattr(strategy4_rank_watch, "is_market_open", fake_is_market_open)
    monkeypatch.setattr(strategy4_rank_watch, "time", SimpleNamespace(sleep=lambda s: None))

    notified = []
    monkeypatch.setattr(strategy4_rank_watch, "send_telegram", lambda message, bot_token, chat_id: notified.append(message))

    output_path = str(tmp_path / "strategy_4" / "signals.jsonl")
    client = SimpleNamespace(appkey="a", secretkey="b", is_mock=True)
    run_rank_watch_loop(client, "TOKEN", "CHAT", output_path=output_path, poll_interval_seconds=0)

    assert len(notified) == 2
    assert any("DDD" in m and "4위" in m and "3위" in m for m in notified)
    assert any("EEE" in m and "5위" in m and "4위" in m for m in notified)

    logged_lines = (tmp_path / "strategy_4" / "signals.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(logged_lines) == 2


def test_run_rank_watch_loop_writes_config_immediately_so_dashboard_lists_it(monkeypatch, tmp_path):
    monkeypatch.setattr(
        strategy4_rank_watch, "get_trading_value_ranking",
        lambda appkey, secretkey, is_mock, window, top_n: {"rows": []},
    )
    monkeypatch.setattr(strategy4_rank_watch, "is_market_open", lambda now: False)  # 조회 없이 바로 종료

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

    monkeypatch.setattr(strategy4_rank_watch, "is_market_open", lambda now: True)  # 장은 계속 열려 있다고 가정
    monkeypatch.setattr(strategy4_rank_watch, "time", SimpleNamespace(sleep=lambda s: None))
    monkeypatch.setattr(strategy4_rank_watch, "send_telegram", lambda *a, **k: None)

    output_path = str(tmp_path / "signals.jsonl")
    stop_flag_path = str(tmp_path / "stop_requested.json")
    fetch_calls = []

    def fake_fetch(appkey, secretkey, is_mock, window, top_n):
        fetch_calls.append(1)
        if len(fetch_calls) == 2:
            request_stop(stop_flag_path)  # 두 번째 조회 도중 중지 요청이 온 상황 재현
        return {"rows": []}

    monkeypatch.setattr(strategy4_rank_watch, "get_trading_value_ranking", fake_fetch)

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

    monkeypatch.setattr(strategy4_rank_watch, "is_market_open", fake_is_market_open)

    def fake_fetch(appkey, secretkey, is_mock, window, top_n):
        raise RuntimeError("조회 실패")

    monkeypatch.setattr(strategy4_rank_watch, "get_trading_value_ranking", fake_fetch)

    output_path = str(tmp_path / "signals.jsonl")
    client = SimpleNamespace(appkey="a", secretkey="b", is_mock=True)
    run_rank_watch_loop(client, "TOKEN", "CHAT", output_path=output_path)  # 예외 없이 정상 종료돼야 함
