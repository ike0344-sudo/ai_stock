"""수집 작업 처리기(datahub.jobs) · 일정 실행기(datahub.scheduler): 허용 목록 · H13 · H16~H21. 가짜 시계 + 가짜 수집기."""
import json
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta

import pandas as pd
import psutil
import pytest

from datahub import alerts, catalog, collectors, jobs, ledger, scheduler, sophie, status
from datahub.calendar import Calendar
from jobrunner.dispatcher import Dispatcher
from jobrunner.store import JobStore
from jobrunner.worker import run_job

from .conftest import REPO
from .test_module2 import _synthetic_daily


@pytest.fixture
def world(hub_root, monkeypatch):
    """임시 루트에 합성 일봉 24거래일(08-03~09-03)·지수·작업 저장소. 수집기는 가짜, 소피증권 조회는 막는다."""
    monkeypatch.setenv(jobs.FAKE_ENV, "1")
    monkeypatch.setattr(sophie, "_http_get", lambda *a, **k: None)
    monkeypatch.setattr(sophie, "_engine_procs", lambda: [])
    d, days = _synthetic_daily(hub_root)
    idx = hub_root / "data/index/daily"
    idx.mkdir(parents=True)
    (idx / "001.csv").write_text("date,o\n" + "\n".join(f"{x},1" for x in days) + "\n", encoding="utf-8")
    store = JobStore(hub_root)
    clock = {"now": datetime(2026, 9, 3, 21, 0)}
    disp = Dispatcher(store, spawner=lambda jid: (run_job(store, jid), (0, 0.0))[1], clock=lambda: clock["now"])
    sent = []
    sch = scheduler.Scheduler(store, clock=lambda: clock["now"], sender=lambda m: sent.append(m) or True)

    class W:
        pass
    w = W()
    w.root, w.store, w.disp, w.clock, w.sch, w.sent, w.days = hub_root, store, disp, clock, sch, sent, days
    monkeypatch.setattr(jobs, "clock", lambda: clock["now"])
    w.tick = lambda: sch.tick(clock["now"])
    w.run = lambda: [disp.tick() for _ in range(3)]            # 예약 승격 + 대기열 실행(가짜 수집기는 인라인 워커 안에서 자식으로 돈다)
    w.jobs = lambda kind=None: sorted(store.list_jobs(kind=kind, limit=50), key=lambda j: j["created_at"])
    return w


def run_now(store, job_id) -> str:
    """대기열을 거치지 않고 바로 running 으로 만들어 워커를 인라인으로 돌린다."""
    assert store.transition(job_id, {"queued"}, status="running")
    return run_job(store, job_id)


def collect(world, codes_days):
    """(종목, 날짜) 쌍을 수집된 것으로 표시한다."""
    for c, d in codes_days:
        p = catalog.path("tick_al", code=c, date=d).with_suffix(".csv")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("time\n", encoding="utf-8")


def all_missing(world, now=None):
    return status.tick_window(now or world.clock["now"], Calendar())["missing_pairs"]


# ---------- 허용 목록 (§7) ----------


def test_allow_list_accepts_hub_commands_and_rejects_others(hub_root):
    ok = [collectors.collect_daily("stale"), collectors.collect_daily("codes", codes=["005930"]),
          collectors.collect_ticks("2026-09-01", "2026-09-03", "x/codes.txt"), collectors.tick_compact(),
          collectors.collect_minute_al("codes", ["005930"]), collectors.collect_minute_al("deep_archive", ["005930"], 60),
          collectors.collect_minute_al("sophie_baseline")]
    for c in ok:
        jobs.check_command(c)
    bad = [collectors.Command(["cmd", "/c", "echo"], str(hub_root)),
           collectors.Command([sys.executable, "evil.py"], str(hub_root)),
           collectors.Command([sys.executable, "-c", "print(1)"], str(hub_root)),
           collectors.Command([sys.executable, "backfill_universe.py"], "C:/elsewhere"),        # 작업 폴더가 다르다
           collectors.Command(["powershell", "-File", "evil.ps1"], str(hub_root)),
           collectors.Command([], str(hub_root))]
    for c in bad:
        with pytest.raises(jobs.CommandNotAllowed):
            jobs.check_command(c)
    with pytest.raises(jobs.CommandNotAllowed):                                                # 허용 ps1 이라도 인자를 더 붙이면 안 된다
        jobs.check_command(collectors.Command(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                               str(hub_root / "kospi-theme-engine/run_minute_refresh.ps1"), "-Now", "&&", "calc"],
                                              str(hub_root / "kospi-theme-engine")))


