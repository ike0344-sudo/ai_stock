"""소피증권 연계 상태 — 읽기만 한다 (설계 §2.4.9, 테스트 H12).

허브는 소피증권 엔진을 끄거나 켜지 않는다(계약 7). 여기서는 설정·표식·로그·프로세스를 **조회**만 한다:
운영 시간(설정 출처 표기) · 엔진 가동 여부와 "어제 상태" · 분봉 기준선 갱신 표식/다음 예정 ·
기준 데이터 data↔dist 동기 · 자정 재기동·재빌드 기록.
"""
import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

import psutil

from . import catalog, locks, policy, status
from .calendar import Calendar

ENGINE_PROC = "ai_stock.exe"
HEALTHZ = "http://127.0.0.1:8770/healthz"
REFRESH_EVERY_DAYS = 13                    # 워치독 minuteRefreshEveryDays 와 같은 값
CONTRACT = [
    "소피증권 데이터(통합 분봉 캐시·기준 데이터)는 소피증권 스크립트로만 쓴다",
    "소피증권 스크립트의 쓰기도 허브 관문(datahub.write)을 쓴다",
    "운영 시간은 소피증권 설정(config.yaml)이 기준이다",
    "엔진은 데이터 쓰기 중에 (재)기동하지 않는다 — 재기동 스크립트가 wait-quiet 로 기다린다",
    "기준선 갱신은 다음 재기동부터 적용된다",
    "수집은 배치 앱키로 한다",
    "허브는 소피증권 엔진을 끄거나 켜지 않는다(상태 조회만)",
    "소피증권 엔진(EXE) 코드는 수정하지 않는다",
    "소피증권 스크립트 수정은 장중(09:00~15:30) 금지, ps1 은 BOM 유지",
    "wait-quiet 는 stdout 에만 쓴다(PowerShell 5.1 의 stderr 규칙)",
]


def _logs() -> Path:
    return catalog.root() / "kospi-theme-engine" / "logs"


def _http_get(url: str, timeout: float = 0.6) -> int | None:
    """상태코드. 인증이 걸려 있어 401 도 '떠 있음'이다. 연결이 안 되면 None."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def _engine_procs() -> list[tuple[int, float]]:
    out = []
    for p in psutil.process_iter(["name"]):                # 이름만 먼저 — 프로세스마다 create_time 을 열면 Windows 에서 2초 넘게 걸린다
        if (p.info["name"] or "").lower() == ENGINE_PROC:
            try:
                out.append((p.pid, p.create_time()))
            except psutil.Error:
                pass
    return out


def engine(now: datetime | None = None, cal: Calendar | None = None, http_get=None, procs=None) -> dict:
    """엔진 상태. 거래일인데 시작 시각이 오늘 00:00 이전이면 stale_day("어제 상태" — 전일 종가가 하루 밀려 있다).
    onefile exe 는 부트로더(부모)+앱(자식) 두 프로세스라 가장 오래된 시작 시각을 쓴다."""
    now, cal = now or datetime.now(), cal or Calendar()
    code = (http_get or _http_get)(HEALTHZ)
    ps = _engine_procs() if procs is None else procs
    started = datetime.fromtimestamp(min(t for _, t in ps)) if ps else None
    pid = min(ps, key=lambda x: x[1])[0] if ps else None
    up = code in (200, 401)
    stale = bool(up and started and cal.is_trading_day(now.date()) and started < datetime.combine(now.date(), datetime.min.time()))
    return {"up": up, "healthz": code, "pid": pid, "started_at": started.isoformat(timespec="seconds") if started else None,
            "stale_day": stale}


def _read_marker(name: str, key: str) -> float | None:
    try:
        return float(json.loads((catalog.root() / "state" / name / f"last_run_{key}.json").read_text(encoding="utf-8-sig"))[f"{key}_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def next_refresh_at(last_finished: datetime | None) -> datetime:
    """워치독 규칙: 마지막 완료 13일 뒤 이후의 첫 토요일 09:00 (기록이 없으면 다음 토요일)."""
    d = ((last_finished + timedelta(days=REFRESH_EVERY_DAYS)) if last_finished else datetime.now()).date()
    while d.weekday() != 5:
        d += timedelta(days=1)
    return datetime.combine(d, datetime.min.time()).replace(hour=9)


def next_refresh_due(last_finished: datetime | None) -> str:
    if last_finished is None:
        return "지금(기록 없음) — 다음 토요일 09:00 이후"
    return f"{next_refresh_at(last_finished).date().isoformat()} (토) 09:00 이후"


def minute_refresh(now: datetime | None = None) -> dict:
    s, f = _read_marker("minute_refresh", "started"), _read_marker("minute_refresh", "finished")
    iso = lambda t: datetime.fromtimestamp(t).isoformat(timespec="minutes") if t else None
    last_result = None
    log = _logs() / "minute_refresh.log"
    if log.is_file():
        lines = log.read_bytes()[-20000:].decode("utf-8", errors="ignore").splitlines()
        hit = [ln for ln in lines if "완료 · 실패" in ln]
        last_result = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+", "", hit[-1]).strip() if hit else None
    return {"running": locks.marker_running("minute_refresh"), "last_started": iso(s), "last_finished": iso(f),
            "last_result": last_result, "next_due": next_refresh_due(datetime.fromtimestamp(f) if f else None)}


def _last_log_time(path: Path, pattern: str) -> datetime | None:
    """로그 끝에서부터 pattern 이 든 마지막 줄의 시각(줄 머리 `YYYY-MM-DD HH:MM:SS`)."""
    if not path.is_file():
        return None
    tail = path.read_bytes()[-300_000:].decode("utf-8", errors="ignore").splitlines()
    for ln in reversed(tail):
        m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", ln)
        if m and re.search(pattern, ln):
            return datetime.fromisoformat(m.group(1))
    return None


def restarts(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    mid = _last_log_time(_logs() / "restart_after_midnight.log", "재기동 PID")
    reb = _last_log_time(_logs() / "rebuild.log", "교체 완료|엔진 재기동")
    return {"last_midnight": mid.isoformat(timespec="seconds") if mid else None,
            "days_since": (now.date() - mid.date()).days if mid else None,
            "last_rebuild": reb.isoformat(timespec="seconds") if reb else None}


def overview(now: datetime | None = None, cal: Calendar | None = None) -> dict:
    """`GET /api/data/sophie` 응답 본문(§4.2)."""
    now, cal = now or datetime.now(), cal or Calendar()
    h = policy.sophie_hours()
    stale_rows = status.stale("daily", sophie_only=True)
    base = status.verdict_dist_sync()
    return {"engine": engine(now, cal), "hours": asdict(h), "minute_refresh": minute_refresh(now),
            "baseline": {"data_updated": base["data_updated"], "dist_updated": base["dist_updated"],
                         "in_sync": base["in_sync"], "applies": "다음 엔진 재기동부터"},
            "universe_daily": {"n_codes": len(status.universe_codes()),
                               "stale_count": sum(1 for r in stale_rows if not r["inactive"]),
                               "stale_inactive_count": sum(1 for r in stale_rows if r["inactive"])},
            "restart": restarts(now), "contract": CONTRACT}
