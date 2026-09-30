"""허브 수집 작업 처리기 — jobrunner 워커가 부른다 (설계 §2.4.10·§2.4.11·§7, 테스트 H13·H15~H21).

`datahub.jobs:collect_daily` 처럼 **이 모듈의 함수**가 handler 다(jobrunner 허용 접두사). 시그니처 `def handler(ctx)`.

- **실행 파일 허용 목록(§7)은 여기서 검사한다**: `sys.executable` + 고정 스크립트 3종(`backfill_universe.py`·
  `tick_collect_804_828_al.py`·`tick_compact_daemon.py`), `-m scripts.fetch_minute`(소피증권 폴더), `run_minute_refresh.ps1 -Now` 만.
  jobrunner 는 받은 argv 를 그대로 돌리므로 임의 명령은 여기서 막는다.
- 진행률은 **장부 progress 기록**(그 작업의 `DATAHUB_JOB_ID`)에서 읽는다. 관문이 잠금을 기다리는 중이면
  `ctx.progress(..., waiting_lock={resource, owner})`.
- `STUDIO_FAKE_COLLECTORS=1` 이면 실제 수집기 대신 `datahub._fake_collector` 를 돌린다(테스트·시연용, API 호출 없음).
"""
import json
import os
import re
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path

from jobrunner.worker import CancelledError

from . import catalog, collectors, ledger, locks, policy, status
from .calendar import Calendar

POLL_SECONDS = 5.0
clock = datetime.now            # 테스트가 가짜 시계로 바꾼다(처리기 안의 "지금")
FAKE_ENV = "STUDIO_FAKE_COLLECTORS"
ALLOWED_SCRIPTS = ("backfill_universe.py", "tick_collect_804_828_al.py", "tick_compact_daemon.py",
                   "scripts/collect_program_al.py")

# kind -> (handler, 작업 그룹, 잠금 자원). 수집은 같은 그룹 `collect` 라 동시에 1개(REST 한도가 계정 단위라서).
KINDS = {
    "collect_daily": ("datahub.jobs:collect_daily", "collect", "daily_minute"),
    "collect_ticks": ("datahub.jobs:collect_ticks", "collect", "tick_al"),
    "collect_minute_al": ("datahub.jobs:collect_minute_al", "collect", "minute_al"),
    "archive_minute_al": ("datahub.jobs:archive_minute_al", "local", "minute_al"),
    # 스케줄러가 만드는 작업은 화면이 종류 이름으로 구분한다(같은 처리기, 다른 kind)
    "tick_nightly": ("datahub.jobs:collect_ticks", "collect", "tick_al"),
    "daily_catchup": ("datahub.jobs:collect_daily", "collect", "daily_minute"),
    "program_nightly": ("datahub.jobs:collect_program_al", "collect", "program_al"),
}


class CommandNotAllowed(Exception):
    pass


def create_job(store, kind: str, payload: dict | None = None, scheduled_at: str | None = None, trigger: str = "user") -> dict:
    """API·스케줄러가 작업 파일을 만든다(실행은 jobrunner 디스패처)."""
    handler, group, lock = KINDS[kind]
    return store.create(kind, group, handler, payload or {}, scheduled_at=scheduled_at, lock=lock, trigger=trigger)


# ---------- 허용 목록 ----------


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def check_command(cmd: "collectors.Command") -> None:
    """허용되지 않은 명령이면 CommandNotAllowed. 셸을 안 쓰므로 인자 리스트 모양만 본다."""
    a, root, theme = cmd.argv, str(catalog.root()), str(catalog.root() / "kospi-theme-engine")
    if not a:
        raise CommandNotAllowed("빈 명령")
    if _same(a[0], sys.executable) and len(a) > 1 and a[1] in ALLOWED_SCRIPTS and _same(cmd.cwd, root):
        return
    if _same(a[0], sys.executable) and a[1:6] == ["-X", "utf8", "-u", "-m", "scripts.fetch_minute"] and _same(cmd.cwd, theme):
        return
    ps1 = str(catalog.root() / "kospi-theme-engine" / "run_minute_refresh.ps1")
    if (a[0].lower() == "powershell" and a[1:6] == ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1]
            and a[6:] == ["-Now"] and _same(cmd.cwd, theme)):
        return
    raise CommandNotAllowed(f"허용되지 않은 명령: {' '.join(a[:4])} …")


