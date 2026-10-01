"""허브 API 라우터(datahub.api) — 설계 §8.3 L1 1~12 + 계약(types/data.ts) 모양 검사. 가짜 시계·가짜 수집기·임시 루트."""
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from datahub import api, catalog, collectors, ledger, locks
from jobrunner.store import JobStore

from .test_jobs_scheduler import world  # noqa: F401  (픽스처: 합성 일봉·지수·작업 저장소·가짜 수집기)

MARKET = datetime(2026, 9, 3, 10, 0)          # 정규장
NIGHT = datetime(2026, 9, 3, 21, 0)


@pytest.fixture
def client(world, monkeypatch):                # noqa: F811
    monkeypatch.setattr(api, "clock", lambda: world.clock["now"])
    monkeypatch.setattr(api, "CACHE_SECONDS", 0)
    app = FastAPI()
    app.state.store = world.store
    app.state.dispatcher = None
    app.include_router(api.router)
    c = TestClient(app)
    c.w = world
    return c


def get(c, path, **kw):
    r = c.get(path, **kw)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def err(r, status, code):
    assert r.status_code == status, r.text
    e = r.json()["error"]
    assert e["code"] == code and set(e) == {"code", "message", "details"}
    return e


# ---------- §8.3 L1 ----------


def test_l1_1_overview_shape(client):
    d = get(client, "/api/data/overview")
    assert set(d) == {"now", "datasets", "activity", "alerts_active", "daily_catchup"}
    assert set(d["now"]) == {"ts", "window", "sophie_hours", "bulk"} and d["now"]["window"] == "night"
    assert set(d["now"]["sophie_hours"]) == {"connect_from", "open", "close", "connect_to", "source"}
    assert len(d["datasets"]) == 18 and [x["id"] for x in d["datasets"]] == [x.id for x in catalog.load().datasets]  # 2026-09-28 rs_* 4개 + sectors_stockeasy
    assert {x["verdict"] for x in d["datasets"]} <= {"good", "warn", "bad"}
    for x in d["datasets"]:
        assert {"id", "label", "basis", "verdict", "reason", "retention", "last_write", "lock"} <= set(x)
    assert d["daily_catchup"] is None and d["now"]["bulk"]["decision"] == "allow_now"


def test_l1_2_policy_market_hours_schedule_only(client):
    client.w.clock["now"] = MARKET
    d = get(client, "/api/data/policy?kind=collect_minute_al&mode=sophie_baseline")
    assert (d["decision"], d["window"], d["weight"]) == ("schedule_only", "market", "heavy")
    assert d["suggest_at"] == "2026-09-03T20:10:00" and d["baseline_effect"] == "updated" and d["blocked"] is None
    assert d["eta_sec"] == 5160 and "86분" in d["estimate_basis"]
    assert set(d) == {"kind", "mode", "weight", "window", "decision", "suggest_at", "reason", "warnings", "n_codes", "eta_sec",
                      "estimate_basis", "baseline_effect", "blocked"}
    e = get(client, "/api/data/policy?kind=collect_daily&mode=codes&codes=005930,000660")
    assert e["weight"] == "light" and e["decision"] == "needs_confirm" and e["n_codes"] == 2 and e["baseline_effect"] is None
    err(client.get("/api/data/policy?kind=nope"), 400, "VALIDATION_ERROR")


def test_l1_3_post_market_hours_now_is_422(client):
    client.w.clock["now"] = MARKET
    e = err(client.post("/api/data/jobs/collect-minute-al", json={"mode": "sophie_baseline", "when": "now"}), 422, "SOPHIE_MARKET_HOURS")
    assert e["details"]["suggest_at"] == "2026-09-03T20:10:00"
    assert client.w.jobs() == []                                                 # 작업이 만들어지지 않았다


def test_l1_4_minute_refresh_running_is_409(client):
    client.w.clock["now"] = NIGHT
    d = client.w.root / "state/minute_refresh"
    d.mkdir(parents=True)
    (d / "last_run_started.json").write_text(json.dumps({"started_at": time.time() - 60}), encoding="utf-8-sig")
    err(client.post("/api/data/jobs/collect-minute-al", json={"mode": "sophie_baseline", "when": "now"}), 409, "MINUTE_REFRESH_RUNNING")
    assert get(client, "/api/data/policy?kind=collect_minute_al&mode=sophie_baseline")["blocked"]["code"] == "MINUTE_REFRESH_RUNNING"


