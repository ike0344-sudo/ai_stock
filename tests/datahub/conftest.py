"""허브 테스트 공용 — DATAHUB_ROOT 를 임시 폴더로 바꿔 잠금·장부·표식·데이터가 실제 state/ 를 안 건드리게."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def hub_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAHUB_ROOT", str(tmp_path))
    monkeypatch.delenv("DATAHUB_TRIGGER", raising=False)
    monkeypatch.delenv("DATAHUB_JOB_ID", raising=False)
    return tmp_path


def run_py(code_or_args: list[str], root: Path, timeout: float = 60):
    """저장소 루트에서 python 을 돌린다(DATAHUB_ROOT=root). stdout/stderr 를 바이트로 분리해 돌려준다."""
    env = {**os.environ, "DATAHUB_ROOT": str(root), "PYTHONUTF8": "1"}
    return subprocess.run([sys.executable, *code_or_args], cwd=REPO, env=env,
                          capture_output=True, timeout=timeout)