def _substitute_fake(cmd: "collectors.Command") -> "collectors.Command":
    """실제 수집기 명령을 가짜 수집기로 바꾼다. 인자 모양은 그대로 넘긴다(허용 목록은 바꾸기 전 원본으로 검사)."""
    a = cmd.argv
    script = a[1] if len(a) > 1 else ""
    if script == "backfill_universe.py":
        kind, rest = "daily", a[2:]
    elif script == "tick_collect_804_828_al.py":
        kind, rest = "ticks", a[2:]
    elif script == "tick_compact_daemon.py":
        kind, rest = "compact", a[2:]
    else:
        kind, rest = "minute", []
    repo = str(Path(__file__).resolve().parent.parent)          # 테스트는 루트가 임시 폴더라 datahub 를 못 찾는다 — 경로를 준다
    env = {**cmd.env, "PYTHONPATH": os.pathsep.join(filter(None, [repo, os.environ.get("PYTHONPATH", "")]))}
    return collectors.Command([sys.executable, "-m", "datahub._fake_collector", kind, *rest], str(catalog.root()), env, cmd.label)


# ---------- 실행 ----------


class _Run:
    """자식 하나를 돌리며 장부에서 진행률을 읽는다."""

    def __init__(self, ctx, lock: str, stage: str, pct_from: float = 0.0, pct_to: float = 100.0):
        self.ctx, self.lock, self.stage = ctx, lock, stage
        self.pct_from, self.pct_to = pct_from, pct_to
        self.waiting = False
        self.deferred = 0
        self.ledger_run: str | None = None
        self._stop = threading.Event()

    def _on_line(self, line: str) -> None:
        if line.startswith("잠금 대기"):
            self.waiting = True
        m = re.search(r"(\d+)종목은 미룸", line)
        if m:
            self.deferred = int(m.group(1))

    def _poll(self) -> None:
        while not self._stop.wait(POLL_SECONDS):
            self.poll_once()

    def poll_once(self) -> None:
        evs = [e for e in ledger.read(1) if e.get("job_id") == self.ctx.job_id and e["event"] in ("start", "progress")]
        if not evs:
            if self.waiting:
                o = locks.owner(self.lock)
                self.ctx.progress(None, self.stage, "잠금 대기 중", waiting_lock={"resource": self.lock, "owner": o.cmdline if o else None})
            return
        last = evs[-1]
        self.ledger_run = last["run"]
        done, total = last.get("done"), last.get("total")
        # 시작만 있고 아직 진행 기록이 없으면 구간 시작값(0%)으로 — "None(—)" 으로 비워 두지 않는다(시작은 됐다는 뜻)
        pct = (self.pct_from + (self.pct_to - self.pct_from) * done / total) if done is not None and total else self.pct_from
        self.ctx.progress(pct, self.stage, f"[{done}/{total}]" if total else "시작", waiting_lock=None)

    def run(self, cmd: "collectors.Command", real_check: bool = True) -> int:
        if real_check:
            check_command(cmd)                                           # 원본 명령을 검사한 뒤
        if os.environ.get(FAKE_ENV) == "1":
            cmd = _substitute_fake(cmd)                                  # 가짜로 바꾼다
        env = {**cmd.env, "DATAHUB_TRIGGER": "hub", "DATAHUB_JOB_ID": self.ctx.job_id}
        t = threading.Thread(target=self._poll, daemon=True)
        t.start()
        try:
            rc = self.ctx.run_child(cmd.argv, cwd=cmd.cwd, env=env, on_line=self._on_line)
        finally:
            self._stop.set()
            self.poll_once()
        if self.ledger_run:
            self.ctx.store.update(self.ctx.job_id, ledger_run=self.ledger_run)
        if self.ctx.is_cancelled():
            raise CancelledError()
        return rc


