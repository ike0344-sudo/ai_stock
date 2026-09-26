"""워커 분리 실행 + 프로세스 생존·트리 종료 (설계서 §2.1, §7).

분리 플래그는 `backtesting/dashboard_server.spawn_detached` 와 **같은 것·같은 이유**다(jobrunner 는 backtesting 을
import 하지 않으므로 복사): 서버를 재시작해도 방금 띄운 수집·백테스트 워커가 같이 죽지 않게 새 프로세스 그룹으로 띄운다.
CREATE_BREAKAWAY_FROM_JOB 은 상위 잡 오브젝트가 breakaway 를 허용하지 않으면 **생성 자체가 예외**라서 먼저 시도하고
실패하면 그 플래그 없이 다시 시도한다.

**이중 기동**: 플래그만으로는 상위가 "부모 PID 로 프로세스 트리를 통째로 정리"하는 경우(`taskkill /F /T`)를 못 막는다 —
2026-09-25 실측: 서버를 `/T` 로 죽이자 detached 워커도 같이 죽었다(spawn_detached 주석이 경고한 그 경우). 그래서 짧게 사는
launcher(`python -m jobrunner.spawn`)가 워커를 띄우고 pid 를 알린 뒤 곧바로 끝난다. 워커의 부모 PID 가 죽은 launcher 를 가리키므로
서버의 트리 종료가 워커에 닿지 않는다(워치독의 `Stop-Process` 같은 단일 종료는 원래 안전하다).

생존 판정은 pid 만으로 하지 않는다 — Windows 는 PID 를 금방 재사용하므로 (pid, create_time) 쌍으로 본다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import psutil

CREATE_NO_WINDOW = 0x08000000  # 서버가 콘솔 없이 떠 있어도 워커 창이 번쩍이지 않게


def _win_flags(*, breakaway: bool) -> int:
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.BELOW_NORMAL_PRIORITY_CLASS  # type: ignore[attr-defined]
             | CREATE_NO_WINDOW)
    if breakaway:
        flags |= subprocess.CREATE_BREAKAWAY_FROM_JOB  # type: ignore[attr-defined]
    return flags


def popen_detached(command: Sequence[str], cwd: str | Path, log_file, env: dict[str, str] | None = None
                   ) -> subprocess.Popen:
    """서버와 운명을 분리해 띄운다(우선순위 BELOW_NORMAL). stdout·stderr 는 log_file 로."""
    kwargs = dict(cwd=str(cwd), env=env, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if os.name == "nt":
        try:
            return subprocess.Popen(list(command), creationflags=_win_flags(breakaway=True), **kwargs)
        except OSError:
            return subprocess.Popen(list(command), creationflags=_win_flags(breakaway=False), **kwargs)
    return subprocess.Popen(list(command), start_new_session=True, preexec_fn=lambda: os.nice(10), **kwargs)


def launch_detached(command: Sequence[str], cwd: str | Path, log_path: Path, env: dict[str, str] | None = None) -> int:
    """launcher 를 거쳐 명령을 띄우고 그 pid 를 돌려준다. 호출 프로세스가 트리째 죽어도 명령은 산다(위 이중 기동)."""
    payload = json.dumps({"command": list(command), "cwd": str(cwd), "log": str(log_path)})
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    out = subprocess.run([sys.executable, "-m", "jobrunner.spawn", payload], cwd=str(Path(__file__).resolve().parent.parent),
                         env=env, capture_output=True, text=True, timeout=30, creationflags=flags, stdin=subprocess.DEVNULL)
    if out.returncode != 0 or not out.stdout.strip().isdigit():
        raise OSError(f"launcher 실패(code={out.returncode}): {(out.stderr or out.stdout).strip()[-300:]}")
    return int(out.stdout.strip())


def _launcher_main(argv: list[str]) -> int:
    spec = json.loads(argv[0])
    with open(spec["log"], "ab") as log:
        proc = popen_detached(spec["command"], spec["cwd"], log)
    print(proc.pid, flush=True)  # 부모(디스패처)가 읽는 유일한 출력
    return 0


def spawn_worker(job_id: str, root: Path, repo_root: Path | None = None) -> tuple[int, float]:
    """`python -m jobrunner.worker <job_id>` 를 분리 실행. (pid, create_time) 을 돌려준다."""
    repo_root = repo_root or Path(__file__).resolve().parent.parent
    log_path = root / "state" / "jobs" / job_id / "log.txt"
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "STUDIO_DATA_ROOT": str(root)}
    pid = launch_detached([sys.executable, "-m", "jobrunner.worker", job_id], repo_root, log_path, env)
    return pid, psutil.Process(pid).create_time()


def is_alive(pid: int | None, create_time: float | None = None) -> bool:
    if not pid:
        return False
    try:
        p = psutil.Process(pid)
        if p.status() == psutil.STATUS_ZOMBIE:
            return False
        return create_time is None or abs(p.create_time() - create_time) < 1.0
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def kill_tree(pid: int, create_time: float | None = None, timeout: float = 5.0) -> None:
    """워커와 그 자식(수집 스크립트·powershell 등)까지 종료. PID 가 재사용된 다른 프로세스는 건드리지 않는다."""
    if not is_alive(pid, create_time):
        return
    try:
        root = psutil.Process(pid)
        procs = root.children(recursive=True) + [root]
    except psutil.NoSuchProcess:
        return
    for p in procs:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs, timeout=timeout)


if __name__ == "__main__":
    raise SystemExit(_launcher_main(sys.argv[1:]))
