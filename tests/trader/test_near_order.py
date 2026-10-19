"""근접 발주 — 현재가가 단계 가격 near_pct% 위로 내려와야만 주문, 같은 날 두 번 안 낸다."""
from datetime import datetime

from trader import desk as d
from trader import feed


def _desk(monkeypatch, px):
    k = object.__new__(d.Desk)
    k.client, k.rules = object(), {"safety": {"near_pct": "1.5", "telegram": False}}
    k.plans = [{"id": "p1", "code": "000001", "name": "가", "active": True, "until": None, "placed_day": None,
                "ref_day": "20261014", "created": "2026-10-19T08:00:00", "tag": "t", "rule": None, "status": "대기",
                "stages": [{"pct": -3, "price": 9700, "qty": 10, "filled": 0}, {"pct": -5, "price": 9500, "qty": 10, "filled": 0}]}]
    k.bought = []
    k.buy = lambda code, qty, price, market, tag, rule=None: k.bought.append(price) or {"ok": True}
    k._is_trading_day = lambda _d: True
    monkeypatch.setattr(d, "_write", lambda *a: None)
    monkeypatch.setitem(feed.quotes, "000001", {"px": px})
    return k


def test_far_price_places_nothing(monkeypatch):
    k = _desk(monkeypatch, 10000)
    k._place_plans(datetime(2026, 10, 20, 9, 5))
    assert k.bought == [] and k.plans[0]["status"] == "감시 중"


def test_near_places_only_close_stage_once(monkeypatch):
    k = _desk(monkeypatch, 9800)                      # 9700×1.015=9845 안 · 9500×1.015=9642 밖
    now = datetime(2026, 10, 20, 9, 5)
    k._place_plans(now)
    k._place_plans(now)
    assert k.bought == [9700] and k.plans[0]["status"] == "주문 걸림 1/2"
    feed.quotes["000001"]["px"] = 9600
    k._place_plans(now)
    assert k.bought == [9700, 9500]


def test_ref_day_auto_from_ledger(monkeypatch, tmp_path):
    import json
    from datetime import date, timedelta
    p = tmp_path / "static" / "dashboard"
    p.mkdir(parents=True)
    recent, old = (date.today() - timedelta(days=3)).isoformat(), (date.today() - timedelta(days=60)).isoformat()
    (p / "value_ledger.json").write_text(json.dumps({"rows": [[old, "A"], [recent, "A"], [old, "B"]]}), encoding="utf-8")
    monkeypatch.setattr(d, "ROOT", tmp_path)
    monkeypatch.setattr(d.Desk, "_ledger", (0.0, {}))
    k = object.__new__(d.Desk)
    k.rules, k.ref_days = {"safety": {"auto_ref_days": "14"}}, {}
    assert k.ref_day("A") == recent.replace("-", "") and k.ref_src("A") == "신고대금"
    assert k.ref_day("B") is None and k.ref_src("B") == "직전"            # 60일 전 신고일은 너무 오래됨
    k.ref_days = {"A": "prev"}
    assert k.ref_day("A") is None
    k.ref_days = {"A": "20261001"}
    assert k.ref_day("A") == "20261001" and k.ref_src("A") == "직접"


def test_rule_ref_day_modes(monkeypatch):
    k = object.__new__(d.Desk)
    k.ref_days = {}
    monkeypatch.setattr(d.Desk, "ledger_day", lambda self, c: "20261016" if c == "A" else None)
    rule = lambda **L: {"ladder": {"on": True, **L}}
    assert k.rule_ref_day(rule(), "A") == "20261016"                  # 기본 = 신고대금 날
    assert k.rule_ref_day(rule(), "B") is False                       # 신고일 없으면 안 삼
    assert k.rule_ref_day(rule(ref_mode="prev"), "B") is None
    assert k.rule_ref_day(rule(ref_mode="date", ref_day="2026-10-01"), "B") == "20261001"
    k.ref_days = {"B": "20261002"}
    assert k.rule_ref_day(rule(), "B") == "20261002"                  # 종목에 직접 정한 날이 먼저