def _job_dir(ctx) -> Path:
    d = ctx.store.job_dir(ctx.job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _codes_file(ctx, codes: list[str]) -> str:
    p = _job_dir(ctx) / "codes.txt"
    p.write_text("\n".join(codes) + "\n", encoding="utf-8")
    return str(p)


def _ok(rc: int, what: str) -> None:
    if rc != 0:
        raise RuntimeError(f"{what} 실패(종료코드 {rc})")


# ---------- handler ----------


def collect_daily(ctx):
    p = ctx.payload
    codes = list(p.get("codes") or [])
    file = _codes_file(ctx, codes) if len(codes) > policy.LIGHT_MAX_CODES else None
    cmd = collectors.collect_daily(p.get("mode", "stale"), None if file else codes, file, p.get("stop_at"))
    ctx.progress(0, "수집", cmd.label)
    _ok(_Run(ctx, "daily_minute", "수집").run(cmd), "일봉 수집")
    ctx.progress(100, "완료")
    return {"message": cmd.label}


def collect_minute_al(ctx):
    p = ctx.payload
    if p.get("mode") == "sophie_baseline" and locks.marker_running("minute_refresh"):
        raise RuntimeError("MINUTE_REFRESH_RUNNING: 분봉 기준선 갱신이 이미 실행 중")
    cmd = collectors.collect_minute_al(p.get("mode", "codes"), p.get("codes"), p.get("days"))
    ctx.progress(0, "수집", cmd.label)
    _ok(_Run(ctx, "minute_al", "수집").run(cmd), "통합 분봉 수집")
    ctx.progress(100, "완료")
    return {"message": cmd.label}


def collect_program_al(ctx):
    """종목별 프로그램 매매 수집. 수집기가 이미 받은 종목은 건너뛰어 다시 돌려도 안전하다."""
    cmd = collectors.collect_program_al()
    ctx.progress(0, "수집", cmd.label)
    _ok(_Run(ctx, "program_al", "수집").run(cmd), "프로그램 매매 수집")
    ctx.progress(100, "완료")
    return {"message": cmd.label}


def archive_minute_al(ctx):
    """캐시 → 보관소 병합. API 를 안 쓰는 로컬 작업이라 자식 없이 이 프로세스 안에서 한다(워커가 이미 분리된 프로세스)."""
    from . import gate, minute_al_archive as arch
    os.environ.update(DATAHUB_TRIGGER="hub", DATAHUB_JOB_ID=ctx.job_id)
    codes = ctx.payload.get("codes") or None
    with gate.write("minute_al", writer="datahub.archive-minute-al", detail={"codes": len(codes) if codes else None}) as w:
        s = arch.archive_all(codes, only_stale=True, progress=lambda i, n: (w.progress(i, n), ctx.progress(100 * i / n, "병합", f"[{i}/{n}]"),
                                                                            _raise_if(ctx)))
        w.result(**{k: v for k, v in s.items() if k != "failed"}, failed=len(s["failed"]))
    ctx.store.update(ctx.job_id, ledger_run=w.id)
    if s["failed"]:
        raise RuntimeError(f"보관소 병합 실패 {len(s['failed'])}종목: {s['failed'][0]}")
    return {"message": f"병합 {s['merged']} · 건너뜀 {s['skipped']} · 행 {s['rows_before']:,}→{s['rows_after']:,}"}


def _raise_if(ctx) -> None:
    if ctx.is_cancelled():
        raise CancelledError()


def tick_run_path(job_id: str) -> Path:
    return catalog.state_base() / "state" / "datahub" / "tick_runs" / f"{job_id}.json"


def collect_ticks(ctx):
    """체결 수집: catch_up(빠진 쌍 전부, 허브 계산) / range(기간 지정).
    수집 → 압축(`tick_compact_daemon.py --once`) → 상태 재계산 → (야간 회차면) 시도 횟수 갱신까지 한 작업에서."""
    p = ctx.payload
    cal, now = Calendar(), clock()
    win = status.tick_window(now, cal)
    ctx.progress(0, "계획")
    if p.get("mode", "catch_up") == "catch_up":
        plan = collectors.plan_tick_catch_up(win)
        if plan is None:
            ctx.log("받을 것 없음 — API 를 호출하지 않는다")
            _write_run(ctx, p, planned=0, remaining=0, deferred=0, failed=0, start=None, end=None)
            ctx.progress(100, "완료", "받을 것 없음")
            return {"message": "받을 것 없음"}
        start, end, codes, planned = plan.start, plan.end, plan.codes, len(plan.pairs)
    else:
        start, end = p["start"], p["end"]
        in_win = {r["date"]: r for r in win["dates"]}
        if start not in in_win or end not in in_win:
            raise ValueError("OUT_OF_TICK_WINDOW: 기간이 체결 조회창(최근 20거래일) 밖이다")
        codes = list(p.get("codes") or [])
        if not codes:
            exp = status.expected_tick_codes(_daily(), [date.fromisoformat(r["date"]) for r in win["dates"] if start <= r["date"] <= end],
                                            catalog.dataset("tick_al").freshness.get("top_n", 35),
                                            set(catalog.dataset("tick_al").freshness.get("extra_codes", [])), _mega())
            codes = sorted({c for v in exp.values() for c in v})
        planned = len(codes)
    stop_at = p.get("stop_at") or (policy.stop_at() if p.get("nightly") else None)
    file = _codes_file(ctx, codes)
    cmd = collectors.collect_ticks(start, end, file, int(p.get("concurrency", 4)), stop_at)
    run = _Run(ctx, "tick_al", "수집", 5, 85)
    ctx.progress(5, "수집", f"{start}~{end} · {len(codes)}종목")
    rc = run.run(cmd)
    ctx.progress(85, "압축")
    crc = _Run(ctx, "tick_al", "압축").run(collectors.tick_compact(collectors.tick_progress_path(start, end, codes)))
    if crc != 0:
        ctx.log(f"압축 종료코드 {crc} — 원본 csv 는 남아 있고 수집된 것으로 친다")
    ctx.progress(95, "재확인")
    plan2 = collectors.plan_tick_catch_up(status.tick_window(clock(), cal))
    still = plan2.pairs if plan2 else []
    late = set(codes[-run.deferred:]) if run.deferred else set()
    deferred = [pr for pr in still if pr[0] in late]
    if p.get("night"):
        collectors.record_night(still, date.fromisoformat(p["night"]), deferred)
    _write_run(ctx, p, planned=planned, remaining=len(still), deferred=len(deferred), failed=len(still) - len(deferred), start=start, end=end)
    _ok(rc, "체결 수집")
    ctx.progress(100, "완료", f"남은 {len(still)}쌍" + (f"(미룸 {len(deferred)})" if deferred else ""))
    return {"message": f"빠진 {planned}쌍 중 {max(planned - len(still), 0)} 수집, 남은 {len(still)}"}


def _write_run(ctx, p, **fields) -> None:
    f = tick_run_path(ctx.job_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"job_id": ctx.job_id, "night": p.get("night"), "finished_at": clock().isoformat(timespec="seconds"), **fields},
                            ensure_ascii=False), encoding="utf-8")


def _daily():
    from backtesting.daily_cache import load_daily_all
    return load_daily_all(daily_dir=str(catalog.path("daily", code="X").parent), cache_path=str(catalog.path("daily_all_cache")))


def _mega() -> set[str]:
    from data_exclude import MEGA_CAP_EXCLUDE
    return set(MEGA_CAP_EXCLUDE)
