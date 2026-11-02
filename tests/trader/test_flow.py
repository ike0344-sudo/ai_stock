"""trader.flow 자체 점검(매수·매도 가르기 · 과열 매수 · C 첫 깨짐만 · 벽)을 테스트에서도 돌린다 — 실제 기록 파일은 안 건드린다."""
import os
import subprocess
import sys
from pathlib import Path


def test_flow_selfcheck():
    r = subprocess.run([sys.executable, "-m", "trader.flow"], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding="utf-8", timeout=120,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})   # 한글 출력 — 콘솔 인코딩과 무관하게
    assert r.returncode == 0 and r.stdout.startswith("ok"), r.stdout + r.stderr


def test_replay_restores_today_high(tmp_path):
    """11-02: 재시작 전 08:00 고가가 HC 에서 빠졌다 — 켤 때 오늘 저장 체결을 다시 흘린다(호가 줄은 건너뜀)."""
    import gzip, json
    from trader import flow
    p = tmp_path / "999990" / "2026-11-02.jsonl.gz"
    p.parent.mkdir()
    rows = [{"k": "0B", "v": {"10": "+1000", "20": "080000", "13": "5", "15": "+5"}},
            {"k": "0D", "v": {"41": "1"}},
            {"k": "0B", "v": {"10": "+900", "20": "090100", "13": "8", "15": "-3"}}]
    with gzip.open(p, "at", encoding="utf-8") as f:
        f.write("\n".join(json.dumps({"t": 0, **r}) for r in rows) + "\n")
    flow._st.pop("999990", None)
    assert flow.replay(tmp_path, "2026-11-02") == 2
    s = flow._st.pop("999990")
    assert s["rhi"] == 1000 and s["rhi_reg"] == 900
