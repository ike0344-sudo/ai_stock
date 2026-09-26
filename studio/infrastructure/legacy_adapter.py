"""LegacyStrategies 포트 구현 — strategy-agent 의 legacy_strategies 함수를 그대로 부른다(수정 없음)."""
from __future__ import annotations

from typing import Any

import pandas as pd

from studio.domain.conditions.evaluator import Evaluation
from studio.domain.models import Panel

from . import legacy_strategies as ls


class LegacyAdapter:
    def evaluate(self, name: str, params: dict[str, Any] | None, panel: Panel) -> Evaluation:
        return ls.evaluate_legacy(name, params, panel)

    def signals(self, name: str, params: dict[str, Any] | None, panel: Panel) -> pd.DataFrame:
        return ls.legacy_signals(name, params, panel)
