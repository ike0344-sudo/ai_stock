"""RunFiles 구현 — results/studio/<run_id>/ 의 가벼운 읽기·수정 (설계서 §3.3).

목록은 meta.json·summary.json·spec.json 만 읽고(parquet 은 안 연다) 수정 시각으로 캐시한다 — 실행이 수백 개여도 빠르게.
meta.json 수정(이름·메모·별표)은 tmp + 교체. 삭제는 그 실행 폴더 하나(ID 정규식 통과분만 — 경로 조작 불가).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .fsutil import retry_perm

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
_METRIC_KEYS = ("total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "num_trades", "win_rate_pct",
                "profit_factor", "expectancy_pct")


class FileRunFiles:
    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            from datahub import catalog
            root = catalog.root() / "results" / "studio"
        self.root = Path(root)
        self._cache: dict[str, tuple[tuple[float, ...], dict[str, Any]]] = {}

    def _dir(self, run_id: str) -> Path:
        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError(f"잘못된 run_id: {run_id!r}")
        return self.root / run_id

    def exists(self, run_id: str) -> bool:
        return bool(RUN_ID_RE.fullmatch(run_id)) and (self.root / run_id / "meta.json").exists()

    def has(self, run_id: str, name: str) -> bool:
        return (self._dir(run_id) / name).exists()

    def read_json(self, run_id: str, name: str) -> dict[str, Any]:
        return json.loads(retry_perm((self._dir(run_id) / name).read_text, "utf-8"))  # 다른 스레드가 meta.json 을 교체하는 순간의 공유 위반은 재시도

    def read_trades(self, run_id: str) -> pd.DataFrame:
        return pd.read_parquet(self._dir(run_id) / "trades.parquet")

    def read_equity(self, run_id: str) -> pd.DataFrame:
        return pd.read_parquet(self._dir(run_id) / "equity.parquet")

    def read_grid(self, run_id: str) -> pd.DataFrame:
        return pd.read_parquet(self._dir(run_id) / "grid.parquet")

    # ---- 목록
    def _row(self, run_id: str) -> dict[str, Any] | None:
        d = self._dir(run_id)
        try:
            sig = tuple(round((d / n).stat().st_mtime, 3) for n in ("meta.json", "summary.json", "spec.json"))
        except OSError:
            return None  # 쓰다 만 폴더 — 목록에서 뺀다
        hit = self._cache.get(run_id)
        if hit and hit[0] == sig:
            return hit[1]
        try:
            meta, spec = self.read_json(run_id, "meta.json"), self.read_json(run_id, "spec.json")
            summary = self.read_json(run_id, "summary.json")
        except (OSError, ValueError):
            return None
        m = summary.get("metrics") or {}
        row = {
            "run_id": run_id, "name": meta.get("name") or spec.get("name"), "kind": meta.get("kind") or "backtest",
            "mode": spec.get("mode"), "period": spec.get("period"), "compat": bool((spec.get("compat") or {}).get("legacy")),
            "created_at": meta.get("created_at"), "engine_version": meta.get("engine_version"),
            "starred": bool(meta.get("starred")), "memo": meta.get("memo"),
            "metrics": {k: m.get(k) for k in _METRIC_KEYS}, "n_trades": summary.get("n_trades"),
            "elapsed_sec": meta.get("elapsed_sec"),
        }
        self._cache[run_id] = (sig, row)
        return row

    def list_rows(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        ids = sorted((p.name for p in self.root.iterdir() if p.is_dir() and RUN_ID_RE.fullmatch(p.name)), reverse=True)
        return [r for r in (self._row(i) for i in ids) if r is not None]

    # ---- 수정·삭제
    def patch_meta(self, run_id: str, patch: Mapping[str, Any]) -> dict[str, Any]:
        d = self._dir(run_id)
        meta = self.read_json(run_id, "meta.json") | dict(patch)
        tmp = d / f".meta.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(3)}.tmp"  # 같은 실행을 스레드 둘이 동시에 고쳐도 tmp 가 안 겹치게
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            retry_perm(os.replace, tmp, d / "meta.json")  # Windows: 다른 스레드·프로세스가 읽는 중이면 교체가 잠깐 거부된다
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        self._cache.pop(run_id, None)
        return meta

    def delete(self, run_id: str) -> None:
        d = self._dir(run_id)
        if d.is_dir():
            shutil.rmtree(d)
        self._cache.pop(run_id, None)
