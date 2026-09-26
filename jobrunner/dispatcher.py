"""작업 디스패처 — 서버 안 스레드 (설계서 §2.1, §6.1).

한 번의 `tick()` 이 하는 일 (스레드는 이걸 주기적으로 부를 뿐이라 테스트는 tick 을 직접 부른다):
  1. running 인데 워커가 사라졌으면 정리 — cancel.flag 있으면 cancelled, 없으면 failed("프로세스가 중간에 사라짐")
  2. 취소 반영 — scheduled·queued 는 바로 cancelled, running 은 워커에게 GRACE 초 주고 그래도 안 끝나면 트리째 종료
  3. scheduled_at 이 지난 scheduled → queued
  4. queued(예약 시각·생성 순) → 그룹 한도(collect 1 · local 1 · compute 2) 안에서 spawn

상태 전이는 전부 compare-and-set(JobStore.transition)이라 서버가 두 개 떠도 같은 작업을 두 번 띄우지 못한다.
서버가 재시작돼도 running 워커는 분리 프로세스라 계속 돌고, 다음 tick 이 (pid, create_time) 으로 그대로 이어받아 본다.
`tick()` 은 잠금으로 직렬화한다 — 주기 스레드와 API(취소 직후 즉시 반영)가 동시에 불러도 안전하다.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from typing import Callable, Mapping

from . import spawn
from .store import GROUPS, JobStore, now_iso

log = logging.getLogger("jobrunner.dispatcher")

DEFAULT_LIMITS: Mapping[str, int] = {"collect": 1, "local": 1, "compute": 2}
STARTUP_GRACE_SECONDS = 30.0   # running 으로 바꾼 뒤 pid 가 기록될 때까지 기다려 주는 시간
CANCEL_GRACE_SECONDS = 30.0    # 취소 요청 후 워커가 스스로 끝나기를 기다려 주는 시간

Spawner = Callable[[str], "tuple[int, float]"]


def _parse_local(ts: str | None) -> dt.datetime | None:
    if not ts:
        return None
    try:
        t = dt.datetime.fromisoformat(ts)
    except ValueError:
        return None
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


class Dispatcher:
    def __init__(
        self,
        store: JobStore,
        *,
        limits: Mapping[str, int] | None = None,
        spawner: Spawner | None = None,
        alive: Callable[[int | None, float | None], bool] = spawn.is_alive,
        killer: Callable[[int, float | None], None] = spawn.kill_tree,
        clock: Callable[[], dt.datetime] = dt.datetime.now,
        poll_seconds: float = 2.0,
    ) -> None:
        self.store = store
        self.limits = {g: 1 for g in GROUPS} | dict(limits or DEFAULT_LIMITS)
        self.spawner = spawner or (lambda job_id: spawn.spawn_worker(job_id, store.root))
        self.alive, self.killer, self.clock = alive, killer, clock
        self.poll_seconds = poll_seconds
        self._tick_lock = threading.RLock()
        # 마지막 tick 이 본 작업 수 — 상태 API(워치독 프로브)가 디스크를 안 훑고 이걸 읽는다. None = 아직 tick 전
        self.last_counts: dict[str, int] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ 스레드
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="jobrunner-dispatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # 한 번의 오류로 디스패처가 죽으면 예약·대기열이 전부 멈춘다 — 로그만 남기고 계속
                log.exception("dispatcher tick 오류(계속 진행)")
            self._stop.wait(self.poll_seconds)

    # ------------------------------------------------------------------ 한 사이클
    def tick(self) -> None:
        with self._tick_lock:
            now = self.clock()
            jobs = self.store.list_active()
            self._reap_running(jobs, now)
            self._apply_cancels(jobs)
            self._promote_scheduled(jobs, now)
            self._start_queued()
            counts = {"scheduled": 0, "queued": 0, "running": 0}
            for j in self.store.list_active():
                counts[j["status"]] = counts.get(j["status"], 0) + 1
            self.last_counts = counts

    def _reap_running(self, jobs: list[dict], now: dt.datetime) -> None:
        for job in (j for j in jobs if j["status"] == "running"):
            job_id = job["job_id"]
            if job.get("pid"):
                if self.alive(job["pid"], job.get("pid_create_time")):
                    continue
                reason = "프로세스가 중간에 사라짐"
            else:
                started = _parse_local(job.get("started_at"))
                if started and (now - started).total_seconds() < STARTUP_GRACE_SECONDS:
                    continue  # spawn 직후 — pid 기록 전
                reason = "워커가 시작되지 못함(pid 기록 없음)"
            if self.store.cancel_requested(job_id):
                self.store.transition(job_id, {"running"}, status="cancelled", finished_at=now_iso())
            else:
                self.store.transition(job_id, {"running"}, status="failed", error=reason, finished_at=now_iso())
                log.warning("작업 %s: %s", job_id, reason)

    def _apply_cancels(self, jobs: list[dict]) -> None:
        for job in jobs:
            job_id = job["job_id"]
            if not self.store.cancel_requested(job_id):
                continue
            if job["status"] in ("scheduled", "queued"):
                self.store.transition(job_id, {"scheduled", "queued"}, status="cancelled", finished_at=now_iso())
            elif job["status"] == "running":
                asked = self.store.cancel_requested_at(job_id)
                if asked is not None and time.time() - asked > CANCEL_GRACE_SECONDS and job.get("pid"):
                    self.killer(job["pid"], job.get("pid_create_time"))
                    self.store.transition(job_id, {"running"}, status="cancelled", finished_at=now_iso())

    def _promote_scheduled(self, jobs: list[dict], now: dt.datetime) -> None:
        for job in (j for j in jobs if j["status"] == "scheduled"):
            due = _parse_local(job.get("scheduled_at"))
            if due is None or due <= now:  # 시각이 깨진 예약은 영원히 묶어 두지 않는다
                self.store.transition(job["job_id"], {"scheduled"}, status="queued")

    def _start_queued(self) -> None:
        active = self.store.list_active()
        running = {g: 0 for g in self.limits}
        for j in active:
            if j["status"] == "running":
                running[j["group"]] = running.get(j["group"], 0) + 1
        queued = sorted((j for j in active if j["status"] == "queued"),
                        key=lambda j: (j.get("scheduled_at") or j["created_at"], j["job_id"]))
        for job in queued:
            group = job["group"]
            if running.get(group, 0) >= self.limits.get(group, 1):
                continue
            job_id = job["job_id"]
            if self.store.cancel_requested(job_id):
                continue  # 다음 tick 의 _apply_cancels 가 정리
            # 먼저 running 으로 확정(CAS)한 뒤 띄운다 — 다른 디스패처가 같은 작업을 또 띄우지 못하게
            if not self.store.transition(job_id, {"queued"}, status="running", started_at=now_iso()):
                continue
            running[group] = running.get(group, 0) + 1
            try:
                pid, create_time = self.spawner(job_id)
            except Exception as exc:
                self.store.transition(job_id, {"running"}, status="failed",
                                      error=f"워커 기동 실패: {type(exc).__name__}: {exc}", finished_at=now_iso())
                log.exception("작업 %s 워커 기동 실패", job_id)
                continue
            # 인라인 러너(테스트)는 spawner 안에서 이미 끝났을 수 있다 — running 일 때만 pid 를 적는다
            self.store.transition(job_id, {"running"}, pid=pid, pid_create_time=create_time)
