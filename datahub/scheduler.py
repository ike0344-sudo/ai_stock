"""허브 일정 실행기 (설계 §2.4.7·§2.4.11, 테스트 H13·H16~H21).

허브 소유 일정 넷 — `tick_nightly`(매일 20:15, 빠진 (종목, 날짜) 전부·같은 밤 재시도·3일 밤 실패 포기) ·
`daily_catchup`(거래일 05:30~08:10, 일봉이 밀렸을 때만) · `minute_archive`(21:00) · `freshness_check`(10분마다 알림) —
을 `tick(now)` 한 번의 판정으로 실행한다. 시계는 인자로 받는다(테스트가 가짜 시계를 넣는다).
**서버 연결은 하지 않는다** — `start(root, store)` 가 스레드만 돌려주고, 서버(monitoring-agent)가 그걸 부른다.

원칙: 날짜가 아니라 "빠진 것"을 받는다. 서버가 꺼져 있다 켜져도 "오늘 밤 아직 안 돈 것"은 시작 날짜 기준으로 바로 돈다(H20).
외부 일정(워치독·8765·소피증권)은 표식·로그·장부로 **관측만** 한다.
"""
import json
import logging
import os
import threading
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

from . import alerts, catalog, collectors, jobs, ledger, locks, policy, sophie, status
from .calendar import Calendar

log = logging.getLogger("datahub.scheduler")
NIGHT_START = "20:15"
CATCHUP_FROM = "05:30"
ARCHIVE_AT = "21:00"
PROGRAM_AT = "20:10"          # 종목별 프로그램 매매 — 20:00 NXT 마감 뒤, **당일분만** 받을 수 있다
RETRY_MINUTES = 60
MAX_NIGHT_ATTEMPTS = 3
PREREQ_MAX_WAIT = timedelta(hours=2)
CHECK_EVERY = timedelta(minutes=10)
HUB_SCHEDULES = ("tick_nightly", "daily_catchup", "minute_archive", "freshness_check", "program_nightly",
                 "news_am", "news_pm", "news_daily")
NEWS_AT = {"news_am": "11:35", "news_pm": "14:55", "news_daily": "17:30"}     # 인포스탁 오전장(~11:20)·오후장(~14:40)·데일리(~16:59) 글이 올라온 뒤
NEWS_UNTIL = {"news_am": "14:30", "news_pm": "18:00", "news_daily": "20:00"}  # 오후장 글이 오전장 글을 덮으면 오전은 영영 못 받는다 — 그 전에 포기
NEWS_JOB = {"news_am": ("infostock_news", {"session": "am"}), "news_pm": ("infostock_news", {"session": "pm"}),
            "news_daily": ("infostock_daily", {})}
ACTIVE = {"scheduled", "queued", "running"}


class NotHubOwned(Exception):
    """허브 소유가 아닌 일정을 고치려 했다(API 409 NOT_HUB_OWNED)."""


def _dir() -> Path:
    return catalog.state_base() / "state" / "datahub"


