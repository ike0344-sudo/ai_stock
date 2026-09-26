import datetime as dt
import itertools
import threading
import time

import pytest

from jobrunner import dispatcher as dp
from jobrunner.dispatcher import Dispatcher
from tests.jobrunner.conftest import make

_pids = itertools.count(1000)


class Fake:
    """spawn·alive·kill 대역 — 실제 프로세스 없이 디스패처 판단만 본다."""

    def __init__(self):
        self.spawned, self.dead, self.killed, self.fail = [], set(), [], False

    def spawner(self, job_id):
        if self.fail:
            raise OSError("no exec")
        self.spawned.append(job_id)
        return next(_pids), 1.0

    def alive(self, pid, ct=None):
        return pid not in self.dead

    def killer(self, pid, ct=None):
        self.killed.append(pid)
        self.dead.add(pid)


@pytest.fixture
def fake():
    return Fake()


@pytest.fixture
def disp(store, fake):
    return Dispatcher(store, spawner=fake.spawner, alive=fake.alive, killer=fake.killer)


def status(store, j):
    return store.read(j["job_id"])["status"]


def test_group_limits_collect1_local1_compute2(store, disp, fake):
    jobs = {g: [make(store, "ok", group=g) for _ in range(3)] for g in ("collect", "local", "compute")}
    disp.tick()
    running = {g: sum(status(store, j) == "running" for j in js) for g, js in jobs.items()}
    assert running == {"collect": 1, "local": 1, "compute": 2}
    assert len(fake.spawned) == 4
    disp.tick()  # 자리가 안 났으니 그대로
    assert len(fake.spawned) == 4


def test_fifo_within_group_and_slot_frees_on_finish(store, disp, fake):
    a, b = make(store, "ok", group="collect"), make(store, "ok", group="collect")
    disp.tick()
    assert (status(store, a), status(store, b)) == ("running", "queued")
    store.transition(a["job_id"], {"running"}, status="succeeded")
    disp.tick()
    assert status(store, b) == "running" and fake.spawned == [a["job_id"], b["job_id"]]


def test_scheduled_waits_until_due(store, fake):
    clock = {"now": dt.datetime(2026, 9, 25, 20, 0, 0)}
    d = Dispatcher(store, spawner=fake.spawner, alive=fake.alive, clock=lambda: clock["now"])
    future = make(store, "ok", scheduled_at="2026-09-25T20:10:00")
    past = make(store, "ok", scheduled_at="2026-09-25T19:59:59", group="compute")
    d.tick()
    assert (status(store, future), status(store, past)) == ("scheduled", "running")
    clock["now"] = dt.datetime(2026, 9, 25, 20, 10, 0)
    d.tick()
    assert status(store, future) == "running"


def test_broken_schedule_time_does_not_block_forever(store, disp):
    j = make(store, "ok", scheduled_at="not-a-time")
    disp.tick()
    assert status(store, j) == "running"


def test_cancel_scheduled_and_queued_never_run(store, disp, fake):
    s = make(store, "ok", scheduled_at="2099-01-01T00:00:00")
    q = make(store, "ok", group="collect")
    q2 = make(store, "ok", group="collect")
    store.request_cancel(s["job_id"])
    store.request_cancel(q2["job_id"])
    disp.tick()
    assert (status(store, s), status(store, q2)) == ("cancelled", "cancelled")
    assert status(store, q) == "running" and fake.spawned == [q["job_id"]]


def test_dead_worker_becomes_failed_or_cancelled(store, disp, fake):
    a, b = make(store, "ok", group="compute"), make(store, "ok", group="compute")
    disp.tick()
    store.request_cancel(b["job_id"])
    for j in (a, b):
        fake.dead.add(store.read(j["job_id"])["pid"])
    disp.tick()
    ja = store.read(a["job_id"])
    assert ja["status"] == "failed" and "사라짐" in ja["error"]
    assert status(store, b) == "cancelled"


