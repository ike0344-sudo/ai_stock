"""RunStore 구현 — results/studio/<run_id>/ (설계서 §3.3).

spec.json · meta.json · summary.json · trades.parquet · equity.parquet.
임시 폴더에 다 쓴 뒤 폴더째 교체(os.replace)해 반쪽 기록이 안 남는다.
run_id = YYYYMMDD-HHMMSS-xxxxxx (API 는 이 정규식 외 거부).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import shutil
from pathlib import Path

import pandas as pd

from studio import ENGINE_VERSION
from studio.application.ports import RunRecord
from studio.domain.spec import Spec

from . import git_info

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


def new_run_id(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)


class FileRunStore:
    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            from datahub import catalog
            root = catalog.root() / "results" / "studio"
        self.root = Path(root)

    def _dir(self, run_id: str) -> Path:
        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError(f"잘못된 run_id: {run_id!r}")
        return self.root / run_id

    def save(self, record: RunRecord, run_id: str | None = None) -> str:
        run_id = run_id or new_run_id()
        final = self._dir(run_id)
        if final.exists():
            raise FileExistsError(f"이미 있는 run_id: {run_id}")
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f".{run_id}.tmp{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        try:
            meta = dict(record.meta) | {
                "run_id": run_id, "engine_version": ENGINE_VERSION, "git": git_info.get(),
                "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
            (tmp / "spec.json").write_text(record.spec.model_dump_json(indent=2), encoding="utf-8")
            (tmp / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            (tmp / "summary.json").write_text(json.dumps(record.summary, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
            record.trades.to_parquet(tmp / "trades.parquet", index=False)
            record.equity.to_parquet(tmp / "equity.parquet", index=False)
            if record.grid is not None:
                record.grid.to_parquet(tmp / "grid.parquet", index=False)
            if record.folds is not None:
                (tmp / "folds.json").write_text(json.dumps(record.folds, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, final)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        record.run_id = run_id
        return run_id

    def load(self, run_id: str) -> RunRecord:
        d = self._dir(run_id)
        if not d.is_dir():
            raise FileNotFoundError(run_id)

        def read(name: str) -> dict:
            return json.loads((d / name).read_text(encoding="utf-8"))

        meta = read("meta.json")
        return RunRecord(
            spec=Spec.model_validate_json((d / "spec.json").read_text(encoding="utf-8")),
            meta=meta, summary=read("summary.json"),
            trades=pd.read_parquet(d / "trades.parquet"), equity=pd.read_parquet(d / "equity.parquet"),
            run_id=run_id, warnings=list(meta.get("warnings", [])),
            grid=pd.read_parquet(d / "grid.parquet") if (d / "grid.parquet").exists() else None,
            folds=read("folds.json") if (d / "folds.json").exists() else None,
        )

    def list_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted((p.name for p in self.root.iterdir() if p.is_dir() and RUN_ID_RE.fullmatch(p.name)),
                      reverse=True)
