import json
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backtesting import strategy3_scalp
from backtesting.strategy3_scalp import (
    MIN_RETURN_PCT,
    MIN_TRADE_VALUE,
    check_candidate,
    describe_strategy_3,
    run_scalp_monitor_loop,
    scan_watchlist_once,
)

TODAY_STR = date.today().isoformat()


def _rising_minute(day: str, closes: list[float]) -> pd.DataFrame:
    index = pd.date_range(f"{day} 09:00", periods=len(closes), freq="1min")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [20_000_000] * len(closes)},
        index=index,
    )


def _flat_minute(day: str, n: int) -> pd.DataFrame:
    return _rising_minute(day, [100.0] * n)


def test_describe_strategy_3_lists_only_two_entry_conditions_and_no_exit_logic():
    description = describe_strategy_3()

    assert set(description.keys()) == {"entry", "exit", "operation", "exchange_basis"}
    assert len(description["entry"]) == 2
    assert "청산" in description["exit"][0]


def test_check_candidate_returns_signal_when_value_and_return_conditions_met(monkeypatch):
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    monkeypatch.setattr(strategy3_scalp, "fetch_today_candles", lambda client, code, feed=None, exchange=None: rising)

    result = check_candidate(object(), "000001")

    assert result is not None
    assert result["stock_code"] == "000001"
    assert result["price"] == rising["close"].iloc[-1]


def test_check_candidate_returns_none_when_conditions_not_met(monkeypatch):
    flat = _flat_minute(TODAY_STR, 5)
    monkeypatch.setattr(strategy3_scalp, "fetch_today_candles", lambda client, code, feed=None, exchange=None: flat)

    result = check_candidate(object(), "000001")

    assert result is None


def test_check_candidate_returns_none_when_no_candles(monkeypatch):
    monkeypatch.setattr(strategy3_scalp, "fetch_today_candles", lambda client, code, feed=None, exchange=None: pd.DataFrame())

    result = check_candidate(object(), "000001")

    assert result is None


def test_scan_watchlist_once_dedupes_via_seen_signals(monkeypatch):
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    monkeypatch.setattr(strategy3_scalp, "fetch_today_candles", lambda client, code, feed=None, exchange=None: rising)

    seen: set = set()
    first = scan_watchlist_once(object(), {"000001"}, seen)
    second = scan_watchlist_once(object(), {"000001"}, seen)

    assert len(first) == 1
    assert second == []  # 같은 (종목, 시각) 신호는 두 번째 호출에서 걸러짐


def test_scan_watchlist_once_continues_when_one_stock_errors(monkeypatch):
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])

    def fake_fetch(client, code, feed=None, exchange=None):
        if code == "bad":
            raise RuntimeError("조회 실패")
        return rising

    monkeypatch.setattr(strategy3_scalp, "fetch_today_candles", fake_fetch)

    signals = scan_watchlist_once(object(), {"bad", "000001"}, set())

    assert len(signals) == 1
    assert signals[0]["stock_code"] == "000001"


def test_run_scalp_monitor_loop_notifies_and_logs_without_placing_orders(monkeypatch, tmp_path):
    monkeypatch.setattr(strategy3_scalp, "top_by_trading_value", lambda client, top_n: pd.DataFrame({"stock_code": ["000001"], "name": ["가상전자"]}))

    calls_state = {"iterations": 0}

    def fake_is_market_open(now):
        calls_state["iterations"] += 1
        return calls_state["iterations"] == 1  # 한 바퀴만 돌고 종료

    monkeypatch.setattr(strategy3_scalp, "is_extended_market_open", fake_is_market_open)
    monkeypatch.setattr(strategy3_scalp, "time", SimpleNamespace(sleep=lambda s: None))

    signal = {"stock_code": "000001", "signal_time": "t1", "price": 71000.0}
    monkeypatch.setattr(strategy3_scalp, "scan_watchlist_once", lambda client, watchlist, seen, feed=None: [signal])

    logged = []
    monkeypatch.setattr(strategy3_scalp, "log_signal", lambda sig, path: logged.append((sig, path)))
    notified = []
    monkeypatch.setattr(strategy3_scalp, "notify_signal_detected", lambda *a, **k: notified.append(a))

    output_path = str(tmp_path / "signals.jsonl")
    client = SimpleNamespace(appkey="a", secretkey="b", is_mock=True)
    run_scalp_monitor_loop(client, "TOKEN", "CHAT", output_path=output_path, use_realtime_feed=False)

    assert logged == [(signal, output_path)]
    assert notified == [("strategy_3", "000001", "가상전자", 71000.0, None, "TOKEN", "CHAT")]


