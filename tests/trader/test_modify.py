"""매도 정정 — 가상 주문은 가격만 바뀌고, 새 가격에 닿으면 바로 체결된다. 호가 단위가 틀리면 거부."""
from trader import desk as d
from trader import feed


def test_paper_modify_reprices_and_fills(monkeypatch):
    k = object.__new__(d.Desk)
    k.paper_state = {"cash": 0.0, "start": 0.0, "hold": {"000001": {"qty": 10, "avg": 9000.0}}, "n": 1,
                     "orders": [{"ord_no": "P102300001", "code": "000001", "side": "sell", "qty": 10, "price": 10500, "market": False, "left": 10}]}
    notes, fills = [], []
    k.note, k.name, k.on_order, k._paper_account = (lambda t, *a: notes.append(t)), (lambda c: c), fills.append, (lambda: None)
    monkeypatch.setattr(d, "_write", lambda *a: None)
    monkeypatch.setitem(feed.quotes, "000001", {"px": 10000})
    assert not k.modify("P102300001", "000001", 10001)["ok"]                 # 1만 원대 호가는 5원(또는 10원) — 10,001 은 안 됨
    assert k.modify("P102300001", "000001", 10200)["ok"] and fills == []      # 아직 위 — 가격만 바뀜
    assert k.paper_state["orders"][0]["price"] == 10200
    assert k.modify("P102300001", "000001", 10000)["ok"]                      # 현재가로 내리면 체결
    assert fills and fills[0]["fill_px"] == 10000 and not k.paper_state["orders"] and "000001" not in k.paper_state["hold"]
    assert not k.modify("P102300001", "000001", 9990)["ok"]                   # 이미 체결된 주문


def test_paper_buy_modify_checks_cash(monkeypatch):
    k = object.__new__(d.Desk)
    k.paper_state = {"cash": 1_000_000.0, "start": 1_000_000.0, "hold": {}, "n": 1,
                     "orders": [{"ord_no": "P102300001", "code": "000001", "side": "buy", "qty": 90, "price": 10000, "market": False, "left": 90}]}
    fills = []
    k.note, k.name, k.on_order, k._paper_account = (lambda t, *a: None), (lambda c: c), fills.append, (lambda: None)
    k.buy_lev = lambda c: (1.0, "cash")
    monkeypatch.setattr(d, "_write", lambda *a: None)
    monkeypatch.setitem(feed.quotes, "000001", {"px": 10500})
    assert not k.modify("P102300001", "000001", 11500)["ok"]                  # 90 × 11,500 = 103.5만 > 100만
    assert k.modify("P102300001", "000001", 10500)["ok"] and fills[0]["fill_px"] == 10500   # 현재가로 올리면 체결


def test_rebuy_after_selling_uses_current_manual_rule(monkeypatch):
    """10-23 HT로보틱스: 다 팔고 다시 사면 그날 아침 청산 규칙이 다시 붙었다 — 지금 고른 규칙으로."""
    k = object.__new__(d.Desk)
    k.rules = {"manual_exit": "new10", "safety": {}}
    k.day = {"bought": {"396300": {"key": "manual", "rule": "old", "t": "09:00:00"}}}
    k.holdings = []
    k.buy_block, k.buy_lev = (lambda n, code=None: None), (lambda c: (1.0, "cash"))
    k._submit = lambda *a, **kw: (k.holdings.append({"code": "396300"}) or {"ok": True})   # 가상 시장가 — 보내자마자 보유
    k.snap = lambda c: {"px": 9000}
    monkeypatch.setattr(d, "_write", lambda *a: None)
    k.buy("396300", 10, 9000, True)
    assert k.day["bought"]["396300"]["rule"] == "new10"
    k.rules["manual_exit"] = "other"
    k.buy("396300", 10, 9000, True)                                            # 들고 있는 종목 추가 매수 — 그 자리 규칙 그대로
    assert k.day["bought"]["396300"]["rule"] == "new10"
