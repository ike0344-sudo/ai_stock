"""알림 규칙 판정 9종 + 하루 1회 중복 방지 + 텔레그램 발송 (설계 §2.4.8, 테스트 H14).

`evaluate` 는 순수 함수다 — 사실(ctx)을 받아 위반한 규칙을 돌려준다. ctx 는 `build_context` 가 모은다.
같은 (규칙, 대상)은 하루 한 번만 보낸다(`state/datahub/alerts_sent.json`).
규칙별 켜기/끄기는 카탈로그 기본값 위에 `state/datahub/overrides.json` 의 `alerts` 가 덮는다.
"""
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

from . import catalog, collectors, locks, sophie, status
from .calendar import Calendar

DEAD_LOCK_MINUTES = 30
LOSS_DAYS_LEFT = 2


@dataclass
class Alert:
    id: str
    target: str            # 같은 규칙 안에서 무엇에 대한 알림인가(중복 방지 키)
    message: str


def _dir() -> Path:
    return catalog.root() / "state" / "datahub"


def enabled_rules() -> dict[str, bool]:
    on = {a.id: a.default == "on" for a in catalog.load().alerts}
    try:
        on.update({k: bool(v) for k, v in json.loads((_dir() / "overrides.json").read_text(encoding="utf-8")).get("alerts", {}).items()})
    except (OSError, ValueError):
        pass
    return on


def titles() -> dict[str, str]:
    return {a.id: a.title or a.id for a in catalog.load().alerts}


