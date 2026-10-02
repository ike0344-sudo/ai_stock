"""H1 카탈로그 · H2~H4 관문·잠금 · H6 달력 · 구조(import 규칙). 설계 §8.2."""
import ast
import json
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path

import pytest

from datahub import catalog, gate, ledger, locks
from datahub.calendar import Calendar

from .conftest import REPO, run_py

# ---------- H1 ----------


def test_h1_real_catalog_loads():
    cat = catalog.load()                                   # 실제 catalog.yaml — pydantic 검증 통과
    assert len(cat.datasets) == 19  # 2026-09-28 rs_rating·rs_raw·rs_period·rs_shares(11->15) + sectors_stockeasy(->16) + program_al(09-30, ->17) + sophie_rank_tape(10-02, ->18) + infostock_news(10-03, ->19)
    assert set(cat.locks) == {"daily_minute", "minute_al", "tick_al", "rs_rating", "program_al", "infostock_news"}  # 2026-09-28 rs_rating · 10-03 infostock_news
    for d in cat.datasets:
        for p in [d.path, *d.also]:
            assert not Path(p).is_absolute() and ".." not in Path(p).parts
        fmt = {f: "x" for f in catalog.placeholders(d.path)}
        assert catalog.path(d.id, **fmt).is_relative_to(REPO), d.id
    assert catalog.path("daily", code="005930") == REPO / "data/stocks/daily/005930.csv"
    with pytest.raises(KeyError):
        catalog.path("daily")                              # {code} 빠짐
    # 집합 표기 `{a,b}` 를 포맷 인자로 쓰면 path() 가 KeyError 로 죽는다(2026-09-25 index 사고) — 실제 이름만 허용
    for d in cat.datasets:
        assert all(p.isidentifier() for p in catalog.placeholders(d.path)), d.id
    assert catalog.path("index", kind="daily", code="001") == REPO / "data/index/daily/001.csv"


def test_h1_rejects_dangling_lock():
    bad = catalog.load().model_dump()
    bad["datasets"][0]["lock"] = "없는잠금"
    with pytest.raises(ValueError, match="없는 잠금"):
        catalog.Catalog.model_validate(bad)


# ---------- H2 · H3 ----------

_HOLD = ("import sys,time\nfrom datahub import write\n"
         "with write('daily_minute', writer=sys.argv[1]):\n"
         "    print('in', time.time(), flush=True); time.sleep(1.0); print('out', time.time(), flush=True)\n")


