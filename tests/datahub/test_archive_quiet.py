"""H7·H8 통합 분봉 보관소 · H9 wait-quiet. 설계 §8.2."""
import importlib
import json
import sys
import threading
import time

import pandas as pd
import pytest

from datahub import catalog, ledger, locks, minute_al_archive as arch

from .conftest import REPO, run_py


def _bars(start: str, n: int, close0: int = 100) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="min", name="date")
    return pd.DataFrame({"open": close0, "high": close0 + 1, "low": close0 - 1, "close": close0,
                         "volume": 10}, index=idx)


# ---------- H7 ----------


def test_h7_archive_rows_never_shrink_and_later_wins(hub_root):
    full = _bars("2026-08-03 09:00", 300)                  # 예전 이력
    arch.merge("005930", full)
    truncated = full.iloc[-100:]                           # fetch_minute 가 20거래일로 잘라 교체한 뒤의 캐시
    r = arch.merge("005930", truncated)
    assert r["after"] == r["before"] == 300                # 잘린 캐시를 병합해도 행이 안 줄어든다
    changed = truncated.iloc[:2].copy()
    changed["close"] = 999                                 # 같은 분을 나중에 정정
    arch.merge("005930", changed)
    got = arch.read("005930")
    assert len(got) == 300 and got.loc[changed.index[0], "close"] == 999
    assert got.index.dtype == "datetime64[ns]" and got.index.name == "date"   # 날짜 인덱스 보존
    assert got.loc[full.index[0], "close"] == 100          # 안 건드린 옛 행은 그대로
    assert not list((hub_root / "data/stocks/minute_al_archive").glob("*.tmp"))


def test_h7_read_range_and_missing(hub_root):
    assert arch.read("999999").empty
    arch.merge("005930", _bars("2026-08-03 09:00", 10), _bars("2026-08-04 09:00", 10))
    assert len(arch.read("005930", "2026-08-04", "2026-08-04")) == 10


def test_archive_all_skips_up_to_date(hub_root):
    cdir = catalog.path("minute_al", code="x").parent
    cdir.mkdir(parents=True)
    _bars("2026-08-03 09:00", 5).to_csv(cdir / "005930.csv")
    _bars("2026-08-03 09:00", 7, 200).to_csv(cdir / "000660.csv")
    s = arch.archive_all()
    assert (s["merged"], s["skipped"], s["failed"]) == (2, 0, [])
    assert (s["rows_before"], s["rows_after"]) == (0, 12)
    s2 = arch.archive_all()                                # 이미 병합됨 -> 건너뜀
    assert (s2["merged"], s2["skipped"]) == (0, 2)


# ---------- H8 ----------


class _FakeClient:
    def __init__(self, records):
        self.records = records

    def get_minute_chart_pages(self, code, tic_scope="1", max_pages=1):
        return [{"stk_min_pole_chart_qry": self.records}]


def _records(df: pd.DataFrame):
    return [{"cntr_tm": ts.strftime("%Y%m%d%H%M%S"), "open_pric": str(r.open), "high_pric": str(r.high),
             "low_pric": str(r.low), "cur_prc": str(r.close), "volume": 0, "trde_qty": str(r.volume)}
            for ts, r in df.iterrows()]


@pytest.fixture
def fm(hub_root, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "kospi-theme-engine"))
    monkeypatch.syspath_prepend(str(REPO))
    mod = importlib.import_module("scripts.fetch_minute")
    cdir = catalog.path("minute_al", code="x").parent
    cdir.mkdir(parents=True)
    monkeypatch.setattr(mod, "MINUTE_AL_DIR", cdir)
    monkeypatch.setattr(mod, "META_FILE", cdir / "_meta.txt")
    monkeypatch.setattr(mod, "API_DELAY_SEC", 0)
    return mod


def test_h8_fetch_minute_replaces_cache_and_archives_union(fm, hub_root, monkeypatch):
    old = _bars("2026-08-03 09:00", 50)
    old.to_csv(catalog.path("minute_al", code="005930"))
    new = _bars("2026-08-03 09:40", 30, 300)               # 09:40~ 은 old 와 겹치고 값이 다르다
    monkeypatch.setattr(fm, "_client", lambda: _FakeClient(_records(new)))
    monkeypatch.setattr(sys, "argv", ["fetch_minute", "--codes", "005930", "--days", "1"])
    fm.main()
    cache = pd.read_csv(catalog.path("minute_al", code="005930"), index_col="date", parse_dates=True)
    assert len(cache) == 30                                # 캐시는 새 봉으로 교체
    got = arch.read("005930")
    assert len(got) == 70                                  # 보관소 = 합집합(50 + 30 - 겹침 10)
    assert got.loc["2026-08-03 09:45", "close"] == 300     # 같은 분은 새 값
    assert got.loc["2026-08-03 09:10", "close"] == 100
    ev = ledger.read(1)
    assert [e["event"] for e in ev][0] == "start" and ev[-1]["event"] == "end" and ev[-1]["ok"] is True
    assert ev[0]["writer"] == "fetch_minute" and ev[0]["lock"] == "minute_al"


