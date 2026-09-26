"""잠금 소유자 조회 + wait-quiet (설계 §2.4.4, §2.4.9, 테스트 H4·H9).

잠금 파일 자체는 `backtesting.risk_manager.risk_state_lock` 이 만든다(토큰 `pid:thread:uuid`).
여기서는 그 파일을 읽어 "누가 잡고 있나, 죽었나"만 본다 — 잠금을 잡거나 지우지 않는다.

wait-quiet 는 소피증권 재기동 스크립트가 PowerShell 5.1 에서 부른다. 5.1 은
`$ErrorActionPreference='Stop'` 이면 native 명령의 **stderr 출력을 NativeCommandError 로 바꾼다**
(rebuild 스크립트의 PyInstaller 사례) — 그래서 이 경로는 stdout 에만 쓴다.
"""
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from . import catalog

QUIET_EXIT_OK, QUIET_EXIT_TIMEOUT = 0, 3
MARKER_STUCK_SECONDS = 6 * 3600          # 워치독 dailyReportStuckThresholdSeconds 와 같은 규칙
MARKERS = ("daily_report", "minute_refresh")


def lock_file(resource: str) -> Path:
    return Path(str(catalog.lock_base(resource)) + ".lock")


@dataclass
class Owner:
    pid: int | None
    token: str
    cmdline: str
    since: float          # 잠금 파일 mtime (획득 시각)
    alive: bool | None    # None = 토큰을 못 읽어 판단 불가
    dead: bool            # 소유자가 죽었는데 파일이 남아 있음


def pid_alive_since(pid: int, since: float) -> bool:
    """`since`(epoch) 이전에 시작한 그 프로세스가 아직 살아 있나. PID 재사용을 create_time 으로 거른다."""
    try:
        p = psutil.Process(pid)
        if p.status() == psutil.STATUS_ZOMBIE:
            return False
        return p.create_time() <= since + 1.0    # 1초: 파일시스템/프로세스 시각 해상도 차이
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return True                              # 권한 등으로 못 봤다 — 살아 있다고 본다


def owner(resource: str) -> Owner | None:
    f = lock_file(resource)
    try:
        token = f.read_bytes().decode(errors="replace")
        since = f.stat().st_mtime
    except OSError:
        return None                              # 잠금 없음(또는 그 사이 풀림)
    try:
        pid = int(token.split(":", 1)[0])
    except ValueError:
        return Owner(None, token, "", since, None, False)
    alive = pid_alive_since(pid, since)
    cmd = ""
    if alive:
        try:
            cmd = " ".join(psutil.Process(pid).cmdline())
        except psutil.Error:
            pass
    return Owner(pid, token, cmd, since, alive, dead=not alive)


def marker_running(name: str, now: float | None = None) -> bool:
    """state/<name>/last_run_{started,finished}.json — 시작 > 끝이고 6시간 이내면 실행 중.
    분봉 갱신 표식은 PowerShell 이 BOM 을 붙여 쓴다 -> utf-8-sig."""
    now = time.time() if now is None else now
    d = catalog.root() / "state" / name
    try:
        started = float(json.loads((d / "last_run_started.json").read_text(encoding="utf-8-sig"))["started_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    try:
        finished = float(json.loads((d / "last_run_finished.json").read_text(encoding="utf-8-sig"))["finished_at"])
    except (OSError, ValueError, KeyError, TypeError):
        finished = None
    return (finished is None or finished < started) and now - started < MARKER_STUCK_SECONDS


def busy_reasons() -> list[str]:
    reasons = []
    o = owner("daily_minute")
    if o is not None and o.alive:
        reasons.append(f"잠금 daily_minute 사용 중: pid {o.pid} {o.cmdline[:120]}".rstrip())
    reasons += [f"표식 {m} 실행 중" for m in MARKERS if marker_running(m)]
    return reasons


def deadline_from(hhmm: str, now: datetime | None = None) -> datetime:
    """지금 이후 처음 오는 HH:MM. 자정을 넘기는 야간 작업(20:15 시작 -> --until 08:10)이
    시작하자마자 '이미 지났다'로 끝나지 않게 한다."""
    now = now or datetime.now()
    h, m = (int(x) for x in hhmm.split(":"))
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return t if t > now else t + timedelta(days=1)


def wait_quiet(until: str | None = None, max_minutes: float | None = None, poll: float = 10.0,
               out=print, sleep=time.sleep) -> int:
    """공유 데이터를 쓰는 작업이 없을 때까지 기다린다. 0 = 조용함, 3 = 기한 초과.
    두 기한 중 먼저 오는 쪽을 쓴다. 둘 다 없으면 30분."""
    now = datetime.now()
    limits = []
    if until:
        limits.append(deadline_from(until, now))
    if max_minutes is not None:
        limits.append(now + timedelta(minutes=max_minutes))
    deadline = min(limits) if limits else now + timedelta(minutes=30)
    last_msg = 0.0
    while True:
        reasons = busy_reasons()
        if not reasons:
            out(f"wait-quiet: 조용함 ({datetime.now():%H:%M:%S})")
            return QUIET_EXIT_OK
        if datetime.now() >= deadline:
            out(f"wait-quiet: 기한 초과 {deadline:%m-%d %H:%M} — 아직 사용 중: {'; '.join(reasons)}")
            return QUIET_EXIT_TIMEOUT
        if time.monotonic() - last_msg >= 60:
            out(f"wait-quiet: 대기 중 — {'; '.join(reasons)}")
            last_msg = time.monotonic()
        sleep(min(poll, max(0.0, (deadline - datetime.now()).total_seconds())))
