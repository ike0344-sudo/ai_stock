"""작업 저장소 — `state/jobs/<job_id>/` (설계서 §3.3).

    job.json       상태·설정. 쓰는 곳: dispatcher(대기→실행, 죽은 워커 정리)·worker(끝 상태). API 는 만들기만 한다.
    progress.json  진행률. worker 만 쓴다.
    log.txt        자식 출력. worker(child.py)만 쓴다 — 비밀값은 쓸 때 가린다.
    cancel.flag    취소 요청. **API 만** 만든다(쓰는 주체 분리 — 서로의 파일을 덮어쓰지 않게).

모든 쓰기는 tmp + os.replace. Windows 는 읽는 중인 파일을 교체하면 PermissionError 라 짧게 재시도한다
(risk_state_lock 에서 실측된 공유위반과 같은 것). 한 작업의 read-modify-write 는 폴더 뮤텍스로 직렬화한다 —
dispatcher(pid 기록)와 worker(run_id·끝 상태)가 같은 job.json 을 거의 동시에 고칠 수 있다.

jobrunner 는 datahub·studio·backtesting·fastapi 를 import 하지 않는다 (§9.3).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Iterable

JOB_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
STATUSES = ("scheduled", "queued", "running", "succeeded", "failed", "cancelled")
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
GROUPS = ("collect", "local", "compute")

_WRITE_RETRIES = 40
_WRITE_SLEEP = 0.05
_MUTEX_STALE_SECONDS = 10.0


def default_root() -> Path:
    """저장소 루트. STUDIO_DATA_ROOT(스튜디오) → DATAHUB_ROOT(허브 테스트와 같은 임시 루트) → 패키지 상위."""
    env = os.environ.get("STUDIO_DATA_ROOT") or os.environ.get("DATAHUB_ROOT")
    return Path(env) if env else Path(__file__).resolve().parent.parent


def new_id(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(_WRITE_RETRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == _WRITE_RETRIES - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(_WRITE_SLEEP)


def _read_json(path: Path) -> dict | None:
    for attempt in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.02 * (attempt + 1))  # 교체 중인 순간을 잡았다 — tmp+교체라 곧 온전해진다
    return None


class _Mutex:
    """폴더 하나(mkdir 는 원자적)로 만드는 짧은 뮤텍스. 죽은 프로세스가 남긴 것은 오래되면 회수한다."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> "_Mutex":
        deadline = time.monotonic() + 15
        while True:
            try:
                self.path.mkdir()
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > _MUTEX_STALE_SECONDS:
                        self.path.rmdir()
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError(f"작업 파일 잠금을 못 얻음: {self.path}")
                time.sleep(0.01)

    def __exit__(self, *exc: object) -> None:
        try:
            self.path.rmdir()
        except OSError:
            pass


class JobStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()
        self.dir = self.root / "state" / "jobs"
        self._terminal: set[str] = set()  # 끝난 작업은 다시 안 읽는다(끝 상태는 되돌아가지 않는다)

    # ------------------------------------------------------------------ 경로
    def job_dir(self, job_id: str) -> Path:
        if not JOB_ID_RE.fullmatch(job_id):
            raise ValueError(f"잘못된 job_id: {job_id!r}")
        return self.dir / job_id

    def log_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "log.txt"

    # ------------------------------------------------------------------ 만들기·읽기
    def create(
        self, kind: str, group: str, handler: str, payload: dict[str, Any] | None = None, *,
        scheduled_at: str | None = None, lock: str | None = None, trigger: str = "user",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        if group not in GROUPS:
            raise ValueError(f"알 수 없는 group: {group!r}")
        job_id = new_id()
        while (self.dir / job_id).exists():  # 같은 초 + 같은 난수(1/1600만) — 사실상 없지만 덮어쓰면 안 된다
            job_id = new_id()
        job = {
            "job_id": job_id, "kind": kind, "group": group, "handler": handler,
            "status": "scheduled" if scheduled_at else "queued",
            "scheduled_at": scheduled_at,
            # 마이크로초까지 — ID 는 초 단위라 같은 초에 만든 작업의 선입선출 순서를 created_at 이 가려야 한다
            "created_at": dt.datetime.now().isoformat(timespec="microseconds"), "started_at": None, "finished_at": None,
            "payload": payload or {}, "run_id": run_id, "lock": lock,
            "pid": None, "pid_create_time": None, "exit_code": None, "error": None, "trigger": trigger,
        }
        (self.dir / job_id).mkdir(parents=True)
        atomic_write_text(self.job_dir(job_id) / "job.json", json.dumps(job, ensure_ascii=False, indent=2))
        return job

    def read(self, job_id: str) -> dict[str, Any] | None:
        return _read_json(self.job_dir(job_id) / "job.json")

    def _mutex(self, job_id: str) -> _Mutex:
        return _Mutex(self.job_dir(job_id) / ".update.lock")

    def update(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        """필드를 고친다(없는 작업이면 None). 끝난 작업의 status 는 바꾸지 않는다."""
        if not self.job_dir(job_id).is_dir():
            return None
        with self._mutex(job_id):
            job = self.read(job_id)
            if job is None:
                return None
            if job["status"] in TERMINAL:
                fields.pop("status", None)
            job.update(fields)
            atomic_write_text(self.job_dir(job_id) / "job.json", json.dumps(job, ensure_ascii=False, indent=2))
            return job

    def transition(self, job_id: str, from_states: Iterable[str], **fields: Any) -> dict[str, Any] | None:
        """지금 상태가 from_states 안일 때만 고친다(compare-and-set). 아니면 None — 취소와 끝남이 겹칠 때
        먼저 온 쪽이 이기고 나중 쪽은 조용히 물러난다."""
        allowed = set(from_states)
        if not self.job_dir(job_id).is_dir():
            return None
        with self._mutex(job_id):
            job = self.read(job_id)
            if job is None or job["status"] not in allowed:
                return None
            job.update(fields)
            atomic_write_text(self.job_dir(job_id) / "job.json", json.dumps(job, ensure_ascii=False, indent=2))
            if job["status"] in TERMINAL:
                self._terminal.add(job_id)
            return job

    # ------------------------------------------------------------------ 목록
    def iter_ids(self) -> list[str]:
        """최신 먼저(ID 가 시각 순)."""
        if not self.dir.is_dir():
            return []
        return sorted((p.name for p in self.dir.iterdir() if p.is_dir() and JOB_ID_RE.fullmatch(p.name)),
                      reverse=True)

    def list_jobs(self, *, status: str | None = None, kind: str | None = None, group: str | None = None,
                  limit: int = 50) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for job_id in self.iter_ids():
            job = self.read(job_id)
            if job is None:
                continue
            if job["status"] in TERMINAL:
                self._terminal.add(job_id)
            if (status and job["status"] != status) or (kind and job["kind"] != kind) \
                    or (group and job["group"] != group):
                continue
            out.append(job)
            if len(out) >= limit:
                break
        return out

    def list_active(self) -> list[dict[str, Any]]:
        """scheduled·queued·running 전부. 끝난 작업은 캐시로 건너뛴다(오래된 예약이 뒤에 있어도 전부 본다)."""
        out = []
        for job_id in self.iter_ids():
            if job_id in self._terminal:
                continue
            job = self.read(job_id)
            if job is None:
                continue
            if job["status"] in TERMINAL:
                self._terminal.add(job_id)
                continue
            out.append(job)
        return out

    # ------------------------------------------------------------------ 진행률(worker 만)
    def write_progress(self, job_id: str, **fields: Any) -> None:
        data = {"pct": None, "stage": None, "message": None, "eta_sec": None, "paused": False,
                "waiting_lock": None} | fields | {"updated_at": now_iso()}
        atomic_write_text(self.job_dir(job_id) / "progress.json", json.dumps(data, ensure_ascii=False))

    def read_progress(self, job_id: str) -> dict[str, Any] | None:
        return _read_json(self.job_dir(job_id) / "progress.json")

    # ------------------------------------------------------------------ 취소(API 만)
    def request_cancel(self, job_id: str) -> None:
        d = self.job_dir(job_id)
        if not d.is_dir():
            raise FileNotFoundError(job_id)
        (d / "cancel.flag").write_text(now_iso(), encoding="utf-8")

    def cancel_requested(self, job_id: str) -> bool:
        return (self.job_dir(job_id) / "cancel.flag").exists()

    def cancel_requested_at(self, job_id: str) -> float | None:
        try:
            return (self.job_dir(job_id) / "cancel.flag").stat().st_mtime
        except OSError:
            return None

    # ------------------------------------------------------------------ 로그
    def read_log(self, job_id: str, offset: int = 0, limit: int = 256 * 1024) -> tuple[bytes, int, bool]:
        """(바이트, 다음 offset, 끝 여부). UTF-8 글자 중간에서 자르지 않는다 — 잘린 꼬리는 다음 호출로 넘긴다."""
        path = self.log_path(job_id)
        try:
            size = path.stat().st_size
            with path.open("rb") as f:
                f.seek(max(0, offset))
                chunk = f.read(limit)
        except FileNotFoundError:
            return b"", max(0, offset), True
        start = max(0, offset)
        if start + len(chunk) < size:  # 더 남았으면 꼬리의 미완성 글자를 잘라낸다(안 되면 그대로 — 바이너리)
            for cut in range(len(chunk), max(len(chunk) - 4, 0), -1):
                try:
                    chunk[:cut].decode("utf-8")
                except UnicodeDecodeError:
                    continue
                chunk = chunk[:cut]
                break
        end = start + len(chunk)
        return chunk, end, end >= size
