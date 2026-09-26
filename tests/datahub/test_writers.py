"""수집기 쪽 변경(--codes / --stop-at)이 API 없이 동작하는지. 수집기는 import 시 chdir 하므로 서브프로세스로 돌린다."""
from .conftest import run_py

_TICK = """
from datetime import datetime, timedelta
import tick_collect_804_828_al as t
assert t.parse_codes("B, A,,B") == ["B", "A"]
t.DEADLINE = datetime.now() - timedelta(seconds=1)
print(t.process_one("005930", None, [False]))          # 시각이 지났으면 네트워크에 닿기 전에 deferred
"""


def test_tick_collector_defers_new_stock_after_stop_at(hub_root):
    r = run_py(["-c", _TICK], hub_root)
    assert r.returncode == 0, r.stderr.decode(errors="replace")
    assert b"('005930', 'deferred')" in r.stdout


def test_backfill_parse_codes(hub_root, tmp_path):
    f = tmp_path / "codes.txt"
    f.write_text("B # 주석\nA\n\n", encoding="utf-8")
    r = run_py(["-c", f"import backfill_universe as b; print(b.parse_codes(r'@{f}'), b.parse_codes('C,A'))"], hub_root)
    assert r.returncode == 0, r.stderr.decode(errors="replace")
    assert b"['B', 'A'] ['C', 'A']" in r.stdout


_BACKFILL = """
import json
from datetime import datetime
import backfill_universe as b
t = b.settled_target(datetime(2026, 9, 25, 17, 0))            # 추석 휴장일 오후
codes, daily_late = b.stale_codes(t, False)
allc, _ = b.stale_codes(t, True)
mon = [str(b.settled_target(datetime(2026, 9, 28, h))) for h in (8, 16)]
print(json.dumps({"t": str(t), "codes": codes, "daily_late": sorted(daily_late), "all": allc, "mon": mon}))
"""


def test_backfill_pool_and_target_use_trading_calendar(tmp_path):
    """휴장일 기준 · 일봉만 있는 종목이 풀에 들어감 · 거래 중단 종목 제외 · 이미 최신이면 대상 아님."""
    import json, os, subprocess, sys
    from .conftest import REPO
    def bar(kind, code, day):
        d = tmp_path / "data/stocks" / kind
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{code}.csv").write_text(f"date,open,high,low,close,volume\n{day} 09:00:00,1,1,1,1,1\n", encoding="utf-8")
    bar("daily", "FRESH1", "2026-09-23")            # 이미 최신 — 휴장일(09-25)에 다시 받으면 안 됨
    bar("daily", "DAILYONLY", "2026-08-31")         # 일봉만 있고 분봉·유니버스엔 없음 (08-31 정체 367종목 유형)
    bar("daily", "HALTED", "2026-08-31")            # 거래 중단
    bar("daily", "MINONLY", "2026-09-23"); bar("minute", "MINONLY", "2026-09-22")   # 분봉만 밀림
    (tmp_path / "data/index/daily").mkdir(parents=True)
    (tmp_path / "data/index/daily/001.csv").write_text("date,o\n2026-09-22,1\n2026-09-23,1\n", encoding="utf-8")
    ref = tmp_path / "kospi-theme-engine/dist/data/reference"
    ref.mkdir(parents=True)
    (ref / "universe.csv").write_text("code,name\nNEWUNI,x\nFRESH1,y\n", encoding="utf-8")    # NEWUNI: 일봉 파일이 아직 없음
    (tmp_path / "state/datahub").mkdir(parents=True)
    (tmp_path / "state/datahub/inactive_codes.json").write_text(json.dumps({"codes": {"HALTED": {"reason": "거래정지"}}}), encoding="utf-8")
    env = {**os.environ, "DATAHUB_ROOT": str(tmp_path), "PYTHONPATH": str(REPO), "PYTHONUTF8": "1"}
    r = subprocess.run([sys.executable, "-c", _BACKFILL], cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["t"] == "2026-09-23" and out["mon"] == ["2026-09-23", "2026-09-28"]         # 휴장일·월요일 아침엔 직전 거래일, 월요일 16시 이후엔 그날
    assert out["codes"] == ["DAILYONLY", "MINONLY", "NEWUNI"]                                # FRESH1 제외, HALTED 제외, 일봉만 있는 종목 포함
    assert out["daily_late"] == ["DAILYONLY", "NEWUNI"]
    assert out["all"] == ["DAILYONLY", "FRESH1", "MINONLY", "NEWUNI"]