def test_job_kinds_and_handlers_use_allowed_prefix():
    from jobrunner.worker import check_handler_name
    for kind, (handler, group, lock) in jobs.KINDS.items():
        check_handler_name(handler)
        assert lock in catalog.load().locks and group in ("collect", "local")


# ---------- 처리기: 진행률·잠금 대기·장부 연결 ----------


def test_collect_daily_handler_records_ledger_and_progress(world, monkeypatch):
    monkeypatch.setattr(jobs, "POLL_SECONDS", 0.1)
    j = jobs.create_job(world.store, "collect_daily", {"mode": "codes", "codes": ["005930"]}, trigger="user")
    res = run_now(world.store, j["job_id"])
    assert res == "succeeded", (world.store.read(j["job_id"])["error"], world.store.log_path(j["job_id"]).read_text(encoding="utf-8")[-600:])
    job = world.store.read(j["job_id"])
    assert job["ledger_run"] and job["status"] == "succeeded"
    ev = [e for e in ledger.read(1) if e["run"] == job["ledger_run"]]
    assert {e["event"] for e in ev} == {"start", "progress", "end"} and ev[0]["trigger"] == "hub" and ev[0]["job_id"] == j["job_id"]
    assert world.store.read_progress(j["job_id"])["pct"] == 100.0


WAIT_SEEN_LIMIT = 300  # 상한일 뿐(통과는 보이는 즉시) — 부하 때 자식 기동이 수 분 밀린 실측(30개 CPU 점유 시 174초)


def test_handler_reports_waiting_lock(world, monkeypatch):
    """다른 쓰기 작업이 잠금을 쥐고 있으면 작업 진행 기록에 waiting_lock(소유자)이 뜨고, 풀리면 끝난다."""
    from datahub import gate
    monkeypatch.setattr(jobs, "POLL_SECONDS", 0.2)
    monkeypatch.setenv("DATAHUB_WAIT_NOTICE_SECONDS", "0.5")
    j = jobs.create_job(world.store, "collect_daily", {"mode": "stale"})
    world.store.transition(j["job_id"], {"queued"}, status="running")
    seen, timeline = [], []
    t0 = time.monotonic()
    with gate.write("daily_minute", writer="blocker"):
        th = threading.Thread(target=run_job, args=(world.store, j["job_id"]))
        th.start()
        # 고정 30초 대기는 부하(전체 스위트·CPU 경합) 때 자식 프로세스 기동(pandas import)이 늦어 모자랐다 →
        # "waiting_lock 이 보일 때까지" 기다리되 상한만 넉넉히(통과는 보이는 즉시). 자식이 죽었으면 기다릴 이유가 없으니 그때도 나온다.
        while time.monotonic() - t0 < WAIT_SEEN_LIMIT and not seen and th.is_alive():
            p = world.store.read_progress(j["job_id"]) or {}
            if p.get("waiting_lock"):
                seen.append(p["waiting_lock"])
            if int((time.monotonic() - t0) * 5) % 25 == 0:  # 5초마다 한 컷 — 실패 때 어디서 멈췄는지 보이게
                lp = world.store.log_path(j["job_id"])
                timeline.append((round(time.monotonic() - t0, 1), p.get("stage"), p.get("message"), lp.stat().st_size if lp.exists() else None,
                                 [(c.pid, c.cmdline()[-3:], round(sum(c.cpu_times()[:2]), 1)) for c in psutil.Process().children(recursive=True)]))
            time.sleep(0.2)
        elapsed = time.monotonic() - t0
    th.join(WAIT_SEEN_LIMIT)
    diag = (f"waiting_lock 이 {elapsed:.1f}초 안에 안 보임 — job={world.store.read(j['job_id'])['status']}, "
            f"타임라인(초, 단계, 메시지, 로그크기)={timeline[-6:]}, log 끝: {world.store.log_path(j['job_id']).read_text(encoding='utf-8', errors='replace')[-600:]}")
    assert seen, diag
    assert seen[0]["resource"] == "daily_minute" and "python" in (seen[0]["owner"] or "").lower()
    assert world.store.read(j["job_id"])["status"] == "succeeded"


