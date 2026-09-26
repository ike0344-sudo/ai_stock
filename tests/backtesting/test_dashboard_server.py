import json
import os
import threading
import time
from datetime import datetime
from http.client import HTTPConnection
from types import SimpleNamespace

import pandas as pd
import pytest

from backtesting import sell_all_job, top35_job
from backtesting.dashboard_server import build_dashboard_server
from backtesting.sell_all_job import SellAllJobState
from backtesting.top35_job import Top35JobState


@pytest.fixture(autouse=True)
def reset_top35_job_state():
    top35_job._state = Top35JobState()
    yield
    top35_job._state = Top35JobState()


@pytest.fixture(autouse=True)
def reset_sell_all_job_state():
    sell_all_job._state = SellAllJobState()
    yield
    sell_all_job._state = SellAllJobState()


@pytest.fixture
def running_server(tmp_path):
    """port=0으로 OS가 배정한 빈 포트에 실제 서버를 띄운다. 상태 파일은
    state_root/strategy_1/ 밑에 두고(run-trading --strategy 기본값과 동일 규칙),
    요청용 커넥션 헬퍼와 각 경로를 속성으로 담은 SimpleNamespace를 준다."""
    state_root = str(tmp_path / "state")
    strategy_dir = os.path.join(state_root, "strategy_1")
    os.makedirs(strategy_dir, exist_ok=True)
    # risk_state.json은 계좌 전체가 공유하는 단일 파일이라 strategy_dir이 아니라
    # state_root 바로 밑에 있다(risk-agent.md 계좌 단일화, 2026-08-29).
    risk_state_path = os.path.join(state_root, "risk_state.json")
    signals_path = os.path.join(strategy_dir, "signals.jsonl")
    orders_path = os.path.join(strategy_dir, "orders.jsonl")
    pnl_history_path = os.path.join(strategy_dir, "pnl_history.jsonl")
    kill_switch_override_path = os.path.join(strategy_dir, "kill_switch_override.json")
    results_dir = str(tmp_path / "results")
    server = build_dashboard_server(state_root=state_root, results_dir=results_dir, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    port = server.server_address[1]

    def get(path: str):
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response, body

    def post(path: str):
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", path)
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response, body

    yield SimpleNamespace(
        get=get, post=post, port=port, state_root=state_root, risk_state_path=risk_state_path,
        strategy_dir=strategy_dir,
        signals_path=signals_path, results_dir=results_dir, orders_path=orders_path,
        pnl_history_path=pnl_history_path, kill_switch_override_path=kill_switch_override_path,
    )

    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_get_api_state_returns_empty_state_when_no_file(running_server):
    get = running_server.get

    response, body = get("/api/state")

    assert response.status == 200
    assert response.getheader("Content-Type") == "application/json; charset=utf-8"
    payload = json.loads(body)
    assert payload == {
        "trading_date": None, "realized_pnl_krw": 0.0,
        "kill_switch_active": False, "open_positions": [],
    }


def test_get_api_state_returns_parsed_file_contents(running_server):
    get = running_server.get
    risk_state_path = running_server.risk_state_path
    with open(risk_state_path, "w", encoding="utf-8") as f:
        json.dump({"trading_date": "2026-07-20", "realized_pnl_krw": -15000.0, "kill_switch_active": True, "open_positions": []}, f)

    response, body = get("/api/state")

    payload = json.loads(body)
    assert payload["realized_pnl_krw"] == -15000.0
    assert payload["kill_switch_active"] is True


def test_get_api_signals_returns_json_array(running_server):
    get = running_server.get
    signals_path = running_server.signals_path
    with open(signals_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"stock_code": "005930", "signal_time": "2026-07-20T09:00:00", "price": 70000.0, "proba": 0.6}) + "\n")

    response, body = get("/api/signals")

    assert response.status == 200
    payload = json.loads(body)
    # 여러 전략의 신호를 합쳐서 보여주므로 각 항목에 어느 전략인지(strategy) 태그가 붙는다.
    assert payload == [{"stock_code": "005930", "signal_time": "2026-07-20T09:00:00", "price": 70000.0, "proba": 0.6, "strategy": "strategy_1"}]