def test_h2_two_processes_do_not_overlap(hub_root):
    env_cmd = [sys.executable, "-c", _HOLD]
    import os
    env = {**os.environ, "DATAHUB_ROOT": str(hub_root), "PYTHONUTF8": "1"}
    ps = [subprocess.Popen([*env_cmd, name], cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
          for name in ("a", "b")]
    spans = []
    for p in ps:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err.decode(errors="replace")
        t = {ln.split()[0]: float(ln.split()[1]) for ln in out.decode().splitlines() if ln.split()[0] in ("in", "out")}
        spans.append((t["in"], t["out"]))
    (a0, a1), (b0, b1) = sorted(spans)
    assert a1 <= b0 + 0.05, f"구간이 겹쳤다: {spans}"
    events = ledger.read(1)
    assert [e["event"] for e in events].count("start") == 2 and [e["event"] for e in events].count("end") == 2
    assert all(e["trigger"] == "external" for e in events)


def test_h3_exception_records_failure_and_releases(hub_root):
    with pytest.raises(ZeroDivisionError):
        with gate.write("daily_minute", writer="boom", detail={"x": 1}) as w:
            w.progress(1, 2)
            1 / 0
    end = [e for e in ledger.read(1) if e["event"] == "end"][0]
    assert end["ok"] is False and "ZeroDivisionError" in end["error"]
    assert not locks.lock_file("daily_minute").exists()
    with gate.write("daily_minute", writer="again"):        # 잠금이 풀렸으니 바로 잡힌다
        pass


def test_h3_env_trigger_and_job_id_recorded(hub_root, monkeypatch):
    monkeypatch.setenv("DATAHUB_TRIGGER", "hub")
    monkeypatch.setenv("DATAHUB_JOB_ID", "20260925-000000-abc123")
    with gate.write("tick_al", writer="t") as w:
        w.result(n=3)
    start, end = ledger.read(1)
    assert (start["trigger"], start["job_id"]) == ("hub", "20260925-000000-abc123")
    assert end["ok"] is True and end["result"] == {"n": 3}


def test_reentry_is_refused(hub_root):
    with gate.write("minute_al", writer="outer"):
        with pytest.raises(RuntimeError, match="재진입"):
            with gate.write("minute_al", writer="inner"):
                pass


def test_market_hours_warns_but_does_not_block(hub_root, monkeypatch, capsys):
    monkeypatch.setattr(gate, "in_sophie_market_hours", lambda now=None: True)
    with gate.write("daily_minute", writer="manual"):
        pass
    assert "정규장" in capsys.readouterr().out


def test_progress_is_throttled(hub_root, monkeypatch):
    monkeypatch.setattr(gate, "PROGRESS_MIN_INTERVAL", 3600)
    with gate.write("daily_minute", writer="p") as w:
        for i in range(1, 6):
            w.progress(i, 5)                               # 마지막(5/5)만 기록돼야 한다
    assert [e["event"] for e in ledger.read(1)] == ["start", "progress", "progress", "end"]     # 첫 진행(1/5)은 바로, 마지막(5/5)은 끝에서


# ---------- H4 ----------


def test_h4_dead_owner_is_reported_and_reclaimed(hub_root):
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    lf = locks.lock_file("daily_minute")
    lf.parent.mkdir(parents=True, exist_ok=True)
    lf.write_bytes(f"{p.pid}:1:deadbeef".encode())
    o = locks.owner("daily_minute")
    assert o is not None and o.dead is True and o.alive is False
    t0 = time.time()
    with gate.write("daily_minute", writer="next"):
        pass
    assert time.time() - t0 < 5                            # 즉시 회수(600초 안 기다림)


def test_owner_pid_reuse_is_dead(hub_root):
    """살아 있는 pid 여도 그 프로세스가 잠금 파일보다 나중에 생겼으면 다른 프로세스(PID 재사용)다."""
    lf = locks.lock_file("daily_minute")
    lf.parent.mkdir(parents=True, exist_ok=True)
    import os
    lf.write_bytes(f"{os.getpid()}:1:x".encode())
    import psutil
    old = psutil.Process().create_time() - 100
    os.utime(lf, (old, old))                               # 잠금이 이 프로세스 시작보다 오래됐다
    assert locks.owner("daily_minute").dead is True


# ---------- H6 ----------


def test_h6_holiday_and_index_dates():
    idx = {date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)}
    cal = Calendar(index_dates=idx, holidays={date(2026, 9, 24), date(2026, 9, 25)})
    assert cal.is_trading_day(date(2026, 9, 23))
    assert not cal.is_trading_day(date(2026, 9, 24))       # 추석 연휴 — 지수 아직 안 쌓였어도 휴장
    assert not cal.is_trading_day(date(2026, 9, 26))       # 토
    assert cal.is_trading_day(date(2026, 9, 28)) is True   # 휴장일 목록에 없는 평일
    assert cal.next_trading_day(date(2026, 9, 23)) == date(2026, 9, 28)
    assert cal.prev_trading_day(date(2026, 9, 28)) == date(2026, 9, 23)
    # 지나간 날은 지수가 기준: 평일인데 봉이 없으면 휴장(공휴일 목록에 없어도)
    cal2 = Calendar(index_dates={date(2026, 9, 21), date(2026, 9, 23)}, holidays=set())
    assert not cal2.is_trading_day(date(2026, 9, 22))
    assert cal2.trading_days(date(2026, 9, 21), date(2026, 9, 23)) == [date(2026, 9, 21), date(2026, 9, 23)]


def test_calendar_reads_real_index_file():
    cal = Calendar()
    assert cal.last_index_date is not None and cal.is_trading_day(cal.last_index_date)


# ---------- 구조: 허브 핵심 import 규칙 (§9.3) ----------

FORBIDDEN_ROOT = {"fastapi", "studio", "jobrunner", "kiwoom_client", "order_execution", "sell_order"}
ALLOWED_BACKTESTING = {"risk_manager", "notifier", "daily_cache"}
NOT_CORE = {"api.py", "jobs.py", "scheduler.py"}          # module-2 — 다른 규칙


def test_datahub_core_import_rules():
    files = [f for f in (REPO / "datahub").glob("*.py") if f.name not in NOT_CORE]
    assert files
    for f in files:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                    else [])
            for m in mods:
                root = m.split(".")[0]
                assert root not in FORBIDDEN_ROOT, f"{f.name}: 금지 import {m}"
                if root == "backtesting":
                    parts = m.split(".")
                    if len(parts) == 1 and isinstance(node, ast.ImportFrom):
                        names = {a.name for a in node.names}
                        assert names <= ALLOWED_BACKTESTING, f"{f.name}: {names}"
                    else:
                        assert len(parts) > 1 and parts[1] in ALLOWED_BACKTESTING, f"{f.name}: 금지 import {m}"
