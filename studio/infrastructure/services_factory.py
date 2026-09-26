"""API 서비스 묶음의 실제 조립 (composition root) — `python -m studio` 가 부른다."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from datahub import catalog
from studio.application.services import Services

from .holdout_ledger import FileHoldoutLedger
from .legacy_adapter import LegacyAdapter
from .legacy_strategies import REGISTRY
from .market_data import LocalMarketData
from .preset_store import FilePresetStore
from .run_files import FileRunFiles
from .run_store import FileRunStore


def legacy_catalog() -> list[dict[str, Any]]:
    """기존 전략 8종 + 파라미터 정의 — `GET /api/meta/strategies`."""
    return [{
        "name": d.name, "label": d.label_ko, "deprecated": d.deprecated, "note": d.note,
        "params": [{"name": p.name, "kind": p.kind, "default": p.default, "lo": p.lo, "hi": p.hi,
                    "choices": list(p.choices) if p.choices else None, "label": p.label_ko, "optional": p.optional}
                   for p in d.params],
    } for d in REGISTRY.values()]


def theme_groups() -> Mapping[str, str]:
    """종목코드 → 소피증권 테마 그룹(data/theme_group_map.csv). 파일이 없으면 빈 매핑(화면은 '없음')."""
    ds = catalog.dataset("reference_static")
    p = next((catalog.root() / f for f in [ds.path, *ds.also] if f.endswith("theme_group_map.csv")), None)
    if p is None or not p.exists():
        return {}
    df = pd.read_csv(p, dtype=str, encoding="utf-8-sig")
    return dict(zip(df["code"], df["group"]))


def default_services() -> Services:
    root = catalog.root() / "results" / "studio"
    return Services(market_data=LocalMarketData, run_store=FileRunStore(root), run_files=FileRunFiles(root),
                    presets=FilePresetStore(), legacy=LegacyAdapter(), legacy_catalog=legacy_catalog,
                    theme_groups=theme_groups, holdout_ledger=FileHoldoutLedger())