def test_archive_job_runs_in_process(world):
    from datahub import minute_al_archive as arch
    cdir = catalog.path("minute_al", code="x").parent
    cdir.mkdir(parents=True)
    idx = pd.date_range("2026-09-01 09:00", periods=5, freq="min", name="date")
    pd.DataFrame({"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}, index=idx).to_csv(cdir / "005930.csv")
    j = jobs.create_job(world.store, "archive_minute_al", {})
    assert run_now(world.store, j["job_id"]) == "succeeded"
    assert len(arch.read("005930")) == 5 and world.store.read(j["job_id"])["ledger_run"]


def test_minute_baseline_refuses_while_marker_running(world):
    d = world.root / "state/minute_refresh"
    d.mkdir(parents=True)
    (d / "last_run_started.json").write_text(json.dumps({"started_at": time.time() - 60}), encoding="utf-8-sig")
    j = jobs.create_job(world.store, "collect_minute_al", {"mode": "sophie_baseline"})
    assert run_now(world.store, j["job_id"]) == "failed"
    assert "MINUTE_REFRESH_RUNNING" in world.store.read(j["job_id"])["error"]


def test_ticks_range_outside_window_is_refused(world):
    j = jobs.create_job(world.store, "collect_ticks", {"mode": "range", "start": "2026-01-01", "end": "2026-01-02"})
    assert run_now(world.store, j["job_id"]) == "failed" and "OUT_OF_TICK_WINDOW" in world.store.read(j["job_id"])["error"]


# ---------- H13 서버가 꺼졌다 켜짐 · 꺼진 일정은 안 돈다 ----------


def test_h13_restart_runs_todays_pending_once_and_respects_switch(world):
    acts = world.tick()
    kinds = sorted(j["kind"] for j in world.jobs())
    assert kinds == ["archive_minute_al", "tick_nightly"]                       # 21:00 이후 — 오늘 밤 체결 + 보관소
    assert any("freshness_check" in a for a in acts)                              # 10분 점검도 첫 tick 에
    assert world.tick() == [] and len(world.jobs()) == 2                          # 두 번째 tick — 다시 만들지 않는다(active 작업 대기)
    world.clock["now"] += timedelta(minutes=5)
    assert world.tick() == []                                                     # 점검은 10분 뒤에
    with pytest.raises(scheduler.NotHubOwned):
        scheduler.set_schedule("daily_report", enabled=False)                    # 외부 일정은 못 고친다
    scheduler.set_schedule("tick_nightly", enabled=False)
    scheduler.set_schedule("minute_archive", enabled=False)
    scheduler.set_schedule("freshness_check", time="21:30")                        # 시각 형식 확인
    with pytest.raises(ValueError):
        scheduler.set_schedule("freshness_check", time="25:99")
    assert scheduler.schedule_enabled("tick_nightly") is False and scheduler.schedule_enabled("daily_catchup") is True


def test_h20_night_window_rules(world):
    """20:15 회차 시각에 서버가 꺼져 있었다: 야간 구간에 켜지면 즉시, 주간에 켜지면 다음 야간 시작에."""
    world.clock["now"] = datetime(2026, 9, 3, 10, 0)                              # 낮
    world.tick()
    assert [j["kind"] for j in world.jobs("tick_nightly")] == []
    world.clock["now"] = datetime(2026, 9, 4, 3, 0)                               # 자정 넘어 새벽 — 어젯밤(09-03)의 회차
    world.tick()
    j = world.jobs("tick_nightly")
    assert len(j) == 1 and j[0]["payload"]["night"] == "2026-09-03"
    assert scheduler.current_night(datetime(2026, 9, 4, 8, 9)) == date(2026, 9, 3) and scheduler.current_night(datetime(2026, 9, 4, 8, 10)) is None
    assert scheduler.current_night(datetime(2026, 9, 4, 20, 15)) == date(2026, 9, 4)


# ---------- H16 · H17 · H21 체결 야간 수집 ----------


def _nightly_kickoff(world, when=None):
    if when:
        world.clock["now"] = when
    world.tick()
    world.run()
    return world.jobs("tick_nightly")


def test_h16_missed_night_is_caught_up_in_one_run(world):
    """하룻밤을 통째로 건너뜀 — 다음 밤 회차가 그 날짜까지 **한 번에** 수집한다."""
    win = status.tick_window(world.clock["now"], Calendar())
    older = [(c, r["date"]) for r in win["dates"][:-2] for c in status.expected_tick_codes(
        pd.read_parquet(catalog.path("daily_all_cache")) if False else jobs._daily(), [date.fromisoformat(r["date"])], 35,
        set(catalog.dataset("tick_al").freshness["extra_codes"]), {"005930", "000660"}).get(date.fromisoformat(r["date"]), ())]
    collect(world, older)                                                          # 마지막 두 거래일(09-02·09-03)만 빠졌다
    pairs = all_missing(world)
    assert {d for _, d in pairs} == {win["dates"][-2]["date"], win["dates"][-1]["date"]}
    js = _nightly_kickoff(world)
    assert len(js) == 1 and js[0]["status"] == "succeeded"                         # 한 작업
    run = json.loads(jobs.tick_run_path(js[0]["job_id"]).read_text(encoding="utf-8"))
    assert run["start"] == win["dates"][-2]["date"] and run["end"] == win["dates"][-1]["date"] and run["planned"] == len(pairs)
    assert run["remaining"] == 0 and all_missing(world) == []
    world.tick()
    assert len(world.jobs("tick_nightly")) == 1                                    # 다 받았으니 같은 밤에 또 만들지 않는다
    st = json.loads((world.root / "state/datahub/schedule_state.json").read_text(encoding="utf-8"))["tick_nightly"]
    assert st["done"] is True and st["attempts"] == 1


def test_h16_nothing_to_do_makes_no_api_call(world):
    collect(world, all_missing(world))
    world.tick()
    assert world.jobs("tick_nightly") == []                                       # 빠진 게 없으면 작업 자체를 안 만든다
    st = json.loads((world.root / "state/datahub/schedule_state.json").read_text(encoding="utf-8"))["tick_nightly"]
    assert st["done"] is True and st["note"] == "받을 것 없음"


def test_h17_deferred_codes_are_not_failures_and_next_night_resumes(world, monkeypatch):
    monkeypatch.setenv("FAKE_TICK_DEFER", "3")                                     # --stop-at 로 뒤쪽 3종목을 시작 못 했다
    js = _nightly_kickoff(world)
    assert len(js) == 1 and js[0]["status"] == "succeeded"                         # 종료코드 0
    run = json.loads(jobs.tick_run_path(js[0]["job_id"]).read_text(encoding="utf-8"))
    assert run["deferred"] > 0 and run["failed"] == 0
    att = collectors.load_attempts()
    assert att["pairs"] == {} and att["nights_log"][-1]["deferred"] == run["deferred"]     # 실패 밤 수에 안 센다
    world.tick()
    assert len(world.jobs("tick_nightly")) == 1                                   # 같은 밤 재시도 없음
    monkeypatch.setenv("FAKE_TICK_DEFER", "0")
    world.clock["now"] += timedelta(days=1)                                        # 다음 밤 — 이어받는다
    js = _nightly_kickoff(world)
    assert len(js) == 2 and js[1]["payload"]["night"] == "2026-09-04" and all_missing(world) == []


def test_h21_same_night_retry_60min_max_3_and_not_for_deferred(world, monkeypatch):
    first_code = collectors.plan_tick_catch_up(status.tick_window(world.clock["now"], Calendar())).codes[0]
    monkeypatch.setenv("FAKE_TICK_FAIL", first_code)                              # 이 종목은 계속 못 받는다
    t0 = world.clock["now"] = datetime(2026, 9, 3, 20, 15)
    world.tick(); world.run(); world.tick()                                        # 1회 실행 -> 못 받은 게 있어 재시도 예약
    js = world.jobs("tick_nightly")
    assert len(js) == 2 and js[1]["status"] == "scheduled"                        # 60분 뒤로 예약됨
    assert js[1]["scheduled_at"] == (t0 + timedelta(minutes=60)).isoformat(timespec="seconds")
    world.clock["now"] += timedelta(minutes=61)
    world.run(); world.tick()                                                      # 2회 실행 -> 3회째 예약
    world.clock["now"] += timedelta(minutes=61)
    world.run(); world.tick()                                                      # 3회 실행 -> 소진
    js = world.jobs("tick_nightly")
    assert len(js) == 3 and all(j["status"] == "succeeded" for j in js)           # 하룻밤 최대 3회
    world.clock["now"] += timedelta(minutes=61)
    world.tick(); world.run()
    assert len(world.jobs("tick_nightly")) == 3                                   # 더는 안 만든다
    st = json.loads((world.root / "state/datahub/schedule_state.json").read_text(encoding="utf-8"))["tick_nightly"]
    assert st["attempts"] == 3 and st["done"] and "소진" in st["note"]


def test_h21_no_retry_when_next_slot_is_past_night_end(world):
    first = collectors.plan_tick_catch_up(status.tick_window(world.clock["now"], Calendar())).codes[0]
    os.environ["FAKE_TICK_FAIL"] = first
    try:
        world.clock["now"] = datetime(2026, 9, 4, 7, 30)                            # 09-03 밤의 끝자락 — +60분이면 08:30 (야간 구간 밖)
        world.tick(); world.run()
        world.tick()
        assert len(world.jobs("tick_nightly")) == 1
    finally:
        os.environ.pop("FAKE_TICK_FAIL")


def test_h18_three_failed_nights_give_up_alert_once_then_retry_restores(world, monkeypatch):
    first = collectors.plan_tick_catch_up(status.tick_window(world.clock["now"], Calendar())).codes[0]
    monkeypatch.setenv("FAKE_TICK_FAIL", first)
    monkeypatch.setattr(scheduler, "MAX_NIGHT_ATTEMPTS", 1)                          # 하룻밤 한 번씩만 — 밤 수를 세는 데 집중
    bad_pairs = {(c, d) for c, d in all_missing(world) if c == first}
    for n in range(3):
        world.clock["now"] = datetime(2026, 9, 3 + n, 20, 15)
        world.tick(); world.run(); world.tick()
    given = collectors.given_up_pairs()
    assert given and {p[0] for p in given} == {first} and bad_pairs & given          # 창이 밤마다 앞으로 밀려 날짜 집합은 달라진다
    world.clock["now"] = datetime(2026, 9, 6, 8, 30)
    ctx = {"trading_day": True, "given_up": [{"pair": "|".join(p), **collectors.load_attempts()["pairs"]["|".join(p)]} for p in given],
           "night_log": []}
    fired = alerts.evaluate(ctx, datetime(2026, 9, 6, 8, 30))
    assert {a.id for a in fired} == {"tick_given_up"} and len(fired) == len(given)              # 쌍마다 하나 — 같은 날 두 번은 dispatch 가 막는다
    plan = collectors.plan_tick_catch_up(status.tick_window(world.clock["now"], Calendar()))
    assert plan is None or given.isdisjoint(set(plan.pairs))                                     # 포기한 쌍은 계획에서 빠진다
    assert collectors.retry("all") == len(given)
    plan2 = collectors.plan_tick_catch_up(status.tick_window(world.clock["now"], Calendar()))
    assert plan2 is not None and first in plan2.codes                                # 되돌린 뒤 다시 계획에 포함


def test_h16_prereq_wait_up_to_2h(world):
    d = world.root / "state/daily_report"
    d.mkdir(parents=True)
    (d / "last_run_started.json").write_text(json.dumps({"started_at": time.time()}), encoding="utf-8")   # 야간 갱신이 도는 중
    assert any("선행 대기" in a for a in world.tick()) and world.jobs("tick_nightly") == []
    world.clock["now"] += timedelta(hours=1, minutes=59)
    assert any("선행 대기" in a for a in world.tick()) and world.jobs("tick_nightly") == []
    world.clock["now"] += timedelta(minutes=2)                                     # 2시간이 지나면 기다리지 않고 진행
    world.tick()
    assert len(world.jobs("tick_nightly")) == 1


# ---------- H19 일봉 아침 따라잡기 ----------


def _daily_csv(root, code, last, days=("2026-08-26", "2026-08-27", "2026-08-28")):
    d = root / "data/stocks/daily"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{code}.csv").write_text("date,open,high,low,close,volume\n" + "\n".join(f"{x},10,11,9,10,100" for x in days if x <= last) + "\n", encoding="utf-8")


@pytest.fixture
def morning(hub_root, monkeypatch):
    monkeypatch.setenv(jobs.FAKE_ENV, "1")
    monkeypatch.setattr(sophie, "_http_get", lambda *a, **k: None)
    monkeypatch.setattr(sophie, "_engine_procs", lambda: [])
    idx = hub_root / "data/index/daily"
    idx.mkdir(parents=True)
    (idx / "001.csv").write_text("date,o\n2026-08-26,1\n2026-08-27,1\n2026-08-28,1\n", encoding="utf-8")       # 목·금까지 (월 08-31 은 앞날)
    ref = hub_root / "kospi-theme-engine/dist/data/reference"
    ref.mkdir(parents=True)
    (ref / "universe.csv").write_text("code,name\nSOPHIE1,s\n", encoding="utf-8")
    store = JobStore(hub_root)
    return hub_root, store, scheduler.Scheduler(store, sender=lambda m: True)


def test_h19_monday_morning_normal_does_nothing(morning):
    root, store, sch = morning
    for c in ("AAA", "SOPHIE1", "BBB"):
        _daily_csv(root, c, "2026-08-28")                                            # 금요일까지 다 있다
    assert sch._daily_catchup(datetime(2026, 8, 31, 6, 0)) == []                    # 월요일 06:00 — 달력일 기준이면 전 종목이 밀림으로 오탐
    assert store.list_jobs(kind="daily_catchup") == []


def test_h19_friday_night_missed_catches_up_sophie_first_with_stop_at(morning):
    root, store, sch = morning
    for c in ("AAA", "SOPHIE1", "BBB"):
        _daily_csv(root, c, "2026-08-27")                                            # 목요일까지 — 금요일 밤 야간 갱신을 놓쳤다
    _daily_csv(root, "DEAD", "2026-08-26")                                           # 거래 중단으로 표시된 종목은 뺀다
    (root / "state/datahub").mkdir(parents=True)
    (root / "state/datahub/inactive_codes.json").write_text(json.dumps({"codes": {"DEAD": {"reason": "거래정지"}}}), encoding="utf-8")
    acts = sch._daily_catchup(datetime(2026, 8, 31, 6, 0))
    (job,) = store.list_jobs(kind="daily_catchup")
    assert job["payload"] == {"mode": "codes", "codes": ["SOPHIE1", "AAA", "BBB"], "stop_at": "08:10"} and job["trigger"] == "hub"
    assert sch._daily_catchup(datetime(2026, 8, 31, 6, 5)) == []                    # 하루 한 번
    # 08:10 까지 못 끝낸 상태(가짜 수집기는 파일을 안 바꾼다) -> 결과 기록 = 알림 재료
    store.transition(job["job_id"], {"queued"}, status="running")
    run_job(store, job["job_id"])
    sch._daily_catchup(datetime(2026, 8, 31, 8, 12))
    c = json.loads((root / "state/datahub/catchup.json").read_text(encoding="utf-8"))
    assert c["remaining"] == 3 and c["sophie_remaining"] == 1 and c["deadline_passed"] is True
    fired = alerts.evaluate({"catchup": c}, datetime(2026, 8, 31, 8, 12))
    assert [a.id for a in fired] == ["daily_catchup_incomplete"]


def test_h19_outside_morning_window_or_holiday_does_nothing(morning):
    root, store, sch = morning
    _daily_csv(root, "AAA", "2026-08-27")
    assert sch._daily_catchup(datetime(2026, 8, 31, 5, 0)) == []                    # 05:30 전
    assert sch._daily_catchup(datetime(2026, 8, 31, 8, 30)) == []                   # 08:10 뒤
    assert sch._daily_catchup(datetime(2026, 8, 29, 6, 0)) == []                    # 토요일
    assert store.list_jobs(kind="daily_catchup") == []


# ---------- 일정 화면 목록 ----------


def test_schedules_view_lists_hub_and_external(world):
    world.tick()
    rows = {r["id"]: r for r in scheduler.schedules_view(world.store, world.clock["now"])}
    assert rows["tick_nightly"]["editable"] and rows["tick_nightly"]["enabled"] and rows["tick_nightly"]["runs"][0]["result"] == "대기" and rows["tick_nightly"]["runs"][0]["ok"] is None and rows["tick_nightly"]["time"] == "20:15"
    assert not rows["daily_report"]["editable"] and rows["daily_report"]["enabled"] is None and rows["daily_report"]["runs"] == [] and rows["minute_refresh"]["next_expected"]
    assert set(rows) == {s.id for s in catalog.load().schedules}


def test_scheduler_thread_start_and_stop(world):
    th = scheduler.start(world.root, world.store, interval=0.05, sender=lambda m: True)
    time.sleep(0.5)
    th.stop(); th.join(5)
    assert not th.is_alive()
