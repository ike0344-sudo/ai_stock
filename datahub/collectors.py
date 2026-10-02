"""수집 명령 조립 + 빠진 체결 쌍 계획 (설계 §2.4.10 표·§2.4.11·§4.2, 테스트 H15·H18).

명령을 **만들기만** 한다 — 실행은 작업 실행기(jobrunner, module-2 뒤쪽)가 한다. 그래서 서버 없이 테스트된다.
허브가 띄우는 수집은 환경변수 `DATAHUB_TRIGGER=hub`·`DATAHUB_JOB_ID` 를 달아 장부가 출처를 안다.
"""
import threading
import json
import os
import sys
import zlib
from dataclasses import dataclass, field
from datetime import date

from . import catalog

NIGHTS_TO_GIVE_UP = 3
MAX_MINUTE_CODES = 500
_PS = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]


@dataclass
class Command:
    argv: list[str]
    cwd: str
    env: dict[str, str] = field(default_factory=dict)
    label: str = ""

    def with_job(self, job_id: str) -> "Command":
        return Command(self.argv, self.cwd, {**self.env, "DATAHUB_TRIGGER": "hub", "DATAHUB_JOB_ID": job_id}, self.label)


def _root() -> str:
    return str(catalog.root())


def _theme_root() -> str:
    return str(catalog.root() / "kospi-theme-engine")


def _codes_arg(codes: list[str] | None, codes_file: str | None) -> list[str]:
    if codes_file:
        return ["--codes", f"@{codes_file}"]
    return [f"--codes={','.join(codes)}"] if codes else []


def collect_daily(mode: str, codes: list[str] | None = None, codes_file: str | None = None,
                  stop_at: str | None = None) -> Command:
    """일봉: stale(밀린 종목) / all(겹쳐받기) / codes(지정, 신규 종목은 5년치)."""
    if mode not in ("stale", "all", "codes"):
        raise ValueError(f"일봉 수집 모드: {mode}")
    argv = [sys.executable, "backfill_universe.py"]
    if mode == "all":
        argv.append("--all")
    elif mode == "codes":
        if not (codes or codes_file):
            raise ValueError("codes 모드는 종목이 필요하다")
        argv += _codes_arg(codes, codes_file)
    if stop_at:
        argv += ["--stop-at", stop_at]
    return Command(argv, _root(), label=f"일봉 {mode}")


def tick_progress_path(start: str, end: str, codes: list[str] | None = None) -> str:
    """수집기(`tick_collect_804_828_al.py`)가 이 인자로 돌 때 쓰는 진행 파일 — 압축기의 --main-progress 용.
    수집기의 태그 규칙(기간 + `--codes` 해시)과 같아야 한다."""
    tag = f"{start.replace('-', '')}_{end.replace('-', '')}"
    if codes:
        tag += f"_c{zlib.crc32(','.join(sorted(codes)).encode()):08x}"
    return f"state/tick_collection/progress_al_{tag}.json"


def collect_ticks(start: str, end: str, codes_file: str, concurrency: int = 4, stop_at: str | None = None,
                  batch_key: bool = True) -> Command:
    """체결: 기간 [start, end] 를 종목 목록(@파일)만큼. 설계 §4.2 명령 그대로."""
    if not 1 <= concurrency <= 6:
        raise ValueError("concurrency 는 1~6")
    argv = [sys.executable, "tick_collect_804_828_al.py", "--start", start, "--end", end,
            "--concurrency", str(concurrency), "--codes", f"@{codes_file}"]
    if batch_key:
        argv.append("--batch-key")
    if stop_at:
        argv += ["--stop-at", stop_at]
    return Command(argv, _root(), label=f"체결 {start}~{end}")


def tick_compact(main_progress: str | None = None) -> Command:
    argv = [sys.executable, "tick_compact_daemon.py", "--once", "--tick-dir", "data/stocks/tick_al"]
    if main_progress:
        argv += ["--main-progress", main_progress]
    return Command(argv, _root(), label="체결 압축")


def collect_minute_al(mode: str, codes: list[str] | None = None, days: int | None = None) -> Command:
    """통합 분봉 4모드(§2.4.10 표).

    sophie_baseline: 소피증권 기준선 갱신 ps1(-Now) · all_cached: 캐시 전체 · codes: 1~500 지정 ·
    deep_archive: codes + days 20~250, 보관소에만 병합(캐시 안 씀)."""
    if mode == "sophie_baseline":
        return Command([*_PS, "-File", str(catalog.root() / "kospi-theme-engine" / "run_minute_refresh.ps1"), "-Now"],
                       _theme_root(), label="통합 분봉 — 소피증권 기준선")
    py = [sys.executable, "-X", "utf8", "-u", "-m", "scripts.fetch_minute"]
    if mode == "all_cached":
        cached = sorted(p.stem for p in (catalog.root() / catalog.dataset("minute_al").path.rsplit("/", 1)[0]).glob("*.csv"))
        return Command([*py, "--codes", ",".join(cached)], _theme_root(), label="통합 분봉 — 캐시 전체")
    if not codes or len(codes) > MAX_MINUTE_CODES:
        raise ValueError(f"종목은 1~{MAX_MINUTE_CODES}개")
    if mode == "codes":
        return Command([*py, "--codes", ",".join(codes)], _theme_root(), label="통합 분봉 — 종목 지정")
    if mode == "deep_archive":
        if days is None or not 20 <= days <= 250:
            raise ValueError("deep_archive 는 days 20~250")
        return Command([*py, "--codes", ",".join(codes), "--days", str(days), "--archive-only"],
                       _theme_root(), label=f"통합 분봉 — 깊게 {days}일(보관소만)")
    raise ValueError(f"통합 분봉 모드: {mode}")


