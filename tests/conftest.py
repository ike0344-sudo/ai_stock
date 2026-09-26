"""테스트 전체 공통 — 실제 허브 장부·잠금을 테스트가 건드리지 못하게 막는다(2026-09-26 사고).

사고: `tests/backtesting` 일부가 `DATAHUB_ROOT` 없이 허브 관문(`datahub.write`)을 지나, 실제 `state/datahub/ledger-*.jsonl` 에
`cmd = python -m pytest ...` 줄을 남기고 실제 `daily_minute` 잠금을 잡았다(밤 수집과 겹치면 테스트가 무한 대기, 감사 기록 오염).
데이터 파일은 임시 폴더라 안전했지만 장부·잠금은 실제 것이었다.

1. **격리** — `DATAHUB_ROOT` 를 지정하지 않는 테스트는 장부·잠금·허브 상태(`state/...`)만 테스트마다 임시 폴더로 옮긴다
   (`DATAHUB_STATE_BASE`, `datahub.catalog.state_base`). 실데이터를 읽는 테스트(패리티 등)는 데이터 경로가 그대로다.
   `DATAHUB_ROOT` 를 지정하는 테스트(허브 테스트의 `hub_root`)는 그 임시 루트가 이미 격리라 영향 없음.
2. **재발 방지** — 세션이 끝났을 때 실제 장부에 **이 테스트 실행이 남긴 줄**(cmd 에 pytest 가 든 줄, 또는 이 프로세스 pid)이 늘었으면
   종료 코드를 실패로 만든다. 장부 전체 크기 비교가 아니라 "테스트가 남긴 줄"만 보는 이유: 실제 수집·밤 작업이 그 사이 정상적으로 쓸 수 있다.
"""
import json
import os
from pathlib import Path

import pytest

REAL_ROOT = Path(__file__).resolve().parents[1]
REAL_LEDGER_DIR = REAL_ROOT / "state" / "datahub"
_before: dict[str, int] = {}


@pytest.fixture(autouse=True)
def _isolate_hub_state(monkeypatch, tmp_path_factory):
    if not os.environ.get("DATAHUB_ROOT"):
        monkeypatch.setenv("DATAHUB_STATE_BASE", str(tmp_path_factory.mktemp("hubstate")))
    yield


def _sizes() -> dict[str, int]:
    return {p.name: p.stat().st_size for p in REAL_LEDGER_DIR.glob("ledger-*.jsonl")} if REAL_LEDGER_DIR.is_dir() else {}


def pytest_sessionstart(session):
    _before.clear()
    _before.update(_sizes())


def polluting_lines(before: dict[str, int], ledger_dir: Path, pid: int) -> list[str]:
    """before 이후 장부에 덧붙은 줄 중 테스트가 남긴 것(cmd 에 pytest, 또는 pid 가 이 프로세스)."""
    bad: list[str] = []
    if not ledger_dir.is_dir():
        return bad
    for p in sorted(ledger_dir.glob("ledger-*.jsonl")):
        start = before.get(p.name, 0)
        if p.stat().st_size <= start:
            continue
        with p.open("rb") as f:
            f.seek(start)
            chunk = f.read()
        for raw in chunk.splitlines():
            try:
                e = json.loads(raw.decode("utf-8-sig"))
            except ValueError:
                continue
            if "pytest" in str(e.get("cmd") or "") or e.get("pid") == pid:
                bad.append(f"{p.name}: {e.get('writer')} [{e.get('lock')}] {e.get('event')} cmd={str(e.get('cmd'))[:80]}")
    return bad


def pytest_sessionfinish(session, exitstatus):
    bad = polluting_lines(_before, REAL_LEDGER_DIR, os.getpid())
    if bad:
        print("\n[tests/conftest] 테스트가 실제 허브 장부에 줄을 남겼다 — 격리 누락:\n  " + "\n  ".join(bad[:10])
              + f"\n  (총 {len(bad)}줄) 관문(datahub.write)을 지나는 테스트는 DATAHUB_ROOT 임시 폴더를 쓰거나 `DATAHUB_STATE_BASE` 가 적용돼야 한다.")
        session.exitstatus = 1
