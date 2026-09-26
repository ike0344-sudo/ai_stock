"""허브 API(datahub/api.py)·스케줄러를 스튜디오 서버에 붙인 연결 검증 — 허브 자체 테스트는 tests/datahub/test_api.py 몫.

여기서 보는 것: 라우터가 캐치올(/api/{rest}) 앞에 붙었는지 · 앱 guard 가 허브 POST 에도 걸리는지(§8.3 #17) ·
서버 기동이 스케줄러를 켜고 끄는지(STUDIO_NO_SCHEDULER 로 끌 수 있는지).
"""
import pytest

from studio import __main__ as server_main


def test_hub_router_mounted_before_catch_all(client):
    r = client.get("/api/data/locks")
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert {x["resource"] for x in rows} == {"daily_minute", "minute_al", "tick_al"}
    # 허브에 없는 경로는 여전히 JSON 404 봉투(캐치올)
    res = client.get("/api/data/no-such-thing")
    assert res.status_code == 404 and res.json()["error"]["code"] == "NOT_FOUND"


def test_17_forged_origin_blocked_on_hub_post(client, store):
    body = {"mode": "stale", "when": "now"}
    res = client.post("/api/data/jobs/collect-daily", json=body, headers={"Origin": "http://evil.example"})
    assert res.status_code == 403 and res.json()["error"]["code"] == "ORIGIN_FORBIDDEN"
    assert store.list_jobs() == []  # 작업이 만들어지지 않았다
    for method, path in (("PATCH", "/api/data/schedules/tick_nightly"), ("PATCH", "/api/data/alerts/archive_behind"),
                         ("POST", "/api/data/tick-window/retry")):
        r = client.request(method, path, json={}, headers={"Origin": "http://evil.example"})
        assert r.status_code == 403, (method, path)


def test_hub_get_rejects_non_loopback_host(client):
    assert client.get("/api/data/locks", headers={"Host": "evil.example"}).status_code == 403


@pytest.fixture
def fake_server(monkeypatch, root):
    calls = {"start": [], "stop": 0, "run": 0}

    class Th:
        def stop(self):
            calls["stop"] += 1

    monkeypatch.setattr(server_main.scheduler, "start", lambda r, s: calls["start"].append((r, s)) or Th())
    monkeypatch.setattr(server_main.uvicorn, "run", lambda *a, **k: calls.__setitem__("run", calls["run"] + 1))
    monkeypatch.delenv("STUDIO_NO_SCHEDULER", raising=False)
    return calls


def test_server_starts_and_stops_scheduler(fake_server, root):
    assert server_main.main() == 0
    (r, store), = fake_server["start"]
    assert str(r) == str(root) and store.root == root
    assert fake_server["run"] == 1 and fake_server["stop"] == 1  # 종료 때 스케줄러도 멈춘다


def test_scheduler_can_be_switched_off(fake_server, monkeypatch):
    monkeypatch.setenv("STUDIO_NO_SCHEDULER", "1")
    assert server_main.main() == 0
    assert fake_server["start"] == [] and fake_server["stop"] == 0 and fake_server["run"] == 1