def test_l1_5_live_lock_owner_is_409_locked(client):
    client.w.clock["now"] = NIGHT
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        time.sleep(0.3)
        lf = locks.lock_file("daily_minute")
        lf.parent.mkdir(parents=True, exist_ok=True)
        lf.write_bytes(f"{p.pid}:1:x".encode())
        e = err(client.post("/api/data/jobs/collect-daily", json={"mode": "stale", "when": "now"}), 409, "LOCKED")
        assert e["details"]["pid"] == p.pid and e["details"]["owner"]["alive"] is True
        rows = {r["resource"]: r for r in get(client, "/api/data/locks")}
        assert set(rows) == {"daily_minute", "minute_al", "tick_al", "rs_rating", "program_al"} and rows["daily_minute"]["held"] and not rows["tick_al"]["held"]  # 2026-09-28 rs_rating 잠금 추가
        assert rows["daily_minute"]["owner"]["pid"] == p.pid and rows["daily_minute"]["covers"] == ["daily", "minute_krx", "index"]
    finally:
        p.kill()


def test_l1_6_collect_busy_is_409(client):
    client.w.clock["now"] = NIGHT
    from datahub import jobs
    j = jobs.create_job(client.w.store, "collect_daily", {"mode": "stale"}, trigger="hub")
    client.w.store.transition(j["job_id"], {"queued"}, status="running")
    e = err(client.post("/api/data/jobs/collect-daily", json={"mode": "stale", "when": "now"}), 409, "COLLECT_BUSY")
    assert e["details"]["job_id"] == j["job_id"]
    ok = client.post("/api/data/jobs/archive-minute-al", json={})                    # 로컬 작업은 수집 한도와 무관
    assert ok.status_code == 202


def test_l1_7_bad_codes_is_400_field_errors(client):
    client.w.clock["now"] = NIGHT
    e = err(client.post("/api/data/jobs/collect-daily", json={"mode": "codes", "codes": ["12345"], "when": "now"}), 400, "VALIDATION_ERROR")
    assert "codes" in e["details"]["fieldErrors"]
    e = err(client.post("/api/data/jobs/collect-daily", json={"mode": "codes", "codes": [], "when": "now"}), 400, "VALIDATION_ERROR")
    assert "codes" in e["details"]["fieldErrors"]
    e = err(client.post("/api/data/jobs/collect-minute-al", json={"mode": "deep_archive", "codes": ["005930"], "days": 10}), 400, "VALIDATION_ERROR")
    assert "days" in e["details"]["fieldErrors"]
    e = err(client.post("/api/data/jobs/collect-daily", json={"mode": "stale", "when": "scheduled"}), 400, "VALIDATION_ERROR")
    assert "scheduled_at" in e["details"]["fieldErrors"]


def test_l1_8_ticks_out_of_window_is_422(client):
    client.w.clock["now"] = NIGHT
    e = err(client.post("/api/data/jobs/collect-ticks", json={"mode": "range", "start": "2026-01-05", "end": "2026-01-06",
                                                             "universe": "default", "concurrency": 4, "when": "now"}), 422, "OUT_OF_TICK_WINDOW")
    assert e["details"]["window_start"] == status_first_day(client)
    err(client.post("/api/data/jobs/collect-ticks", json={"mode": "range", "start": "2026-09-02", "end": "2026-09-01", "universe": "default",
                                                         "concurrency": 4}), 400, "VALIDATION_ERROR")
    err(client.post("/api/data/jobs/collect-ticks", json={"mode": "range", "start": "2026-09-01", "end": "2026-09-02", "universe": "default",
                                                         "concurrency": 9}), 400, "VALIDATION_ERROR")


def status_first_day(client):
    return get(client, "/api/data/tick-window")["dates"][0]["date"]


def test_l1_9_ticks_scheduled_is_202(client):
    at = "2026-09-03T22:00:00"
    r = client.post("/api/data/jobs/collect-ticks", json={"mode": "catch_up", "when": "scheduled", "scheduled_at": at})
    assert r.status_code == 202, r.text
    d = r.json()["data"]
    assert d["status"] == "scheduled" and d["scheduled_at"] == at and set(d) == {"job_id", "status", "scheduled_at"}
    (job,) = client.w.jobs("collect_ticks")
    assert job["status"] == "scheduled" and job["trigger"] == "user"
    client.w.clock["now"] = MARKET                                                 # 정규장 안 시각으로 예약은 400
    e = err(client.post("/api/data/jobs/collect-ticks", json={"mode": "catch_up", "when": "scheduled", "scheduled_at": "2026-09-03T11:00:00"}), 400, "VALIDATION_ERROR")
    assert "scheduled_at" in e["details"]["fieldErrors"]


