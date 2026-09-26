"""tests/conftest.py 의 격리·가드 자체를 조인다 — 이게 깨지면 테스트가 실제 허브 장부·잠금을 다시 건드린다."""
import json
import os
from pathlib import Path

from datahub import catalog, gate, ledger
from tests.conftest import REAL_LEDGER_DIR, REAL_ROOT, polluting_lines


def test_without_datahub_root_state_goes_to_a_temp_dir_not_the_real_repo():
    assert not os.environ.get("DATAHUB_ROOT")  # 이 테스트는 hub_root 를 안 쓴다 = 실데이터를 읽는 테스트와 같은 조건
    base = catalog.state_base()
    assert base != REAL_ROOT and REAL_ROOT not in base.parents
    assert catalog.root() == REAL_ROOT  # 데이터 경로는 그대로(패리티 등이 실데이터를 읽는다)


def test_gate_write_under_default_root_never_touches_real_ledger_or_lock():
    before = {p.name: p.stat().st_size for p in REAL_LEDGER_DIR.glob("ledger-*.jsonl")}
    lock_file = Path(str(catalog.lock_base("daily_minute")) + ".lock")
    assert REAL_ROOT not in lock_file.parents  # 잠금도 임시 폴더
    with gate.write("daily_minute", writer="isolation-test"):
        pass
    assert ledger.read(1)  # 임시 장부에는 남았고
    assert {p.name: p.stat().st_size for p in REAL_LEDGER_DIR.glob("ledger-*.jsonl")} == before  # 실제 장부는 그대로


def test_polluting_lines_only_counts_lines_appended_by_tests(tmp_path):
    f = tmp_path / "ledger-2026-09.jsonl"
    old = json.dumps({"cmd": "python -m pytest tests", "pid": 1}) + "\n"  # 시작 전부터 있던 줄은 세지 않는다
    f.write_text(old, encoding="utf-8")
    before = {f.name: f.stat().st_size}
    new = [{"cmd": "python fetch.py", "pid": 5, "writer": "real"},                    # 실제 수집 — 정상
           {"cmd": "python -m pytest tests -q", "pid": 6, "writer": "update_top35"},  # 테스트가 남김
           {"cmd": "x", "pid": os.getpid(), "writer": "inproc"}]                      # 이 프로세스가 남김
    with f.open("a", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(e) + "\n" for e in new))
    bad = polluting_lines(before, tmp_path, os.getpid())
    assert len(bad) == 2 and any("update_top35" in b for b in bad) and any("inproc" in b for b in bad)
    assert polluting_lines({f.name: f.stat().st_size}, tmp_path, os.getpid()) == []  # 더 안 늘면 없음
