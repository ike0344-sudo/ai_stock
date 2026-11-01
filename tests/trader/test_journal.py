"""선정 일지 — 뺀 종목도 남고(뺌), 기준일은 다 쌓이며, 백테스트는 기준일마다 대입·빠진 종목은 알린다(10-22)."""
import json

from trader import backtest as bt
from trader import desk as d


def test_pick_keeps_ref_days_and_unpick_marks_dropped(monkeypatch):
    k = object.__new__(d.Desk)
    k.journal, k.name = [], lambda c: "가"
    monkeypatch.setattr(d, "_write", lambda *a: None)
    k.pick("000001", "20261016", "직접 고름")
    k.pick("000001", "20261021", "직접 고름")
    assert k.journal[0]["ref_days"] == ["20261016", "20261021"]
    k.unpick("000001")
    assert len(k.journal) == 1 and k.journal[0]["dropped"] and k.journal[0]["closed"]
    k.pick("000001", None, "직접 고름")                     # 다시 고르면 새 줄
    assert len(k.journal) == 2


def test_journal_events_each_ref_day_and_missing(monkeypatch, tmp_path):
    (tmp_path / "journal.json").write_text(json.dumps([
        {"code": "000001", "name": "가", "ref_day": "20261021", "ref_days": ["20261016", "20261021"]},
        {"code": "000002", "name": "나", "ref_day": None}]), encoding="utf-8")
    (tmp_path / "static" / "dashboard").mkdir(parents=True)
    (tmp_path / "static" / "dashboard" / "value_ledger.json").write_text(json.dumps({"rows": [
        ["2026-10-16", "000001"] + [None] * 19 + [9000], ["2026-10-21", "000001"] + [None] * 19 + [11000]]}), encoding="utf-8")
    monkeypatch.setattr(bt, "STATE", tmp_path)
    monkeypatch.setattr(bt, "ROOT", tmp_path)
    miss: list = []
    ev = bt.journal_events("2026-10-01", "2026-10-31", "reg", miss)
    assert [(e[0], e[3]) for e in ev] == [("2026-10-16", 9000), ("2026-10-21", 11000)]
    assert miss == ["나(기준일 없음)"]


def test_value_high_now_reg_only_uses_regular_value(monkeypatch):
    from datetime import datetime as real_dt
    from trader import feed
    k = object.__new__(d.Desk)
    k._is_trading_day = lambda _d: True
    k.vref = lambda c: {"aft": 1500, "reg": 1200}
    monkeypatch.setitem(feed.quotes, "000001", {"value": 1600e8, "chg": 12.0})
    monkeypatch.setattr(d, "datetime", type("T", (), {"now": staticmethod(lambda: real_dt(2026, 10, 22, 10, 0))}))
    k._reg_today = lambda c: (1100, 12.0)                   # 통합 1,600억(≥1,500)이어도 정규장 1,100억 < 1,200억 → 아님
    assert k.value_high_now("000001") and not k.value_high_now("000001", reg_only=True)
    k._reg_today = lambda c: (1250, 12.0)
    assert k.value_high_now("000001", 10, reg_only=True) and not k.value_high_now("000001", 15, reg_only=True)


def test_ma_range_band_is_percent():
    lo, hi = bt.ma_range(10000, 0, 0.6)                    # ±0.6% — 예전엔 ±60%(4,000~16,000)
    assert round(lo) == 9940 and round(hi) == 10060


def test_facts_close_on_by_base(monkeypatch):
    f = object.__new__(bt.DailyFacts)                       # 재매수 금지 선을 정규장/애프터 종가로 고른다(10-22)
    from bisect import bisect_left
    f._bl = bisect_left
    f.al, f.reg = {"x": (["20261016"], [9200], [8830])}, {"x": (["20261016"], [9010], [9180])}
    f._rows = lambda c: (f.al[c], f.reg[c])
    assert f.close_on("x", "20261016", "reg") == 9010 and f.close_on("x", "20261016", "aft") == 8830


def test_journal_codes_skip_dropped(monkeypatch, tmp_path):
    (tmp_path / "journal.json").write_text(json.dumps([
        {"code": "A", "dropped": True}, {"code": "B", "closed": "x"}, {"code": "C"}, {"code": "A"}]), encoding="utf-8")
    monkeypatch.setattr(bt, "STATE", tmp_path)
    assert bt.journal_codes() == {"A", "B", "C"}          # A 는 다시 고른 줄이 있어 남는다
    (tmp_path / "journal.json").write_text(json.dumps([{"code": "A", "dropped": True}, {"code": "C"}]), encoding="utf-8")
    assert bt.journal_codes() == {"C"}