def test_get_api_signals_combines_all_strategies_sorted_by_time(tmp_path):
    from backtesting.dashboard_server import build_dashboard_server

    state_root = str(tmp_path / "state")
    os.makedirs(os.path.join(state_root, "strategy_1"))
    os.makedirs(os.path.join(state_root, "strategy_2"))
    with open(os.path.join(state_root, "strategy_1", "signals.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"stock_code": "005930", "signal_time": "2026-07-20T09:00:00", "price": 70000.0}) + "\n")
    with open(os.path.join(state_root, "strategy_2", "signals.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"stock_code": "000660", "signal_time": "2026-07-20T10:15:00", "price": 215000.0}) + "\n")

    server = build_dashboard_server(state_root=state_root, results_dir=str(tmp_path / "results"), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/api/signals")
    response = conn.getresponse()
    body = response.read()
    conn.close()

    server.shutdown()
    server.server_close()
    thread.join(timeout=5)

    payload = json.loads(body)
    assert [s["stock_code"] for s in payload] == ["000660", "005930"]  # 시각 내림차순
    assert payload[0]["strategy"] == "strategy_2"
    assert payload[1]["strategy"] == "strategy_1"


def test_get_root_serves_index_html(running_server):
    get = running_server.get

    response, body = get("/")

    assert response.status == 200
    assert "text/html" in response.getheader("Content-Type")
    assert b"trading-dashboard" in body


def test_get_ranking_html_serves_dedicated_ranking_page(running_server):
    get = running_server.get

    response, body = get("/ranking.html")

    assert response.status == 200
    assert "text/html" in response.getheader("Content-Type")
    assert b"trading-value-ranking" in body


def test_get_unknown_path_returns_404(running_server):
    get = running_server.get

    response, _ = get("/does-not-exist")

    assert response.status == 404


def test_get_api_results_returns_empty_list_when_no_results_dir(running_server):
    get = running_server.get

    response, body = get("/api/results")

    assert response.status == 200
    assert json.loads(body) == []


def test_get_api_results_lists_saved_files(running_server):
    get = running_server.get
    results_dir = running_server.results_dir
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "ma_crossover_20260720_143000.csv"), "w", encoding="utf-8") as f:
        f.write("stock_code,total_return_pct\n005930,12.5\n")

    response, body = get("/api/results")

    payload = json.loads(body)
    assert len(payload) == 1
    assert payload[0]["filename"] == "ma_crossover_20260720_143000.csv"


def test_get_api_results_detail_returns_parsed_rows(running_server):
    get = running_server.get
    results_dir = running_server.results_dir
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "ma_crossover_20260720_143000.csv"), "w", encoding="utf-8") as f:
        f.write("stock_code,total_return_pct\n005930,12.5\n")

    response, body = get("/api/results/ma_crossover_20260720_143000.csv")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["columns"] == ["stock_code", "total_return_pct"]
    assert payload["rows"] == [{"stock_code": "005930", "total_return_pct": "12.5"}]


def test_get_api_results_detail_returns_404_for_unknown_file(running_server):
    get = running_server.get

    response, _ = get("/api/results/does-not-exist.csv")

    assert response.status == 404


def test_post_top35_update_starts_job(running_server, monkeypatch):
    get = running_server.get
    post = running_server.post
    monkeypatch.setattr(top35_job, "update_top35", lambda client, data_dir, market, on_progress=None: pd.DataFrame([{"stock_code": "005930", "name": "삼성전자", "status": "ok"}]))

    response, body = post("/api/top35-update")

    assert response.status == 200
    assert json.loads(body) == {"started": True}


def test_post_top35_update_returns_409_when_already_running(running_server, monkeypatch):
    get = running_server.get
    post = running_server.post
    release = threading.Event()

    def blocking_update_top35(client, data_dir, market, on_progress=None):
        release.wait(timeout=2.0)
        return pd.DataFrame([{"stock_code": "005930", "name": "삼성전자", "status": "ok"}])

    monkeypatch.setattr(top35_job, "update_top35", blocking_update_top35)

    first, _ = post("/api/top35-update")
    assert first.status == 200

    deadline = time.time() + 2.0
    while time.time() < deadline and top35_job.get_status()["status"] != "running":
        time.sleep(0.01)

    second, second_body = post("/api/top35-update")

    assert second.status == 409
    assert json.loads(second_body)["started"] is False
    release.set()


def test_get_top35_status_returns_current_state(running_server):
    get = running_server.get

    response, body = get("/api/top35-status")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["status"] == "idle"


# ---- Cycle #2: orders / pnl-history / kill-switch ----

def test_get_api_orders_returns_empty_list_when_no_file(running_server):
    response, body = running_server.get("/api/orders")

    assert response.status == 200
    assert json.loads(body) == []


def test_get_api_orders_returns_recorded_orders(running_server):
    with open(running_server.orders_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"side": "buy", "code": "005930", "quantity": 28, "price": 70000.0, "reason": "entry", "order_time": "2026-07-20T09:31:00"}) + "\n")

    response, body = running_server.get("/api/orders")

    assert response.status == 200
    payload = json.loads(body)
    assert len(payload) == 1
    assert payload[0]["code"] == "005930"


