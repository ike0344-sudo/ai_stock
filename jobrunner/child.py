"""자식 명령 실행 — 출력 줄을 log.txt 에 (비밀값 가려서) 붙이고 줄 콜백을 부른다 (설계서 §2.1, §7).

수집 스크립트·소피증권 ps1 같은 기존 프로그램을 **인자 리스트로, 셸 없이** 돌린다. 허용 목록(`sys.executable` + 정해진
스크립트)은 명령을 조립하는 handler(`datahub.jobs`)의 몫이다 — jobrunner 는 무엇을 돌리는지 모른다.

취소: `is_cancelled()` 를 1초마다 보고 True 면 트리째 종료한다(자식이 다시 자식을 띄우는 경우까지).
출력 디코딩: UTF-8 을 먼저 시도하고 안 되면 cp949 — powershell 5.1 스크립트는 콘솔 코드페이지로 내보낸다.
"""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Callable, Mapping, Sequence

from . import spawn
from .mask import Masker


def decode_line(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp949", errors="replace")


def run_child(
    argv: Sequence[str],
    *,
    cwd: str | Path,
    log_path: Path,
    env: Mapping[str, str] | None = None,
    on_line: Callable[[str], None] | None = None,
    masker: Masker | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> int:
    """종료코드를 돌려준다. 취소로 죽였으면 -1 이 아니라 실제 종료코드(대개 1)이므로 호출자가 is_cancelled 로 구분한다."""
    masker = masker or Masker()
    child_env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", **(env or {})}
    flags = 0
    if os.name == "nt":
        flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS | spawn.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    proc = subprocess.Popen(
        list(argv), cwd=str(cwd), env=child_env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags,
    )
    done = threading.Event()

    def watch() -> None:
        while not done.wait(1.0):
            if is_cancelled and is_cancelled():
                spawn.kill_tree(proc.pid)
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("a", encoding="utf-8", newline="\n") as log:
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b""):
                line = masker.mask(decode_line(raw).rstrip("\r\n"))
                log.write(line + "\n")
                log.flush()
                if on_line:
                    try:
                        on_line(line)
                    except Exception as exc:  # 줄 콜백(진행률 파싱 등)이 실패해도 자식은 계속 읽어야 한다 — 파이프가 막힌다
                        log.write(f"[jobrunner] on_line 오류(계속 진행): {exc}\n")
        return proc.wait()
    finally:
        done.set()
        if proc.poll() is None:
            spawn.kill_tree(proc.pid)
