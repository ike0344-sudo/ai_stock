"""jobrunner 워커가 부르는 작업 처리기 — 얇게 (설계서 §2.2(e), §3.3).

`job.json.handler = "studio.application.jobs:run_backtest_job"`. 워커(jobrunner)는 이 모듈을 이름 문자열로만 안다.
처리기는 backtest_service 를 부르고 결과를 RunStore 에 저장할 뿐이다 — 판단 로직은 서비스에 있다.

의존(시장 데이터·기존 전략·실행 저장소)은 응용 계층이 infrastructure 를 import 할 수 없어서(§9.3) 조립 지점
`studio.infrastructure.wiring.default_deps` 를 **이름으로** 불러온다(composition root). 테스트는 `deps_factory` 를 바꿔 끼운다.

취소: 서비스가 단계 경계(load·signals·…)마다 진행 콜백을 부르므로 거기서 cancel.flag 를 본다 — 단계 단위 협조 취소.
멈추면 예외를 던지고, 워커는 취소 요청이 있었으면 그 예외를 실패가 아니라 cancelled 로 기록한다.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable

from studio.domain.spec import Spec

from .backtest_service import run_backtest
from .optimize_service import run_holdout_check, run_optimize, run_walkforward
from .ports import HoldoutLedger, LegacyStrategies, MarketData, RunStore, TradingCalendar


@dataclass
class Deps:
    market_data: MarketData
    run_store: RunStore
    legacy: LegacyStrategies | None = None
    # 검증(module-5) — 기본값 None 이면 검증 작업이 없는 것으로 동작(달력은 일봉 패널 날짜로 대신, 병렬 1)
    holdout_ledger: HoldoutLedger | None = None
    calendar: TradingCalendar | None = None
    parallel_workers: Callable[[], int] | None = None  # 지금 시각의 그리드 병렬 수(소피증권 가동 cpu//4, 야간 cpu//2)
    worker_bootstrap: str | None = None  # 프로세스 풀 워커가 의존을 만드는 "모듈:함수"
    memory_limit: Callable[[int], int] | None = None  # 워커당 바이트 → 메모리가 허락하는 최대 워커 수(가용 메모리 − 예비)


deps_factory: Callable[[], Deps] | None = None


def _deps() -> Deps:
    if deps_factory is not None:
        return deps_factory()
    return importlib.import_module("studio.infrastructure.wiring").default_deps()


def run_backtest_job(ctx: Any) -> dict[str, Any]:
    payload = ctx.payload
    spec = Spec.model_validate(payload["spec"])
    run_id = payload["run_id"]
    deps = _deps()

    def progress(stage: str, frac: float) -> None:
        if ctx.is_cancelled():
            raise RuntimeError("취소 요청으로 중단")
        ctx.progress(frac * 100, stage)

    record = run_backtest(spec, deps.market_data, progress, legacy=deps.legacy, overrides=payload.get("overrides"))
    deps.run_store.save(record, run_id=run_id)
    ctx.set_run_id(run_id)
    ctx.progress(100, "done", f"저장 완료: {run_id}")
    return {"run_id": run_id}


# --------------------------------------------------------------------------- 검증 작업 (module-5)


def _progress(ctx: Any) -> Callable[[str, float], None]:
    def progress(stage: str, frac: float) -> None:
        if ctx.is_cancelled():
            raise RuntimeError("취소 요청으로 중단")
        ctx.progress(frac * 100, stage)
    return progress


def _opt_config(spec: Spec, cfg: dict[str, Any] | None):
    """payload.config(선택) 를 OptimizeConfig 로 — 빠진 칸은 Spec.validation 에서. 날짜는 ISO 문자열로 온다."""
    import dataclasses
    import datetime as dt

    from studio.domain.validation import OptimizeConfig
    cfg = dict(cfg or {})
    if isinstance(cfg.get("split_date"), str):
        cfg["split_date"] = dt.date.fromisoformat(cfg["split_date"])
    if cfg.get("vary") is not None:
        cfg["vary"] = tuple(cfg["vary"])
    return dataclasses.replace(OptimizeConfig.from_validation(spec.validation), **cfg)


def _workers(deps: Deps) -> int:
    return max(1, deps.parallel_workers()) if deps.parallel_workers else 1


def _finish(ctx: Any, deps: Deps, record: Any, run_id: str) -> dict[str, Any]:
    deps.run_store.save(record, run_id=run_id)
    ctx.set_run_id(run_id)
    ctx.progress(100, "done", f"저장 완료: {run_id}")
    return {"run_id": run_id}


def run_optimize_job(ctx: Any) -> dict[str, Any]:
    """payload: {spec, run_id, config?}"""
    p = ctx.payload
    spec = Spec.model_validate(p["spec"])
    deps = _deps()
    record = run_optimize(spec, deps.market_data, _opt_config(spec, p.get("config")), _progress(ctx),
                          legacy=deps.legacy, calendar=deps.calendar, workers=_workers(deps),
                          bootstrap=deps.worker_bootstrap, memory_limit=deps.memory_limit)
    return _finish(ctx, deps, record, p["run_id"])


def run_walkforward_job(ctx: Any) -> dict[str, Any]:
    """payload: {spec, run_id, walkforward: {train_days, test_days, step_days?, mode?}, config?}"""
    from studio.domain.validation import WalkForwardConfig
    p = ctx.payload
    spec = Spec.model_validate(p["spec"])
    deps = _deps()
    wf = dict(p["walkforward"])
    wcfg = WalkForwardConfig(int(wf["train_days"]), int(wf["test_days"]), wf.get("step_days"),
                             wf.get("mode", "rolling"), base=_opt_config(spec, p.get("config")))
    record = run_walkforward(spec, deps.market_data, wcfg, _progress(ctx), legacy=deps.legacy,
                             calendar=deps.calendar, workers=_workers(deps), bootstrap=deps.worker_bootstrap,
                             memory_limit=deps.memory_limit)
    return _finish(ctx, deps, record, p["run_id"])


def run_holdout_check_job(ctx: Any) -> dict[str, Any]:
    """payload: {spec, run_id, overrides, source_run_id?, config?} — 홀드아웃은 이 작업으로만 연다."""
    p = ctx.payload
    spec = Spec.model_validate(p["spec"])
    deps = _deps()
    if deps.holdout_ledger is None:
        raise RuntimeError("홀드아웃 장부가 연결되지 않았다(deps.holdout_ledger)")
    record = run_holdout_check(spec, p.get("overrides"), deps.market_data, deps.holdout_ledger,
                               _opt_config(spec, p.get("config")), _progress(ctx), legacy=deps.legacy,
                               calendar=deps.calendar, source_run_id=p.get("source_run_id"), run_id=p.get("run_id"))
    return _finish(ctx, deps, record, p["run_id"])
