"""module-5 API — 검증 작업 제출(최적화·워크포워드·홀드아웃) · 조합 수 · 조합 표·폴드 · 홀드아웃 이력 (설계서 §8.3 #20)."""
import pytest

from studio.application import jobs as app_jobs
from studio.infrastructure.holdout_ledger import FileHoldoutLedger
from tests.studio.application.fakes import FakeMarketData, make_panel
from tests.studio.application.test_optimize_service import spec_dict

RUN_ID = r"^\d{8}-\d{6}-[0-9a-f]{6}$"


@pytest.fixture
def v(client, disp, services, fake_deps, root, monkeypatch):
    """420일치 가짜 시장 + 장부를 연결한 클라이언트."""
    md = FakeMarketData(make_panel(n=420, seed=5))
    ledger = FileHoldoutLedger(root / "results" / "studio" / "holdout_ledger.json")
    monkeypatch.setattr(app_jobs, "deps_factory", lambda: app_jobs.Deps(market_data=md, run_store=fake_deps, holdout_ledger=ledger))
    services.holdout_ledger = ledger
    return client


def run(client, disp, path, body):
    res = client.post(path, json=body)
    assert res.status_code == 202, res.text
    disp.tick()
    job = client.get(f"/api/jobs/{res.json()['data']['job_id']}").json()["data"]
    return res.json()["data"]["run_id"], job


CFG = {"train_pct": 60}
SPEC = spec_dict(validation={"holdout_pct": 20, "objective": "sharpe", "min_trades": 3})


def test_grid_info_counts_without_running(v):
    d = v.post("/api/validation/grid-info", json={"spec": SPEC}).json()["data"]
    assert d["n"] == 15 and d["axes"] == {"n": 5, "m": 3} and not d["too_large"] and not d["warn"]
    d = v.post("/api/validation/grid-info", json={"spec": SPEC, "vary": ["n"]}).json()["data"]
    assert d["n"] == 5
    assert v.post("/api/validation/grid-info", json={"spec": SPEC, "vary": ["없는"]}).status_code == 422


def test_optimize_flow_grid_and_detail(v, disp):
    rid, job = run(v, disp, "/api/jobs/optimize", {"spec": SPEC, "config": CFG})
    assert job["status"] == "succeeded", job
    detail = v.get(f"/api/runs/{rid}").json()["data"]
    assert detail["meta"]["kind"] == "optimize" and detail["has_grid"] and not detail["has_folds"]
    assert "optimize" in detail["summary"]
    grid = v.get(f"/api/runs/{rid}/grid").json()["data"]
    assert len(grid) == 15 and sum(1 for r in grid if r["selected"]) == 1  # 전 조합 + 선택 1개
    assert v.get(f"/api/runs/{rid}/folds").status_code == 404
    assert v.get("/api/runs").json()["data"][0]["kind"] == "optimize"


def test_grid_too_large_is_422_with_numbers(v):
    big = spec_dict(params={"n": {"default": 20, "min": 1, "max": 100, "step": 1}, "m": {"default": 10, "min": 1, "max": 100, "step": 1}})
    res = v.post("/api/jobs/optimize", json={"spec": big})  # 10,000 조합 — 설계서 #20 은 6,000, 같은 규칙
    assert res.status_code == 422 and res.json()["error"]["code"] == "GRID_TOO_LARGE"
    assert res.json()["error"]["details"] == {"n": 10000, "limit": 5000}
    assert v.post("/api/jobs/walkforward", json={"spec": big, "walkforward": {"train_days": 100, "test_days": 30}}).status_code == 422
    # 큐에 아무것도 안 들어갔다
    assert v.get("/api/jobs").json()["data"] == [] or all(j["kind"] != "optimize" for j in v.get("/api/jobs").json()["data"])


def test_no_variable_and_intraday_and_bad_config_rejected(v):
    fixed = spec_dict(params={"n": {"default": 20}, "m": {"default": 10}})
    r = v.post("/api/jobs/optimize", json={"spec": fixed})
    assert r.status_code == 422 and r.json()["error"]["code"] == "SPEC_INVALID" and "변수" in r.json()["error"]["message"]
    assert v.post("/api/jobs/optimize", json={"spec": SPEC, "config": {"train_pct": 150}}).status_code == 422
    assert v.post("/api/jobs/optimize", json={"spec": SPEC, "config": {"holdout_pct": 5}}).status_code == 400  # 명세 validation 에 둔다
    assert v.post("/api/jobs/optimize", json={"spec": SPEC, "config": {"vary": ["없는"]}}).status_code == 422
    assert v.post("/api/jobs/optimize", json={"spec": {"name": "x"}}).status_code == 400
    assert v.post("/api/jobs/optimize", json={}).status_code == 400


