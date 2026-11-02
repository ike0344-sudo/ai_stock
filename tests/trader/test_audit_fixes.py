"""10-23 데스크 점검에서 고친 것 — 날 넘긴 가상 주문·익절, 추가 매수 익절 다시 걸기, 첫 시장가 매수 청산 규칙, 규칙 이름 바꿈."""
from datetime import date

from trader import desk as d


def _k(monkeypatch):
    k = object.__new__(d.Desk)
    k.rules = {"safety": {"paper": True}, "manual_exit": "x1", "rules": []}
    monkeypatch.setattr(d, "_write", lambda *a: None)
    return k


def test_new_day_drops_old_paper_orders_and_reopens_unfilled_takes(monkeypatch):
    k = _k(monkeypatch)
    k._mode, k.day = True, {"date": "2026-10-22"}
    md = date.today().strftime("%m%d")
    k.paper_state = {"orders": [{"ord_no": "P102200001"}, {"ord_no": f"P{md}00002"}]}
    k.meta = {"A": {"takes_done": [0, 1, 2], "takes_filled": [0]}}
    monkeypatch.setattr(d.daily_facts, "_facts", {"for": date.today(), "building": False})
    k._new_day()
    assert [o["ord_no"] for o in k.paper_state["orders"]] == [f"P{md}00002"]   # 어제 가상 주문은 장 끝나 사라짐(키움처럼)
    assert k.meta["A"]["takes_done"] == [0]                                    # 체결된 1차만 끝 — 2·3차는 오늘 다시 건다


def test_add_buy_after_partial_take_replaces_takes(monkeypatch):
    k = _k(monkeypatch)
    k.day = {"bought": {}}
    k.meta = {"A": {"init_qty": 100, "seen_qty": 50, "takes_done": [0], "take_sig": "s", "rule": "x1"}}   # 100주 중 50주 익절된 뒤
    k.holdings = [{"code": "A", "quantity": 90, "current_price": 1}]                                    # 40주 더 삼(90 < init 100)
    k._sync_meta()
    assert "take_sig" not in k.meta["A"] and k.meta["A"]["seen_qty"] == 90   # tick 이 옛 익절을 거두고 새로 건다


def test_first_market_buy_gets_rule_before_meta_is_made(monkeypatch):
    k = _k(monkeypatch)
    k.day, k.meta, k.holdings = {"bought": {}}, {}, []
    k.buy_block, k.buy_lev, k.snap = (lambda n, code=None: None), (lambda c: (1.0, "cash")), (lambda c: {"px": 1000})

    def submit(*a, **kw):                                  # 가상 시장가 — 보내는 중에 체결되고 보유 메타가 만들어진다
        k.holdings.append({"code": "A", "quantity": 10, "current_price": 1000})
        k._sync_meta()
        return {"ok": True}
    k._submit = submit
    k.buy("A", 10, 0, True)
    assert k.meta["A"]["rule"] == "x1"


def test_renamed_rule_still_owns_its_plan():
    rule = {"id": "r1", "name": "새 이름"}
    assert d.Desk._plan_of({"buy_rule": "r1", "tag": "옛 이름"}, rule)
    assert d.Desk._plan_of({"tag": "새 이름"}, rule) and not d.Desk._plan_of({"buy_rule": "r2", "tag": "새 이름"}, rule)
