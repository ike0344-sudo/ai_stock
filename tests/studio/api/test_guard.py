"""§8.3 L1 17(Origin 위조 403) + §7 보안 — Host 검사(리바인딩)·본문 상한·CORS 없음."""
import pytest

from tests.studio.application.fakes import spec_dict

BT = spec_dict(universe={"type": "top_value", "n": 4, "exclude": []})


def code(res):
    return res.json()["error"]["code"]


def test_17_forged_origin_is_403_and_creates_nothing(client, store):
    res = client.post("/api/jobs/backtest", json=BT, headers={"Origin": "http://evil.example"})
    assert res.status_code == 403 and code(res) == "ORIGIN_FORBIDDEN"
    assert store.list_jobs() == []  # 요청이 핸들러까지 가지 못했다


@pytest.mark.parametrize("origin", ["http://127.0.0.1:9999", "http://localhost:8780", "null", "https://127.0.0.1:8780"])
def test_origin_must_equal_host_exactly(client, origin):
    assert client.post("/api/jobs/backtest", json=BT, headers={"Origin": origin}).status_code == 403


def test_same_origin_and_no_origin_pass(client):
    ok = client.post("/api/jobs/backtest", json=BT, headers={"Origin": "http://127.0.0.1:8780"})
    assert ok.status_code == 202
    assert client.post("/api/jobs/backtest", json=BT).status_code == 202  # curl·서버 간 호출


def test_cross_site_fetch_metadata_rejected(client):
    res = client.post("/api/jobs/backtest", json=BT, headers={"Sec-Fetch-Site": "cross-site"})
    assert res.status_code == 403


def test_forged_origin_blocks_cancel_and_other_unsafe_methods(client, store):
    job = store.create("x", "local", "studio.application.jobs:run_backtest_job", {})
    bad = {"Origin": "http://evil.example"}
    assert client.post(f"/api/jobs/{job['job_id']}/cancel", headers=bad).status_code == 403
    assert not store.cancel_requested(job["job_id"])
    assert client.delete("/api/jobs/x", headers=bad).status_code == 403
    assert client.put("/api/nope", headers=bad).status_code == 403


def test_get_ignores_origin(client):
    assert client.get("/api/meta/status", headers={"Origin": "http://evil.example"}).status_code == 200


def test_dev_origin_env_allows_vite_only(client, monkeypatch):
    monkeypatch.setenv("STUDIO_DEV_ORIGIN", "http://localhost:5173")
    assert client.post("/api/jobs/backtest", json=BT, headers={"Origin": "http://localhost:5173"}).status_code == 202
    assert client.post("/api/jobs/backtest", json=BT, headers={"Origin": "http://evil.example"}).status_code == 403


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8780", "192.168.0.5:8780", "100.126.113.127:8780",
                                  "127.0.0.1.evil.example"])
def test_non_loopback_host_rejected_for_every_method(client, host):
    """DNS 리바인딩: 악성 도메인이 127.0.0.1 로 되돌아와도 Host 가 그 도메인이라 막힌다 — GET 도."""
    res = client.get("/api/meta/status", headers={"Host": host})
    assert res.status_code == 403 and code(res) == "ORIGIN_FORBIDDEN"
    res = client.post("/api/jobs/backtest", json=BT, headers={"Host": host, "Origin": f"http://{host}"})
    assert res.status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8780", "localhost:8780", "[::1]:8780"])
def test_loopback_hosts_accepted(client, host):
    assert client.get("/api/meta/status", headers={"Host": host}).status_code == 200


def test_body_over_256kb_is_413_by_content_length(client, store):
    res = client.post("/api/jobs/backtest", content=b"x" * (256 * 1024 + 1),
                      headers={"content-type": "application/json"})
    assert res.status_code == 413 and code(res) == "PAYLOAD_TOO_LARGE"
    assert store.list_jobs() == []


def test_body_over_256kb_is_413_when_streamed_without_length(client):
    def chunks():
        for _ in range(9):
            yield b"x" * (32 * 1024)

    res = client.post("/api/jobs/backtest", content=chunks(), headers={"content-type": "application/json"})
    assert res.status_code == 413 and code(res) == "PAYLOAD_TOO_LARGE"


def test_body_at_limit_is_not_413(client):
    res = client.post("/api/jobs/backtest", content=b"[" + b" " * (256 * 1024 - 2) + b"]",
                      headers={"content-type": "application/json"})
    assert res.status_code == 400  # 크기는 통과, 명세 형식 오류


def test_no_cors_headers_anywhere(client):
    res = client.get("/api/meta/status", headers={"Origin": "http://127.0.0.1:8780"})
    assert not [h for h in res.headers if h.lower().startswith("access-control-")]
    pre = client.options("/api/jobs/backtest", headers={"Origin": "http://evil.example",
                                                        "Access-Control-Request-Method": "POST"})
    assert not [h for h in pre.headers if h.lower().startswith("access-control-")]


def test_docs_and_openapi_are_off(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
