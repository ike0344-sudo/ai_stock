"""조건 템플릿 API (설계서 §5.5) — app.py 연결 전이라 작은 앱에 라우터만 붙여 본다."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio.api import errors
from studio.api.routes import templates


@pytest.fixture
def client():
    app = FastAPI()
    errors.install(app)
    app.include_router(templates.router)
    return TestClient(app)


BASE = "/api/meta/condition-templates"


def test_list_by_mode_has_categories_slots_and_disabled_reasons(client):
    d = client.get(BASE, params={"mode": "intraday", "bar_minutes": 5, "source": "al"}).json()["data"]
    assert [c["key"] for c in d["categories"]][:2] == ["breakout", "ma"] and len(d["templates"]) >= 40
    v = next(t for t in d["templates"] if t["id"] == "value_eok")
    assert v["example"] == "5분봉 거래대금이 20억 이상이다" and v["available"]
    tf = next(s for s in v["slots"] if s["kind"] == "tf")
    assert any(not c["enabled"] and c["reason"] for c in tf["choices"])
    daily = client.get(BASE, params={"mode": "daily_portfolio"}).json()["data"]["templates"]
    assert not next(t for t in daily if t["id"] == "cum_value")["available"]


@pytest.mark.parametrize("params", [{"mode": "weekly"}, {"mode": "intraday", "bar_minutes": 7}, {"mode": "intraday", "source": "x"}, {"bar_minutes": "abc"}])
def test_list_rejects_bad_options(client, params):
    r = client.get(BASE, params=params)
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_build_returns_condition_sentence_and_filled_values(client):
    r = client.post(BASE + "/build", json={"id": "value_eok", "values": {"tf": "m5", "x": 20}, "mode": "intraday", "bar_minutes": 1}).json()["data"]
    assert r["condition"] == {"left": {"kind": "ind", "name": "value_eok", "tf": "m5"}, "op": "gte", "right": {"kind": "const", "value": 20.0}}
    assert r["sentence"] == "5분봉 거래대금이 20억 이상이다" and r["values"] == {"tf": "m5", "x": 20, "cmp": "gte"}
    r = client.post(BASE + "/build", json={"id": "pos_loss", "values": {"x": 3}, "mode": "daily_portfolio"}).json()["data"]
    assert r["condition"]["right"]["value"] == -3.0 and r["sentence"] == "산 가격보다 3% 이상 내렸다(손실)"


def test_build_errors_are_plain_korean_with_the_slot(client):
    r = client.post(BASE + "/build", json={"id": "value_eok", "values": {"x": -5}, "mode": "daily_portfolio"})
    assert r.status_code == 400 and "사이로 적어" in r.json()["error"]["details"]["fieldErrors"]["x"]
    r = client.post(BASE + "/build", json={"id": "value_eok", "values": {"tf": "m3"}, "mode": "intraday", "bar_minutes": 5})
    assert r.status_code == 400 and "배수" in r.json()["error"]["details"]["fieldErrors"]["tf"]
    assert client.post(BASE + "/build", json={"id": "nope", "mode": "daily_portfolio"}).status_code == 404
    assert client.post(BASE + "/build", json={"values": {}}).status_code == 400
    assert client.post(BASE + "/build", content=b"x").status_code == 400
    assert client.post(BASE + "/build", json={"id": "cum_value", "mode": "daily_portfolio"}).status_code == 400


def test_match_gives_sentence_or_null_and_never_crashes_on_odd_conditions(client):
    good = client.post(BASE + "/build", json={"id": "rsi_level", "values": {"x": 25}, "mode": "daily_portfolio"}).json()["data"]["condition"]
    odd = {"left": {"kind": "ind", "name": "no_such_indicator"}, "op": "gt", "right": {"kind": "const", "value": 1}}
    hold3 = {"left": {"kind": "ind", "name": "value_eok"}, "op": "gte", "right": {"kind": "const", "value": 20}, "hold": 3}
    r = client.post(BASE + "/match", json={"conditions": [good, hold3, odd, {}], "mode": "daily_portfolio"}).json()["data"]
    assert r[0]["id"] == "rsi_level" and r[0]["sentence"] == "RSI(14)가 25 이하다" and r[0]["values"]["x"] == 25 and r[0]["category"] == "indicator"
    assert r[1:] == [None, None, None]
    assert client.post(BASE + "/match", json={"conditions": "x", "mode": "intraday"}).status_code == 400
    assert client.post(BASE + "/match", json={"conditions": [{}] * 201, "mode": "intraday"}).status_code == 400