def test_get_api_pnl_history_returns_empty_list_when_no_file(running_server):
    response, body = running_server.get("/api/pnl-history")

    assert response.status == 200
    assert json.loads(body) == []


def test_get_api_pnl_history_returns_sorted_entries(running_server):
    with open(running_server.pnl_history_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"date": "2026-07-19", "realized_pnl_krw": -12000.0}) + "\n")
        f.write(json.dumps({"date": "2026-07-18", "realized_pnl_krw": 35000.0}) + "\n")

    response, body = running_server.get("/api/pnl-history")

    payload = json.loads(body)
    assert [e["date"] for e in payload] == ["2026-07-18", "2026-07-19"]


def test_get_kill_switch_status_defaults_to_not_requested(running_server):
    response, body = running_server.get("/api/kill-switch/status")

    assert response.status == 200
    assert json.loads(body) == {"requested": False, "requested_at": None}


def test_post_kill_switch_activate_sets_requested_true(running_server):
    response, body = running_server.post("/api/kill-switch/activate")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["requested"] is True

    status_response, status_body = running_server.get("/api/kill-switch/status")
    assert json.loads(status_body)["requested"] is True


def test_post_kill_switch_clear_sets_requested_false(running_server):
    running_server.post("/api/kill-switch/activate")

    response, body = running_server.post("/api/kill-switch/clear")

    assert response.status == 200
    assert json.loads(body)["requested"] is False


def test_get_api_config_returns_empty_object_when_no_file(running_server):
    response, body = running_server.get("/api/config")

    assert response.status == 200
    assert json.loads(body) == {}


