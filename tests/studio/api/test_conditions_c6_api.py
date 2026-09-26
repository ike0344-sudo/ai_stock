"""studio-conditions c6 — 서버 능력(capabilities)·지표 메타 확장 칸·조건검색 레시피 API."""
import json

import pytest

from studio.application.capabilities import capabilities, ops, unmet_needs
from studio.application.recipes import CATEGORY_ORDER
from studio.domain.conditions import catalog as cat
from studio.domain.spec import Spec, bind_params
from studio.infrastructure import services_factory


@pytest.fixture
def cclient(client, services):
    services.recipes = services_factory.recipes  # 저장소의 실제 레시피 파일
    return client


def test_indicators_carry_capabilities_and_ops_from_the_model(cclient):
    d = cclient.get("/api/meta/indicators").json()["data"]
    caps = d["capabilities"]
    assert set(caps) == {"timeframes", "condition_fields", "group_fields", "operand_kinds", "pos_names", "exit_fields", "formulas"}
    # 서버가 실제로 아는 것만 켜진다 — 이 값들은 모델·카탈로그에서 읽은 것(c1 이 들어와 시간 단위·hold·negate·pos 가 켜져 있다)
    assert caps["timeframes"] == list(cat.TIMEFRAMES) and caps["condition_fields"] == ["hold"] and caps["group_fields"] == ["negate"]
    assert "pos" in caps["operand_kinds"] and caps["pos_names"] == list(cat.POS_NAMES)
    assert d["ops"] == ops()
    assert {"field", "ind", "market", "const"} <= set(caps["operand_kinds"])
    # 기본 칸은 그대로, 확장 칸(category 등)은 카탈로그가 줄 때만 나간다
    sma = next(i for i in d["indicators"] if i["name"] == "sma")
    assert {"name", "label", "desc", "params", "modes", "timing", "compute"} <= set(sma)
    assert sma["category"] == "trend" and sma["category_ko"] == "가격·이평·신고가" and sma["live"] is True and sma["definition"] and sma["example"]
    assert next(i for i in d["indicators"] if i["name"] == "vwap")["volume_based"] is True
    assert d["categories"][0] == {"key": "trend", "label": "가격·이평·신고가"}


def test_formulas_capability_follows_the_mounted_router(cclient):
    """수식 라우터(/api/formulas)가 실제로 붙어 있으면 화면이 수식 편집기를 켠다 — 라우트 등록 방식(FastAPI 버전)이 달라도 잡혀야 한다."""
    assert cclient.get("/api/meta/indicators").json()["data"]["capabilities"]["formulas"] is True


def test_unmet_needs_speaks_plain_korean():
    caps = {"timeframes": None, "operand_kinds": ["field", "ind"], "exit_fields": []}
    ind = {"sma": cat.INDICATORS["sma"]}
    out = unmet_needs(["timeframes", "indicator:ma_aligned", "op:is_true", "pos", "exit_field:take_profit_levels", "indicator:sma"], caps, ind, ["gt"])
    assert out == ["시간 단위 선택(일봉 지표를 분봉에서 쓰기)", "지표 'ma_aligned'", "연산자 'is_true'", "포지션 피연산자", "청산 규칙 'take_profit_levels'"]
    assert unmet_needs(["timeframes"], {**caps, "timeframes": ["bar"]}, ind, []) == []


def test_recipes_listed_with_availability_and_reasons(cclient):
    rows = cclient.get("/api/meta/recipes").json()["data"]
    assert len(rows) >= 10
    ids = {r["id"] for r in rows}
    assert {"new_high_20", "golden_cross", "intraday_high_break", "intraday_daily_high_break"} <= ids
    by = {r["id"]: r for r in rows}
    assert by["new_high_20"]["available"] is True and by["new_high_20"]["unavailable_reason"] is None
    # 서버가 아직 모르는 재료를 쓰는 레시피는 숨기지 않고 이유와 함께 나간다
    caps = capabilities()
    for r in rows:  # 서버 능력과 레시피 가용성이 어긋나지 않는다(지원되면 켜지고 아니면 이유가 있다)
        assert r["available"] == (r["unavailable_reason"] is None)
    assert by["intraday_daily_high_break"]["available"] == (caps["timeframes"] is not None)
    assert by["ma_aligned_first"]["available"] == ("ma_aligned" in cat.INDICATORS)
    order = [CATEGORY_ORDER.index(r["category"]) for r in rows if r["category"] in CATEGORY_ORDER]
    assert order == sorted(order)  # 분류 순서대로


def _spec(recipe: dict, mode: str) -> dict:
    d = {
        "version": 1, "name": recipe["title"], "mode": mode, "period": {"start": "2026-08-24", "end": "2026-09-23"},
        "universe": {"type": "codes", "codes": ["005930"]} if mode == "daily_single" else {"type": "top_value", "n": 30},
        "strategy": {"source": "builder", "entry": recipe["entry"], "exit": recipe["exit"]},
        "exits": recipe.get("exits") or {}, "params": recipe.get("params") or {},
    }
    if mode == "daily_single":
        d["portfolio"] = {"max_positions": 1, "max_weight_pct": 100}
    if mode == "intraday":
        d["intraday"] = {"bar_minutes": 5}
    return d