def test_run_scalp_monitor_loop_writes_heartbeat_before_first_cycle(monkeypatch, tmp_path):
    from backtesting.heartbeat import read_heartbeat_age_seconds

    monkeypatch.setattr(strategy3_scalp, "top_by_trading_value", lambda client, top_n: pd.DataFrame({"stock_code": ["000001"], "name": ["가상전자"]}))
    monkeypatch.setattr(strategy3_scalp, "is_extended_market_open", lambda now: False)  # 루프 진입 전 확인이 목적

    output_path = str(tmp_path / "strategy_3" / "signals.jsonl")
    client = SimpleNamespace(appkey="a", secretkey="b", is_mock=True)
    run_scalp_monitor_loop(client, "TOKEN", "CHAT", output_path=output_path, use_realtime_feed=False)

    age = read_heartbeat_age_seconds(str(tmp_path / "strategy_3"))
    assert age is not None and age < 5


def test_run_scalp_monitor_loop_stops_when_stop_flag_requested_mid_run(monkeypatch, tmp_path):
    from backtesting.stop_control import request_stop

    monkeypatch.setattr(strategy3_scalp, "top_by_trading_value", lambda client, top_n: pd.DataFrame({"stock_code": ["000001"], "name": ["가상전자"]}))
    monkeypatch.setattr(strategy3_scalp, "is_extended_market_open", lambda now: True)  # 장은 계속 열려 있다고 가정
    monkeypatch.setattr(strategy3_scalp, "time", SimpleNamespace(sleep=lambda s: None))
    monkeypatch.setattr(strategy3_scalp, "log_signal", lambda sig, path: None)
    monkeypatch.setattr(strategy3_scalp, "notify_signal_detected", lambda *a, **k: None)

    output_path = str(tmp_path / "signals.jsonl")
    stop_flag_path = str(tmp_path / "stop_requested.json")
    scan_calls = []

    def fake_scan(client, watchlist, seen, feed=None):
        scan_calls.append(1)
        if len(scan_calls) == 2:
            request_stop(stop_flag_path)  # 두 번째 사이클 도중 중지 요청이 온 상황 재현
        return []

    monkeypatch.setattr(strategy3_scalp, "scan_watchlist_once", fake_scan)

    client = SimpleNamespace(appkey="a", secretkey="b", is_mock=True)
    run_scalp_monitor_loop(client, "TOKEN", "CHAT", output_path=output_path, use_realtime_feed=False, stop_flag_path=stop_flag_path)

    assert len(scan_calls) == 2  # 세 번째 사이클로 안 넘어감


