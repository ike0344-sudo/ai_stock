"""실행 중 곡선이 실제 jobrunner progress.json → `/api/jobs/{id}` 의 progress.live_curve 로 나온다(인라인 러너 — 실제 JobContext)."""
from tests.studio.api.conftest import make_run
from tests.studio.application.fakes import spec_dict


def test_job_progress_carries_live_curve_after_a_backtest_job(client, disp, fake_deps):
    body = spec_dict(universe={"type": "top_value", "n": 4, "exclude": []})
    res = client.post("/api/jobs/backtest", json=body)
    assert res.status_code == 202, res.text
    disp.tick()
    job = client.get(f"/api/jobs/{res.json()['data']['job_id']}").json()["data"]
    assert job["status"] == "succeeded"
    curve = job["progress"]["live_curve"]
    assert 20 < len(curve) <= 300
    assert set(curve[0]) == {"date", "equity", "cash", "n_positions", "n_trades", "last_event"}
    assert [p["date"] for p in curve] == sorted(p["date"] for p in curve)
    # 목록에도 같은 progress 가 실린다 — 화면이 폴링 목록에서 곡선을 뺄지는 monitoring-agent 판단(편지)
    assert any("live_curve" in j["progress"] for j in client.get("/api/jobs").json()["data"])
