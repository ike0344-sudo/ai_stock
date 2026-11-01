"""trader.flow 자체 점검(매수·매도 가르기 · 과열 매수 · C 첫 깨짐만 · 벽)을 테스트에서도 돌린다 — 실제 기록 파일은 안 건드린다."""
import os
import subprocess
import sys
from pathlib import Path


def test_flow_selfcheck():
    r = subprocess.run([sys.executable, "-m", "trader.flow"], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding="utf-8", timeout=120,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})   # 한글 출력 — 콘솔 인코딩과 무관하게
    assert r.returncode == 0 and r.stdout.startswith("ok"), r.stdout + r.stderr
