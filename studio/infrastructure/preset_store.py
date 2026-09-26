"""PresetStore 구현 — presets/studio/<이름>.json (커밋 대상, 설계서 §3.3: state/ 는 git 복구 불가라 프리셋은 저장소에 둔다).

이름 규칙 `^[\\w가-힣\\- ]{1,40}$` (§7) — 점·슬래시가 없어 경로 조작이 불가능하다. 목록에는 파일 이름(=키)과 명세의 표시 이름을 둘 다 준다.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from studio.application.services import PresetNotFound

NAME_RE = re.compile(r"^[\w가-힣\- ]{1,40}$")


class FilePresetStore:
    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            from datahub import catalog
            root = catalog.root() / "presets" / "studio"
        self.root = Path(root)

    def _path(self, name: str) -> Path:
        if not NAME_RE.fullmatch(name):
            raise ValueError(f"잘못된 프리셋 이름: {name!r}")
        return self.root / f"{name}.json"

    def list(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        out = []
        for p in sorted(self.root.glob("*.json")):
            if not NAME_RE.fullmatch(p.stem):
                continue
            try:
                spec = json.loads(p.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            out.append({"name": p.stem, "title": spec.get("name"), "mode": spec.get("mode"),
                        "period": spec.get("period"), "n_params": len(spec.get("params") or {})})
        return out

    def get(self, name: str) -> dict[str, Any]:
        p = self._path(name)
        if not p.exists():
            raise PresetNotFound(name)
        return json.loads(p.read_text(encoding="utf-8-sig"))

    def put(self, name: str, spec: Mapping[str, Any]) -> None:
        p = self._path(name)
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, p)

    def delete(self, name: str) -> None:
        p = self._path(name)
        if not p.exists():
            raise PresetNotFound(name)
        p.unlink()
