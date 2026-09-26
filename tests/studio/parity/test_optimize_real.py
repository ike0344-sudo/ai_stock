"""실데이터 검증 스모크 — 프로세스 풀(병렬)이 직렬과 같은 표를 내는지, 워크포워드·홀드아웃이 실제 데이터로 도는지.

@pytest.mark.parity — 데이터가 없으면 skip. 워커가 패널을 각자 올리므로 분 단위로 걸린다(3x3 격자).
"""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from studio.application.optimize_service import run_holdout_check, run_optimize, run_walkforward
from studio.domain.spec import Spec
from studio.domain.validation import OptimizeConfig, WalkForwardConfig
from studio.infrastructure import wiring
from studio.infrastructure.holdout_ledger import FileHoldoutLedger

PARQUET = os.path.join("data", "cache", "daily_all.parquet")
PRESET = Path(__file__).resolve().parents[3] / "presets" / "studio" / "golden_cross_5_20.json"

pytestmark = pytest.mark.parity


@pytest.fixture(scope="module")
def spec():
    if not os.path.exists(PARQUET):
        pytest.skip("daily_all.parquet 없음")
    d = json.loads(PRESET.read_text(encoding="utf-8"))
    d["period"] = {"start": "2023-01-02", "end": "2026-08-31"}
    d["universe"] = {"type": "top_value", "n": 30, "exclude": ["spac", "preferred", "mega_cap"]}
    d["params"] = {"short": {"default": 5, "min": 4, "max": 6, "step": 1}, "long": {"default": 20, "min": 15, "max": 25, "step": 5}}
    d["validation"] = {"holdout_pct": 20, "objective": "sharpe", "min_trades": 10}
    return Spec.model_validate(d)


@pytest.fixture(scope="module")
def deps():
    return wiring.default_deps()


def test_parallel_grid_equals_serial(spec, deps):
    cfg = OptimizeConfig.from_validation(spec.validation)
    kw = dict(legacy=deps.legacy, calendar=deps.calendar)
    a = run_optimize(spec, deps.market_data, cfg, **kw)
    b = run_optimize(spec, deps.market_data, cfg, workers=2, bootstrap=wiring.BOOTSTRAP, **kw)
    pd.testing.assert_frame_equal(a.grid, b.grid)
    assert a.summary["optimize"]["selected"] == b.summary["optimize"]["selected"] and len(a.grid) == 9
    # 홀드아웃(달력 기준 마지막 20% 거래일)은 최적화 곡선에 없다
    seg = a.summary["optimize"]["segments"]
    assert a.equity["ts"].max() < pd.Timestamp(seg["holdout"][0])


def test_walkforward_and_holdout_on_real_data(spec, deps, tmp_path):
    wf = run_walkforward(spec, deps.market_data, WalkForwardConfig(250, 100, base=OptimizeConfig.from_validation(spec.validation)),
                         legacy=deps.legacy, calendar=deps.calendar)
    assert wf.folds["folds"] and wf.summary["walkforward"]["n_validated"] >= 1
    ledger = FileHoldoutLedger(tmp_path / "l.json")
    p = {"short": 5, "long": 20}
    r1 = run_holdout_check(spec, p, deps.market_data, ledger, legacy=deps.legacy, calendar=deps.calendar)
    r2 = run_holdout_check(spec, p, deps.market_data, ledger, legacy=deps.legacy, calendar=deps.calendar)
    assert r1.summary["holdout"]["nth_open"] == 1 and r2.summary["holdout"]["nth_open"] == 2
    assert any("2번째 열었다" in w for w in r2.warnings)
    h0 = pd.Timestamp(r1.summary["holdout"]["period"][0])
    assert r1.equity["ts"].min() >= h0
