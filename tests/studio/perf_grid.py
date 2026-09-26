"""그리드 성능·정합 실측(설계서 §8.9: 100조합 <= 5분) - 수동 실행: python tests/studio/perf_grid.py [workers]"""
import json
import sys
import time

sys.path.insert(0, ".")
from studio.application.optimize_service import run_optimize
from studio.domain.spec import Spec
from studio.domain.validation import OptimizeConfig
from studio.infrastructure import wiring
from studio.infrastructure.legacy_adapter import LegacyAdapter


def build(n_short=10, n_long=10):
    d = json.load(open("presets/studio/golden_cross_5_20.json", encoding="utf-8"))
    d["params"] = {"short": {"default": 5, "min": 3, "max": 3 + n_short - 1, "step": 1},
                   "long": {"default": 20, "min": 10, "max": 10 + 5 * (n_long - 1), "step": 5}}
    d["validation"] = {"holdout_pct": 20, "objective": "sharpe", "min_trades": 30}
    return Spec.model_validate(d)


if __name__ == "__main__":
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    deps = wiring.default_deps()
    spec = build()
    t = time.time()
    # 메모리 상한을 따른다(2026-09-25: 워커 4개 측정이 이 PC 의 커밋을 2.4GB 까지 떨어뜨림) — 예비는 wiring.RESERVE_BYTES(6GB)
    print("가용 메모리 %.1fGB, 예비 %.1fGB" % (wiring.available_bytes() / 1024 ** 3, wiring.RESERVE_BYTES / 1024 ** 3))
    rec = run_optimize(spec, deps.market_data, OptimizeConfig.from_validation(spec.validation),
                       lambda s, f: None, legacy=deps.legacy, calendar=deps.calendar, workers=workers,
                       bootstrap=wiring.BOOTSTRAP if workers > 1 else None, memory_limit=wiring.workers_for_memory)
    print([w for w in rec.warnings if "메모리" in w])
    el = time.time() - t
    o = rec.summary["optimize"]
    print(f"workers={workers} combos={o['n_combos']} valid={o['n_valid']} elapsed={el:.1f}s per_combo={el / o['n_combos']:.2f}s")
    print("selected", o["selected"]["params"], "IS sharpe %.2f OOS sharpe %.2f" % (o["selected"]["is"]["sharpe"], o["selected"]["oos"]["sharpe"]))
    print("segments", o["segments"], "stability", {k: o["neighbor_stability"][k] for k in ("ratio", "warn")})
    print(rec.warnings)
    rec.grid.to_parquet(f".tmp_grid_w{workers}.parquet")