def _read(name: str, default):
    try:
        return json.loads((_dir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(name: str, data) -> None:
    _dir().mkdir(parents=True, exist_ok=True)
    tmp = _dir() / f"{name}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_dir() / name)


def track_active(found: list["Alert"], now: datetime) -> dict[str, str]:
    """지금 위반 중인 알림의 '처음 감지 시각'(`alerts_active.json`). 계속 위반이면 처음 시각을 유지하고, 풀리면 지운다."""
    prev = _read("alerts_active.json", {})
    cur = {f"{a.id}|{a.target}": prev.get(f"{a.id}|{a.target}") or now.isoformat(timespec="seconds") for a in found}
    if cur != prev:
        _write("alerts_active.json", cur)
    return cur


def last_sent() -> dict[str, dict]:
    """규칙별 마지막 발송({ts, message}) — 날짜가 바뀌어도 남는다."""
    return _read("alerts_last.json", {})


def set_enabled(rule_id: str, enabled: bool) -> None:
    """규칙 켜기/끄기(`state/datahub/overrides.json` 의 alerts)."""
    if rule_id not in titles():
        raise KeyError(rule_id)
    ov = _read("overrides.json", {})
    ov.setdefault("alerts", {})[rule_id] = bool(enabled)
    _write("overrides.json", ov)


def build_context(now: datetime | None = None, cal: Calendar | None = None, memo: dict | None = None) -> dict:
    """규칙이 볼 사실을 모은다(디스크·프로세스를 읽음). 무겁다 — 10분 주기 점검용."""
    now, cal = now or datetime.now(), cal or Calendar()
    lock_rows = []
    for name in catalog.load().locks:
        o = locks.owner(name)
        if o is not None:
            lock_rows.append({"resource": name, "dead": o.dead, "since": o.since, "cmdline": o.cmdline})
    attempts = collectors.load_attempts()
    try:
        catchup = json.loads((_dir() / "catchup.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        catchup = None
    return {"trading_day": cal.is_trading_day(now.date()),
            "daily": status.dataset_status("daily", now, cal, memo),
            "tick": status.memo_tick_window(memo, now, cal),
            "archive": status.archive_coverage(),
            "locks": lock_rows,
            "engine": sophie.engine(now, cal),
            "night_log": attempts.get("nights_log", []),
            "given_up": [{"pair": k, **v} for k, v in attempts["pairs"].items() if v.get("given_up")],
            "catchup": catchup,
            "unledgered": len(status.unledgered_writes(now - timedelta(minutes=10), now))}


def evaluate(ctx: dict, now: datetime, enabled: dict[str, bool] | None = None) -> list[Alert]:
    on = enabled if enabled is not None else {a.id: a.default == "on" for a in catalog.load().alerts}
    out: list[Alert] = []
    add = lambda id_, target, msg: on.get(id_, False) and out.append(Alert(id_, target, msg))
    t, trading = now.time(), ctx.get("trading_day", False)

    d = ctx.get("daily") or {}
    if trading and t >= dtime(7, 30) and d and ((d.get("reference_date") or "") < (d.get("expected_date") or "") or d.get("sophie_stale_count", 0) > 0):
        add("daily_stale_before_open", "daily",
            f"일봉 기준일 {d.get('reference_date')} < 기대일 {d.get('expected_date')}, 소피증권 유니버스 밀림 {d.get('sophie_stale_count', 0)}종목")

    for r in (ctx.get("tick") or {}).get("dates", []):
        if r["missing"] and r["status"] != "pending" and r["days_left"] <= LOSS_DAYS_LEFT:
            add("tick_window_loss", r["date"], f"체결 {r['date']} 이 {r['days_left']}거래일 안에 조회창 밖으로 — 미수집 {len(r['missing'])}종목(되살릴 수 없음)")

    n = (ctx.get("archive") or {}).get("missing_vs_cache", 0)
    if n:
        add("archive_behind", "minute_al_archive", f"통합 분봉 보관소에 빠진 캐시 {n}종목 — 보관 누락")

    for lk in ctx.get("locks", []):
        if lk["dead"] and now.timestamp() - lk["since"] >= DEAD_LOCK_MINUTES * 60:
            add("dead_lock_owner", lk["resource"], f"잠금 {lk['resource']} 소유자가 죽은 채 {DEAD_LOCK_MINUTES}분 이상 남아 있음")

    if trading and t >= dtime(8, 20) and (ctx.get("engine") or {}).get("stale_day"):
        add("sophie_stale_day", "engine", f"소피증권 엔진이 어제 상태로 떠 있음(시작 {ctx['engine'].get('started_at')})")

    log = ctx.get("night_log", [])
    if len(log) >= 2:
        a, b = log[-2], log[-1]
        consecutive = date.fromisoformat(b["night"]) - date.fromisoformat(a["night"]) == timedelta(days=1)
        if consecutive and all(x["remaining"] - x.get("deferred", 0) > 0 for x in (a, b)):
            add("tick_nightly_failed", b["night"], f"체결 야간 수집이 이틀 밤 연속 다 돌고도 {b['remaining'] - b.get('deferred', 0)}쌍이 남음")

    for g in ctx.get("given_up", []):
        if g.get("given_up_at", "") >= (now.date() - timedelta(days=1)).isoformat():
            add("tick_given_up", g["pair"], f"체결 {g['pair']} 3일 밤 실패 — 수동 확인 필요 목록으로 이동")

    c = ctx.get("catchup")
    if c and c.get("deadline_passed") and c.get("remaining", 0) > 0:
        add("daily_catchup_incomplete", "daily", f"아침 일봉 따라잡기가 못 끝남 — 남은 {c['remaining']}종목(소피증권 영향 {c.get('sophie_remaining', 0)})")

    if ctx.get("unledgered", 0) > 0:
        add("unledgered_write", "ledger", f"장부 없는 쓰기 {ctx['unledgered']}건 감지")
    return out


def _sent_path() -> Path:
    return _dir() / "alerts_sent.json"


def _load_sent(today: str) -> dict:
    try:
        s = json.loads(_sent_path().read_text(encoding="utf-8"))
        if s.get("date") == today:
            return s
    except (OSError, ValueError):
        pass
    return {"date": today, "keys": []}


def telegram_sender(message: str) -> bool:
    from backtesting.notifier import WARNING, send_telegram
    return send_telegram(f"[데이터 허브] {message}", os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                         os.environ.get("TELEGRAM_CHAT_ID", ""), level=WARNING)


def dispatch(alerts: list[Alert], now: datetime | None = None, send=telegram_sender) -> list[Alert]:
    """아직 오늘 안 보낸 알림만 보낸다. 발송이 실패하면 '보냄'으로 기록하지 않아 다음 점검이 다시 시도한다."""
    now = now or datetime.now()
    sent = _load_sent(now.date().isoformat())
    fresh = []
    for a in alerts:
        key = f"{a.id}|{a.target}"
        if key in sent["keys"]:
            continue
        if send(a.message):
            sent["keys"].append(key)
            fresh.append(a)
            last = last_sent()
            last[a.id] = {"ts": now.isoformat(timespec="seconds"), "message": a.message}
            _write("alerts_last.json", last)
    _dir().mkdir(parents=True, exist_ok=True)
    tmp = _sent_path().with_name(f"alerts_sent.json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_sent_path())
    return fresh


def check_and_send(now: datetime | None = None, send=telegram_sender) -> list[Alert]:
    now = now or datetime.now()
    return dispatch(evaluate(build_context(now), now, enabled_rules()), now, send)
