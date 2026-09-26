"""사용자 수식 저장소·API (설계서 §3.5·§4·§7) — app.py 연결 전이라 이 테스트가 직접 만든 작은 앱에 라우터를 붙여 본다."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio.api import errors
from studio.api.routes import conditions, formulas
from studio.application.formula_service import FormulaNotFound
from studio.application.services import Services
from studio.infrastructure.formula_store import FileFormulaStore
from tests.studio.application.fakes import FakeMarketData


@pytest.fixture
def store(tmp_path):
    return FileFormulaStore(tmp_path / "presets" / "studio" / "formulas")


@pytest.fixture
def client(store, tmp_path):
    app = FastAPI()
    errors.install(app)
    app.include_router(conditions.router)
    app.include_router(formulas.router)
    app.state.services = Services(market_data=FakeMarketData, run_store=None, run_files=None, presets=None, formulas=store)
    return TestClient(app)


def test_put_get_list_delete_roundtrip(client, store, tmp_path):
    r = client.put("/api/formulas/눌림 목", json={"text": "C > MA(C,20) AND RSI(14) < 40", "description": "테스트"})
    assert r.status_code == 200 and r.json()["data"]["name"] == "눌림 목"
    f = tmp_path / "presets" / "studio" / "formulas" / "눌림 목.json"
    assert set(json.loads(f.read_text(encoding="utf-8"))) == {"name", "text", "description", "created_at"}

    g = client.get("/api/formulas/눌림 목").json()["data"]
    assert g["text"] == "C > MA(C,20) AND RSI(14) < 40" and g["error"] is None
    assert g["ast"]["logic"] == "all" and len(g["ast"]["items"]) == 2          # 불러올 때 컴파일된 AST 를 함께
    assert g["ast"]["formula"] == "C > MA(C,20) AND RSI(14) < 40"                # 원문이 최상위 그룹에 같이 실린다(Group.formula)
    assert [x["name"] for x in client.get("/api/formulas").json()["data"]] == ["눌림 목"]

    assert client.delete("/api/formulas/눌림 목").json()["data"]["deleted"] is True
    assert client.get("/api/formulas/눌림 목").status_code == 404
    assert client.delete("/api/formulas/눌림 목").status_code == 404
    assert client.get("/api/formulas").json()["data"] == []


def test_overwrite_keeps_created_at(client):
    first = client.put("/api/formulas/a", json={"text": "C > 1"}).json()["data"]
    second = client.put("/api/formulas/a", json={"text": "C > 2", "description": "x"}).json()["data"]
    assert second["created_at"] == first["created_at"] and second["text"] == "C > 2"


def test_invalid_formula_is_422_with_position_and_not_saved(client, store):
    r = client.put("/api/formulas/bad", json={"text": "C > 1 AND\n  FOO(3) > 1"})
    assert r.status_code == 422
    e = r.json()["error"]
    assert e["code"] == "FORMULA_INVALID" and e["details"]["line"] == 2 and e["details"]["col"] == 3 and e["details"]["expected"]
    assert store.list() == []


@pytest.mark.parametrize("name", ["../x", "a/b", "a.b", "x" * 41, "a\\b", "..", "a:b"])
def test_bad_names_cannot_reach_the_filesystem(client, store, name):
    r = client.put(f"/api/formulas/{name}", json={"text": "C > 1"})
    assert r.status_code in (400, 404, 405)          # 라우팅 단계에서 걸러지든 이름 검사에서 걸러지든 저장은 안 된다
    assert store.list() == []
    with pytest.raises(ValueError):
        store.put(name, "C > 1")
    assert client.get(f"/api/formulas/{name}").status_code in (404, 405)


def test_put_body_shape(client):
    assert client.put("/api/formulas/a", json=["C > 1"]).status_code == 400
    assert client.put("/api/formulas/a", json={"text": 5}).status_code == 400
    assert client.put("/api/formulas/a", json={"text": "C > 1", "description": "x" * 501}).status_code == 400
    assert client.put("/api/formulas/a", content=b"not json").status_code == 400


def test_load_of_formula_that_no_longer_compiles_reports_error_not_500(client, store):
    store.put("옛것", "OLD_INDICATOR(3) > 1")           # 카탈로그가 바뀌어 지금은 안 되는 저장본
    g = client.get("/api/formulas/옛것").json()["data"]
    assert g["ast"] is None and g["error"]["line"] == 1


def test_missing_store_is_503(store):
    app = FastAPI()
    errors.install(app)
    app.include_router(formulas.router)
    app.state.services = Services(market_data=FakeMarketData, run_store=None, run_files=None, presets=None)
    assert TestClient(app).get("/api/formulas").status_code == 503


def test_validate_formula_ok_and_syntax_error_are_both_200(client):
    ok = client.post("/api/conditions/validate", json={"formula": "C > MA(C,20)"}).json()["data"]
    assert ok["ok"] is True and ok["ast"]["items"][0]["op"] == "gt" and ok["error"] is None
    bad = client.post("/api/conditions/validate", json={"formula": "C > "})
    assert bad.status_code == 200
    d = bad.json()["data"]
    assert d["ok"] is False and d["ast"] is None and (d["error"]["line"], d["error"]["col"]) == (1, 5)   # 끝 토큰 자리(공백 뒤)


def test_validate_formula_reports_ast_shape_errors_separately(client):
    # 문법은 맞지만 명세 형식(AST)이 아직 받지 못하는 칸 — 오류 경로를 돌려준다(AST 확장 뒤에는 이 식이 통과해야 한다)
    from studio.domain.conditions.ast import FieldOperand
    d = client.post("/api/conditions/validate", json={"formula": "M5.C > 1"}).json()["data"]
    if "tf" in FieldOperand.model_fields:
        assert d["ok"] is True
    else:
        assert d["ok"] is False and d["error"] is None and d["errors"] and d["ast"]["items"][0]["left"]["tf"] == "m5"


def test_validate_with_spec_still_works_and_needs_one_of_them(client):
    assert client.post("/api/conditions/validate", json={}).status_code == 400
    assert client.post("/api/conditions/validate", content=b"x").status_code == 400
    assert client.post("/api/conditions/validate", json={"spec": {"bad": 1}}).status_code == 200


def test_store_get_missing_raises():
    with pytest.raises(FormulaNotFound):
        FileFormulaStore("nonexistent-dir-xyz").get("nope")


def test_check_route_ok_syntax_error_and_no_store_needed(store):
    app = FastAPI()
    errors.install(app)
    app.include_router(formulas.router)          # 저장소 없이도 검사는 된다
    c = TestClient(app)
    ok = c.post("/api/formulas/check", json={"text": "M5.C > M5.MA(C,20) AND RSI(14) < 30", "mode": "intraday"})
    assert ok.status_code == 200 and ok.json()["data"]["ok"] is True and ok.json()["data"]["ast"]["items"][0]["left"]["tf"] == "m5"
    bad = c.post("/api/formulas/check", json={"text": "C > 1 AND\n  FOO(3)"})
    assert bad.status_code == 422
    e = bad.json()["error"]
    assert e["code"] == "FORMULA_INVALID" and (e["details"]["line"], e["details"]["col"]) == (2, 3) and e["details"]["expected"]
    assert c.post("/api/formulas/check", json={"nope": 1}).status_code == 400
    assert c.post("/api/formulas/check", content=b"x").status_code == 400


def test_check_ast_with_formula_text_embeds_into_a_spec_without_changing_hashes():
    from studio.application import formula_service
    from studio.application.backtest_service import spec_hash
    from studio.domain.conditions.formula import compile_formula
    from studio.domain.spec import Spec
    from tests.studio.application.fakes import spec_dict
    res = formula_service.check("C > MA(C,20)")
    assert res["ok"] and res["ast"]["formula"] == "C > MA(C,20)"
    with_text, plain = spec_dict(), spec_dict()
    with_text["strategy"]["entry"], plain["strategy"]["entry"] = res["ast"], compile_formula("C > MA(C,20)")
    assert spec_hash(Spec.model_validate(with_text)) == spec_hash(Spec.model_validate(plain))
