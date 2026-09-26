"""허브 API 라우터 `/api/data/*` — 계약: `frontend/src/types/data.ts` · `docs/02-design/api/datahub-api.md` (설계 §4.1·§4.2).

**FastAPI 는 이 파일만 import 한다**(허브 핵심은 서버를 모른다, §9.3). 얇은 래퍼다 — 이미 있는 함수의 반환 dict 를 그대로 쓰고,
계약에 있는 칸만 여기서 덧붙인다. 라우터 객체(`router`)만 제공한다 — 앱 연결(`app.include_router`)은 서버 쪽(studio/api/app.py) 몫이다.

- 성공 `{"data": …}`, 실패 `{"error": {"code","message","details"}}`. 이 라우터가 스스로 봉투를 만든다(앱 예외 처리기에 기대지 않는다).
- 값을 모르면 null. 리스트가 비면 빈 배열(404 는 "없는 id" 에만 — 화면은 404 를 "라우트 없음"으로 읽는다).
- 작업 저장소는 `request.app.state.store`(jobrunner.JobStore), 즉시 시작은 `request.app.state.dispatcher`(있으면).
"""
import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, field_validator
from jobrunner.store import JobStore

from . import alerts, catalog, collectors, jobs, ledger, locks, policy, quality, scheduler, sophie, status
from .calendar import Calendar

clock: Callable[[], datetime] = datetime.now          # 테스트가 가짜 시계로 바꾼다
CACHE_SECONDS = 60.0                                  # overview 는 무거워(유휴 4초) 60초 캐시 — 설계 §8.9. 화면이 10초마다 불러도 계산은 분당 1번
CODE_RE = re.compile(r"^[0-9A-Z]{6}$")

SCHEDULE_IDS_BY_DATASET = {
    "daily": ["daily_report", "top35_live", "daily_catchup"], "minute_krx": ["daily_report", "top35_live"], "index": ["daily_report"],
    "minute_al": ["minute_refresh"], "minute_al_archive": ["minute_archive", "minute_refresh"], "tick_al": ["tick_nightly"],
    "sophie_reference": ["minute_refresh", "sophie_restart", "sophie_rebuild"], "sophie_live_logs": ["sophie_rebuild"],
    "high120": ["daily_report"],
}


# ---------- 오류 봉투 (자급자족) ----------


class HubError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status_code, self.code, self.message, self.details = status_code, code, message, details or {}


def _envelope(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}}, status_code=status_code)


