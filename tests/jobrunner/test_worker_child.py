import sys
import threading
import time

import psutil
import pytest

from jobrunner import child, spawn, worker
from jobrunner.worker import HandlerNotAllowed, check_handler_name, run_job
from tests.jobrunner.conftest import make


@pytest.mark.parametrize("bad", [
    "os:system", "builtins:exec", "datahub.jobs.evil:f", "datahub.jobs:../x", "datahub.jobs:f;x", "datahub.jobsx:f",
    "studio.application.jobs_evil:f", "datahub.jobs", "", None, 5, "datahub.jobs:", "studio.infrastructure:x",
])
def test_handler_allowlist_rejects(bad, monkeypatch):
    monkeypatch.setattr(worker, "ALLOWED_HANDLER_PREFIXES", ("datahub.jobs:", "studio.application.jobs:"))
    with pytest.raises(HandlerNotAllowed):
        check_handler_name(bad)


@pytest.mark.parametrize("good", ["datahub.jobs:collect_daily", "studio.application.jobs:run_backtest_job"])
def test_handler_allowlist_accepts(good, monkeypatch):
    monkeypatch.setattr(worker, "ALLOWED_HANDLER_PREFIXES", ("datahub.jobs:", "studio.application.jobs:"))
    assert check_handler_name(good) == good


def running(store, j):
    store.transition(j["job_id"], {"queued"}, status="running")
    return j["job_id"]


def test_success_records_run_id_progress_and_masks_log(store):
    jid = running(store, make(store, "ok", payload={"run_id": "20260925-120000-abcdef"}))
    assert run_job(store, jid) == "succeeded"
    job = store.read(jid)
    assert job["status"] == "succeeded" and job["run_id"] == "20260925-120000-abcdef" and job["exit_code"] == 0
    assert job["pid"] and job["finished_at"]
    assert store.read_progress(jid)["pct"] == 50
    log = store.log_path(jid).read_text(encoding="utf-8")
    assert "sk-test-SECRET-VALUE-123456" not in log and "abcdefghijklmnop1234" not in log
    assert "토큰은 **** 입니다" in log and "Bearer ****" in log


def test_failure_keeps_error_and_traceback(store):
    jid = running(store, make(store, "boom"))
    assert run_job(store, jid) == "failed"
    job = store.read(jid)
    assert job["error"] == "ValueError: 터졌다" and job["exit_code"] == 1
    assert "Traceback" in store.log_path(jid).read_text(encoding="utf-8")


def test_cancelled_by_exception_or_flag(store):
    a = running(store, make(store, "cancelled"))
    assert run_job(store, a) == "cancelled"
    b = running(store, make(store, "boom"))
    store.request_cancel(b)  # 취소 요청 뒤에 난 예외는 실패가 아니라 취소다
    assert run_job(store, b) == "cancelled"


def test_cooperative_cancel_mid_run(store):
    jid = running(store, make(store, "wait_for_cancel"))
    threading.Timer(0.3, store.request_cancel, args=[jid]).start()
    assert run_job(store, jid) == "cancelled"


def test_worker_yields_when_dispatcher_already_settled_job(store):
    jid = running(store, make(store, "ok"))
    store.transition(jid, {"running"}, status="failed", error="프로세스가 중간에 사라짐")
    assert run_job(store, jid) == "failed"  # 이미 끝난 작업은 안 돌린다
    assert store.read(jid)["error"] == "프로세스가 중간에 사라짐"
    j2 = make(store, "ok")  # queued(=아직 running 아님) 이면 실행 안 함
    assert run_job(store, j2["job_id"]) == "queued"


def test_disallowed_handler_in_job_json_fails_without_import(store):
    jid = running(store, store.create("x", "local", "os:system", {}))
    assert run_job(store, jid) == "failed"
    assert "허용되지 않은" in store.read(jid)["error"]


def test_child_run_masks_and_callbacks(store):
    jid = running(store, make(store, "child_echo"))
    assert run_job(store, jid) == "succeeded", store.read(jid)
    assert "sk-test" not in store.log_path(jid).read_text(encoding="utf-8")


def test_child_cancel_kills_process_tree(tmp_path):
    log = tmp_path / "l.txt"
    flag = {"c": False}
    threading.Timer(1.5, lambda: flag.update(c=True)).start()
    code_s = ("import subprocess,sys,time; "
              "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
              "print('up', flush=True); time.sleep(60)")
    t0 = time.time()
    code = child.run_child([sys.executable, "-c", code_s], cwd=tmp_path, log_path=log, is_cancelled=lambda: flag["c"])
    assert time.time() - t0 < 15 and code != 0
    assert "up" in log.read_text(encoding="utf-8")


def test_child_decodes_cp949_and_survives_bad_callback(tmp_path):
    log = tmp_path / "l.txt"
    prog = "import sys; sys.stdout.buffer.write('한글 출력\\n'.encode('cp949')); sys.stdout.flush()"
    code = child.run_child([sys.executable, "-c", prog], cwd=tmp_path, log_path=log, on_line=lambda line: 1 / 0)
    text = log.read_text(encoding="utf-8")
    assert code == 0 and "한글 출력" in text and "on_line 오류" in text


def test_spawn_alive_uses_create_time_and_kill_tree(tmp_path):
    with (tmp_path / "o").open("ab") as f:
        p = spawn.popen_detached([sys.executable, "-c", "import time; time.sleep(60)"], tmp_path, f)
    ct = psutil.Process(p.pid).create_time()
    assert spawn.is_alive(p.pid, ct)
    assert not spawn.is_alive(p.pid, ct + 100)  # 같은 PID 라도 시작 시각이 다르면 다른 프로세스(PID 재사용)
    assert not spawn.is_alive(None) and not spawn.is_alive(0)
    spawn.kill_tree(p.pid, ct + 100)  # 재사용된 PID 는 죽이지 않는다
    assert spawn.is_alive(p.pid, ct)
    spawn.kill_tree(p.pid, ct)
    p.wait(timeout=5)
    assert not spawn.is_alive(p.pid, ct)


@pytest.mark.skipif(sys.platform != "win32", reason="taskkill /T 는 Windows 전용")
def test_worker_survives_tree_kill_of_its_spawner(tmp_path):
    """2026-09-25 실측 재현: 서버를 taskkill /F /T 로 죽여도 launcher 경유 워커는 살아남는다."""
    import subprocess
    parent_code = (
        "import sys, time; sys.path.insert(0, %r); from pathlib import Path; from jobrunner import spawn; "
        "pid = spawn.launch_detached([sys.executable, '-c', 'import time; time.sleep(60)'], %r, Path(%r)); "
        "print(pid, flush=True); time.sleep(60)" % (str(spawn.Path(spawn.__file__).resolve().parent.parent),
                                                     str(tmp_path), str(tmp_path / "w.log")))
    parent = subprocess.Popen([sys.executable, "-c", parent_code], stdout=subprocess.PIPE, text=True)
    worker_pid = int(parent.stdout.readline())
    ct = psutil.Process(worker_pid).create_time()
    try:
        assert spawn.is_alive(worker_pid, ct)
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(parent.pid)], capture_output=True)
        parent.wait(timeout=10)
        time.sleep(0.5)
        assert spawn.is_alive(worker_pid, ct), "트리 종료가 워커까지 닿았다 — 이중 기동이 깨졌다"
    finally:
        spawn.kill_tree(worker_pid, ct)
        parent.kill()
