"""작업 워커 — `python -m jobrunner.worker <job_id>` (설계서 §2.1, §3.3, §7).

job.json 의 `handler`("모듈:함수")를 import 해 부른다. **허용 접두사만** 받는다 — job.json 이 어떻게든 바뀌어도
임의 코드를 import 하지 못하게(§7). handler 는 이름 문자열로만 연결되므로 jobrunner 는 datahub·studio 를 import 하지 않는다.

handler 계약 (datahub.jobs · studio.application.jobs 가 지킨다):

    def my_handler(ctx: JobContext) -> dict | None

    ctx.job_id, ctx.payload, ctx.root                    작업 정보
    ctx.progress(pct, stage="", message="", **extra)     progress.json 갱신 (pct 0~100, extra: eta_sec·paused·waiting_lock)
    ctx.log(line)                                        log.txt 에 한 줄(비밀값 가림)
    ctx.is_cancelled()                                   cancel.flag 가 있나 — 긴 루프에서 주기적으로 본다
    ctx.set_run_id(run_id)                               job.json.run_id 기록
    ctx.run_child(argv, cwd=..., env=..., on_line=...)   자식 명령 실행(줄 → log.txt, 취소 시 트리 종료), 종료코드 반환
    반환: None 또는 {"run_id": ..., "message": ...} — run_id 가 있으면 job.json 에 기록

    예외 → failed (error = "ExcType: 메시지", traceback 은 log.txt). CancelledError 나 취소 요청 후의 예외 → cancelled.

상태 전이는 compare-and-set 이다: 워커는 running → 끝 상태만 쓴다. 이미 dispatcher 가 cancelled·failed 로 정리했으면
조용히 물러난다.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import psutil

from . import child
from .mask import Masker
from .store import JOB_ID_RE, JobStore, default_root, now_iso

ALLOWED_HANDLER_PREFIXES = ("datahub.jobs:", "studio.application.jobs:")
_HANDLER_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")


class CancelledError(Exception):
    """handler 가 취소를 발견하고 스스로 멈출 때 던진다."""


class HandlerNotAllowed(Exception):
    pass


def check_handler_name(name: object) -> str:
    """허용 접두사 + "모듈:함수" 형식이 아니면 HandlerNotAllowed. import 는 하지 않는다."""
    if not isinstance(name, str) or not _HANDLER_RE.fullmatch(name) or not name.startswith(ALLOWED_HANDLER_PREFIXES):
        raise HandlerNotAllowed(f"허용되지 않은 handler: {name!r} (허용 접두사 {ALLOWED_HANDLER_PREFIXES})")
    return name


def resolve_handler(name: str) -> Callable[["JobContext"], Any]:
    module_name, func_name = check_handler_name(name).split(":")
    return getattr(importlib.import_module(module_name), func_name)


class JobContext:
    def __init__(self, store: JobStore, job: Mapping[str, Any], masker: Masker | None = None) -> None:
        self.store = store
        self.job_id: str = job["job_id"]
        self.payload: dict[str, Any] = dict(job.get("payload") or {})
        self.root: Path = store.root
        self._masker = masker or Masker.from_env(store.root)

    def progress(self, pct: float | None, stage: str = "", message: str = "", **extra: Any) -> None:
        self.store.write_progress(
            self.job_id, pct=None if pct is None else round(max(0.0, min(100.0, float(pct))), 1),
            stage=stage, message=self._masker.mask(message), **extra)

    def log(self, line: str) -> None:
        path = self.store.log_path(self.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(self._masker.mask(line).rstrip("\r\n") + "\n")

    def is_cancelled(self) -> bool:
        return self.store.cancel_requested(self.job_id)

    def set_run_id(self, run_id: str) -> None:
        self.store.update(self.job_id, run_id=run_id)

    def run_child(self, argv: Sequence[str], *, cwd: str | Path | None = None, env: Mapping[str, str] | None = None,
                  on_line: Callable[[str], None] | None = None) -> int:
        return child.run_child(
            argv, cwd=cwd or self.root, log_path=self.store.log_path(self.job_id), env=env, on_line=on_line,
            masker=self._masker, is_cancelled=self.is_cancelled)


def run_job(store: JobStore, job_id: str) -> str:
    """dispatcher 가 running 으로 만든 작업 하나를 끝까지 돌린다. 최종 status 를 돌려준다(인라인 러너·테스트도 이걸 쓴다)."""
    job = store.read(job_id)
    if job is None or job["status"] != "running":
        return job["status"] if job else "missing"
    me = psutil.Process(os.getpid())
    store.update(job_id, pid=me.pid, pid_create_time=me.create_time())  # dispatcher 가 죽었어도 생존 확인이 되게
    ctx = JobContext(store, job)
    status, error, extra = "succeeded", None, {}
    try:
        result = resolve_handler(job["handler"])(ctx)
        if isinstance(result, Mapping):
            if result.get("run_id"):
                extra["run_id"] = result["run_id"]
    except Exception as exc:  # SystemExit·KeyboardInterrupt 는 그대로 죽는다 — dispatcher 가 "사라짐"으로 정리한다
        if isinstance(exc, CancelledError) or ctx.is_cancelled():
            status = "cancelled"
            ctx.log("취소됨")
        else:
            status, error = "failed", f"{type(exc).__name__}: {exc}"
            ctx.log("".join(traceback.format_exception(exc)).rstrip())
    fields = dict(status=status, error=error, finished_at=now_iso(), exit_code=0 if status == "succeeded" else 1, **extra)
    store.transition(job_id, {"running"}, **fields)
    return status


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or not JOB_ID_RE.fullmatch(argv[0]):
        print("usage: python -m jobrunner.worker <job_id>", file=sys.stderr)
        return 2
    return 0 if run_job(JobStore(default_root()), argv[0]) == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
