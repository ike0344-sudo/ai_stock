"""모듈 4 API — 지표·전략·종목·봉 / 실행 기록(목록·상세·거래·CSV·수정·삭제·비교) / 조건 검증·미리보기 / 프리셋.

§8.3 #13(백테스트 잡→결과) #16(ID 형식 404) #14(없는 지표 400 대신 validate 의 경로 오류) + 보안(위조 Origin 403).
"""
import json

import pytest

from tests.studio.api.conftest import make_run
from tests.studio.application.fakes import spec_dict

BT = spec_dict(universe={"type": "top_value", "n": 4, "exclude": []})


def err(res, status, code):
    assert res.status_code == status, res.text
    assert res.json()["error"]["code"] == code
    return res.json()["error"]


@pytest.fixture
def run_id(client, disp):
    return make_run(client, disp)


# ------------------------------------------------------------------ 카탈로그·종목
def test_indicator_catalog_has_everything_the_editor_needs(client):
    d = client.get("/api/meta/indicators").json()["data"]
    names = {i["name"] for i in d["indicators"]}
    assert {"sma", "highest", "rsi", "vol_ratio", "value_rank"} <= names
    sma = next(i for i in d["indicators"] if i["name"] == "sma")
    assert {p["name"] for p in sma["params"]} == {"src", "n"} and "daily_portfolio" in sma["modes"]
    assert d["ops"][:6] == ["gt", "gte", "lt", "lte", "cross_above", "cross_below"]  # c1 이 cross_*_within·is_true·is_false 를 뒤에 붙였다
    assert d["fields"] and d["market"]["indexes"] == ["kospi", "kosdaq"] and d["n_range"] == [1, 500]


def test_legacy_strategies_listed_with_params(client):
    rows = client.get("/api/meta/strategies").json()["data"]
    assert len(rows) == 8 and next(r for r in rows if r["name"] == "pullback_reentry")["deprecated"] is True
    ma = next(r for r in rows if r["name"] == "ma_crossover")
    assert [p["name"] for p in ma["params"]] == ["short_window", "long_window"] and ma["params"][0]["default"] == 5


def test_data_ranges_for_the_period_picker(client):
    d = client.get("/api/meta/data-ranges").json()["data"]
    assert set(d) == {"daily", "kospi", "kosdaq"} and d["daily"][0] == "2022-01-03" and d["daily"][1] > d["daily"][0]


def test_stock_search_and_bars(client):
    hits = client.get("/api/stocks", params={"q": "삼성"}).json()["data"]
    assert [h["code"] for h in hits] == ["005930"] and hits[0]["name"] == "삼성전자"
    assert client.get("/api/stocks", params={"q": "0000"}).json()["data"][0]["code"].startswith("0000")
    assert client.get("/api/stocks", params={"q": ""}).json()["data"] == []
    b = client.get("/api/stocks/005930/bars", params={"start": "2023-01-02", "end": "2023-02-28"}).json()["data"]
    assert b["name"] == "삼성전자" and b["interval"] == "1d" and len(b["bars"]) > 20
    assert set(b["bars"][0]) == {"t", "o", "h", "l", "c", "v"} and b["bars"][0]["t"] >= "2023-01-02"
    err(client.get("/api/stocks/005930/bars", params={"interval": "2h"}), 422, "MODE_NOT_SUPPORTED")
    err(client.get("/api/stocks/005930/bars", params={"interval": "5m"}), 404, "NOT_FOUND")  # 이 서버엔 분봉 보관소가 없다(일봉 대역)
    err(client.get("/api/stocks/999999/bars"), 404, "NOT_FOUND")
    err(client.get("/api/stocks/ab/bars"), 404, "NOT_FOUND")


