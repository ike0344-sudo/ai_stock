"""§8.3 L1 — 13(백테스트 잡→run_id→succeeded)·16(ID 형식 위반 404)·18(예약 잡 취소)·19(로그 이어받기·가림) + 목록·오류 봉투.

번호 12(`/api/data/ledger`)는 허브 API 라 이번 범위에 없다(데이터 허브 라우터는 lead 가 따로 넣는다).
"""
import psutil

from tests.studio.application.fakes import spec_dict

BT_SPEC = spec_dict(universe={"type": "top_value", "n": 4, "exclude": []})


def err(res, status, code):
    assert res.status_code == status, res.text
    body = res.json()
    assert list(body) == ["error"] and body["error"]["code"] == code
    assert {"message", "details"} <= set(body["error"])
    return body["error"]


def test_13_backtest_job_to_succeeded_with_run_id(client, disp, fake_deps):
    res = client.post("/api/jobs/backtest", json=BT_SPEC)
    assert res.status_code == 202
    data = res.json()["data"]
    job_id, run_id = data["job_id"], data["run_id"]
    got = client.get(f"/api/jobs/{job_id}").json()["data"]
    assert got["status"] == "queued" and got["run_id"] == run_id and got["group"] == "compute"
    disp.tick()  # 대기열 → (인라인) 실행
    got = client.get(f"/api/jobs/{job_id}").json()["data"]
    assert got["status"] == "succeeded", got
    assert got["progress"]["pct"] == 100.0 and got["error"] is None and got["run_id"] == run_id
    rec = fake_deps.load(run_id)  # results/studio/<run_id> 에 실제로 저장됐다
    assert rec.summary["metrics"] and rec.run_id == run_id
    assert "payload" not in got and "handler" not in got and "pid" not in got  # 내부 값은 안 내보낸다
    listed = client.get("/api/jobs", params={"status": "succeeded", "kind": "backtest"}).json()["data"]
    assert [j["job_id"] for j in listed] == [job_id]


def test_backtest_job_failure_is_visible(client, disp, monkeypatch, fake_deps):
    spec = dict(BT_SPEC, period={"start": "2010-01-01", "end": "2010-12-31"})  # 데이터 범위 밖
    job_id = client.post("/api/jobs/backtest", json=spec).json()["data"]["job_id"]
    disp.tick()
    got = client.get(f"/api/jobs/{job_id}").json()["data"]
    assert got["status"] == "failed" and got["error"]
    assert "Traceback" in client.get(f"/api/jobs/{job_id}/log").json()["data"]["text"]


def test_backtest_validation_errors(client):
    e = err(client.post("/api/jobs/backtest", json={"version": 1, "mode": "nope"}), 400, "VALIDATION_ERROR")
    assert e["details"]["fieldErrors"]
    err(client.post("/api/jobs/backtest", content=b"{not json", headers={"content-type": "application/json"}),
        400, "VALIDATION_ERROR")
    bad = dict(BT_SPEC, params={"x": {"default": 5, "min": 1, "max": 3}})
    assert client.post("/api/jobs/backtest", json=bad).status_code in (400, 422)


def test_16_bad_id_is_404_not_500(client):
    for bad in ("..%2Fx", "20260925-201000-ZZZZZZ", "x", "20990101-000000-abcdef"):
        err(client.get(f"/api/jobs/{bad}"), 404, "NOT_FOUND")
        err(client.get(f"/api/jobs/{bad}/log"), 404, "NOT_FOUND")
        err(client.post(f"/api/jobs/{bad}/cancel"), 404, "NOT_FOUND")


def test_unknown_api_path_is_json_404(client):
    err(client.get("/api/nope"), 404, "NOT_FOUND")
    err(client.post("/api/nope/x"), 404, "NOT_FOUND")


def test_18_cancel_scheduled_never_runs(client, store, disp):
    job = store.create("collect_daily", "collect", "datahub.jobs:collect_daily", {}, scheduled_at="2099-01-01T00:00:00")
    res = client.post(f"/api/jobs/{job['job_id']}/cancel")
    assert res.status_code == 200 and res.json()["data"]["status"] == "cancelled"
    disp.tick()
    got = store.read(job["job_id"])
    assert got["status"] == "cancelled" and got["started_at"] is None and got["pid"] is None
    err(client.post(f"/api/jobs/{job['job_id']}/cancel"), 409, "JOB_NOT_CANCELLABLE")  # 끝난 잡


def test_cancel_only_writes_flag_for_running_job(client, store):
    job = store.create("x", "local", "studio.application.jobs:run_backtest_job", {})
    me = psutil.Process()  # 살아 있는 워커 흉내 — 디스패처의 생존 확인을 통과한다
    store.transition(job["job_id"], {"queued"}, status="running", pid=me.pid, pid_create_time=me.create_time())
    res = client.post(f"/api/jobs/{job['job_id']}/cancel")
    assert res.json()["data"] == {"job_id": job["job_id"], "status": "running", "cancel_requested": True}
    assert store.cancel_requested(job["job_id"])
    assert client.get(f"/api/jobs/{job['job_id']}").json()["data"]["cancel_requested"] is True


