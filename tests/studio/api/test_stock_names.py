"""결과 화면 종목 표기를 종목명으로(21:10) — 이름은 서버 한 곳(종목 마스터 names_of)에서: 상세 names 맵·빈 이름 거래 채움·실시간 곡선 last_event.name."""
from types import SimpleNamespace

import pandas as pd

from studio.application import jobs, run_queries, stock_service
from tests.studio.api.conftest import make_run


class MD:
    def __init__(self):
        self.info = pd.DataFrame({"name": ["삼성전자", None, "  ", "카카오"]}, index=["005930", "000660", "111111", "035720"])

    def stock_info(self):
        return self.info


def test_names_of_is_the_single_source_and_omits_unknown_or_blank_names():
    assert stock_service.names_of(MD(), ["005930", "035720", "000660", "111111", "999999", "005930"]) == {"005930": "삼성전자", "035720": "카카오"}


def test_blank_trade_names_are_filled_from_the_master_and_named_ones_are_kept():
    tr = pd.DataFrame({"code": ["005930", "035720", "999999"], "name": [None, "옛이름", None], "net_pnl": [1, 2, 3]})
    out = run_queries._named(SimpleNamespace(market_data=lambda: MD()), tr)
    assert list(out["name"][:2]) == ["삼성전자", "옛이름"] and pd.isna(out["name"].iloc[2])  # 마스터에도 없으면 비워 둔다(화면이 코드로 보임)
    assert tr["name"].isna().tolist() == [True, False, True]  # 원본은 안 건드림


def test_codes_in_collects_every_place_a_code_can_show_up():
    tr = pd.DataFrame({"code": ["005930"]})
    summary = {"intraday": {"code_periods": {"035720": ["a", "b"]}, "codes_without_minutes": ["000660"]}, "robustness": {"concentration": {"by_code": [{"removed": ["111111", "005930"]}]}}}
    assert set(run_queries._codes_in(tr, summary)) == {"005930", "035720", "000660", "111111"}


def test_run_detail_and_trades_carry_names_for_every_traded_code(client, disp):
    rid = make_run(client, disp)
    d = client.get(f"/api/runs/{rid}").json()["data"]
    trades = client.get(f"/api/runs/{rid}/trades").json()["data"]
    assert trades and set(d["names"]) >= {t["code"] for t in trades if t["name"]}
    assert all(isinstance(v, str) and v for v in d["names"].values())


def test_live_curve_last_event_gets_the_stock_name():
    lc = jobs.LiveCurve(namer=lambda c: {"005930": "삼성전자"}.get(c))
    lc.add({"date": "2026-01-02", "equity": 1.0, "frac": 0.1, "last_event": {"ts": "2026-01-02", "code": "005930", "side": "buy"}})
    lc.add({"date": "2026-01-03", "equity": 1.0, "last_event": {"ts": "2026-01-03", "code": "999999", "side": "sell"}})
    lc.add({"date": "2026-01-04", "equity": 1.0, "last_event": None})
    assert lc.points[0]["last_event"]["name"] == "삼성전자"
    assert "name" not in lc.points[1]["last_event"]  # 이름을 모르면 안 붙인다(화면이 코드로)
    assert lc.points[2]["last_event"] is None and "frac" not in lc.points[0]


def test_stocks_names_endpoint_maps_codes_and_skips_unknown(client):
    r = client.get("/api/stocks/names", params={"codes": "005930,999999, ,000660"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert "999999" not in d and all(isinstance(v, str) and v for v in d.values())
    assert client.get("/api/stocks/names").json()["data"] == {}