def test_get_api_config_returns_strategy_run_parameters(running_server):
    config_path = os.path.join(running_server.strategy_dir, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({"strategy": "strategy_1", "top_n": 35, "proba_threshold": 0.6, "is_mock": True}, f)

    response, body = running_server.get("/api/config")

    assert response.status == 200
    assert json.loads(body) == {"strategy": "strategy_1", "top_n": 35, "proba_threshold": 0.6, "is_mock": True}


def test_get_api_market_snapshot_returns_index_data(running_server, monkeypatch):
    from backtesting import dashboard_server

    monkeypatch.setattr(
        dashboard_server, "get_market_snapshot",
        lambda appkey, secretkey, is_mock: {
            "kospi": {"value": 2650.0, "change_pct": 1.2},
            "kosdaq": {"value": 850.0, "change_pct": -0.5},
            "nasdaq": {"value": 18200.0, "change_pct": 0.8},
        },
    )

    response, body = running_server.get("/api/market-snapshot")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["kospi"]["value"] == 2650.0
    assert payload["nasdaq"]["change_pct"] == 0.8


def test_get_api_account_snapshot_returns_deposit_and_holdings(running_server, monkeypatch):
    from backtesting import dashboard_server

    monkeypatch.setattr(
        dashboard_server, "get_account_snapshot",
        lambda appkey, secretkey, is_mock: {
            "deposit": {"deposit_krw": 10_000_000, "order_available_krw": 9_725_300,
                        "withdrawable_krw": 9_917_875, "d2_deposit_krw": 9_725_300},
            "holdings": [{"code": "005930", "name": "삼성전자", "quantity": 1, "avg_price": 273750,
                          "current_price": 273750, "eval_amount": 271304, "pl_amount": -2446, "pl_pct": -0.8935}],
        },
    )

    response, body = running_server.get("/api/account-snapshot")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["deposit"]["deposit_krw"] == 10_000_000
    assert payload["holdings"][0]["code"] == "005930"


def test_get_api_trading_value_ranking_defaults_to_extended_window(running_server, monkeypatch):
    from backtesting import dashboard_server

    captured = {}
    monkeypatch.setattr(
        dashboard_server, "get_trading_value_ranking",
        lambda appkey, secretkey, is_mock, window: captured.update(window=window) or {
            "rows": [{"stock_code": "005930", "name": "삼성전자", "rank": 1, "trading_value": 1000}],
            "as_of": "10:00:00", "active": True,
        },
    )

    response, body = running_server.get("/api/trading-value-ranking")

    assert response.status == 200
    assert captured["window"] == "extended"
    payload = json.loads(body)
    assert payload["rows"][0]["stock_code"] == "005930"
    assert payload["active"] is True


def test_get_api_trading_value_ranking_accepts_extended_window(running_server, monkeypatch):
    from backtesting import dashboard_server

    captured = {}
    monkeypatch.setattr(
        dashboard_server, "get_trading_value_ranking",
        lambda appkey, secretkey, is_mock, window: captured.update(window=window) or {"rows": [], "as_of": None, "active": False},
    )

    response, _ = running_server.get("/api/trading-value-ranking?window=extended")

    assert response.status == 200
    assert captured["window"] == "extended"


def test_get_api_trading_value_ranking_accepts_regular_window(running_server, monkeypatch):
    from backtesting import dashboard_server

    captured = {}
    monkeypatch.setattr(
        dashboard_server, "get_trading_value_ranking",
        lambda appkey, secretkey, is_mock, window: captured.update(window=window) or {"rows": [], "as_of": None, "active": False},
    )

    response, _ = running_server.get("/api/trading-value-ranking?window=regular")

    assert response.status == 200
    assert captured["window"] == "regular"


def test_get_api_trading_value_ranking_rejects_unknown_window(running_server):
    response, body = running_server.get("/api/trading-value-ranking?window=bogus")

    assert response.status == 400
    assert "error" in json.loads(body)


def test_post_sell_all_starts_job(running_server, monkeypatch):
    monkeypatch.setattr(
        sell_all_job, "KiwoomClient",
        lambda appkey, secretkey, is_mock: SimpleNamespace(
            get_account_evaluation=lambda: {"stk_acnt_evlt_prst": [], "return_code": 0},
        ),
    )

    response, body = running_server.post("/api/sell-all")

    assert response.status == 200
    assert json.loads(body) == {"started": True}


def test_post_sell_all_returns_409_when_already_running(running_server, monkeypatch):
    release = threading.Event()

    def blocking_get_account_evaluation():
        release.wait(timeout=2.0)
        return {"stk_acnt_evlt_prst": [], "return_code": 0}

    monkeypatch.setattr(
        sell_all_job, "KiwoomClient",
        lambda appkey, secretkey, is_mock: SimpleNamespace(get_account_evaluation=blocking_get_account_evaluation),
    )

    first, _ = running_server.post("/api/sell-all")
    assert first.status == 200

    deadline = time.time() + 2.0
    while time.time() < deadline and sell_all_job.get_status()["status"] != "running":
        time.sleep(0.01)

    second, second_body = running_server.post("/api/sell-all")

    assert second.status == 409
    assert json.loads(second_body)["started"] is False
    release.set()


def test_get_sell_all_status_returns_current_state(running_server):
    response, body = running_server.get("/api/sell-all-status")

    assert response.status == 200
    assert json.loads(body)["status"] == "idle"


def test_post_sell_places_order_for_given_code_and_quantity(running_server, monkeypatch):
    from backtesting import dashboard_server

    monkeypatch.setattr(
        dashboard_server, "sell_order",
        SimpleNamespace(sell_one=lambda appkey, secretkey, is_mock, code, quantity: {
            "return_code": 0, "return_msg": "모의투자 매도주문완료",
        }),
    )

    response, body = running_server.post("/api/sell?code=005930&quantity=3")

    assert response.status == 200
    assert json.loads(body) == {"ok": True, "message": "모의투자 매도주문완료"}


def test_post_sell_returns_502_when_order_rejected(running_server, monkeypatch):
    from backtesting import dashboard_server

    monkeypatch.setattr(
        dashboard_server, "sell_order",
        SimpleNamespace(sell_one=lambda appkey, secretkey, is_mock, code, quantity: {
            "return_code": 5, "return_msg": "주문 거부",
        }),
    )

    response, body = running_server.post("/api/sell?code=005930&quantity=3")

    assert response.status == 502
    assert json.loads(body) == {"ok": False, "message": "주문 거부"}


def test_post_sell_returns_400_when_quantity_missing(running_server):
    response, body = running_server.post("/api/sell?code=005930")

    assert response.status == 400
    assert json.loads(body)["ok"] is False


def test_post_sell_returns_403_and_skips_order_when_risk_manager_rejects(running_server, monkeypatch):
    from backtesting import dashboard_server, risk_manager

    sell_one_called = []
    monkeypatch.setattr(
        dashboard_server, "sell_order",
        SimpleNamespace(sell_one=lambda *a, **k: sell_one_called.append(1) or {"return_code": 0, "return_msg": "ok"}),
    )
    monkeypatch.setattr(
        dashboard_server.risk_manager, "check_order",
        lambda order, portfolio, **kwargs: risk_manager.RiskDecision(
            approved=False, reason="테스트 거부", rule_id="test_rule",
        ),
    )

    response, body = running_server.post("/api/sell?code=005930&quantity=3")

    assert response.status == 403
    assert json.loads(body) == {"ok": False, "message": "테스트 거부"}
    assert sell_one_called == []


def test_post_sell_all_returns_403_and_skips_job_when_risk_manager_rejects(running_server, monkeypatch):
    from backtesting import dashboard_server, risk_manager

    monkeypatch.setattr(
        dashboard_server.risk_manager, "check_order",
        lambda order, portfolio, **kwargs: risk_manager.RiskDecision(
            approved=False, reason="테스트 거부", rule_id="test_rule",
        ),
    )

    response, body = running_server.post("/api/sell-all")

    assert response.status == 403
    assert json.loads(body) == {"started": False, "reason": "테스트 거부"}
    assert sell_all_job.get_status()["status"] == "idle"


def test_get_api_strategy_info_returns_rules_for_known_strategy(running_server):
    response, body = running_server.get("/api/strategy-info?strategy=strategy_1")

    assert response.status == 200
    payload = json.loads(body)
    assert set(payload.keys()) == {"entry", "exit", "operation", "exchange_basis"}
    assert len(payload["entry"]) > 0


def test_get_api_strategy_info_returns_empty_object_for_unknown_strategy(running_server):
    response, body = running_server.get("/api/strategy-info?strategy=strategy_99")

    assert response.status == 200
    assert json.loads(body) == {}


# ---- Multi-strategy selection ----

def test_get_api_strategies_lists_subfolders_and_defaults_selection(running_server):
    response, body = running_server.get("/api/strategies")

    assert response.status == 200
    payload = json.loads(body)
    # heartbeat 파일이 없으니(run-trading을 아직 시작 안 함) running은 False
    assert payload == {"strategies": ["strategy_1"], "selected": "strategy_1", "running": {"strategy_1": False}}


def test_get_api_strategies_reports_running_false_when_stop_requested_even_with_fresh_heartbeat(running_server):
    # "중지" 버튼을 눌러 루프가 막 종료됐을 때, 마지막 하트비트는 아직 신선한 상태로
    # 남아있다 — stop_requested.json이 있으면 하트비트 나이와 무관하게 False여야 한다.
    strategy_dir = running_server.strategy_dir
    with open(os.path.join(strategy_dir, "heartbeat.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time()}, f)
    with open(os.path.join(strategy_dir, "stop_requested.json"), "w", encoding="utf-8") as f:
        f.write("{}")

    response, body = running_server.get("/api/strategies")

    payload = json.loads(body)
    assert payload["running"] == {"strategy_1": False}


def test_get_api_strategies_reports_running_true_with_fresh_heartbeat(running_server):
    strategy_dir = running_server.strategy_dir
    with open(os.path.join(strategy_dir, "heartbeat.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time()}, f)

    response, body = running_server.get("/api/strategies")

    payload = json.loads(body)
    assert payload["running"] == {"strategy_1": True}


def test_get_api_strategies_reports_running_false_with_stale_heartbeat(running_server):
    strategy_dir = running_server.strategy_dir
    with open(os.path.join(strategy_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"interval_seconds": 1.0}, f)
    with open(os.path.join(strategy_dir, "heartbeat.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time() - 120}, f)  # interval_seconds*3=3초보다 훨씬 지남

    response, body = running_server.get("/api/strategies")

    payload = json.loads(body)
    assert payload["running"] == {"strategy_1": False}


def test_get_api_strategies_excludes_nasdaq_drop_monitor_folder(running_server):
    # nasdaq_drop_monitor는 같은 state/ 루트를 쓰지만 strategy_catalog에 등록된
    # 매매 전략이 아니다 — 전략 드롭다운/상태 배지에 섞여 나오면 안 된다.
    nasdaq_dir = os.path.join(running_server.state_root, "nasdaq_drop_monitor")
    os.makedirs(nasdaq_dir, exist_ok=True)
    with open(os.path.join(nasdaq_dir, "heartbeat.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time()}, f)

    response, body = running_server.get("/api/strategies")

    payload = json.loads(body)
    assert payload["strategies"] == ["strategy_1"]
    assert "nasdaq_drop_monitor" not in payload["running"]


def test_get_api_strategies_excludes_dashboard_monitor_folder(running_server):
    # dashboard_monitor도 nasdaq_drop_monitor와 같은 이유로 매매 전략이 아니다 —
    # 전략 드롭다운/상태 배지에 섞여 나오면 안 된다.
    monitor_dir = os.path.join(running_server.state_root, "dashboard_monitor")
    os.makedirs(monitor_dir, exist_ok=True)
    with open(os.path.join(monitor_dir, "heartbeat.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time()}, f)

    response, body = running_server.get("/api/strategies")

    payload = json.loads(body)
    assert payload["strategies"] == ["strategy_1"]
    assert "dashboard_monitor" not in payload["running"]


# ---- 나스닥 급락 감시 상태 ----

def test_get_nasdaq_drop_monitor_status_returns_false_when_no_heartbeat(running_server):
    response, body = running_server.get("/api/nasdaq-drop-monitor-status")

    assert response.status == 200
    assert json.loads(body) == {"running": False}


def test_get_nasdaq_drop_monitor_status_returns_true_with_fresh_heartbeat(running_server):
    nasdaq_dir = os.path.join(running_server.state_root, "nasdaq_drop_monitor")
    os.makedirs(nasdaq_dir, exist_ok=True)
    with open(os.path.join(nasdaq_dir, "heartbeat.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time()}, f)

    response, body = running_server.get("/api/nasdaq-drop-monitor-status")

    assert json.loads(body) == {"running": True}


def test_get_nasdaq_drop_monitor_status_returns_false_when_stop_requested(running_server):
    nasdaq_dir = os.path.join(running_server.state_root, "nasdaq_drop_monitor")
    os.makedirs(nasdaq_dir, exist_ok=True)
    with open(os.path.join(nasdaq_dir, "heartbeat.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time()}, f)
    with open(os.path.join(nasdaq_dir, "stop_requested.json"), "w", encoding="utf-8") as f:
        f.write("{}")

    response, body = running_server.get("/api/nasdaq-drop-monitor-status")

    assert json.loads(body) == {"running": False}


# ---- 대시보드 감시 상태 ----

def test_get_dashboard_monitor_status_returns_false_when_no_heartbeat(running_server):
    response, body = running_server.get("/api/dashboard-monitor-status")

    assert response.status == 200
    assert json.loads(body) == {"running": False}


def test_get_dashboard_monitor_status_returns_true_with_fresh_heartbeat(running_server):
    monitor_dir = os.path.join(running_server.state_root, "dashboard_monitor")
    os.makedirs(monitor_dir, exist_ok=True)
    with open(os.path.join(monitor_dir, "heartbeat.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time()}, f)

    response, body = running_server.get("/api/dashboard-monitor-status")

    assert json.loads(body) == {"running": True}


def test_get_dashboard_monitor_status_returns_false_when_stop_requested(running_server):
    monitor_dir = os.path.join(running_server.state_root, "dashboard_monitor")
    os.makedirs(monitor_dir, exist_ok=True)
    with open(os.path.join(monitor_dir, "heartbeat.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time()}, f)
    with open(os.path.join(monitor_dir, "stop_requested.json"), "w", encoding="utf-8") as f:
        f.write("{}")

    response, body = running_server.get("/api/dashboard-monitor-status")

    assert json.loads(body) == {"running": False}


def test_get_api_strategies_returns_empty_list_and_fallback_selected_when_no_folders(tmp_path):
    from backtesting.dashboard_server import build_dashboard_server

    server = build_dashboard_server(state_root=str(tmp_path / "state"), results_dir=str(tmp_path / "results"), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/api/strategies")
    response = conn.getresponse()
    body = response.read()
    conn.close()

    server.shutdown()
    server.server_close()
    thread.join(timeout=5)

    assert response.status == 200
    payload = json.loads(body)
    assert payload == {"strategies": [], "selected": "strategy_1", "running": {}}


def test_get_api_state_shares_account_wide_risk_state_across_strategies(tmp_path):
    """risk_state.json은 계좌 전체가 공유하는 단일 파일이라(risk-agent.md 계좌
    단일화, 2026-08-29) ?strategy=strategy_1/strategy_2 어느 쪽으로 물어도 같은
    포지션/손익을 봐야 한다 — 전략별 폴더 밑에 있는 risk_state.json은(레거시든
    실수든) 무시되고 절대 읽히지 않는다."""
    from backtesting.dashboard_server import build_dashboard_server

    state_root = str(tmp_path / "state")
    os.makedirs(os.path.join(state_root, "strategy_1"))
    os.makedirs(os.path.join(state_root, "strategy_2"))
    with open(os.path.join(state_root, "risk_state.json"), "w", encoding="utf-8") as f:
        json.dump({"trading_date": "2026-07-20", "realized_pnl_krw": 1000.0, "kill_switch_active": False, "open_positions": []}, f)
    # 전략별 폴더 밑에 남아있는 risk_state.json(레거시/실수)은 무시돼야 한다.
    with open(os.path.join(state_root, "strategy_2", "risk_state.json"), "w", encoding="utf-8") as f:
        json.dump({"trading_date": "2026-07-20", "realized_pnl_krw": -2000.0, "kill_switch_active": False, "open_positions": []}, f)

    server = build_dashboard_server(state_root=state_root, results_dir=str(tmp_path / "results"), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def get(path):
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response, body

    _, body1 = get("/api/state?strategy=strategy_1")
    _, body2 = get("/api/state?strategy=strategy_2")

    server.shutdown()
    server.server_close()
    thread.join(timeout=5)

    assert json.loads(body1)["realized_pnl_krw"] == 1000.0
    assert json.loads(body2)["realized_pnl_krw"] == 1000.0


# ---- build_strategy_command ----

def test_build_strategy_command_uses_run_trading_for_strategy_1_with_config_flags():
    from backtesting.dashboard_server import build_strategy_command

    command = build_strategy_command("strategy_1", {"top_n": 35, "interval_seconds": 1.0})

    assert command[1:5] == ["-m", "backtesting.cli", "run-trading", "--strategy"]
    assert "strategy_1" in command
    assert "--top-n" in command and "35" in command
    assert "--interval-seconds" in command and "1.0" in command


def test_build_strategy_command_omits_flags_not_present_in_config():
    from backtesting.dashboard_server import build_strategy_command

    command = build_strategy_command("strategy_2", {"interval_seconds": 30.0})

    assert "--interval-seconds" in command
    assert "--top-n" not in command
    assert "--model-path" not in command


# ---- spawn_detached ----

def test_spawn_detached_uses_breakaway_flag_on_windows_when_available(monkeypatch, tmp_path):
    import backtesting.dashboard_server as dashboard_server_module
    from backtesting.dashboard_server import spawn_detached

    monkeypatch.setattr(dashboard_server_module.os, "name", "nt")
    captured = {}

    class _FakePopen:
        def __init__(self, command, **kwargs):
            captured["kwargs"] = kwargs

    monkeypatch.setattr(dashboard_server_module.subprocess, "Popen", _FakePopen)

    with open(tmp_path / "log.txt", "w", encoding="utf-8") as log_file:
        spawn_detached(["python", "-m", "x"], str(tmp_path), log_file)

    expected = dashboard_server_module.subprocess.CREATE_NEW_PROCESS_GROUP | dashboard_server_module.subprocess.CREATE_BREAKAWAY_FROM_JOB
    assert captured["kwargs"]["creationflags"] == expected


def test_spawn_detached_falls_back_without_breakaway_when_job_disallows_it(monkeypatch, tmp_path):
    # 실측 사고 재현: 대시보드를 관리하는 상위 프로세스의 잡 오브젝트가 breakaway를
    # 허용하지 않으면 CREATE_BREAKAWAY_FROM_JOB 플래그를 준 Popen 자체가 예외를 던진다
    # (조용히 무시되지 않음) — 이때 그 플래그 없이 재시도해야 시작 기능 자체가
    # 죽지 않는다.
    import backtesting.dashboard_server as dashboard_server_module
    from backtesting.dashboard_server import spawn_detached

    monkeypatch.setattr(dashboard_server_module.os, "name", "nt")
    calls = []

    class _FakePopen:
        def __init__(self, command, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise OSError("job object does not allow breakaway")

    monkeypatch.setattr(dashboard_server_module.subprocess, "Popen", _FakePopen)

    with open(tmp_path / "log.txt", "w", encoding="utf-8") as log_file:
        spawn_detached(["python", "-m", "x"], str(tmp_path), log_file)

    assert len(calls) == 2  # breakaway 시도 실패 후 재시도
    assert calls[1]["creationflags"] == dashboard_server_module.subprocess.CREATE_NEW_PROCESS_GROUP


# ---- POST /api/strategy/start, /api/strategy/stop ----

def test_post_api_strategy_start_spawns_subprocess_with_config_derived_command(running_server, monkeypatch):
    strategy_dir = running_server.strategy_dir
    with open(os.path.join(strategy_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"top_n": 35, "interval_seconds": 1.0}, f)

    captured = {}

    class _FakePopen:
        def __init__(self, command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs

    import backtesting.dashboard_server as dashboard_server_module
    monkeypatch.setattr(dashboard_server_module.subprocess, "Popen", _FakePopen)

    response, body = running_server.post("/api/strategy/start?strategy=strategy_1")

    assert response.status == 200
    assert json.loads(body) == {"started": True}
    assert "--interval-seconds" in captured["command"]
    assert captured["kwargs"]["cwd"] == dashboard_server_module.PROJECT_ROOT


def test_post_api_strategy_start_refuses_when_already_running(running_server, monkeypatch):
    strategy_dir = running_server.strategy_dir
    with open(os.path.join(strategy_dir, "heartbeat.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time()}, f)

    popen_calls = []
    import backtesting.dashboard_server as dashboard_server_module
    monkeypatch.setattr(dashboard_server_module.subprocess, "Popen", lambda *a, **k: popen_calls.append(1))

    response, body = running_server.post("/api/strategy/start?strategy=strategy_1")

    assert response.status == 409
    assert json.loads(body) == {"started": False, "reason": "이미 실행 중입니다"}
    assert popen_calls == []


# ---- CSRF: Origin header check on POST ----

def _post_with_origin(port: int, path: str, origin: str) -> tuple:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", path, headers={"Origin": origin})
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return response, body


def test_post_rejects_cross_origin_request(running_server):
    response, body = _post_with_origin(
        running_server.port, "/api/sell-all", "http://evil.example",
    )

    assert response.status == 403
    assert json.loads(body)["ok"] is False


def test_post_allows_same_origin_request(running_server):
    response, body = _post_with_origin(
        running_server.port, "/api/sell-all", f"http://127.0.0.1:{running_server.port}",
    )

    assert response.status != 403


def test_post_api_strategy_stop_writes_stop_flag_file(running_server):
    strategy_dir = running_server.strategy_dir
    stop_flag_path = os.path.join(strategy_dir, "stop_requested.json")
    assert not os.path.exists(stop_flag_path)

    response, body = running_server.post("/api/strategy/stop?strategy=strategy_1")

    assert response.status == 200
    assert json.loads(body) == {"stopped": True}
    assert os.path.exists(stop_flag_path)


def test_origin_trust_follows_host_header_for_each_bound_address():
    # 쉼표 다중 바인딩: 어느 주소로 들어와도 자기 Host 와 같은 Origin 만 통과, 위조는 거부(네트워크·주문 없음)
    from types import SimpleNamespace
    from backtesting.dashboard_server import DashboardRequestHandler

    def trusted(host, origin):
        h = SimpleNamespace(headers={"Host": host, "Origin": origin})
        return DashboardRequestHandler._origin_is_trusted(h)

    for host in ("127.0.0.1:8765", "100.126.113.127:8765"):
        assert trusted(host, f"http://{host}")
        assert not trusted(host, "http://evil.example")


def test_run_dashboard_server_extra_host_failure_keeps_primary_serving(monkeypatch, capsys):
    # 첫 주소(127.0.0.1)는 뜨고, 못 잡는 두 번째 주소는 경고만 남기고 죽지 않는다
    import time
    from backtesting import dashboard_server as ds

    real = ds.build_dashboard_server
    built = []

    def fake(*a, host="", **k):
        if host == "203.0.113.9":  # 이 PC 에 없는 주소 → OSError
            built.append(host)
            raise OSError("cannot assign")
        return real(*a, host=host, **k)

    monkeypatch.setattr(ds, "build_dashboard_server", fake)
    monkeypatch.setattr(ds.threading.Event, "wait", lambda self, t=None: self.set())  # 60초 대기 생략
    monkeypatch.setattr(ds.ThreadingHTTPServer, "serve_forever", lambda self, *a: time.sleep(0.3))  # 추가 스레드가 돌 시간
    ds.run_dashboard_server(port=0, host="127.0.0.1,203.0.113.9")
    assert built and "바인딩 실패" in capsys.readouterr().out