def collect_program_al() -> Command:
    """종목별 프로그램 매매(ka90008) — 그날 거래대금 상위 50. 당일분만 받을 수 있다."""
    return Command([sys.executable, "scripts/collect_program_al.py"], _root(), label="프로그램 매매 수집")


def collect_infostock_news(session: str = "") -> Command:
    """인포스탁 특징테마 뉴스(매일경제 톡속보 최신 글). session: am | pm | "" (오늘 것이면 아무거나)."""
    argv = [sys.executable, "scripts/collect_infostock_news.py"] + (["--session", session] if session else [])
    return Command(argv, _root(), label=f"인포스탁 뉴스 수집({session or '최신'})")


def archive_minute_al(codes: list[str] | None = None) -> Command:
    argv = [sys.executable, "-X", "utf8", "-m", "datahub", "archive-minute-al"] + (["--codes", *codes] if codes else ["--all"])
    return Command(argv, _root(), label="보관소 병합")


# ---------- 빠진 체결 쌍 계획 (§2.4.11 단계 2~3) ----------


def _attempts_path():
    return catalog.state_base() / "state" / "datahub" / "tick_attempts.json"


def load_attempts() -> dict:
    """{'pairs': {'CODE|DATE': {'nights': [...], 'given_up': bool}}, 'nights_log': [...]}"""
    try:
        return json.loads(_attempts_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"pairs": {}, "nights_log": []}


def _save(state: dict) -> None:
    p = _attempts_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def given_up_pairs(state: dict | None = None) -> set[tuple[str, str]]:
    state = state or load_attempts()
    return {tuple(k.split("|")) for k, v in state["pairs"].items() if v.get("given_up")}


@dataclass
class TickPlan:
    start: str
    end: str
    codes: list[str]                     # 조회창에서 먼저 사라질 날짜가 걸린 종목부터
    pairs: list[tuple[str, str]]


def plan_tick_catch_up(window: dict, state: dict | None = None) -> TickPlan | None:
    """`status.tick_window()` 결과에서 빠진 쌍을 골라 한 번의 실행 범위·종목 순서로.
    포기 목록은 뺀다. 종목 순서 = 그 종목의 가장 급한(조회창에서 먼저 사라질) 날짜 순. 빠진 게 없으면 None."""
    skip = given_up_pairs(state)
    left = {r["date"]: r["days_left"] for r in window["dates"]}
    pairs = [(c, d) for c, d in window["missing_pairs"] if (c, d) not in skip]
    if not pairs:
        return None
    urgency: dict[str, int] = {}
    for c, d in pairs:
        urgency[c] = min(urgency.get(c, 99), left[d])
    codes = sorted(urgency, key=lambda c: (urgency[c], c))
    return TickPlan(min(d for _, d in pairs), max(d for _, d in pairs), codes, sorted(pairs, key=lambda p: (p[1], p[0])))


def record_night(still_missing: list[tuple[str, str]], night: date,
                 deferred: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """하룻밤 회차 뒤, 그래도 빠진 쌍에 그날 밤을 기록한다. 같은 쌍이 **3일 밤** 빠지면 포기 목록으로 옮기고
    새로 포기된 쌍을 돌려준다(알림 `tick_given_up` 용). 이제 채워진 쌍은 기록에서 지운다.
    deferred: 시간 제한(--stop-at)으로 **시작도 못 한** 쌍 — 실패가 아니라서 밤 수에 안 센다(다음 회차가 이어받는다)."""
    deferred_set = {tuple(p) for p in (deferred or [])}
    state = load_attempts()
    keys = {f"{c}|{d}" for c, d in still_missing}
    state["pairs"] = {k: v for k, v in state["pairs"].items() if k in keys or v.get("given_up")}
    newly = []
    for c, d in still_missing:
        if (c, d) in deferred_set:
            continue
        e = state["pairs"].setdefault(f"{c}|{d}", {"nights": [], "given_up": False})
        if night.isoformat() not in e["nights"]:
            e["nights"].append(night.isoformat())
        if not e["given_up"] and len(e["nights"]) >= NIGHTS_TO_GIVE_UP:
            e["given_up"] = True
            e["given_up_at"] = night.isoformat()
            newly.append((c, d))
    log = [x for x in state["nights_log"] if x["night"] != night.isoformat()]
    log.append({"night": night.isoformat(), "remaining": len(still_missing), "deferred": len(deferred_set)})
    state["nights_log"] = sorted(log, key=lambda x: x["night"])[-30:]
    _save(state)
    return newly


def retry(pairs: list[tuple[str, str]] | str) -> int:
    """포기 목록에서 빼고 시도 기록을 0 으로(`POST /api/data/tick-window/retry`). 되돌린 쌍 수."""
    state = load_attempts()
    n = 0
    for k in list(state["pairs"]):
        c, d = k.split("|")
        if state["pairs"][k].get("given_up") and (pairs == "all" or (c, d) in {tuple(p) for p in pairs}):
            del state["pairs"][k]
            n += 1
    _save(state)
    return n


def plan_daily_catch_up(now, cal=None) -> list[str]:
    """일봉 아침 따라잡기 대상(§2.4.11 단계 2) — **거래일 달력** 기준으로 마감 확정일(`settled_day`)보다 오래된 종목.
    거래 중단 종목은 뺀다. 소피증권 유니버스 종목이 앞에 온다(시간 제한에 걸려도 화면에 영향이 큰 것부터)."""
    from . import status
    from .calendar import Calendar
    target = (cal or Calendar()).settled_day(now).isoformat()
    dead, sophie = set(status.inactive_codes()), status.universe_codes()
    late = [c for c, d in sorted(status.latest_dates("daily").items()) if d < target and c not in dead]
    return [c for c in late if c in sophie] + [c for c in late if c not in sophie]