def test_h8_archive_only_leaves_cache_alone(fm, hub_root, monkeypatch):
    old = _bars("2026-08-03 09:00", 20)
    old.to_csv(catalog.path("minute_al", code="005930"))
    before = catalog.path("minute_al", code="005930").read_bytes()
    monkeypatch.setattr(fm, "_client", lambda: _FakeClient(_records(_bars("2026-07-01 09:00", 15))))
    monkeypatch.setattr(sys, "argv", ["fetch_minute", "--codes", "005930", "--archive-only"])
    fm.main()
    assert catalog.path("minute_al", code="005930").read_bytes() == before
    assert not (fm.MINUTE_AL_DIR / "_meta.txt").exists()
    assert len(arch.read("005930")) == 35                  # 옛 15 + 캐시 20


def test_h8_merge_failure_keeps_old_cache(fm, hub_root, monkeypatch):
    """보관소 병합이 실패하면 캐시를 교체하지 않는다 — 교체하면 이력이 사라진다."""
    _bars("2026-08-03 09:00", 20).to_csv(catalog.path("minute_al", code="005930"))
    before = catalog.path("minute_al", code="005930").read_bytes()

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(fm.minute_al_archive, "merge", boom)
    monkeypatch.setattr(fm, "_client", lambda: _FakeClient(_records(_bars("2026-08-05 09:00", 5))))
    monkeypatch.setattr(sys, "argv", ["fetch_minute", "--codes", "005930"])
    fm.main()
    assert catalog.path("minute_al", code="005930").read_bytes() == before


# ---------- H9 ----------


def _quiet(root, *args):
    return run_py(["-m", "datahub", "wait-quiet", *args], root)


def test_h9_quiet_returns_zero_fast_and_stderr_empty(hub_root):
    t0 = time.time()
    r = _quiet(hub_root, "--max-minutes", "1")
    assert r.returncode == 0 and r.stderr == b"" and time.time() - t0 < 20
    assert "조용함".encode() in r.stdout


def test_h9_live_owner_times_out_with_3(hub_root):
    import subprocess
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        time.sleep(0.3)
        lf = locks.lock_file("daily_minute")               # 프로세스가 뜬 뒤에 잠금 파일을 만든다(create_time <= mtime)
        lf.parent.mkdir(parents=True, exist_ok=True)
        lf.write_bytes(f"{p.pid}:1:x".encode())
        r = _quiet(hub_root, "--max-minutes", "0.03")
        assert r.returncode == 3 and r.stderr == b"" and b"daily_minute" in r.stdout
    finally:
        p.kill()


@pytest.mark.parametrize("bom", [False, True])
def test_h9_running_marker_blocks(hub_root, bom):
    d = hub_root / "state" / "minute_refresh"
    d.mkdir(parents=True)
    enc = "utf-8-sig" if bom else "utf-8"
    (d / "last_run_started.json").write_text(json.dumps({"started_at": time.time() - 60}), encoding=enc)
    r = _quiet(hub_root, "--max-minutes", "0.03")
    assert r.returncode == 3 and r.stderr == b"" and "minute_refresh".encode() in r.stdout
    (d / "last_run_finished.json").write_text(json.dumps({"finished_at": time.time()}), encoding=enc)
    r = _quiet(hub_root, "--max-minutes", "1")
    assert r.returncode == 0 and r.stderr == b""


def test_h9_stale_marker_over_6h_is_ignored(hub_root):
    d = hub_root / "state" / "daily_report"
    d.mkdir(parents=True)
    (d / "last_run_started.json").write_text(json.dumps({"started_at": time.time() - 7 * 3600}))
    assert not locks.marker_running("daily_report")


def test_h9_waits_then_returns_quiet(hub_root):
    d = hub_root / "state" / "daily_report"
    d.mkdir(parents=True)
    (d / "last_run_started.json").write_text(json.dumps({"started_at": time.time()}))
    threading.Timer(0.5, lambda: (d / "last_run_finished.json").write_text(
        json.dumps({"finished_at": time.time() + 1}))).start()
    out = []
    assert locks.wait_quiet(max_minutes=1, poll=0.1, out=out.append) == 0
    assert any("대기 중" in m for m in out) and "조용함" in out[-1]


def test_deadline_from_rolls_to_tomorrow():
    from datetime import datetime
    assert locks.deadline_from("08:00", datetime(2026, 9, 26, 0, 5)) == datetime(2026, 9, 26, 8, 0)
    assert locks.deadline_from("08:10", datetime(2026, 9, 25, 20, 15)) == datetime(2026, 9, 26, 8, 10)