def _read(name: str, default):
    try:
        return json.loads((_dir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(name: str, data) -> None:
    p = _dir() / name
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


# ---------- 덮어쓰기(overrides.json) ----------


def _schedule_def(sid: str):
    return next((s for s in catalog.load().schedules if s.id == sid), None)


def schedule_enabled(sid: str) -> bool:
    ov = _read("overrides.json", {}).get("schedules", {}).get(sid, {})
    return ov["enabled"] if "enabled" in ov else (_schedule_def(sid) is not None and _schedule_def(sid).default == "on")


def schedule_time(sid: str, default: str) -> str:
    return _read("overrides.json", {}).get("schedules", {}).get(sid, {}).get("time") or default


def set_schedule(sid: str, enabled: bool | None = None, time: str | None = None) -> dict:
    """켜기·끄기·시각 변경(`PATCH /api/data/schedules/{id}`). 허브 소유만 — 외부는 NotHubOwned."""
    d = _schedule_def(sid)
    if d is None:
        raise KeyError(sid)
    if d.owner != "hub":
        raise NotHubOwned(sid)
    if time is not None:
        dtime.fromisoformat(time)                          # 형식 검사(HH:MM)
    ov = _read("overrides.json", {})
    cur = ov.setdefault("schedules", {}).setdefault(sid, {})
    if enabled is not None:
        cur["enabled"] = bool(enabled)
    if time is not None:
        cur["time"] = time
    _write("overrides.json", ov)
    return cur


# ---------- 시간 계산 ----------


def current_night(now: datetime, start: str = NIGHT_START, stop: str | None = None) -> date | None:
    """지금이 야간 구간(start ~ 다음날 stop)이면 그 밤의 이름(시작 날짜). 아니면 None(주간)."""
    stop = stop or policy.stop_at()
    if now.time() >= dtime.fromisoformat(start):
        return now.date()
    if now.time() < dtime.fromisoformat(stop):
        return now.date() - timedelta(days=1)
    return None


class Scheduler:
    def __init__(self, store, clock=datetime.now, sender=alerts.telegram_sender):
        self.store, self.clock, self.sender = store, clock, sender

    # ---- 공통 ----
    def _state(self) -> dict:
        return _read("schedule_state.json", {})

    def _save(self, st: dict) -> None:
        _write("schedule_state.json", st)

    def _job(self, job_id: str | None):
        return self.store.read(job_id) if job_id else None

    def tick(self, now: datetime | None = None) -> list[str]:
        """한 번 판정해 한 일을 돌려준다(로그·테스트용)."""
        now = now or self.clock()
        acts: list[str] = []
        for name, fn in (("tick_nightly", self._tick_nightly), ("daily_catchup", self._daily_catchup),
                         ("minute_archive", self._minute_archive), ("freshness_check", self._freshness_check),
                         ("program_nightly", self._program_nightly),
                         ("news_am", lambda now: self._news(now, "news_am")),
                         ("news_pm", lambda now: self._news(now, "news_pm")),
                         ("news_daily", lambda now: self._news(now, "news_daily"))):
            try:
                acts += fn(now)
            except Exception:                              # 한 일정의 오류가 다른 일정을 막지 않는다
                log.exception("일정 %s 실패", name)
                acts.append(f"{name}:오류")
        return acts

    # ---- tick_nightly (§2.4.11) ----
    def _tick_nightly(self, now: datetime) -> list[str]:
        sid = "tick_nightly"
        if not schedule_enabled(sid):
            return []
        start = schedule_time(sid, NIGHT_START)
        night = current_night(now, start)
        if night is None:
            return []                                      # 주간 — 다음 야간 시작에
        cal = Calendar()
        allst = self._state()
        st = allst.get(sid) or {}
        if st.get("night") != night.isoformat():
            st = {"night": night.isoformat(), "jobs": [], "evaluated": [], "attempts": 0, "wait_since": None, "done": False, "note": ""}
        acts: list[str] = []
        # 진행 중이거나 예약된 작업이 있으면 기다린다. 끝난 작업은 결과를 보고 재시도를 정한다.
        for jid in st["jobs"]:
            job = self._job(jid)
            if job is None or job["status"] in ACTIVE:
                allst[sid] = st
                self._save(allst)
                return acts
            if jid not in st["evaluated"]:
                st["evaluated"].append(jid)
                acts += self._after_tick_job(st, job, now, night)
        if st["done"]:
            allst[sid] = st
            self._save(allst)
            return acts
        if len(st["evaluated"]) < len(st["jobs"]):
            return acts
        # 선행(야간 갱신·분봉 기준선 갱신)이 도는 중이면 최대 2시간 기다린다 — REST 한도 경합 방지
        busy = [m for m in locks.MARKERS if locks.marker_running(m)]
        if busy:
            ws = datetime.fromisoformat(st["wait_since"]) if st["wait_since"] else now
            st["wait_since"] = ws.isoformat(timespec="seconds")
            if now - ws < PREREQ_MAX_WAIT:
                allst[sid] = st
                self._save(allst)
                return acts + [f"{sid}:선행 대기({','.join(busy)})"]
        plan = collectors.plan_tick_catch_up(status.tick_window(now, cal))
        if plan is None:
            st.update(done=True, note="받을 것 없음")
            collectors.record_night([], night)
            allst[sid] = st
            self._save(allst)
            return acts + [f"{sid}:받을 것 없음"]
        st["attempts"] += 1
        job = jobs.create_job(self.store, "tick_nightly", {"mode": "catch_up", "night": night.isoformat(), "nightly": True,
                                                            "retry": st["attempts"] - 1}, trigger="hub")
        st["jobs"].append(job["job_id"])
        allst[sid] = st
        self._save(allst)
        return acts + [f"{sid}:작업 생성 {job['job_id']} (빠진 {len(plan.pairs)}쌍, {plan.start}~{plan.end})"]

    def _after_tick_job(self, st: dict, job: dict, now: datetime, night: date) -> list[str]:
        run = _read(f"tick_runs/{job['job_id']}.json", None)
        failed = run["failed"] if run else None            # 실패(미룬 것 제외)로 남은 쌍
        if failed == 0 and job["status"] in ("succeeded", "failed"):
            st.update(done=True, note="완료" if run["remaining"] == 0 else f"미룬 {run['deferred']}쌍은 다음 밤에")
            return [f"tick_nightly:끝({st['note']})"]
        if job["status"] == "cancelled":
            st.update(done=True, note="취소됨")
            return ["tick_nightly:취소됨"]
        at = now + timedelta(minutes=RETRY_MINUTES)
        night_end = datetime.combine(night + timedelta(days=1), dtime.fromisoformat(policy.stop_at()))
        if st["attempts"] >= MAX_NIGHT_ATTEMPTS or at >= night_end:
            st.update(done=True, note=f"재시도 소진(시도 {st['attempts']}회)" if st["attempts"] >= MAX_NIGHT_ATTEMPTS else "야간 구간 끝 — 남은 건 다음 밤에")
            return ["tick_nightly:재시도 없음"]
        nxt = jobs.create_job(self.store, "tick_nightly", {"mode": "catch_up", "night": night.isoformat(), "nightly": True,
                                                            "retry": st["attempts"]}, scheduled_at=at.isoformat(timespec="seconds"), trigger="hub")
        st["attempts"] += 1
        st["jobs"].append(nxt["job_id"])
        return [f"tick_nightly:{RETRY_MINUTES}분 뒤 재시도 예약(시도 {st['attempts']}회째)"]

    # ---- daily_catchup ----
    def _daily_catchup(self, now: datetime) -> list[str]:
        sid = "daily_catchup"
        if not schedule_enabled(sid):
            return []
        cal = Calendar()
        stop = policy.stop_at()
        allst = self._state()
        st = allst.get(sid) or {}
        acts: list[str] = []
        if st.get("date") == now.date().isoformat():
            if st.get("job") and not st.get("final"):      # 이미 띄웠다 — 끝났으면 결과를 catchup.json 에 (알림 재료)
                job = self._job(st["job"])
                if job and job["status"] not in ACTIVE:
                    remaining = collectors.plan_daily_catch_up(now, cal)
                    sophie_left = [c for c in remaining if c in status.universe_codes()]
                    passed = now.time() >= dtime.fromisoformat(stop)
                    _write("catchup.json", {"date": st["date"], "finished_at": now.isoformat(timespec="seconds"),
                                            "received": max(st.get("planned", 0) - len(remaining), 0), "remaining": len(remaining),
                                            "sophie_remaining": len(sophie_left), "deadline_passed": passed and len(remaining) > 0})
                    st["final"] = passed or not remaining
                    allst[sid] = st
                    self._save(allst)
                    acts.append(f"{sid}:결과 기록(남은 {len(remaining)})")
            return acts
        t = now.time()
        if not (cal.is_trading_day(now.date()) and dtime.fromisoformat(CATCHUP_FROM) <= t < dtime.fromisoformat(stop)):
            return acts
        st = {"date": now.date().isoformat(), "job": None, "final": False}
        d = status.dataset_status("daily", now, cal)
        sophie_codes = status.universe_codes()
        plan = collectors.plan_daily_catch_up(now, cal)
        behind = (d.get("reference_date") or "") < cal.settled_day(now).isoformat()
        if not (behind or any(c in sophie_codes for c in plan)) or not plan:
            st["final"] = True                             # 정상 — 아무것도 안 한다(월요일 아침 오탐 없음)
            allst[sid] = st
            self._save(allst)
            return acts
        job = jobs.create_job(self.store, "daily_catchup", {"mode": "codes", "codes": plan, "stop_at": stop}, trigger="hub")
        st["job"] = job["job_id"]
        st["planned"] = len(plan)
        allst[sid] = st
        self._save(allst)
        return acts + [f"{sid}:작업 생성 {job['job_id']} ({len(plan)}종목, 소피증권 먼저)"]

    # ---- minute_archive ----
    def _minute_archive(self, now: datetime) -> list[str]:
        sid = "minute_archive"
        if not schedule_enabled(sid) or now.time() < dtime.fromisoformat(schedule_time(sid, ARCHIVE_AT)):
            return []
        allst = self._state()
        st = allst.get(sid) or {}
        if st.get("date") == now.date().isoformat():
            return []
        job = jobs.create_job(self.store, "archive_minute_al", {}, trigger="hub")
        allst[sid] = {"date": now.date().isoformat(), "job": job["job_id"]}
        self._save(allst)
        return [f"{sid}:작업 생성 {job['job_id']}"]

    # ---- program_nightly ----
    def _program_nightly(self, now: datetime) -> list[str]:
        """거래일 20:10 에 한 번. 실패하면 같은 밤 30분 뒤 다시(최대 3번) — 자정이 지나면 영영 못 받는다."""
        sid = "program_nightly"
        if not schedule_enabled(sid) or now.time() < dtime.fromisoformat(schedule_time(sid, PROGRAM_AT)):
            return []
        if not Calendar().is_trading_day(now.date()):
            return []
        allst = self._state()
        st = allst.get(sid) or {}
        today = now.date().isoformat()
        if st.get("date") == today:
            job = self._job(st.get("job"))
            failed = job is not None and job.get("status") in ("failed", "error", "cancelled")
            if not failed or st.get("tries", 1) >= 3 or                     now - datetime.fromisoformat(st["at"]) < timedelta(minutes=30):
                return []
        tries = st.get("tries", 0) + 1 if st.get("date") == today else 1
        job = jobs.create_job(self.store, "program_nightly", {}, trigger="hub")
        allst[sid] = {"date": today, "job": job["job_id"], "tries": tries, "at": now.isoformat()}
        self._save(allst)
        return [f"{sid}:작업 생성 {job['job_id']} ({tries}번째)"]

    # ---- news_am / news_pm ----
    def _news(self, now: datetime, sid: str) -> list[str]:
        """거래일 정해진 시각부터, 그 세션 글을 받을 때까지 10분 간격으로 최대 5번. 글 보기 페이지가 로그인 벽이라
        최신 글로만 받을 수 있다 — 오후장 글이 올라오면 오전장은 영영 못 받는다."""
        if not schedule_enabled(sid) or not (dtime.fromisoformat(schedule_time(sid, NEWS_AT[sid])) <= now.time() < dtime.fromisoformat(NEWS_UNTIL[sid])):
            return []
        if not Calendar().is_trading_day(now.date()):
            return []
        allst = self._state()
        st = allst.get(sid) or {}
        today = now.date().isoformat()
        if st.get("date") == today:
            job = self._job(st.get("job"))
            if job is None or job.get("status") in ("queued", "running", "done"):
                return []
            if st.get("tries", 1) >= 5 or now - datetime.fromisoformat(st["at"]) < timedelta(minutes=10):
                return []
        tries = st.get("tries", 0) + 1 if st.get("date") == today else 1
        kind, payload = NEWS_JOB[sid]
        job = jobs.create_job(self.store, kind, payload, trigger="hub")
        allst[sid] = {"date": today, "job": job["job_id"], "tries": tries, "at": now.isoformat()}
        self._save(allst)
        return [f"{sid}:작업 생성 {job['job_id']} ({tries}번째)"]

    # ---- freshness_check ----
    def _freshness_check(self, now: datetime) -> list[str]:
        sid = "freshness_check"
        if not schedule_enabled(sid):
            return []
        allst = self._state()
        st = allst.get(sid) or {}
        last = datetime.fromisoformat(st["last"]) if st.get("last") else None
        if last and now - last < CHECK_EVERY:
            return []
        sent = alerts.check_and_send(now, self.sender)
        allst[sid] = {"last": now.isoformat(timespec="seconds"), "sent": [a.id for a in sent]}
        self._save(allst)
        return [f"{sid}:알림 {len(sent)}건"]


# ---------- 일정 목록 (`GET /api/data/schedules`, 계약: frontend/src/types/data.ts ScheduleRow) ----------

DEFAULT_TIMES = {"tick_nightly": NIGHT_START, "minute_archive": ARCHIVE_AT, "program_nightly": PROGRAM_AT,
                 **NEWS_AT}     # 시각을 바꿀 수 있는 허브 일정
JOB_KIND = {"tick_nightly": "tick_nightly", "daily_catchup": "daily_catchup", "minute_archive": "archive_minute_al",
            "program_nightly": "program_nightly", "news_am": "infostock_news", "news_pm": "infostock_news",
            "news_daily": "infostock_daily"}


def _marker_times(name: str):
    def rd(k):
        try:
            return json.loads((catalog.root() / "state" / name / f"last_run_{k}.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
    s, f = rd("started"), rd("finished")
    iso = lambda t: datetime.fromtimestamp(t).isoformat(timespec="minutes") if t else None
    return iso(s.get("started_at")), iso(f.get("finished_at")), f.get("ok")


def _next_slot(now: datetime, hhmm: str, cal: Calendar, trading_only: bool = False) -> str:
    t = dtime.fromisoformat(hhmm)
    d = now.date()
    if now.time() >= t:
        d += timedelta(days=1)
    while trading_only and not cal.is_trading_day(d):
        d += timedelta(days=1)
    return datetime.combine(d, t).isoformat(timespec="minutes")


def _run_row(job: dict) -> dict:
    run = _read(f"tick_runs/{job['job_id']}.json", None)
    ok = None if job["status"] in ACTIVE else job["status"] == "succeeded"
    planned = run["planned"] if run else None
    remaining = run["remaining"] if run else None
    return {"job_id": job["job_id"], "started": job.get("started_at") or job.get("scheduled_at") or job["created_at"][:19],
            "finished": job.get("finished_at"), "planned": planned,
            "received": (planned - remaining) if run else None, "remaining": remaining,
            "deferred": run["deferred"] if run else None, "ok": ok,
            "result": (f"빠진 {planned}쌍 중 {planned - remaining} 수집" if run else {"queued": "대기", "scheduled": "예약", "running": "실행 중",
                                                                                      "succeeded": "완료", "failed": job.get("error") or "실패",
                                                                                      "cancelled": "취소됨"}[job["status"]])}


def schedules_view(store, now: datetime | None = None) -> list[dict]:
    """일정 전부 — 주인·마지막·결과·다음·놓침. 허브 소유는 켜기/끄기·시각 변경 가능(editable), 외부는 관측만."""
    now, cal = now or datetime.now(), Calendar()
    return [schedule_row(store, d.id, now, cal) for d in catalog.load().schedules]


def schedule_row(store, sid: str, now: datetime | None = None, cal: Calendar | None = None) -> dict:
    now, cal = now or datetime.now(), cal or Calendar()
    d = _schedule_def(sid)
    if d is None:
        raise KeyError(sid)
    row = {"id": d.id, "label": d.label or d.id, "owner": d.owner, "when": d.when, "does": d.does, "enabled": None, "editable": False,
           "time": None, "last_started": None, "last_finished": None, "last_ok": None, "last_result": None, "next_expected": None,
           "missed": False, "missed_note": None, "runs": []}
    if d.owner == "hub":
        row.update(enabled=schedule_enabled(d.id), editable=True, time=schedule_time(d.id, DEFAULT_TIMES[d.id]) if d.id in DEFAULT_TIMES else None)
        kind = JOB_KIND.get(d.id)
        js = [j for j in store.list_jobs(kind=kind, limit=14) if j.get("trigger") == "hub"] if kind else []
        row["runs"] = [_run_row(j) for j in js]
        if js:
            last = next((r for r in row["runs"] if r["ok"] is not None), None)
            if last:
                row.update(last_started=last["started"], last_finished=last["finished"], last_ok=last["ok"], last_result=last["result"])
        if d.id == "freshness_check":
            st = _read("schedule_state.json", {}).get("freshness_check", {})
            row.update(last_started=st.get("last"), last_finished=st.get("last"), last_ok=True if st.get("last") else None,
                       last_result=f"알림 {len(st.get('sent', []))}건" if st.get("last") else None,
                       next_expected=(datetime.fromisoformat(st["last"]) + CHECK_EVERY).isoformat(timespec="minutes") if st.get("last") else None)
        elif d.id == "daily_catchup":
            row["next_expected"] = _next_slot(now, CATCHUP_FROM, cal, trading_only=True)
        else:
            row["next_expected"] = _next_slot(now, row["time"], cal)
        return row
    row.update(_observe(d.id, now, cal, now.date()))
    return row


def _observe(sid: str, now: datetime, cal: Calendar, today: date) -> dict:
    """외부 일정 관측: 마지막 시작·끝·결과, 다음 예정, 놓침."""
    if sid == "daily_report":
        s, f, ok = _marker_times("daily_report")
        ran_today = bool(s and s[:10] == today.isoformat())
        missed = cal.is_trading_day(today) and now.hour >= 18 and not ran_today
        return {"last_started": s, "last_finished": f, "last_ok": ok, "missed": missed, "missed_note": "오늘 16시 회차 기록 없음" if missed else None,
                "next_expected": _next_slot(now, "16:00", cal, trading_only=True)}
    if sid == "minute_refresh":
        m = sophie.minute_refresh(now)
        fin = datetime.fromisoformat(m["last_finished"]) if m["last_finished"] else None
        return {"last_started": m["last_started"], "last_finished": m["last_finished"], "last_result": m["last_result"],
                "next_expected": sophie.next_refresh_at(fin).isoformat(timespec="minutes")}     # ISO — "이후" 는 when 에 있다
    if sid == "top35_live":
        ev = [e for e in ledger.read(10) if e["event"] == "end" and e.get("writer") == "update_top35"]
        last = ev[-1]["ts"] if ev else None
        missed = cal.is_trading_day(today) and now.hour >= 17 and not (last and last[:10] == today.isoformat())
        return {"last_finished": last, "last_ok": ev[-1].get("ok") if ev else None, "missed": missed,
                "missed_note": "오늘 15:40 기록 없음" if missed else None, "next_expected": _next_slot(now, "15:40", cal, trading_only=True)}
    r = sophie.restarts(now)
    if sid == "sophie_restart":
        days = r["days_since"]
        missed = days is None or days > 1
        return {"last_started": r["last_midnight"], "last_finished": r["last_midnight"], "next_expected": _next_slot(now, "00:05", cal),
                "missed": missed, "missed_note": (f"{days}일째 기록 없음" if days is not None else "기록 없음") if missed else None}
    return {"last_started": r["last_rebuild"], "last_finished": r["last_rebuild"]}                # sophie_rebuild


# ---------- 서버 연결 지점 ----------


class SchedulerThread(threading.Thread):
    def __init__(self, scheduler: Scheduler, interval: float = 60.0):
        super().__init__(name="datahub-scheduler", daemon=True)
        self.scheduler, self.interval, self.stop_event = scheduler, interval, threading.Event()

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.scheduler.tick()
            except Exception:
                log.exception("스케줄러 tick 실패")
            self.stop_event.wait(self.interval)

    def stop(self) -> None:
        self.stop_event.set()


def start(root, store, interval: float = 60.0, sender=alerts.telegram_sender) -> SchedulerThread:
    """스케줄러 스레드를 시작해 돌려준다. 서버(monitoring-agent)가 기동 때 부르고 종료 때 `.stop()` 한다.
    서버가 꺼져 있다 켜지면 첫 tick 에서 "오늘 밤 아직 안 돈 것"이 바로 실행된다."""
    th = SchedulerThread(Scheduler(store, sender=sender), interval)
    th.start()
    return th