# ------------------------------------------------------------------ 실행 기록
def test_list_detail_trades_equity_after_a_run(client, run_id):
    rows = client.get("/api/runs").json()["data"]
    assert [r["run_id"] for r in rows] == [run_id]
    r = rows[0]
    assert r["mode"] == "daily_portfolio" and r["kind"] == "backtest" and r["starred"] is False and r["memo"] is None
    assert set(r["metrics"]) >= {"total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "num_trades"}

    d = client.get(f"/api/runs/{run_id}").json()["data"]
    assert d["run_id"] == run_id and d["spec"]["name"] == "테스트" and d["summary"]["metrics"]
    assert d["narration"] and "산다" in d["narration"]
    a = d["analysis"]
    assert set(a) >= {"monthly", "yearly", "exit_reasons", "by_sector", "by_theme_group", "histogram"}
    assert a["monthly"] and {"period", "return_pct"} <= set(a["monthly"][0])
    assert a["yearly"][0]["period"] == "2022" and a["by_sector"]
    assert a["by_theme_group"] is not None  # 매핑이 주어지면 계산
    assert d["has_grid"] is False and d["has_folds"] is False

    tr = client.get(f"/api/runs/{run_id}/trades").json()["data"]
    assert len(tr) == d["summary"]["n_trades"] and tr
    assert {"code", "name", "entry_ts", "entry_price", "exit_ts", "net_pnl", "net_pct", "exit_reason", "mfe_pct"} <= set(tr[0])
    assert "T" in tr[0]["entry_ts"]  # 시각은 ISO 문자열
    eq = client.get(f"/api/runs/{run_id}/equity").json()["data"]
    assert eq and {"ts", "equity", "drawdown_pct", "benchmark_kospi"} <= set(eq[0])


def test_responses_are_strict_json_even_with_nan_and_inf(client, run_id):
    """NaN·inf 가 섞인 결과(손실 없음의 profit_factor 등)도 봉투가 깨지지 않는다 — 브라우저 JSON.parse 가 거부하는 값이 없어야 한다."""
    for path in (f"/api/runs/{run_id}", f"/api/runs/{run_id}/trades", f"/api/runs/{run_id}/equity", "/api/runs"):
        text = client.get(path).text
        json.loads(text, parse_constant=lambda c: (_ for _ in ()).throw(AssertionError(f"{path}: {c}")))


def test_csv_export_has_bom_and_header(client, run_id):
    res = client.get(f"/api/runs/{run_id}/export/trades.csv")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert res.content.startswith(b"\xef\xbb\xbf") and res.content[3:].decode("utf-8").splitlines()[0].startswith("code,name")
    assert f"trades_{run_id}.csv" in res.headers["content-disposition"]


def test_patch_only_name_memo_star_and_list_filters(client, run_id):
    r = client.patch(f"/api/runs/{run_id}", json={"name": "내 이름", "memo": "메모 1", "starred": True}).json()["data"]
    assert (r["name"], r["memo"], r["starred"]) == ("내 이름", "메모 1", True)
    assert client.get(f"/api/runs/{run_id}").json()["data"]["meta"]["name"] == "내 이름"
    assert client.get(f"/api/runs/{run_id}").json()["data"]["spec"]["name"] == "테스트"  # 명세 이름은 그대로
    assert len(client.get("/api/runs", params={"starred": "true"}).json()["data"]) == 1
    assert client.get("/api/runs", params={"starred": "false"}).json()["data"] == []
    assert len(client.get("/api/runs", params={"q": "메모"}).json()["data"]) == 1
    assert client.get("/api/runs", params={"q": "없는말"}).json()["data"] == []
    assert client.get("/api/runs", params={"mode": "tick"}).json()["data"] == []
    # 명세는 못 고친다(사전 판정 기준 보호)
    e = err(client.patch(f"/api/runs/{run_id}", json={"spec": {}}), 400, "VALIDATION_ERROR")
    assert "spec" in e["details"]["fieldErrors"]
    err(client.patch(f"/api/runs/{run_id}", json={"exits": {"stop_loss_pct": 1}}), 400, "VALIDATION_ERROR")
    err(client.patch(f"/api/runs/{run_id}", json={"name": ""}), 400, "VALIDATION_ERROR")
    err(client.patch(f"/api/runs/{run_id}", json={"starred": "yes"}), 400, "VALIDATION_ERROR")
    err(client.patch(f"/api/runs/{run_id}", content=b"[1]", headers={"content-type": "application/json"}), 400, "VALIDATION_ERROR")
    assert client.patch(f"/api/runs/{run_id}", json={"memo": None}).json()["data"]["memo"] is None


def test_delete_removes_only_that_run(client, disp, run_id, root):
    other = make_run(client, disp, exits={"stop_loss_pct": 5})
    assert client.delete(f"/api/runs/{run_id}").json()["data"] == {"run_id": run_id, "deleted": True}
    err(client.get(f"/api/runs/{run_id}"), 404, "NOT_FOUND")
    err(client.delete(f"/api/runs/{run_id}"), 404, "NOT_FOUND")
    assert [r["run_id"] for r in client.get("/api/runs").json()["data"]] == [other]
    assert (root / "results" / "studio" / other / "meta.json").exists()  # 다른 실행·데이터는 그대로


@pytest.mark.parametrize("bad", ["..%2Fx", "20260925-201000-ZZZZZZ", "x", "20990101-000000-abcdef"])
def test_16_bad_ids_are_404_everywhere(client, bad):
    for method, path in (("GET", f"/api/runs/{bad}"), ("GET", f"/api/runs/{bad}/trades"), ("GET", f"/api/runs/{bad}/equity"),
                         ("GET", f"/api/runs/{bad}/export/trades.csv"), ("PATCH", f"/api/runs/{bad}"), ("DELETE", f"/api/runs/{bad}")):
        err(client.request(method, path, json={}), 404, "NOT_FOUND")


def test_compare_two_runs_with_condition_diff(client, disp, run_id):
    other = make_run(client, disp, exits={"stop_loss_pct": 5})
    d = client.post("/api/runs/compare", json={"ids": [run_id, other]}).json()["data"]
    assert [r["run_id"] for r in d["runs"]] == [run_id, other]
    assert d["runs"][0]["equity"] and {"ts", "equity", "rel"} <= set(d["runs"][0]["equity"][0])
    assert abs(d["runs"][0]["equity"][0]["rel"] - 100) < 1  # 시작을 100 으로 맞춘 곡선
    assert d["runs"][0]["metrics_all"]["sharpe"] is not None
    items = d["diffs"][0]["items"]
    assert d["diffs"][0]["vs"] == run_id and [i["text"] for i in items if i["path"] == "exits.stop_loss_pct"] == ["손절(%): 없음 → 5"]


def test_compare_input_validation(client, run_id):
    err(client.post("/api/runs/compare", json={"ids": [run_id]}), 400, "VALIDATION_ERROR")
    err(client.post("/api/runs/compare", json={"ids": [run_id, run_id]}), 400, "VALIDATION_ERROR")
    err(client.post("/api/runs/compare", json={"ids": ["x", "y"]}), 404, "NOT_FOUND")
    err(client.post("/api/runs/compare", json={"ids": [run_id, "20990101-000000-abcdef"]}), 404, "NOT_FOUND")
    err(client.post("/api/runs/compare", json={"ids": list(range(6))}), 404, "NOT_FOUND")


def test_spec_diff_uses_narrated_sentences_for_condition_groups():
    from studio.application.spec_diff import diff_specs
    from studio.domain.spec import Spec
    a = Spec.model_validate(spec_dict())
    d2 = spec_dict()
    d2["strategy"]["entry"]["items"][0]["right"]["params"]["n"] = 60
    b = Spec.model_validate(d2)
    items = diff_specs(a, b)
    assert len(items) == 1 and items[0]["path"] == "strategy.entry" and "20" in items[0]["a"] and "60" in items[0]["b"]
    assert diff_specs(a, a) == []


# ------------------------------------------------------------------ 조건 검증·미리보기
def test_validate_ok_returns_narration(client):
    d = client.post("/api/conditions/validate", json={"spec": BT}).json()["data"]
    assert d["ok"] is True and d["errors"] == [] and "산다" in d["narration"]


def test_14_validate_unknown_indicator_points_at_the_row(client):
    bad = spec_dict()
    bad["strategy"]["entry"]["items"][0]["right"]["name"] = "nope"
    d = client.post("/api/conditions/validate", json={"spec": bad}).json()["data"]
    assert d["ok"] is False and d["narration"] is None
    e = d["errors"][0]
    assert e["path"].startswith("strategy.entry.items.0.right") and "nope" in e["message"] and "Value error" not in e["message"]
    assert all(p not in e["loc"] for p in ("ind", "builder", "Condition")), e["loc"]  # 판별 태그는 경로에서 뺀다


def test_validate_range_errors_and_data_period(client):
    out = spec_dict(period={"start": "2010-01-01", "end": "2010-12-31"})
    d = client.post("/api/conditions/validate", json={"spec": out}).json()["data"]
    assert d["ok"] is False and d["errors"][0]["path"] == "period" and "겹치지" in d["errors"][0]["message"]
    partial = spec_dict(period={"start": "2021-06-01", "end": "2023-06-30"})  # 데이터는 2022-01 부터
    d = client.post("/api/conditions/validate", json={"spec": partial}).json()["data"]
    assert d["ok"] is True and d["warnings"] and d["warnings"][0]["dataset"] == "daily"
    empty = spec_dict()
    empty["strategy"]["entry"]["items"] = []
    d = client.post("/api/conditions/validate", json={"spec": empty}).json()["data"]
    assert d["ok"] is False and "entry" in d["errors"][0]["path"]


def test_validate_bad_params_default_out_of_range(client):
    bad = spec_dict(exits={"stop_loss_pct": {"param": "sl"}}, params={"sl": {"default": 0.0, "min": 0, "max": 10}})
    d = client.post("/api/conditions/validate", json={"spec": bad}).json()["data"]
    assert d["ok"] is False and "sl" in json.dumps(d["errors"], ensure_ascii=False)


def test_validate_needs_spec_key(client):
    err(client.post("/api/conditions/validate", json=BT), 400, "VALIDATION_ERROR")
    err(client.post("/api/conditions/validate", content=b"{nope", headers={"content-type": "application/json"}), 400, "VALIDATION_ERROR")


def test_preview_returns_todays_matches_with_operand_values(client):
    # 종가가 2일 최고가(전일 포함) 위 — 랜덤워크 400일에서 마지막 날 몇 종목은 걸린다
    hi = {"kind": "ind", "name": "highest", "params": {"src": "high", "n": 2}}
    spec = spec_dict(universe={"type": "all", "exclude": []})
    spec["strategy"]["entry"]["items"] = [{"left": {"kind": "field", "name": "close"}, "op": "gt", "right": hi}]
    res = client.post("/api/conditions/preview", json={"spec": spec, "limit": 50})
    assert res.status_code == 200, res.text
    d = res.json()["data"]
    from tests.studio.application.fakes import FakeMarketData
    assert d["date"] == str(FakeMarketData().data_ranges()["daily"][1])  # 데이터의 최신 거래일 기준
    assert d["universe_size"] == 8 and d["matched"] == len(d["rows"]) and not d["truncated"]
    for row in d["rows"]:
        left, right = row["operands"][0]["left"], row["operands"][0]["right"]
        assert left > right  # 표시된 피연산자 값이 실제로 조건을 만족한다
        assert row["operands"][0]["text"].count(">") == 1 and row["value_rank"] is not None
    assert [r["value"] for r in d["rows"]] == sorted((r["value"] for r in d["rows"]), reverse=True)


def test_preview_rejects_unsupported_mode_and_invalid_spec(client):
    intraday = dict(BT, mode="intraday", intraday={"bar_minutes": 5})
    err(client.post("/api/conditions/preview", json={"spec": intraday}), 422, "SPEC_INVALID")
    e = err(client.post("/api/conditions/preview", json={"spec": {"version": 1}}), 400, "VALIDATION_ERROR")
    assert e["details"]["fieldErrors"]
    err(client.post("/api/conditions/preview", json={"spec": BT, "limit": 0}), 400, "VALIDATION_ERROR")


def test_preview_with_legacy_strategy(client):
    spec = spec_dict(strategy={"source": "legacy", "name": "ma_crossover", "params": {"short_window": 2, "long_window": 5}},
                     universe={"type": "all", "exclude": []})
    d = client.post("/api/conditions/preview", json={"spec": spec}).json()["data"]
    assert d["matched"] == len(d["rows"]) and all("operands" not in r for r in d["rows"])


# ------------------------------------------------------------------ 프리셋
def test_presets_list_get_put_delete(client):
    rows = client.get("/api/presets").json()["data"]
    assert {r["name"] for r in rows} >= {"new_high_20", "golden_cross_5_20", "tick_breakout_5m"}
    nh = next(r for r in rows if r["name"] == "new_high_20")
    assert nh["mode"] == "daily_portfolio" and nh["n_params"] == 3 and "신고가" in nh["title"]
    spec = client.get("/api/presets/new_high_20").json()["data"]["spec"]
    assert spec["strategy"]["source"] == "builder"
    # 파일에 없던 칸(costs·fills·compat)도 기본값으로 채워서 준다 — 화면이 부분 명세를 받아 죽지 않게(실측 사고)
    assert spec["costs"]["commission_rate"] == 0.00015 and spec["fills"]["same_bar_policy"] == "stop_first" and spec["compat"] == {"legacy": False}
    # 저장(덮어쓰기 포함) → 검증·정규화된 명세로
    r = client.put("/api/presets/내 프리셋", json=dict(BT, name="내 조건")).json()["data"]
    assert r == {"name": "내 프리셋", "title": "내 조건", "mode": "daily_portfolio"}
    assert client.get("/api/presets/내 프리셋").json()["data"]["spec"]["name"] == "내 조건"
    assert client.delete("/api/presets/내 프리셋").json()["data"]["deleted"] is True
    err(client.get("/api/presets/내 프리셋"), 404, "NOT_FOUND")
    err(client.delete("/api/presets/내 프리셋"), 404, "NOT_FOUND")


def test_preset_input_validation(client):
    e = err(client.put("/api/presets/ok", json={"version": 1, "name": "x"}), 400, "VALIDATION_ERROR")
    assert e["details"]["fieldErrors"]
    e = err(client.put("/api/presets/bad.name", json=BT), 400, "VALIDATION_ERROR")
    assert "name" in e["details"]["fieldErrors"]
    err(client.get("/api/presets/..%2Fsecret"), 404, "NOT_FOUND")
    err(client.delete("/api/presets/a.b"), 404, "NOT_FOUND")
    err(client.put("/api/presets/ok", content=b"{no", headers={"content-type": "application/json"}), 400, "VALIDATION_ERROR")


# ------------------------------------------------------------------ 보안·구성
def test_state_changing_routes_reject_forged_origin(client, run_id):
    bad = {"Origin": "http://evil.example"}
    assert client.patch(f"/api/runs/{run_id}", json={"starred": True}, headers=bad).status_code == 403
    assert client.delete(f"/api/runs/{run_id}", headers=bad).status_code == 403
    assert client.put("/api/presets/x", json=BT, headers=bad).status_code == 403
    assert client.post("/api/runs/compare", json={"ids": [run_id, run_id]}, headers=bad).status_code == 403
    assert client.get(f"/api/runs/{run_id}").status_code == 200  # 아무것도 바뀌지 않았다
    assert client.get("/api/runs").json()["data"][0]["starred"] is False


def test_routes_report_unconfigured_services_clearly(root, disp, fake_deps):
    from fastapi.testclient import TestClient
    from studio.api.app import create_app
    c = TestClient(create_app(root, dispatcher=disp), base_url="http://127.0.0.1:8780")
    err(c.get("/api/runs"), 503, "SERVICES_UNAVAILABLE")
    assert c.get("/api/meta/indicators").status_code == 200  # 서비스가 필요 없는 카탈로그는 그대로


def test_broken_preset_is_returned_raw_not_500(client, root):
    (root / "presets" / "studio" / "broken.json").write_text('{"version": 1, "name": "x"}', encoding="utf-8")
    d = client.get("/api/presets/broken").json()["data"]
    assert d["spec"] == {"version": 1, "name": "x"}