def test_live_worker_untouched_and_adopted_after_server_restart(store, disp, fake):
    j = make(store, "ok")
    disp.tick()
    fresh = Dispatcher(store, spawner=fake.spawner, alive=fake.alive, killer=fake.killer)  # 서버 재시작
    fresh.tick()
    assert status(store, j) == "running" and len(fake.spawned) == 1


def test_running_without_pid_gets_grace_then_fails(store, fake):
    j = make(store, "ok")
    now = dt.datetime.now()
    d = Dispatcher(store, spawner=fake.spawner, alive=fake.alive, clock=lambda: now)
    store.transition(j["job_id"], {"queued"}, status="running", started_at=now.isoformat(timespec="seconds"))
    d.tick()
    assert status(store, j) == "running"
    d.clock = lambda: now + dt.timedelta(seconds=dp.STARTUP_GRACE_SECONDS + 5)
    d.tick()
    assert status(store, j) == "failed"


def test_spawn_failure_marks_failed_and_frees_slot(store, disp, fake):
    a = make(store, "ok", group="collect")
    fake.fail = True
    disp.tick()
    assert "워커 기동 실패" in store.read(a["job_id"])["error"]
    fake.fail = False
    b = make(store, "ok", group="collect")
    disp.tick()
    assert status(store, b) == "running"


def test_running_cancel_waits_grace_then_kills_tree(store, disp, fake, monkeypatch):
    j = make(store, "ok")
    disp.tick()
    pid = store.read(j["job_id"])["pid"]
    store.request_cancel(j["job_id"])
    disp.tick()
    assert status(store, j) == "running" and not fake.killed  # 워커가 스스로 끝낼 시간을 준다
    monkeypatch.setattr(dp, "CANCEL_GRACE_SECONDS", -1)
    disp.tick()
    assert fake.killed == [pid] and status(store, j) == "cancelled"


def test_two_dispatchers_never_double_start(store, fake):
    for _ in range(20):
        make(store, "ok", group="compute")
    ds = [Dispatcher(store, spawner=fake.spawner, alive=fake.alive, limits={"compute": 20}) for _ in range(2)]
    ts = [threading.Thread(target=d.tick) for d in ds]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(fake.spawned) == len(set(fake.spawned)) == 20


def test_thread_loop_survives_tick_error_and_stops(store, fake):
    calls = []
    d = Dispatcher(store, spawner=fake.spawner, alive=fake.alive, poll_seconds=0.01)
    orig = d.tick

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("x")
        orig()

    d.tick = flaky
    j = make(store, "ok")
    d.start()
    deadline = time.time() + 3
    while time.time() < deadline and status(store, j) != "running":
        time.sleep(0.02)
    d.stop()
    assert status(store, j) == "running" and len(calls) >= 2


def test_real_worker_process_end_to_end(store):
    """진짜 워커 프로세스: 허용 안 된 handler 는 import 전에 failed 로 끝난다(§7) — 분리 실행·기록 경로 실측."""
    j = store.create("evil", "local", "os:system", {})
    d = Dispatcher(store)
    d.tick()
    deadline = time.time() + 30
    while time.time() < deadline and status(store, j) not in ("failed", "succeeded"):
        time.sleep(0.2)
        d.tick()
    got = store.read(j["job_id"])
    assert got["status"] == "failed" and "허용되지 않은" in got["error"], got
    assert got["pid"] and got["exit_code"] == 1


def test_fifo_holds_for_jobs_created_in_the_same_second(store, fake):
    """ID 는 초 단위 + 난수라 같은 초에 만든 작업끼리는 ID 순이 무작위다 — created_at(마이크로초)이 순서를 가린다."""
    d = Dispatcher(store, spawner=fake.spawner, alive=fake.alive, limits={"collect": 50})
    ids = [make(store, "ok", group="collect")["job_id"] for _ in range(30)]
    d.tick()
    assert fake.spawned == ids
