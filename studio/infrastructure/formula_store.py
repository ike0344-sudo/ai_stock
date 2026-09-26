"""FormulaStore 구현 — presets/studio/formulas/<이름>.json `{name, text, description, created_at}` (설계서 §3.5·§7).

이름 규칙 `^[가-힣A-Za-z0-9_\\- ]{1,40}$` — 점·슬래시가 없어 경로 조작이 불가능하다. 프리셋(`presets/studio/*.json`)과 같은 저장소에
두되 하위 폴더라 프리셋 목록(`glob("*.json")`)에 섞이지 않는다. 덮어쓰기는 만든 시각(created_at)을 유지한다.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from studio.application.formula_service import FormulaNotFound

from .fsutil import retry_perm

NAME_RE = re.compile(r"^[가-힣A-Za-z0-9_\- ]{1,40}$")


class FileFormulaStore:
    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            from datahub import catalog
            root = catalog.root() / "presets" / "studio" / "formulas"
        self.root = Path(root)

    def _path(self, name: str) -> Path:
        if not NAME_RE.fullmatch(name):
            raise ValueError(f"잘못된 수식 이름: {name!r}")
        return self.root / f"{name}.json"

    def _read(self, p: Path) -> dict[str, Any]:
        return json.loads(retry_perm(lambda: p.read_text(encoding="utf-8-sig")))  # 동시 저장이 교체하는 순간 Windows 가 잠깐 거부한다

    def list(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        out = []
        for p in sorted(self.root.glob("*.json")):
            if not NAME_RE.fullmatch(p.stem):
                continue
            try:
                d = self._read(p)
            except (OSError, ValueError):
                continue
            out.append({"name": p.stem, "text": d.get("text", ""), "description": d.get("description", ""),
                        "created_at": d.get("created_at")})
        return out

    def get(self, name: str) -> dict[str, Any]:
        p = self._path(name)
        if not p.exists():
            raise FormulaNotFound(name)
        d = self._read(p)
        return {"name": name, "text": d.get("text", ""), "description": d.get("description", ""),
                "created_at": d.get("created_at")}

    def put(self, name: str, text: str, description: str = "") -> dict[str, Any]:
        p = self._path(name)
        try:
            created = self._read(p).get("created_at") if p.exists() else None
        except (OSError, ValueError):
            created = None
        rec = {"name": name, "text": text, "description": description,
               "created_at": created or datetime.now().isoformat(timespec="seconds")}
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(3)}.tmp")  # 스레드·호출마다 다른 이름
        try:
            tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            retry_perm(os.replace, tmp, p)
        finally:
            tmp.unlink(missing_ok=True)
        return rec

    def delete(self, name: str) -> None:
        p = self._path(name)
        if not p.exists():
            raise FormulaNotFound(name)
        p.unlink()
