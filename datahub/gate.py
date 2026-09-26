"""쓰기 관문 `write()` — 잠금 + 장부 + 정책 경고 (설계 §2.4.3, 테스트 H2·H3).

    from datahub import write

    with write("daily_minute", writer="backfill_universe", detail={"codes": 12}) as w:
        for i, code in enumerate(codes, 1):
            ...                        # 기존 쓰기 코드 그대로
            w.progress(i, len(codes))
        w.result(ok=ok, fail=fail)     # 끝 기록에 붙는 요약(자유 형식)

잠금은 `risk_state_lock`(블로킹)이다 — 야간 작업이 잠금 때문에 실패하면 안 되므로 기다린다.
재진입(같은 스레드가 같은 자원에 다시 write)은 영원히 자기 자신을 기다리게 되므로 즉시 막는다.
"""
import os
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime

import psutil
from backtesting.risk_manager import risk_state_lock

from . import catalog, ledger, locks, policy

WAIT_NOTICE_SECONDS = float(os.environ.get("DATAHUB_WAIT_NOTICE_SECONDS") or 60)   # 테스트가 줄인다
PROGRESS_MIN_INTERVAL = 60

_held: dict[str, int] = {}
_held_guard = threading.Lock()


def _say(msg: str) -> None:
    print(msg, flush=True)


def _cmdline() -> str:
    try:
        return subprocess.list2cmdline(psutil.Process().cmdline())
    except psutil.Error:
        return subprocess.list2cmdline(sys.argv)


def in_sophie_market_hours(now: datetime | None = None) -> bool:
    """소피증권 정규장(config.yaml market.open~close)의 거래일 안인가 — 시간대 판정은 policy.window 하나로."""
    return policy.window(now or datetime.now()) == "market"


class Run:
    def __init__(self, lock: str, writer: str, detail: dict | None):
        self.id = uuid.uuid4().hex[:12]
        self.lock, self.writer, self.detail = lock, writer, detail or {}
        self.trigger = os.environ.get("DATAHUB_TRIGGER") or "external"
        self.job_id = os.environ.get("DATAHUB_JOB_ID") or None
        self.done = self.total = None
        self.ok = True                 # 본문이 예외 없이 끝났어도 실패로 표시하고 싶으면 False 로
        self.error: str | None = None
        self._result: dict = {}
        self._last_progress = float("-inf")           # 첫 progress 는 바로 기록 — 화면 진행률이 60초 동안 비어 있지 않게
        self._warned = False

    def _emit(self, event: str, **extra) -> None:
        try:
            ledger.append({"event": event, "run": self.id, "lock": self.lock, "writer": self.writer,
                           "trigger": self.trigger, "job_id": self.job_id, "pid": os.getpid(),
                           "cmd": _cmdline(), "detail": self.detail, "done": self.done,
                           "total": self.total, **extra})
        except Exception as exc:       # 장부 실패가 수집을 죽이면 안 된다 — 알리고 계속
            if not self._warned:
                _say(f"[datahub] 장부 기록 실패(계속 진행): {type(exc).__name__}: {exc}")
                self._warned = True

    def progress(self, done: int, total: int) -> None:
        self.done, self.total = done, total
        now = time.monotonic()
        if done >= total or now - self._last_progress >= PROGRESS_MIN_INTERVAL:
            self._last_progress = now
            self._emit("progress", ok=None, error=None)

    def result(self, **summary) -> None:
        self._result.update(summary)


def _announce_waiting(lock: str, stop: threading.Event) -> None:
    while not stop.wait(WAIT_NOTICE_SECONDS):
        o = locks.owner(lock)
        _say(f"잠금 대기: {o.cmdline if o and o.cmdline else '(소유자 확인 불가)'}")


@contextmanager
def write(lock: str, writer: str, detail: dict | None = None):
    base = catalog.lock_base(lock)                 # 카탈로그에 없는 잠금이면 KeyError
    me = threading.get_ident()
    with _held_guard:
        if _held.get(lock) == me:
            raise RuntimeError(f"잠금 재진입: {lock} — 이미 이 스레드가 write() 안에 있다(교착)")
    stop = threading.Event()
    threading.Thread(target=_announce_waiting, args=(lock, stop), daemon=True).start()
    try:
        with risk_state_lock(str(base)):
            stop.set()
            with _held_guard:
                _held[lock] = me
            run = Run(lock, writer, detail)
            try:
                if run.trigger != "hub" and in_sophie_market_hours():
                    _say("[datahub] 경고: 소피증권 정규장 시간이다 — REST 한도 경합·화면 지연 가능(막지는 않는다)")
                run._emit("start", ok=None, error=None)
                try:
                    yield run
                except BaseException as exc:
                    clean_exit = isinstance(exc, SystemExit) and exc.code in (None, 0)
                    run._emit("end", ok=clean_exit and run.ok, result=run._result,
                              error=None if clean_exit else f"{type(exc).__name__}: {exc}"[:300])
                    raise
                else:
                    run._emit("end", ok=run.ok, result=run._result, error=run.error)
            finally:
                with _held_guard:
                    _held.pop(lock, None)
    finally:
        stop.set()