def test_l1_9b_ticks_now_at_night_and_nothing_to_do(client):
    client.w.clock["now"] = NIGHT
    r = client.post("/api/data/jobs/collect-ticks", json={"mode": "catch_up", "when": "now"})
    assert r.status_code == 202 and r.json()["data"]["status"] == "queued"
    from .test_jobs_scheduler import all_missing, collect
    collect(client.w, all_missing(client.w))
    r = client.post("/api/data/jobs/collect-ticks", json={"mode": "catch_up", "when": "now"})
    assert r.status_code == 200 and r.json() == {"data": {"nothing_to_do": True}}


def test_l1_10_schedule_patch(client):
    err(client.patch("/api/data/schedules/daily_report", json={"enabled": False}), 409, "NOT_HUB_OWNED")
    err(client.patch("/api/data/schedules/nope", json={"enabled": False}), 404, "NOT_FOUND")
    r = client.patch("/api/data/schedules/tick_nightly", json={"enabled": False, "time": "20:30"})
    assert r.status_code == 200
    row = r.json()["data"]
    assert row["enabled"] is False and row["time"] == "20:30" and row["editable"] is True
    err(client.patch("/api/data/schedules/tick_nightly", json={"time": "25:00"}), 400, "VALIDATION_ERROR")
    err(client.patch("/api/data/schedules/daily_catchup", json={"time": "06:00"}), 400, "VALIDATION_ERROR")      # 시각이 없는 일정
    rows = get(client, "/api/data/schedules")
    assert [r["id"] for r in rows] == [s.id for s in catalog.load().schedules] and len(rows) == 10  # 09-30 program_nightly
    ext = next(r for r in rows if r["id"] == "daily_report")
    assert ext["enabled"] is None and ext["editable"] is False and ext["runs"] == []
    keys = {"id", "label", "owner", "when", "does", "enabled", "editable", "time", "last_started", "last_finished", "last_ok", "last_result",
            "next_expected", "missed", "missed_note", "runs"}
    assert all(set(r) == keys for r in rows)


def test_l1_11_sophie(client):
    logs = client.w.root / "kospi-theme-engine/logs"
    logs.mkdir(parents=True)
    (logs / "minute_refresh.log").write_text("2026-09-19 21:12:00 완료 · 실패 13종목 · 보유 2041종목\n", encoding="utf-8")
    d = get(client, "/api/data/sophie")
    assert d["hours"]["source"].startswith("기본값") and d["minute_refresh"]["last_result"] == "완료 · 실패 13종목 · 보유 2041종목"
    assert set(d) == {"engine", "hours", "minute_refresh", "baseline", "universe_daily", "restart", "contract"} and len(d["contract"]) == 10


def test_l1_12_ledger_human_source_and_filters(client):
    def run(run_id, cmd, lock, writer, trigger="external", job_id=None):
        base = {"run": run_id, "lock": lock, "writer": writer, "trigger": trigger, "job_id": job_id, "pid": 1, "cmd": cmd, "detail": {"k": 1}, "done": None, "total": None}
        ledger.append({"event": "start", "ok": None, "error": None, **base})
        ledger.append({"event": "end", "ok": True, "error": None, **base})
    run("r1", "python daily_report_job.py", "daily_minute", "backfill_universe")
    run("r2", "python -m backtesting.cli dashboard", "daily_minute", "update_top35")
    run("r3", "python -m scripts.fetch_minute --codes 1", "minute_al", "fetch_minute")
    run("r4", "python backfill_universe.py", "daily_minute", "backfill_universe", "hub", "20260925-201000-a1b2c3")
    run("r5", "python x.py", "tick_al", "manual_script")
    rows = get(client, "/api/data/ledger")
    assert {r["run"]: r["source"] for r in rows} == {"r1": "야간 갱신", "r2": "8765", "r3": "소피증권", "r4": "허브", "r5": "수동"}
    assert rows[0]["ts"] >= rows[-1]["ts"]                                         # 최신이 앞
    assert set(rows[0]) == {"run", "ts", "ended", "duration_sec", "lock", "writer", "source", "trigger", "job_id", "state", "done", "total", "detail", "error"}
    assert all(r["state"] == "완료" and r["ended"] and r["detail"] == {"k": 1} for r in rows)
    assert {r["run"] for r in get(client, "/api/data/ledger?lock=minute_al")} == {"r3"}
    assert {r["run"] for r in get(client, "/api/data/ledger?source=허브")} == {"r4"}
    assert len(get(client, "/api/data/ledger?limit=2")) == 2
    err(client.get("/api/data/ledger?lock=bad"), 400, "VALIDATION_ERROR")
    err(client.get("/api/data/ledger?limit=501"), 400, "VALIDATION_ERROR")
    assert get(client, "/api/data/ledger?since=2999-01-01") == []