def test_run_scalp_monitor_loop_refreshes_watchlist_each_cycle_and_picks_up_new_entrant(monkeypatch, tmp_path):
    # 실측 재현: 12시엔 top35 밖이었다가 13시대 랠리로 새로 진입한 종목(예: 삼성E&A)이
    # 워치리스트를 시작 시 한 번만 고정하면 재시작 전까지 영영 감시 대상이 아니었다 —
    # 매 사이클 다시 뽑아서 새로 진입한 종목도 바로 스캔 대상에 들어가야 한다.
    watchlists = iter([
        pd.DataFrame({"stock_code": ["000001"], "name": ["가상전자1"]}),  # 시작 시 최초 조회
        pd.DataFrame({"stock_code": ["000001"], "name": ["가상전자1"]}),  # 1사이클 갱신: 신규종목 아직 없음
        pd.DataFrame({"stock_code": ["000001", "999999"], "name": ["가상전자1", "신규진입종목"]}),  # 2사이클 갱신: 신규종목 진입
    ])
    monkeypatch.setattr(strategy3_scalp, "top_by_trading_value", lambda client, top_n: next(watchlists))

    calls_state = {"iterations": 0}

    def fake_is_market_open(now):
        calls_state["iterations"] += 1
        return calls_state["iterations"] <= 2

    monkeypatch.setattr(strategy3_scalp, "is_extended_market_open", fake_is_market_open)
    monkeypatch.setattr(strategy3_scalp, "time", SimpleNamespace(sleep=lambda s: None))

    seen_watchlists = []

    def fake_scan(client, watchlist, seen, feed=None):
        seen_watchlists.append(set(watchlist))
        return []

    monkeypatch.setattr(strategy3_scalp, "scan_watchlist_once", fake_scan)

    output_path = str(tmp_path / "signals.jsonl")
    client = SimpleNamespace(appkey="a", secretkey="b", is_mock=True)
    run_scalp_monitor_loop(client, "TOKEN", "CHAT", output_path=output_path, use_realtime_feed=False)

    assert seen_watchlists == [{"000001"}, {"000001", "999999"}]


def test_run_scalp_monitor_loop_keeps_previous_watchlist_when_refresh_fails(monkeypatch, tmp_path):
    calls_state = {"n": 0}

    def fake_fetch(client, top_n):
        calls_state["n"] += 1
        if calls_state["n"] == 1:
            return pd.DataFrame({"stock_code": ["000001"], "name": ["가상전자1"]})
        raise RuntimeError("일시적 API 오류")

    monkeypatch.setattr(strategy3_scalp, "top_by_trading_value", fake_fetch)

    iterations = {"n": 0}

    def fake_is_market_open(now):
        iterations["n"] += 1
        return iterations["n"] <= 2

    monkeypatch.setattr(strategy3_scalp, "is_extended_market_open", fake_is_market_open)
    monkeypatch.setattr(strategy3_scalp, "time", SimpleNamespace(sleep=lambda s: None))

    seen_watchlists = []

    def fake_scan(client, watchlist, seen, feed=None):
        seen_watchlists.append(set(watchlist))
        return []

    monkeypatch.setattr(strategy3_scalp, "scan_watchlist_once", fake_scan)

    output_path = str(tmp_path / "signals.jsonl")
    client = SimpleNamespace(appkey="a", secretkey="b", is_mock=True)
    run_scalp_monitor_loop(client, "TOKEN", "CHAT", output_path=output_path, use_realtime_feed=False)

    assert seen_watchlists == [{"000001"}, {"000001"}]  # 두 번째 갱신 실패 시 기존 목록 유지


def test_run_scalp_monitor_loop_writes_config_immediately_so_dashboard_lists_it(monkeypatch, tmp_path):
    """log_signal은 신호가 한 번도 안 뜨면 폴더 자체를 안 만들어서, 대시보드
    (list_strategies가 state/ 서브폴더 존재로 전략 목록을 만듦)에 전략3이 영영 안
    뜨는 문제가 있었다 — 시작하자마자 config.json을 써서 즉시 노출되는지 확인."""
    monkeypatch.setattr(strategy3_scalp, "top_by_trading_value", lambda client, top_n: pd.DataFrame({"stock_code": ["000001"], "name": ["가상전자"]}))
    monkeypatch.setattr(strategy3_scalp, "is_extended_market_open", lambda now: False)  # 신호 없이 바로 종료
    monkeypatch.setattr(strategy3_scalp, "scan_watchlist_once", lambda client, watchlist, seen, feed=None: [])

    output_path = str(tmp_path / "strategy_3" / "signals.jsonl")
    client = SimpleNamespace(appkey="a", secretkey="b", is_mock=True)
    run_scalp_monitor_loop(client, "TOKEN", "CHAT", output_path=output_path, top_n=35, poll_interval_seconds=30.0, use_realtime_feed=False)

    config_path = tmp_path / "strategy_3" / "config.json"
    assert config_path.exists()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["strategy"] == "strategy_3"
    assert config["mode"] == "signal_only"
    assert config["is_mock"] is True
