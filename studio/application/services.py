"""API 가 쓰는 의존 묶음 — 설계서 §9 (studio.api → application, infrastructure 는 조립 지점에서만).

`create_app(services=...)` 로 주입한다. 실제 구현은 `studio.infrastructure.services_factory.default_services()`,
테스트는 가짜(대역)를 넣는다. 시장 데이터는 **요청마다 새로 만드는 팩토리**다 — 서버가 며칠씩 떠 있는 동안 야간 갱신으로
일봉이 바뀌므로 캐시를 프로세스에 오래 들고 있으면 낡은 값을 보여준다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

import pandas as pd

from .ports import HoldoutLedger, LegacyStrategies, MarketData, RunStore


class RunFiles(Protocol):
    """results/studio/<run_id>/ 의 가벼운 읽기·수정 (전체 로드 없이 목록·상세·거래를 준다)."""

    def exists(self, run_id: str) -> bool: ...

    def has(self, run_id: str, name: str) -> bool:
        """그 실행 폴더에 파일(grid.parquet·folds.json 등)이 있나."""

    def list_rows(self) -> list[dict[str, Any]]: ...

    def read_json(self, run_id: str, name: str) -> dict[str, Any]: ...

    def read_trades(self, run_id: str) -> pd.DataFrame: ...

    def read_equity(self, run_id: str) -> pd.DataFrame: ...

    def read_grid(self, run_id: str) -> pd.DataFrame: ...

    def patch_meta(self, run_id: str, patch: Mapping[str, Any]) -> dict[str, Any]: ...

    def delete(self, run_id: str) -> None: ...


class PresetNotFound(Exception):
    pass


class PresetStore(Protocol):
    def list(self) -> list[dict[str, Any]]: ...

    def get(self, name: str) -> dict[str, Any]: ...

    def put(self, name: str, spec: Mapping[str, Any]) -> None: ...

    def delete(self, name: str) -> None: ...


@dataclass
class Services:
    market_data: Callable[[], MarketData]
    run_store: RunStore
    run_files: RunFiles
    presets: PresetStore
    legacy: LegacyStrategies | None = None
    legacy_catalog: Callable[[], list[dict[str, Any]]] = field(default=lambda: [])
    theme_groups: Callable[[], Mapping[str, str]] = field(default=lambda: {})
    holdout_ledger: HoldoutLedger | None = None  # 홀드아웃 열기 확인 대화상자의 이력(읽기만)