# ---------- 나머지 엔드포인트 모양 ----------


def test_datasets_detail_and_404(client):
    d = get(client, "/api/data/datasets/tick_al")
    assert d["id"] == "tick_al" and d["path"].endswith("{date}.parquet") and d["schedule_ids"] == ["tick_nightly"]
    assert set(d) >= {"notes", "path", "writers", "readers", "freshness", "lock_owner", "recent_ledger", "schedule_ids"} and d["lock_owner"] is None
    err(client.get("/api/data/datasets/nope"), 404, "NOT_FOUND")


def test_tick_window_shape_and_retry(client):
    d = get(client, "/api/data/tick-window")
    assert set(d) == {"verdict", "reason", "window_days", "universe", "min_days_left", "dates", "auto", "note"} and len(d["dates"]) == 20
    assert set(d["dates"][0]) == {"date", "status", "collected_codes", "expected_codes", "days_left", "missing_count", "missing_sample"}
    assert len(d["dates"][0]["missing_sample"]) <= 20 and d["dates"][0]["missing_count"] > 20
    assert set(d["auto"]) == {"schedule", "enabled", "next_run", "last_night", "given_up"} and d["auto"]["given_up"] == []
    pair = ("000000", d["dates"][0]["date"])
    for n in range(3):
        collectors.record_night([pair], datetime(2026, 9, 1 + n).date())
    d = get(client, "/api/data/tick-window")
    assert d["auto"]["given_up"] == [{"code": "000000", "name": None, "date": pair[1], "attempts": 3, "days_left": 0}]
    r = client.post("/api/data/tick-window/retry", json={"pairs": [{"code": pair[0], "date": pair[1]}]})
    assert r.status_code == 200 and r.json() == {"data": {"retried": 1}}
    assert client.post("/api/data/tick-window/retry", json={"pairs": "all"}).json() == {"data": {"retried": 0}}
    err(client.post("/api/data/tick-window/retry", json={"pairs": "some"}), 400, "VALIDATION_ERROR")


def test_stale_gaps_quality_archive_activity_alerts(client):
    s = get(client, "/api/data/stale")
    assert set(s) == {"dataset", "reference_date", "rows"} and s["rows"] == [] or set(s["rows"][0]) == {"code", "name", "last", "days_behind", "sophie", "inactive"}
    g = get(client, "/api/data/gaps?days=5")
    assert g["threshold"] == 0.9 and g["days"] == 5 and len(g["rows"]) == 5 and set(g["rows"][0]) == {"date", "codes", "share"}
    q = get(client, "/api/data/quality")
    assert set(q) == {"dataset", "since", "rows_checked", "counts", "issues"} and set(q["counts"]) == {"ohlc", "nonpositive", "duplicate_date", "jump", "zero_volume_run"}
    a = get(client, "/api/data/archive")
    assert set(a) == {"verdict", "reason", "codes_cache", "codes_archive", "missing_vs_cache", "missing_codes", "last_merge_at", "first_date", "last_date", "span_buckets"}
    assert get(client, "/api/data/activity") == [] and get(client, "/api/data/ledger/unledgered?hours=1") == []
    err(client.get("/api/data/stale?dataset=minute_al"), 400, "VALIDATION_ERROR")
    al = get(client, "/api/data/alerts")
    assert len(al["rules"]) == 9 and {a["id"] for a in al["active"]} == {"tick_window_loss"} and set(al["rules"][0])       # 합성 세계는 체결이 하나도 없다 == {"id", "title", "when", "enabled", "default_enabled", "last_sent", "last_message"}
    r = client.patch("/api/data/alerts/archive_behind", json={"enabled": False})
    assert r.status_code == 200 and r.json()["data"]["enabled"] is False and r.json()["data"]["default_enabled"] is True
    err(client.patch("/api/data/alerts/nope", json={"enabled": True}), 404, "NOT_FOUND")
    err(client.patch("/api/data/alerts/archive_behind", json={"enabled": "maybe"}), 400, "VALIDATION_ERROR")


def test_activity_shows_running_run_and_waiting_job(client):
    ledger.append({"event": "start", "run": "live1", "lock": "daily_minute", "writer": "backfill_universe", "trigger": "hub", "job_id": "20260925-000000-abc123",
                   "pid": __import__("os").getpid(), "cmd": "python backfill_universe.py", "detail": {}, "done": 5, "total": 10, "ok": None, "error": None})
    (row,) = get(client, "/api/data/activity")
    assert row["source"] == "허브" and row["state"] == "실행 중" and (row["done"], row["total"]) == (5, 10) and row["dataset"] == "daily"
    assert set(row) == {"source", "writer", "lock", "dataset", "state", "done", "total", "since", "run", "job_id"}


