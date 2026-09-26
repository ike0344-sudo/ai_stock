"""§9.3 — jobrunner 는 datahub·studio·backtesting·fastapi 를 import 하지 않는다(handler 는 문자열로만)."""
import ast
from pathlib import Path

FORBIDDEN = {"datahub", "studio", "backtesting", "fastapi", "kiwoom_client", "requests"}


def test_jobrunner_imports():
    bad = []
    for f in Path(__file__).resolve().parents[2].joinpath("jobrunner").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            bad += [f"{f.name}: {n}" for n in names if n.split(".")[0] in FORBIDDEN]
    assert not bad, bad
