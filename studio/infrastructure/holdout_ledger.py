"""홀드아웃 열람 장부 — results/studio/holdout_ledger.json (설계서 §3.3, §3.8).

{structure_hash: [ {opened_at, run_id, family_hash, period, params, ...}, ... ]}
읽고-고치고-쓰기를 잠금 파일(`.lock`, O_EXCL)로 감싼다 — 작업이 동시에 둘 돌아도 기록이 안 사라진다.
잠금이 30초 넘게 남아 있으면 죽은 프로세스가 남긴 것으로 보고 치운다.

Windows 주의: 다른 스레드·프로세스가 열어 둔(또는 삭제 대기 중인) 파일에 대한 open(O_EXCL)·replace·read 는
`FileExistsError` 가 아니라 **PermissionError** 로 실패한다. 실제로 12스레드 동시 기록에서 기록이 빠졌다(2026-09-25 실측) —
PermissionError 는 "바쁨"으로 보고 재시도하고, 끝내 못 쓰면 **예외를 던진다**(조용히 넘기지 않는다: 열람 횟수 경고가 틀려지므로).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_STALE_SEC = 30
_WAIT_SEC = 10
_RETRY = 250  # PermissionError 재시도 횟수(× 0.02초 = 5초)


def _retry(fn, *args):
    """Windows 의 일시적 PermissionError(파일이 다른 핸들에 잡힘)를 짧게 재시도. 끝내 안 되면 그 예외를 그대로 던진다."""
    for i in range(_RETRY):
        try:
            return fn(*args)
        except PermissionError:
            if i == _RETRY - 1:
                raise
            time.sleep(0.02)


class FileHoldoutLedger:
    def __init__(self, path: Path | str | None = None) -> None:
        if path is None:
            from datahub import catalog
            path = catalog.root() / "results" / "studio" / "holdout_ledger.json"
        self.path = Path(path)
        self._lock = self.path.with_suffix(".lock")

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        try:
            return json.loads(_retry(self.path.read_text, "utf-8"))
        except FileNotFoundError:
            return {}

    def history(self, structure_hash: str) -> list[dict[str, Any]]:
        return list(self._read().get(structure_hash, []))

    def family_history(self, family_hash: str) -> list[dict[str, Any]]:
        """골격(family_hash)이 같은 모든 열람 — 구조 해시가 달라도(리터럴을 바꿔도) 잡는다."""
        return [e for es in self._read().values() for e in es if e.get("family_hash") == family_hash]

    def all_entries(self) -> dict[str, list[dict[str, Any]]]:
        return self._read()

    def record_open(self, structure_hash: str, entry: dict[str, Any]) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + _WAIT_SEC
        while True:
            try:
                fd = os.open(self._lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except (FileExistsError, PermissionError):  # 잠금 보유 중이거나 삭제 대기 중 — 바쁨
                try:
                    if time.time() - self._lock.stat().st_mtime > _STALE_SEC:
                        self._lock.unlink(missing_ok=True)
                        continue
                except (FileNotFoundError, PermissionError):
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError(f"홀드아웃 장부 잠금을 {_WAIT_SEC}초 안에 못 얻었다: {self._lock}")
                time.sleep(0.05)
        try:
            data = self._read()
            data.setdefault(structure_hash, []).append(entry)
            tmp = self.path.with_suffix(f".tmp{os.getpid()}")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            _retry(os.replace, tmp, self.path)
            return len(data[structure_hash])
        finally:
            _retry(lambda: self._lock.unlink(missing_ok=True))
