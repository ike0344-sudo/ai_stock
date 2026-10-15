"""쓰기 장부 — 공유 데이터에 쓴 모든 작업의 시작·진행·끝 (설계 §2.4.5).

`state/datahub/ledger-YYYY-MM.jsonl`, 추가만. 한 줄 추가는 작은 잠금 안에서 한다.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from backtesting.risk_manager import risk_state_lock

from . import catalog
from .locks import pid_alive_since

LEDGER_LOCK = "state/locks/datahub_ledger"


def _dir() -> Path:
    return catalog.state_base() / "state" / "datahub"


def file_for(when: datetime) -> Path:
    return _dir() / f"ledger-{when:%Y-%m}.jsonl"


def append(event: dict) -> None:
    now = datetime.now()
    line = json.dumps({"ts": now.isoformat(timespec="seconds"), **event}, ensure_ascii=False) + "\n"
    p = file_for(now)
    p.parent.mkdir(parents=True, exist_ok=True)
    with risk_state_lock(str(catalog.state_base() / LEDGER_LOCK)):
        with p.open("a", encoding="utf-8", newline="") as fh:
            fh.write(line)


def read(days: int = 7) -> list[dict]:
    """최근 days 일의 이벤트(월 파일 두 개까지 훑는다)."""
    since = datetime.now() - timedelta(days=days)
    cut = since.isoformat(timespec="seconds")
    events = []
    for f in {file_for(since), file_for(datetime.now())}:
        events += [ev for ev in _parsed(f) if ev.get("ts", "") >= cut]
    return sorted(events, key=lambda e: e["ts"])


_PARSED: dict[str, tuple[tuple[int, int], list[dict]]] = {}


def _parsed(f: Path) -> list[dict]:
    """월 파일 한 개의 이벤트 — 파일(크기·수정시각)이 그대로면 다시 파싱하지 않는다. 개요 한 번에 read 가 19번 불려
    7천 줄 JSON 을 매번 다시 읽느라 2.5초가 들었다(10-14 측정). 돌려준 dict 는 공유되니 고치지 말 것."""
    try:
        st = f.stat()
    except OSError:
        return []
    key = (st.st_size, st.st_mtime_ns)
    hit = _PARSED.get(str(f))
    if hit and hit[0] == key:
        return hit[1]
    out = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue                                 # 쓰다 만 줄 — 건너뛴다
    _PARSED[str(f)] = (key, out)
    return out


def runs(events: list[dict]) -> list[dict]:
    """이벤트를 run 단위로 묶고 상태를 붙인다: 실행 중 / 완료 / 실패 / 중단됨(끝 기록 없이 pid 죽음)."""
    by_run: dict[str, dict] = {}
    for ev in events:
        r = by_run.setdefault(ev["run"], {"run": ev["run"], "start": None, "last": None, "end": None})
        if ev["event"] == "start":
            r["start"] = ev
        elif ev["event"] == "end":
            r["end"] = ev
        if ev["event"] in ("start", "progress"):
            r["last"] = ev
    out = []
    for r in by_run.values():
        s = r["start"] or r["last"] or r["end"]
        if r["end"] is not None:
            state = "완료" if r["end"].get("ok") else "실패"
        else:
            started = datetime.fromisoformat(s["ts"]).timestamp()
            state = "실행 중" if s.get("pid") and pid_alive_since(s["pid"], started) else "중단됨"
        prog = r["end"] or r["last"] or {}
        ended = r["end"]["ts"] if r["end"] else None
        dur = (datetime.fromisoformat(ended) - datetime.fromisoformat(s["ts"])).total_seconds() if ended else None
        out.append({"run": r["run"], "ts": s["ts"], "ended": ended, "duration_sec": dur, "writer": s.get("writer"), "lock": s.get("lock"),
                    "trigger": s.get("trigger"), "job_id": s.get("job_id"), "cmd": s.get("cmd"), "detail": s.get("detail"),
                    "source": source_label(s.get("cmd")), "state": state, "done": prog.get("done"),
                    "total": prog.get("total"), "error": (r["end"] or {}).get("error")})
    return sorted(out, key=lambda x: x["ts"])


def source_label(cmd: str | None) -> str:
    """명령줄 -> 사람 말(§2.4.5)."""
    c = (cmd or "").replace("\\", "/")
    for needle, label in (("backtesting.cli dashboard", "8765"), ("daily_report_job", "야간 갱신"),
                          ("run_minute_refresh", "소피증권"), ("fetch_minute", "소피증권"),
                          ("jobrunner.worker", "허브")):
        if needle in c:
            return label
    return "수동"