def test_overview_reports_active_alert_with_first_seen(client):
    cdir = catalog.path("minute_al", code="x").parent
    cdir.mkdir(parents=True)
    (cdir / "005930.csv").write_text("date,open,high,low,close,volume\n2026-09-01 09:00:00,1,1,1,1,1\n", encoding="utf-8")     # 보관소에 없는 캐시
    d = get(client, "/api/data/overview")
    (a,) = [x for x in d["alerts_active"] if x["id"] == "archive_behind"]
    assert a["title"] == "분봉 보관 누락" and a["first_seen"] == "2026-09-03T21:00:00" and set(a) == {"id", "title", "target", "message", "first_seen"}
    client.w.clock["now"] += timedelta(minutes=30)
    d = get(client, "/api/data/overview")
    assert [x["first_seen"] for x in d["alerts_active"] if x["id"] == "archive_behind"] == ["2026-09-03T21:00:00"]      # 계속이면 처음 시각 유지
    assert [x["id"] for x in get(client, "/api/data/alerts")["active"]] == [x["id"] for x in d["alerts_active"]]


def test_submit_creates_job_with_expected_kind_and_payload(client):
    client.w.clock["now"] = NIGHT
    r = client.post("/api/data/jobs/collect-daily", json={"mode": "codes", "codes": ["005930", "000660"], "when": "now"})
    assert r.status_code == 202 and r.json()["data"]["status"] == "queued"
    (j,) = client.w.jobs("collect_daily")
    assert j["payload"] == {"mode": "codes", "codes": ["005930", "000660"]} and j["group"] == "collect" and j["lock"] == "daily_minute"
    r = client.post("/api/data/jobs/collect-minute-al", json={"mode": "deep_archive", "codes": ["005930"], "days": 60, "when": "scheduled",
                                                                "scheduled_at": "2026-09-04T01:00:00"})
    assert r.status_code == 202
    (m,) = client.w.jobs("collect_minute_al")
    assert m["payload"] == {"mode": "deep_archive", "codes": ["005930"], "days": 60} and m["status"] == "scheduled"
    assert client.w.jobs("collect_daily")[0]["job_id"] == j["job_id"]


def test_needs_confirm_in_sophie_live_hours(client):
    client.w.clock["now"] = datetime(2026, 9, 3, 16, 0)                            # 소피증권 가동, 정규장 밖 — 대량은 확인 후
    e = err(client.post("/api/data/jobs/collect-daily", json={"mode": "stale", "when": "now"}), 422, "SOPHIE_LIVE_CONFIRM")
    assert e["details"]["suggest_at"] == "2026-09-03T20:10:00"
    r = client.post("/api/data/jobs/collect-daily", json={"mode": "stale", "when": "now", "confirm": True})
    assert r.status_code == 202


def test_router_module_is_the_only_fastapi_importer():
    """구조: datahub 안에서 fastapi 를 import 하는 파일은 api.py 하나뿐."""
    import ast
    from pathlib import Path
    root = Path(api.__file__).parent
    for f in root.glob("*.py"):
        mods = {n.module.split(".")[0] if isinstance(n, ast.ImportFrom) and n.module else a.name.split(".")[0]
                for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in getattr(n, "names", [])}
        assert ("fastapi" in mods) == (f.name == "api.py"), f.name


def test_overview_cache_60s_and_invalidated_by_submit(client, monkeypatch):
    assert "CACHE_SECONDS = 60.0" in __import__("pathlib").Path(api.__file__).read_text(encoding="utf-8")     # 설계 §8.9 (픽스처가 테스트용으로 0 으로 덮으므로 소스로 확인)
    monkeypatch.setattr(api, "CACHE_SECONDS", 60.0)
    api._cache.clear()
    calls = []
    real = api._overview
    monkeypatch.setattr(api, "_overview", lambda store, now: calls.append(now) or real(store, now))
    client.w.clock["now"] = NIGHT
    get(client, "/api/data/overview")
    client.w.clock["now"] += timedelta(seconds=30)
    get(client, "/api/data/overview")
    assert len(calls) == 1                                                        # 60초 안에는 다시 계산하지 않는다
    assert client.post("/api/data/jobs/archive-minute-al", json={}).status_code == 202
    get(client, "/api/data/overview")
    assert len(calls) == 2                                                        # 작업을 제출하면 캐시를 비운다