def test_19_log_resume_and_masking(client, store):
    job = store.create("x", "local", "studio.application.jobs:run_backtest_job", {})
    jid = job["job_id"]
    # 바이트로 써서 Windows 의 \n→\r\n 변환을 피한다(실제 로그는 child.py 가 newline="\n" 으로 쓴다)
    store.log_path(jid).write_bytes(
        "첫 줄\nkey=sk-test-SECRET-VALUE-123456\nAuthorization: Bearer abcdefghijklmnop1234\n".encode("utf-8"))
    first = client.get(f"/api/jobs/{jid}/log").json()["data"]
    assert first["eof"] and "sk-test" not in first["text"] and "abcdefghijklmnop" not in first["text"]
    assert "첫 줄" in first["text"] and "key=****" in first["text"] and "Bearer ****" in first["text"]
    off = first["next_offset"]
    with store.log_path(jid).open("ab") as f:
        f.write("새 줄\n".encode("utf-8"))
    more = client.get(f"/api/jobs/{jid}/log", params={"offset": off}).json()["data"]
    assert more["text"] == "새 줄\n" and more["eof"] and more["next_offset"] > off  # N 이후만
    assert client.get(f"/api/jobs/{jid}/log", params={"offset": 99999}).json()["data"]["text"] == ""
    err(client.get(f"/api/jobs/{jid}/log", params={"offset": -1}), 400, "VALIDATION_ERROR")


def test_log_of_job_without_log_file(client, store):
    job = store.create("x", "local", "studio.application.jobs:run_backtest_job", {})
    assert client.get(f"/api/jobs/{job['job_id']}/log").json()["data"] == {"text": "", "next_offset": 0, "eof": True}


def test_list_filters_and_validation(client, store):
    for g in ("collect", "local", "compute"):
        store.create("k_" + g, g, "studio.application.jobs:run_backtest_job", {})
    rows = client.get("/api/jobs").json()["data"]
    assert len(rows) == 3 and all(r["progress"]["pct"] is None and r["cancel_requested"] is False for r in rows)
    assert len(client.get("/api/jobs", params={"group": "local"}).json()["data"]) == 1
    assert len(client.get("/api/jobs", params={"limit": 2}).json()["data"]) == 2
    e = err(client.get("/api/jobs", params={"status": "bogus", "group": "bogus"}), 400, "VALIDATION_ERROR")
    assert set(e["details"]["fieldErrors"]) == {"status", "group"}
    err(client.get("/api/jobs", params={"limit": 0}), 400, "VALIDATION_ERROR")


def test_meta_status_counts_active_jobs(client, store):
    assert client.get("/api/meta/status").json()["data"]["jobs"] == {"scheduled": 0, "queued": 0, "running": 0}
    store.create("a", "local", "studio.application.jobs:run_backtest_job", {})
    store.create("b", "local", "studio.application.jobs:run_backtest_job", {}, scheduled_at="2099-01-01T00:00:00")
    j = store.create("c", "compute", "studio.application.jobs:run_backtest_job", {})
    store.transition(j["job_id"], {"queued"}, status="running")
    data = client.get("/api/meta/status").json()["data"]
    assert data["jobs"] == {"scheduled": 1, "queued": 1, "running": 1} and data["engine_version"]


def test_unexpected_error_is_500_envelope_without_leak(root, disp, fake_deps, monkeypatch):
    from fastapi.testclient import TestClient
    from studio.api.app import create_app
    app = create_app(root, dispatcher=disp)
    monkeypatch.setattr(disp.store, "list_active", lambda: 1 / 0)
    c = TestClient(app, base_url="http://127.0.0.1:8780", raise_server_exceptions=False)
    e = err(c.get("/api/meta/status"), 500, "INTERNAL")
    assert "division" not in str(e) and "Traceback" not in str(e)


def test_static_files_served_after_api(root, disp, fake_deps):
    from fastapi.testclient import TestClient
    from studio.api.app import create_app
    static = root / "static" / "studio"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<html>스튜디오</html>", encoding="utf-8")
    c = TestClient(create_app(root, dispatcher=disp), base_url="http://127.0.0.1:8780")
    assert "스튜디오" in c.get("/").text
    assert c.get("/api/meta/status").status_code == 200
    err(c.get("/api/nope"), 404, "NOT_FOUND")
    assert c.get("/nope.js").status_code == 404


def test_meta_status_uses_dispatcher_counts_without_scanning_disk(client, store, disp, monkeypatch):
    """워치독 프로브 경로: tick 이 세어 둔 값을 읽고, 디스크(list_active)를 다시 훑지 않는다."""
    store.create("a", "local", "studio.application.jobs:run_backtest_job", {}, scheduled_at="2099-01-01T00:00:00")
    disp.tick()
    assert disp.last_counts == {"scheduled": 1, "queued": 0, "running": 0}
    monkeypatch.setattr(store, "list_active", lambda: 1 / 0)  # 훑으면 터진다
    data = client.get("/api/meta/status").json()["data"]
    assert data["jobs"] == {"scheduled": 1, "queued": 0, "running": 0}