def test_every_usable_recipe_is_a_valid_spec_in_each_declared_mode(cclient):
    """레시피가 깨지면(없는 지표·모드 불일치·범위 밖 값) 화면에서 불러오는 순간 오류가 난다 — 쓸 수 있는 것은 전부 명세로 검증한다.
    서버가 새 재료를 지원하기 시작하면(needs 충족) 그 레시피도 이 시험에 자동으로 들어온다."""
    checked = 0
    for r in cclient.get("/api/meta/recipes").json()["data"]:
        if not r["available"]:
            continue
        for mode in r["modes"]:
            bind_params(Spec.model_validate(_spec(r, mode)))
            checked += 1
    assert checked >= 12


def test_recipe_files_are_consistent():
    rows = services_factory.recipes()
    assert len({r["id"] for r in rows}) == len(rows) >= 10
    for r in rows:
        assert r["category"] in CATEGORY_ORDER, r["id"]
        assert r["modes"] and set(r["modes"]) <= set(cat.MODES), r["id"]
        assert r["title"] and r["description"], r["id"]
        assert all(n.split(":")[0] in ("timeframes", "indicator", "op", "pos", "exit_field") for n in r.get("needs", [])), r["id"]


def test_broken_recipe_file_is_skipped_not_fatal(tmp_path, monkeypatch):
    d = tmp_path / "presets" / "studio" / "recipes"
    d.mkdir(parents=True)
    (d / "ok.json").write_text(json.dumps({"id": "ok", "category": "신고가", "title": "t", "modes": ["daily_portfolio"], "entry": {"logic": "all", "items": []}, "exit": {"logic": "any", "items": []}}), encoding="utf-8")
    (d / "bad.json").write_text("{ not json", encoding="utf-8")
    (d / "wrong_id.json").write_text(json.dumps({"id": "other", "category": "신고가", "title": "t", "modes": [], "entry": {}, "exit": {}}), encoding="utf-8")
    monkeypatch.setattr(services_factory.catalog, "root", lambda: tmp_path)
    assert [r["id"] for r in services_factory.recipes()] == ["ok"]


def test_recipes_without_services_wiring_is_empty_list_not_error(client):
    assert client.get("/api/meta/recipes").json()["data"] == []


def _daily_spec(**over):
    from tests.studio.application.fakes import spec_dict
    return spec_dict(universe={"type": "top_value", "n": 4, "exclude": []}, **over)


def test_validate_puts_bracket_path_on_the_row_and_strips_it_from_message(client):
    """c1 은 모드·시간 단위·pos 위치 오류 머리에 `[strategy.entry.items.0.right]` 를 붙인다 — 화면이 그 조건 행을 빨갛게 하도록 path 로 뽑는다."""
    s = _daily_spec()
    s["strategy"]["entry"]["items"][0]["right"]["tf"] = "daily_prev"  # 일봉 모드에서 시간 단위 — 오류
    r = client.post("/api/conditions/validate", json={"spec": s}).json()["data"]
    assert r["ok"] is False
    e = r["errors"][0]
    assert e["path"] == "strategy.entry.items.0.right" and e["loc"] == ["strategy", "entry", "items", 0, "right"]
    assert not e["message"].startswith("[") and "시간 단위" in e["message"]
    # pos 를 진입 조건에 쓰면 그 행이 가리켜진다
    s2 = _daily_spec()
    s2["strategy"]["entry"]["items"][0]["left"] = {"kind": "pos", "name": "return_pct"}
    e2 = client.post("/api/conditions/validate", json={"spec": s2}).json()["data"]["errors"][0]
    assert e2["path"].startswith("strategy.entry.items.0")


def test_preview_survives_new_operators_and_operands(client):
    """오늘 종목 미리보기가 새 연산자(참이면·최근 N봉 크로스)·right 없음·산술 피연산자에서 죽지 않는다(backtest-agent 지적 — 이전엔 KeyError)."""
    hi = {"kind": "ind", "name": "highest", "params": {"src": "high", "n": 20}}
    close = {"kind": "field", "name": "close"}
    items = [
        {"left": {"kind": "ind", "name": "new_high", "params": {"n": 20}}, "op": "is_true"},
        {"left": close, "op": "cross_above_within", "right": hi, "within": 3},
        {"left": {"kind": "expr", "op": "*", "left": close, "right": {"kind": "const", "value": 1.0}}, "op": "gt", "right": {"kind": "const", "value": 0}},
    ]
    s = _daily_spec()
    s["strategy"]["entry"] = {"logic": "any", "items": items, "negate": False}
    res = client.post("/api/conditions/preview", json={"spec": s, "limit": 10})
    assert res.status_code == 200, res.text
    rows = res.json()["data"]["rows"]
    assert rows, "산술 조건(종가×1 > 0)은 모든 종목이 만족한다"
    texts = [o["text"] for o in rows[0]["operands"]]
    assert any("이(가) 참" in t for t in texts) and any("최근 3봉 안 상향 돌파" in t for t in texts)
    unary = next(o for o in rows[0]["operands"] if "이(가) 참" in o["text"])
    assert unary["right"] is None  # 오른쪽 값이 없는 연산자
