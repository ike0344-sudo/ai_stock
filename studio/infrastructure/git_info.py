"""실행 재현 정보 — 현재 git 커밋과 작업 트리가 더러운지(meta.json)."""
from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str, cwd: Path = _ROOT) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=10, check=True)  # text=True 만 쓰면 cp949 로 읽어 한글 경로에서 깨진다
        return r.stdout.strip()
    except Exception:
        return None


def get(cwd: Path = _ROOT) -> dict:
    """{'commit': 짧은 해시|None, 'dirty': bool|None} — git 을 못 부르면 None(모른다고 적는다)."""
    commit = _git("rev-parse", "--short", "HEAD", cwd=cwd)
    status = _git("status", "--porcelain", "--untracked-files=no", cwd=cwd)
    return {"commit": commit, "dirty": (bool(status) if status is not None else None)}