def _field_errors(errors: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for e in errors:
        loc = ".".join(str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path"))
        out.setdefault(loc or "_", str(e.get("msg", "")).removeprefix("Value error, "))
    return out


class HubRoute(APIRoute):
    """이 라우터의 오류를 계약 봉투로 바꾼다 — HubError 와 요청 검증 오류(400 fieldErrors)."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except HubError as e:
                return _envelope(e.status_code, e.code, e.message, e.details)
            except RequestValidationError as e:
                return _envelope(400, "VALIDATION_ERROR", "요청 형식이 올바르지 않음",
                                 {"fieldErrors": _field_errors(e.errors())})
        return handler


router = APIRouter(prefix="/api/data", route_class=HubRoute)


def _ok(data: Any, status_code: int = 200) -> JSONResponse | dict:
    return {"data": data} if status_code == 200 else JSONResponse({"data": data}, status_code=status_code)


def _store(request: Request) -> JobStore:
    st = getattr(request.app.state, "store", None)
    return st if st is not None else JobStore(catalog.root())


def _iso(d: datetime | None) -> str | None:
    return d.isoformat(timespec="seconds") if d else None


# ---------- 공통 조각 ----------

_names_cache: dict = {"mtime": None, "names": {}}


def _names() -> dict[str, str]:
    p = catalog.root() / "data" / "stock_names.json"
    try:
        m = p.stat().st_mtime
        if _names_cache["mtime"] != m:
            _names_cache.update(mtime=m, names=json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}
    return _names_cache["names"]


def _owner_dict(resource: str) -> dict | None:
    o = locks.owner(resource)
    if o is None:
        return None
    return {"pid": o.pid, "cmdline": o.cmdline, "since": datetime.fromtimestamp(o.since).isoformat(timespec="seconds"),
            "alive": bool(o.alive), "dead": bool(o.dead), "source": ledger.source_label(o.cmdline)}


def _run_row(r: dict) -> dict:
    """장부 run -> LedgerRun. 허브가 띄운 것(trigger=hub)은 출처를 '허브'로."""
    src = "허브" if r.get("trigger") == "hub" else r["source"]
    return {"run": r["run"], "ts": r["ts"], "ended": r["ended"], "duration_sec": r["duration_sec"], "lock": r["lock"],
            "writer": r["writer"], "source": src, "trigger": r["trigger"], "job_id": r["job_id"], "state": r["state"],
            "done": r["done"], "total": r["total"], "detail": r["detail"], "error": r["error"]}


def _lock_datasets(resource: str) -> list[str]:
    return catalog.load().locks[resource].covers


def _collect_busy(store: JobStore) -> dict | None:
    """허브 수집(그룹 collect)이 이미 1개 실행·대기 중이면 그 작업."""
    for j in store.list_active():
        if j["group"] == "collect" and j["status"] in ("running", "queued"):
            return j
    return None


# ---------- overview ----------

_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, fn: Callable[[], Any]) -> Any:
    import time
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    val = fn()
    _cache[key] = (time.monotonic(), val)
    return val


def _activity(store: JobStore, now: datetime) -> list[dict]:
    rows = []
    for r in ledger.runs(ledger.read(1)):
        if r["state"] != "실행 중":
            continue
        row = _run_row(r)
        rows.append({"source": row["source"], "writer": row["writer"], "lock": row["lock"],
                     "dataset": (_lock_datasets(row["lock"])[0] if row["lock"] in catalog.load().locks else None),
                     "state": "실행 중", "done": row["done"], "total": row["total"], "since": row["ts"], "run": row["run"], "job_id": row["job_id"]})
    for j in store.list_active():                          # 관문에서 잠금을 기다리는 허브 작업
        if j["status"] != "running":
            continue
        wl = (store.read_progress(j["job_id"]) or {}).get("waiting_lock")
        if wl:
            res = wl.get("resource")
            rows.append({"source": "허브", "writer": j["kind"], "lock": res, "dataset": _lock_datasets(res)[0] if res in catalog.load().locks else None,
                         "state": "잠금 대기", "done": None, "total": None, "since": j.get("started_at") or j["created_at"][:19], "run": None,
                         "job_id": j["job_id"]})
    for name, source, writer in (("daily_report", "야간 갱신", "daily_report_job"), ("minute_refresh", "소피증권", "run_minute_refresh")):
        if locks.marker_running(name):
            s, _, _ = scheduler._marker_times(name)
            rows.append({"source": source, "writer": writer, "lock": None, "dataset": None, "state": "실행 중", "done": None, "total": None,
                         "since": s or _iso(now), "run": None, "job_id": None})
    return rows


def _overview(store: JobStore, now: datetime) -> dict:
    cal, memo = Calendar(), {}
    hours = policy.sophie_hours()
    bulk = policy.decide("collect_ticks", "catch_up", 0, now, hours, cal)
    found = alerts.evaluate(alerts.build_context(now, cal, memo), now, alerts.enabled_rules())
    first = alerts.track_active(found, now)
    titles = alerts.titles()
    cu = scheduler._read("catchup.json", None)
    return {
        "now": {"ts": _iso(now), "window": bulk.window, "sophie_hours": {"connect_from": hours.connect_from, "open": hours.open,
                                                                         "close": hours.close, "connect_to": hours.connect_to, "source": hours.source},
                "bulk": {"decision": bulk.decision, "suggest_at": _iso(bulk.suggest_at)}},
        "datasets": status.overview(now, memo),
        "activity": _activity(store, now),
        "alerts_active": [{"id": a.id, "title": titles.get(a.id, a.id), "target": a.target, "message": a.message,
                           "first_seen": first.get(f"{a.id}|{a.target}", _iso(now))} for a in found],
        "daily_catchup": ({"date": cu["date"], "received": cu.get("received", 0), "remaining": cu["remaining"],
                           "sophie_remaining": cu["sophie_remaining"], "deadline_passed": cu["deadline_passed"]}
                          if cu and cu.get("date") == now.date().isoformat() else None),
    }


@router.get("/overview")
def get_overview(request: Request):
    store = _store(request)
    return _ok(_cached("overview", lambda: _overview(store, clock())))


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, request: Request):
    try:
        d = catalog.dataset(dataset_id)
    except KeyError:
        raise HubError(404, "NOT_FOUND", f"없는 데이터셋: {dataset_id}") from None
    now = clock()
    row = status.dataset_status(dataset_id, now)
    recent = [_run_row(r) for r in reversed(ledger.runs(ledger.read(30))) if d.lock and r["lock"] == d.lock][:20]
    return _ok(row | {"notes": d.notes, "path": d.path, "writers": [w.model_dump() for w in d.writers], "readers": d.readers,
                      "freshness": d.freshness, "lock_owner": _owner_dict(d.lock) if d.lock else None,
                      "recent_ledger": recent, "schedule_ids": SCHEDULE_IDS_BY_DATASET.get(dataset_id, [])})


@router.get("/activity")
def get_activity(request: Request):
    return _ok(_activity(_store(request), clock()))


@router.get("/locks")
def get_locks():
    return _ok([{"resource": name, "covers": lk.covers, "held": bool((o := locks.owner(name)) and o.alive), "owner": _owner_dict(name)}
                for name, lk in catalog.load().locks.items()])


# ---------- 장부 ----------


@router.get("/ledger")
def get_ledger(lock: str | None = Query(None), source: str | None = Query(None), since: str | None = Query(None),
               limit: int = Query(100, ge=1, le=500)):
    fields: dict[str, str] = {}
    if lock is not None and lock not in catalog.load().locks:
        fields["lock"] = "daily_minute | minute_al | tick_al 중 하나"
    days = 14
    if since is not None:
        try:
            days = max(1, min(62, math.ceil((clock() - datetime.fromisoformat(since)).total_seconds() / 86400) + 1))
        except ValueError:
            fields["since"] = "ISO 날짜/시각이어야 함"
    if fields:
        raise HubError(400, "VALIDATION_ERROR", "요청 형식이 올바르지 않음", {"fieldErrors": fields})
    rows = [_run_row(r) for r in reversed(ledger.runs(ledger.read(days)))]
    if lock:
        rows = [r for r in rows if r["lock"] == lock]
    if source:
        rows = [r for r in rows if r["source"] == source]
    if since:
        rows = [r for r in rows if r["ts"] >= since]
    return _ok(rows[:limit])


@router.get("/ledger/unledgered")
def get_unledgered(hours: int = Query(24, ge=1, le=168)):
    now = clock()
    return _ok(status.unledgered_writes(now - timedelta(hours=hours), now))


# ---------- 정책 ----------

KINDS = ("collect_daily", "collect_ticks", "collect_minute_al", "archive_minute_al")


def _minute_targets() -> int | None:
    """소피증권 분봉 기준선 대상 수 — 마지막 갱신 로그의 `대상 N종목` 줄."""
    log = catalog.root() / "kospi-theme-engine" / "logs" / "minute_refresh.log"
    try:
        hits = re.findall(r"대상 (\d+)종목", log.read_bytes()[-200_000:].decode("utf-8", errors="ignore"))
        return int(hits[-1]) if hits else None
    except OSError:
        return None


def _estimate(kind: str, mode: str | None, n: int | None) -> tuple[int | None, str | None]:
    """예상 소요(초)와 근거. **추정**이다 — 모르면 (None, None)."""
    if kind == "collect_minute_al":
        if mode == "sophie_baseline":
            return 5160, "2026-09-19 실측 86분(288종목)"
        if mode in ("all_cached", "codes") and n:
            return round(n * 15 * 1.1), "종목 × 15페이지 × 1.1초(설계 §2.4.10)"
        if mode == "deep_archive" and n:
            return None, None
    if kind == "collect_daily" and mode in ("stale", "all") and n:
        return round(n * 6.5), "2026-09-15 야간 백필 실측 13,093초 ÷ 약 2,000종목"
    if kind == "collect_ticks" and n:
        return round(n * 360 / 4), "2026-09-20 실측 종목당 약 6분(동시 4)"
    return None, None


def _blocked(kind: str, mode: str | None, store: JobStore) -> dict | None:
    if kind == "collect_minute_al" and mode == "sophie_baseline" and locks.marker_running("minute_refresh"):
        return {"code": "MINUTE_REFRESH_RUNNING", "message": "소피증권 분봉 기준선 갱신이 이미 실행 중입니다", "details": {}}
    if kind != "archive_minute_al":
        busy = _collect_busy(store)
        if busy:
            return {"code": "COLLECT_BUSY", "message": "허브 수집이 이미 1개 실행 중입니다", "details": {"job_id": busy["job_id"]}}
    o = _owner_dict(jobs.KINDS[kind][2])
    if o and o["alive"]:
        return {"code": "LOCKED", "message": f"다른 작업이 데이터를 쓰는 중입니다(pid {o['pid']})", "details": {"owner": o, "pid": o["pid"]}}
    return None


def _n_codes(kind: str, mode: str | None, codes: list[str], now: datetime) -> int | None:
    if kind == "collect_daily":
        if mode == "codes":
            return len(codes)
        rows = [r for r in status.stale("daily") if not r["inactive"]]
        return len(rows) if mode == "stale" else max(0, len(status.latest_dates("daily")) - len(status.inactive_codes()))
    if kind == "collect_ticks":
        if mode == "range":
            return len(codes) or None
        plan = collectors.plan_tick_catch_up(status.tick_window(now, Calendar()))
        return len(plan.codes) if plan else 0
    if kind == "collect_minute_al":
        if mode == "sophie_baseline":
            return _minute_targets()
        if mode == "all_cached":
            return len(list((catalog.root() / catalog.dataset("minute_al").path.rsplit("/", 1)[0]).glob("*.csv")))
        return len(codes)
    return len(list((catalog.root() / catalog.dataset("minute_al").path.rsplit("/", 1)[0]).glob("*.csv")))


def _policy(store: JobStore, kind: str, mode: str | None, codes: list[str], now: datetime) -> dict:
    n = _n_codes(kind, mode, codes, now)
    blocked = _blocked(kind, mode, store)
    d = policy.decide(kind, mode, n or 0, now, hub_busy=bool(blocked and blocked["code"] == "COLLECT_BUSY"))
    eta, basis = _estimate(kind, mode, n)
    return {"kind": kind, "mode": mode, "weight": d.weight, "window": d.window, "decision": d.decision, "suggest_at": _iso(d.suggest_at),
            "reason": d.reason, "warnings": d.warnings, "n_codes": n, "eta_sec": eta, "estimate_basis": basis,
            "baseline_effect": (("updated" if mode == "sophie_baseline" else "unchanged") if kind == "collect_minute_al" else None),
            "blocked": blocked}


@router.get("/policy")
def get_policy(request: Request, kind: str = Query(...), mode: str | None = Query(None), codes: str | None = Query(None)):
    if kind not in KINDS:
        raise HubError(400, "VALIDATION_ERROR", "요청 형식이 올바르지 않음", {"fieldErrors": {"kind": " | ".join(KINDS) + " 중 하나"}})
    lst = [c for c in (codes or "").split(",") if c]
    return _ok(_policy(_store(request), kind, mode, lst, clock()))


# ---------- 밀림·결측·품질 ----------


def _only_daily(dataset: str) -> None:
    if dataset != "daily":
        raise HubError(400, "VALIDATION_ERROR", "요청 형식이 올바르지 않음", {"fieldErrors": {"dataset": "지금은 daily 만 지원"}})


@router.get("/stale")
def get_stale(dataset: str = Query("daily"), sophie_only: bool = Query(False)):
    _only_daily(dataset)
    dates = status.latest_dates("daily")
    ref = max(set(dates.values()), key=list(dates.values()).count) if dates else None
    names = _names()
    rows = [{"code": r["code"], "name": names.get(r["code"]), "last": r["last"],
             "days_behind": (date.fromisoformat(ref) - date.fromisoformat(r["last"])).days, "sophie": r["sophie"], "inactive": r["inactive"]}
            for r in status.stale("daily", sophie_only)]
    return _ok({"dataset": dataset, "reference_date": ref, "rows": rows})


@router.get("/gaps")
def get_gaps(dataset: str = Query("daily"), days: int = Query(120, ge=1, le=400)):
    _only_daily(dataset)
    return _ok({"dataset": dataset, "days": days, "threshold": 0.9, "rows": status.gaps(days=days, now=clock())})


@router.get("/quality")
def get_quality(dataset: str = Query("daily"), since: str | None = Query(None), limit: int = Query(200, ge=1, le=200)):
    _only_daily(dataset)
    q = quality.daily_quality(since=since, limit=limit)
    names = _names()
    return _ok({"dataset": dataset, "since": since, "rows_checked": q["rows_checked"], "counts": q["counts"],
                "issues": [i | {"name": names.get(i["code"])} for i in q["issues"]]})


# ---------- 체결 조회창 · 보관소 ----------


def _tick_window(store: JobStore, now: datetime) -> dict:
    cal = Calendar()
    w = status.tick_window(now, cal)
    left = {r["date"]: r["days_left"] for r in w["dates"]}
    att = collectors.load_attempts()
    names = _names()
    st = scheduler._read("schedule_state.json", {}).get("tick_nightly") or {}
    last_night = None
    if st.get("night") and st.get("jobs"):
        js = [j for j in (store.read(x) for x in st["jobs"]) if j]
        run = scheduler._read(f"tick_runs/{js[-1]['job_id']}.json", None) if js else None
        last_night = {"night": st["night"], "started": next((j.get("started_at") for j in js if j.get("started_at")), None),
                      "finished": js[-1].get("finished_at") if js else None, "attempts": st.get("attempts", 0),
                      "collected_pairs": (run["planned"] - run["remaining"]) if run else 0,
                      "remaining_pairs": run["remaining"] if run else 0, "deferred": run["deferred"] if run else 0}
    given = []
    for k, v in att["pairs"].items():
        if v.get("given_up"):
            c, d = k.split("|")
            given.append({"code": c, "name": names.get(c), "date": d, "attempts": len(v["nights"]), "days_left": left.get(d)})
    return {"verdict": w["verdict"], "reason": w["reason"], "window_days": w["window_days"],
            "universe": "날짜별 전일 거래대금 상위 35 합집합(초대형주 제외, 보충 2종목)", "min_days_left": w["min_days_left"],
            "dates": [{"date": r["date"], "status": r["status"], "collected_codes": r["collected_codes"], "expected_codes": r["expected_codes"],
                       "days_left": r["days_left"], "missing_count": len(r["missing"]), "missing_sample": r["missing"][:20]} for r in w["dates"]],
            "auto": {"schedule": "tick_nightly", "enabled": scheduler.schedule_enabled("tick_nightly"),
                     "next_run": scheduler._next_slot(now, scheduler.schedule_time("tick_nightly", scheduler.NIGHT_START), cal),
                     "last_night": last_night, "given_up": given},
            "note": "키움 체결 조회창은 약 20거래일 — 밖으로 밀려난 날짜는 다시 받을 수 없음"}


@router.get("/tick-window")
def get_tick_window(request: Request):
    return _ok(_tick_window(_store(request), clock()))


class TickPair(BaseModel):
    code: str
    date: str


class TickRetry(BaseModel):
    pairs: list[TickPair] | Literal["all"]


@router.post("/tick-window/retry")
def post_tick_retry(body: TickRetry):
    pairs = "all" if body.pairs == "all" else [(p.code, p.date) for p in body.pairs]
    return _ok({"retried": collectors.retry(pairs)})


@router.get("/archive")
def get_archive():
    cov = status.archive_coverage()
    return _ok({"verdict": cov["verdict"], "reason": cov["reason"], "codes_cache": cov["codes_cache"], "codes_archive": cov["codes_archive"],
                "missing_vs_cache": cov["missing_vs_cache"], "missing_codes": cov["missing_codes"], **status.archive_spans()})


# ---------- 일정 · 알림 · 소피증권 ----------


class SchedulePatch(BaseModel):
    enabled: bool | None = None
    time: str | None = None

    @field_validator("time")
    @classmethod
    def _hhmm(cls, v):
        if v is not None and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("HH:MM 형식이어야 함")
        return v


@router.get("/schedules")
def get_schedules(request: Request):
    return _ok(scheduler.schedules_view(_store(request), clock()))


@router.patch("/schedules/{schedule_id}")
def patch_schedule(schedule_id: str, body: SchedulePatch, request: Request):
    d = next((x for x in catalog.load().schedules if x.id == schedule_id), None)
    if d is None:
        raise HubError(404, "NOT_FOUND", f"없는 일정: {schedule_id}")
    if d.owner != "hub":
        raise HubError(409, "NOT_HUB_OWNED", "허브 소유가 아닌 일정은 관측만 됩니다(워치독·8765·소피증권이 관리)")
    if body.time is not None and schedule_id not in scheduler.DEFAULT_TIMES:
        raise HubError(400, "VALIDATION_ERROR", "이 일정은 시각을 바꿀 수 없음", {"fieldErrors": {"time": "시각 변경 불가"}})
    scheduler.set_schedule(schedule_id, body.enabled, body.time)
    _cache.clear()
    return _ok(scheduler.schedule_row(_store(request), schedule_id, clock()))


def _rule(rule_id: str) -> dict:
    a = next(x for x in catalog.load().alerts if x.id == rule_id)
    last = alerts.last_sent().get(rule_id) or {}
    return {"id": a.id, "title": a.title or a.id, "when": a.when, "enabled": alerts.enabled_rules().get(a.id, False),
            "default_enabled": a.default == "on", "last_sent": last.get("ts"), "last_message": last.get("message")}


@router.get("/alerts")
def get_alerts(request: Request):
    ov = _cached("overview", lambda: _overview(_store(request), clock()))
    return _ok({"rules": [_rule(a.id) for a in catalog.load().alerts], "active": ov["alerts_active"]})


class AlertPatch(BaseModel):
    enabled: bool


@router.patch("/alerts/{rule_id}")
def patch_alert(rule_id: str, body: AlertPatch):
    try:
        alerts.set_enabled(rule_id, body.enabled)
    except KeyError:
        raise HubError(404, "NOT_FOUND", f"없는 알림 규칙: {rule_id}") from None
    _cache.pop("overview", None)
    return _ok(_rule(rule_id))


@router.get("/sophie")
def get_sophie():
    return _ok(sophie.overview(clock()))


# ---------- 수집 작업 제출 ----------


class CollectWhen(BaseModel):
    when: Literal["now", "scheduled"] = "now"
    scheduled_at: str | None = Field(None, validate_default=True)
    confirm: bool = False

    @field_validator("scheduled_at")
    @classmethod
    def _sched(cls, v, info):
        if info.data.get("when") == "scheduled":
            if not v:
                raise ValueError("when=scheduled 는 scheduled_at 이 필요함")
            try:
                datetime.fromisoformat(v)
            except ValueError:
                raise ValueError("ISO 시각이어야 함") from None
        return v


def _codes_field(v, info, lo: int, hi: int, need: bool):
    for c in v or []:
        if not CODE_RE.match(c):
            raise ValueError(f"종목코드 형식 위반: {c} (6자리 영문 대문자·숫자)")
    if need and not (lo <= len(v or []) <= hi):
        raise ValueError(f"종목은 {lo}~{hi}개")
    return v


class CollectDaily(CollectWhen):
    mode: Literal["stale", "all", "codes"]
    codes: list[str] | None = Field(None, validate_default=True)

    @field_validator("codes")
    @classmethod
    def _codes(cls, v, info):
        return _codes_field(v, info, 1, 3000, info.data.get("mode") == "codes")


class CollectTicks(CollectWhen):
    mode: Literal["catch_up", "range"]
    start: str | None = None
    end: str | None = None
    universe: Literal["default", "codes"] = "default"
    codes: list[str] | None = None
    concurrency: int = Field(4, ge=1, le=6)

    @field_validator("end")
    @classmethod
    def _range(cls, v, info):
        if info.data.get("mode") == "range":
            try:
                a, b = date.fromisoformat(info.data.get("start") or ""), date.fromisoformat(v or "")
            except ValueError:
                raise ValueError("start·end 는 YYYY-MM-DD") from None
            if a > b:
                raise ValueError("start 가 end 보다 늦음")
        return v

    @field_validator("codes")
    @classmethod
    def _codes(cls, v, info):
        return _codes_field(v, info, 1, 3000, info.data.get("universe") == "codes")


class CollectMinuteAl(CollectWhen):
    mode: Literal["sophie_baseline", "all_cached", "codes", "deep_archive"]
    codes: list[str] | None = Field(None, validate_default=True)
    days: int | None = Field(None, validate_default=True)

    @field_validator("codes")
    @classmethod
    def _codes(cls, v, info):
        m = info.data.get("mode")
        return _codes_field(v, info, 1, 300 if m == "deep_archive" else 500, m in ("codes", "deep_archive"))

    @field_validator("days")
    @classmethod
    def _days(cls, v, info):
        if info.data.get("mode") == "deep_archive" and (v is None or not 20 <= v <= 250):
            raise ValueError("deep_archive 는 days 20~250")
        return v


class Empty(BaseModel):
    pass


def _submit(request: Request, kind: str, mode: str | None, codes: list[str], when: CollectWhen, payload: dict) -> JSONResponse:
    store, now = _store(request), clock()
    p = _policy(store, kind, mode, codes, now)
    if when.when == "scheduled":
        at = datetime.fromisoformat(when.scheduled_at)
        if at <= now:
            raise HubError(400, "VALIDATION_ERROR", "요청 형식이 올바르지 않음", {"fieldErrors": {"scheduled_at": "미래 시각이어야 함"}})
        if policy.window(at) in ("market", "sophie_live") and p["weight"] != "local":
            raise HubError(400, "VALIDATION_ERROR", "요청 형식이 올바르지 않음",
                           {"fieldErrors": {"scheduled_at": f"야간 구간({policy.sophie_hours().connect_to} 이후)이어야 함"}})
        sched = _iso(at)
    else:
        if p["blocked"]:
            b = p["blocked"]
            raise HubError(409, b["code"], b["message"], b["details"])
        if p["decision"] == "schedule_only":
            raise HubError(422, "SOPHIE_MARKET_HOURS", p["reason"], {"suggest_at": p["suggest_at"]})
        if p["decision"] == "needs_confirm" and not when.confirm:
            raise HubError(422, "SOPHIE_LIVE_CONFIRM", p["reason"], {"suggest_at": p["suggest_at"]})
        sched = None
    job = jobs.create_job(store, kind, payload, scheduled_at=sched, trigger="user")
    _cache.clear()                                        # 새 작업이 개요(활동)에 바로 보이게
    disp = getattr(request.app.state, "dispatcher", None)
    if disp is not None:
        disp.tick()
    cur = store.read(job["job_id"]) or job
    return _ok({"job_id": job["job_id"], "status": cur["status"], "scheduled_at": cur.get("scheduled_at")}, 202)


@router.post("/jobs/collect-daily", status_code=202)
def post_collect_daily(body: CollectDaily, request: Request):
    return _submit(request, "collect_daily", body.mode, body.codes or [], body, {"mode": body.mode, "codes": body.codes or []})


@router.post("/jobs/collect-ticks", status_code=202)
def post_collect_ticks(body: CollectTicks, request: Request):
    now = clock()
    if body.mode == "range":
        win = {r["date"]: r for r in status.tick_window(now, Calendar())["dates"]}
        if body.start not in win or body.end not in win:
            raise HubError(422, "OUT_OF_TICK_WINDOW", "체결 조회창(최근 20거래일) 밖의 날짜입니다", {"window_start": min(win)})
        payload = {"mode": "range", "start": body.start, "end": body.end, "universe": body.universe, "codes": body.codes or [],
                   "concurrency": body.concurrency}
        return _submit(request, "collect_ticks", "range", body.codes or [], body, payload)
    if collectors.plan_tick_catch_up(status.tick_window(now, Calendar())) is None:
        return JSONResponse({"data": {"nothing_to_do": True}}, status_code=200)
    return _submit(request, "collect_ticks", "catch_up", [], body, {"mode": "catch_up", "concurrency": body.concurrency})


@router.post("/jobs/collect-minute-al", status_code=202)
def post_collect_minute(body: CollectMinuteAl, request: Request):
    return _submit(request, "collect_minute_al", body.mode, body.codes or [], body,
                   {"mode": body.mode, "codes": body.codes or [], "days": body.days})


@router.post("/jobs/archive-minute-al", status_code=202)
def post_archive(request: Request):
    when = CollectWhen()
    return _submit(request, "archive_minute_al", None, [], when, {})