def test_walkforward_flow_and_folds(v, disp):
    body = {"spec": SPEC, "config": {"train_pct": 60}, "walkforward": {"train_days": 120, "test_days": 40}}
    rid, job = run(v, disp, "/api/jobs/walkforward", body)
    assert job["status"] == "succeeded", job
    folds = v.get(f"/api/runs/{rid}/folds").json()["data"]
    assert folds["config"]["mode"] == "rolling" and len(folds["folds"]) >= 1
    assert v.get(f"/api/runs/{rid}").json()["data"]["has_folds"]
    bad = v.post("/api/jobs/walkforward", json={"spec": SPEC, "walkforward": {"train_days": 0, "test_days": 40}})
    assert bad.status_code == 422
    assert v.post("/api/jobs/walkforward", json={"spec": SPEC}).status_code == 400
    assert v.post("/api/jobs/walkforward", json={"spec": SPEC, "walkforward": {"train_days": 50, "test_days": 40, "step_days": 10}}).status_code == 422


def test_holdout_history_and_open(v, disp):
    h = v.post("/api/validation/holdout-history", json={"spec": SPEC}).json()["data"]
    assert h["count"] == 0 and h["ledger_connected"] and h["opens"] == []
    ov = {"n": 20, "m": 10}
    rid, job = run(v, disp, "/api/jobs/holdout-check", {"spec": SPEC, "overrides": ov})
    assert job["status"] == "succeeded", job
    assert v.get(f"/api/runs/{rid}").json()["data"]["summary"]["holdout"]["nth_open"] == 1
    # 손절 같은 리터럴을 바꿔도 골격이 같으면 같은 전략으로 센다
    tweaked = dict(SPEC, exits={"stop_loss_pct": 8})
    h = v.post("/api/validation/holdout-history", json={"spec": tweaked}).json()["data"]
    assert h["count"] == 1
    rid2, _ = run(v, disp, "/api/jobs/holdout-check", {"spec": tweaked, "overrides": ov})
    assert v.get(f"/api/runs/{rid2}").json()["data"]["summary"]["holdout"]["nth_open"] == 2
    assert any("2번째" in w for w in v.get(f"/api/runs/{rid2}").json()["data"]["warnings"])
    assert v.post("/api/jobs/holdout-check", json={"spec": SPEC, "overrides": {"없는": 1}}).status_code == 422
    assert v.post("/api/jobs/holdout-check", json={"spec": SPEC, "overrides": {"n": "x"}}).status_code == 400


def test_history_without_ledger_is_empty_not_error(client):
    h = client.post("/api/validation/holdout-history", json={"spec": SPEC}).json()["data"]
    assert h["count"] == 0 and h["ledger_connected"] is False


def test_grid_of_plain_backtest_is_404(client, disp):
    from tests.studio.api.conftest import make_run
    rid = make_run(client, disp)
    assert client.get(f"/api/runs/{rid}/grid").status_code == 404
    assert client.get("/api/runs/..%2Fx/grid").status_code == 404


def test_spec_of_finished_optimize_cannot_be_patched(v, disp):
    rid, _ = run(v, disp, "/api/jobs/optimize", {"spec": SPEC, "config": CFG})
    r = v.patch(f"/api/runs/{rid}", json={"spec": {}})
    assert r.status_code == 400  # 사전 판정 기준은 실행 뒤 못 고친다


def test_criteria_result_is_json_safe_with_numpy_metrics():
    """실데이터 최적화가 저장 단계에서 죽었다(TypeError: bool is not JSON serializable) — 지표가 numpy 값이면 passed 가 np.bool_ 였다."""
    import json

    import numpy as np

    from studio.domain.validation import evaluate_criteria
    out = evaluate_criteria({"sharpe": 0.5, "max_drawdown_pct": 30}, {"sharpe": np.float64(1.0), "max_drawdown_pct": np.float64(40.0)})
    assert [c["passed"] for c in out] == [True, False]
    json.dumps(out)
