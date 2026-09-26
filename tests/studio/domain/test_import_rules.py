"""§9.3 — studio.domain 은 I/O·기존 backtesting·datahub·다른 studio 계층을 import 하지 않는다 (AST 검사)."""
import ast
import pathlib

import pytest

DOMAIN = pathlib.Path(__file__).resolve().parents[3] / "studio" / "domain"
FORBIDDEN = {"os", "io", "subprocess", "socket", "requests", "psutil", "fastapi", "backtesting", "datahub",
             "kiwoom_client", "order_execution", "sell_order", "jobrunner"}
FORBIDDEN_STUDIO = {"application", "infrastructure", "api"}


def _imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module
            if node.module == "studio":  # from studio import infrastructure
                yield from (f"studio.{a.name}" for a in node.names)


@pytest.mark.parametrize("path", sorted(DOMAIN.rglob("*.py")), ids=lambda p: str(p.relative_to(DOMAIN)))
def test_domain_imports(path):
    bad = []
    for mod in _imports(path):
        parts = mod.split(".")
        if parts[0] in FORBIDDEN or "trading_loop" in parts:
            bad.append(mod)
        if parts[0] == "studio" and len(parts) > 1 and parts[1] in FORBIDDEN_STUDIO:
            bad.append(mod)
    assert not bad, f"{path.name}: 금지된 import {bad}"


APPLICATION = DOMAIN.parent / "application"
# §9.3: application 은 domain + **stdlib** 만 안다(os·io 같은 stdlib 은 허용 — 금지는 domain 쪽 규칙). 비표준 라이브러리·기존 코드·바깥 계층은 금지.
APP_FORBIDDEN = {"requests", "psutil", "pyarrow", "fastapi", "backtesting", "datahub", "kiwoom_client",
                 "order_execution", "sell_order", "jobrunner"}
APP_FORBIDDEN_STUDIO = {"infrastructure", "api"}  # application → infrastructure 금지(포트로만)


@pytest.mark.parametrize("path", sorted(APPLICATION.rglob("*.py")), ids=lambda p: str(p.relative_to(APPLICATION)))
def test_application_imports(path):
    """§9.3: studio.application 은 domain·stdlib 만 — backtesting·datahub·infrastructure·api·fastapi 금지."""
    bad = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                mods = [node.module] + ([f"studio.{a.name}" for a in node.names] if node.module == "studio" else [])
        for mod in mods:
            parts = mod.split(".")
            if parts[0] in APP_FORBIDDEN or (parts[0] == "studio" and len(parts) > 1 and parts[1] in APP_FORBIDDEN_STUDIO):
                bad.append(mod)
    assert not bad, f"{path.name}: 금지된 import {bad}"
