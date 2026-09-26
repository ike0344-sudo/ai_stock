"""설계서 §9.3 — studio.api 와 studio.application 의 import 경계 (AST 로 검사)."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REAL_ORDER = {"kiwoom_client", "backtesting.trading_loop", "order_execution", "sell_order"}


def imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module)
    return out


def violations(pkg: str, banned_prefixes: tuple[str, ...]) -> list[str]:
    bad = []
    for f in (ROOT / pkg).rglob("*.py"):
        for m in imports(f):
            if m.startswith(banned_prefixes) or m in REAL_ORDER:
                bad.append(f"{f.relative_to(ROOT)}: {m}")
    return bad


def test_api_layer_does_not_reach_into_infrastructure_or_backtesting():
    assert not violations("studio/api", ("studio.infrastructure", "backtesting", "kiwoom_client"))


def test_application_layer_is_framework_and_infrastructure_free():
    assert not violations("studio/application", ("studio.infrastructure", "studio.api", "fastapi", "backtesting", "kiwoom_client"))
