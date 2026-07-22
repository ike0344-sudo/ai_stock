from kiwoom_client import KiwoomClient


def test_throttle_does_not_sleep_on_first_call(monkeypatch):
    sleeps = []
    monkeypatch.setattr("kiwoom_client.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("kiwoom_client.time.monotonic", lambda: 100.0)

    client = KiwoomClient("key", "secret", min_request_interval=0.5)
    client._throttle()

    assert sleeps == []


def test_throttle_sleeps_when_called_too_soon(monkeypatch):
    sleeps = []
    times = iter([100.0, 100.1])  # 두 번째 호출이 0.1초 뒤 -> 0.4초 대기해야 함
    monkeypatch.setattr("kiwoom_client.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("kiwoom_client.time.monotonic", lambda: next(times))

    client = KiwoomClient("key", "secret", min_request_interval=0.5)
    client._throttle()
    client._throttle()

    assert len(sleeps) == 1
    assert sleeps[0] == 100.5 - 100.1


def test_throttle_does_not_sleep_when_enough_time_passed(monkeypatch):
    sleeps = []
    times = iter([100.0, 101.0])  # 1초 뒤 -> min_request_interval(0.5s) 넘었으니 대기 불필요
    monkeypatch.setattr("kiwoom_client.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("kiwoom_client.time.monotonic", lambda: next(times))

    client = KiwoomClient("key", "secret", min_request_interval=0.5)
    client._throttle()
    client._throttle()

    assert sleeps == []


def _client_with_stub_request(monkeypatch, pages_by_call: list[dict], cont_yns: list[str]):
    """request_tr을 스텁으로 대체해 실제 네트워크 없이 페이지네이션 로직만 검증."""
    client = KiwoomClient("key", "secret")
    calls = []

    def fake_request_tr(api_id, body, path="/api/dostk/chart", cont_yn="N", next_key=""):
        i = len(calls)
        calls.append({"api_id": api_id, "body": body, "path": path, "cont_yn": cont_yn, "next_key": next_key})
        client.last_cont_yn = cont_yns[i]
        client.last_next_key = f"key{i}" if cont_yns[i] == "Y" else ""
        return pages_by_call[i]

    monkeypatch.setattr(client, "request_tr", fake_request_tr)
    return client, calls


def test_paginate_stops_when_cont_yn_not_y(monkeypatch):
    client, calls = _client_with_stub_request(
        monkeypatch, pages_by_call=[{"p": 1}, {"p": 2}], cont_yns=["Y", "N"]
    )

    pages = client._paginate("ka99999", {"a": 1}, path="/api/dostk/chart", max_pages=10)

    assert len(pages) == 2
    assert calls[0]["cont_yn"] == "N" and calls[0]["next_key"] == ""
    assert calls[1]["cont_yn"] == "Y" and calls[1]["next_key"] == "key0"


def test_paginate_stops_at_max_pages_even_if_cont_yn_still_y(monkeypatch):
    client, calls = _client_with_stub_request(
        monkeypatch, pages_by_call=[{"p": 1}, {"p": 2}, {"p": 3}], cont_yns=["Y", "Y", "Y"]
    )

    pages = client._paginate("ka99999", {"a": 1}, path="/api/dostk/chart", max_pages=2)

    assert len(pages) == 2


def test_get_daily_chart_pages_uses_ka10081(monkeypatch):
    client, calls = _client_with_stub_request(monkeypatch, pages_by_call=[{"p": 1}], cont_yns=["N"])

    client.get_daily_chart_pages("005930", base_date="20260716", max_pages=5)

    assert calls[0]["api_id"] == "ka10081"
    assert calls[0]["body"] == {"stk_cd": "005930", "base_dt": "20260716", "upd_stkpc_tp": "1"}


def test_get_stock_list_returns_list_field(monkeypatch):
    client = KiwoomClient("key", "secret")
    monkeypatch.setattr(
        client, "request_tr",
        lambda api_id, body, path="/api/dostk/chart", cont_yn="N", next_key="": {"list": [{"code": "005930"}]},
    )

    result = client.get_stock_list("0")

    assert result == [{"code": "005930"}]


def test_get_index_daily_chart_uses_inds_cd(monkeypatch):
    client = KiwoomClient("key", "secret")
    captured = {}

    def fake_request_tr(api_id, body, path="/api/dostk/chart", cont_yn="N", next_key=""):
        captured.update(api_id=api_id, body=body)
        return {}

    monkeypatch.setattr(client, "request_tr", fake_request_tr)

    client.get_index_daily_chart("001", base_date="20260716")

    assert captured["api_id"] == "ka20006"
    assert captured["body"] == {"inds_cd": "001", "base_dt": "20260716"}


def test_get_stock_quote_uses_ka10004_and_mrkcond_path(monkeypatch):
    client = KiwoomClient("key", "secret")
    captured = {}

    def fake_request_tr(api_id, body, path="/api/dostk/chart", cont_yn="N", next_key=""):
        captured.update(api_id=api_id, body=body, path=path)
        # 실계좌 ka10004 호출로 확인한 실제 필드명: 최우선호가는 sel_fpr_bid/buy_fpr_bid이며
        # "-255000"처럼 전일종가 대비 방향 부호가 붙는다(sel_1bid 같은 필드는 존재하지 않음).
        return {"sel_fpr_bid": "-70100", "buy_fpr_bid": "-70000"}

    monkeypatch.setattr(client, "request_tr", fake_request_tr)

    result = client.get_stock_quote("005930")

    assert captured["api_id"] == "ka10004"
    assert captured["body"] == {"stk_cd": "005930"}
    assert captured["path"] == "/api/dostk/mrkcond"
    assert result == {"sel_fpr_bid": "-70100", "buy_fpr_bid": "-70000"}


def test_get_index_minute_chart_pages_uses_ka20005(monkeypatch):
    client, calls = _client_with_stub_request(monkeypatch, pages_by_call=[{"p": 1}], cont_yns=["N"])

    client.get_index_minute_chart_pages("101", tic_scope="1", max_pages=3)

    assert calls[0]["api_id"] == "ka20005"
    assert calls[0]["body"] == {"inds_cd": "101", "tic_scope": "1"}


def _capture_request_tr(client, monkeypatch, response=None):
    captured = {}

    def fake_request_tr(api_id, body, path="/api/dostk/chart", cont_yn="N", next_key=""):
        captured.update(api_id=api_id, body=body, path=path)
        return response if response is not None else {}

    monkeypatch.setattr(client, "request_tr", fake_request_tr)
    return captured


def test_place_order_buy_uses_kt10000_and_ordr_path(monkeypatch):
    client = KiwoomClient("key", "secret")
    captured = _capture_request_tr(client, monkeypatch, {"ord_no": "0000123", "return_code": 0})

    result = client.place_order("005930", side="buy", quantity=10)

    assert captured["api_id"] == "kt10000"
    assert captured["path"] == "/api/dostk/ordr"
    assert captured["body"] == {
        "dmst_stex_tp": "KRX", "stk_cd": "005930", "ord_qty": "10",
        "ord_uv": "", "trde_tp": "3", "cond_uv": "",
    }
    assert result["ord_no"] == "0000123"


def test_place_order_sell_uses_kt10001(monkeypatch):
    client = KiwoomClient("key", "secret")
    captured = _capture_request_tr(client, monkeypatch)

    client.place_order("005930", side="sell", quantity=5)

    assert captured["api_id"] == "kt10001"


def test_place_order_limit_price_sets_ord_uv(monkeypatch):
    client = KiwoomClient("key", "secret")
    captured = _capture_request_tr(client, monkeypatch)

    client.place_order("005930", side="buy", quantity=1, price=70000, order_type="0")

    assert captured["body"]["ord_uv"] == "70000"
    assert captured["body"]["trde_tp"] == "0"


def test_place_order_market_order_ignores_price(monkeypatch):
    client = KiwoomClient("key", "secret")
    captured = _capture_request_tr(client, monkeypatch)

    client.place_order("005930", side="buy", quantity=1, price=70000, order_type="3")

    assert captured["body"]["ord_uv"] == ""


def test_cancel_order_uses_kt10003(monkeypatch):
    client = KiwoomClient("key", "secret")
    captured = _capture_request_tr(client, monkeypatch)

    client.cancel_order("0000123", "005930", quantity=10)

    assert captured["api_id"] == "kt10003"
    assert captured["path"] == "/api/dostk/ordr"
    assert captured["body"] == {
        "dmst_stex_tp": "KRX", "orig_ord_no": "0000123", "stk_cd": "005930", "cncl_qty": "10",
    }


def test_get_pending_orders_without_stock_code_queries_all(monkeypatch):
    client = KiwoomClient("key", "secret")
    captured = _capture_request_tr(client, monkeypatch, {"oso": []})

    client.get_pending_orders()

    assert captured["api_id"] == "ka10075"
    assert captured["path"] == "/api/dostk/acnt"
    assert captured["body"] == {"all_stk_tp": "0", "trde_tp": "0", "stex_tp": "0"}
    assert "stk_cd" not in captured["body"]


def test_get_pending_orders_with_stock_code_scopes_to_one_stock(monkeypatch):
    client = KiwoomClient("key", "secret")
    captured = _capture_request_tr(client, monkeypatch)

    client.get_pending_orders(stock_code="005930")

    assert captured["body"]["all_stk_tp"] == "1"
    assert captured["body"]["stk_cd"] == "005930"


def test_get_positions_uses_kt00005_and_acnt_path(monkeypatch):
    client = KiwoomClient("key", "secret")
    captured = _capture_request_tr(client, monkeypatch, {"stk_cntr_remn": []})

    result = client.get_positions()

    assert captured["api_id"] == "kt00005"
    assert captured["path"] == "/api/dostk/acnt"
    assert captured["body"] == {"dmst_stex_tp": "KRX"}
    assert result == {"stk_cntr_remn": []}


def test_get_deposit_detail_uses_kt00001_and_acnt_path(monkeypatch):
    client = KiwoomClient("key", "secret")
    captured = _capture_request_tr(client, monkeypatch, {"entr": "000000010000000", "return_code": 0})

    result = client.get_deposit_detail()

    assert captured["api_id"] == "kt00001"
    assert captured["path"] == "/api/dostk/acnt"
    assert captured["body"] == {"qry_tp": "3"}
    assert result == {"entr": "000000010000000", "return_code": 0}


def test_get_account_evaluation_uses_kt00004_and_acnt_path(monkeypatch):
    client = KiwoomClient("key", "secret")
    captured = _capture_request_tr(client, monkeypatch, {"stk_acnt_evlt_prst": [], "return_code": 0})

    result = client.get_account_evaluation()

    assert captured["api_id"] == "kt00004"
    assert captured["path"] == "/api/dostk/acnt"
    assert captured["body"] == {"qry_tp": "0", "dmst_stex_tp": "KRX"}
    assert result == {"stk_acnt_evlt_prst": [], "return_code": 0}
