"""최적화·워크포워드·홀드아웃 **요청 시점 검사** (설계서 §8.3 #20, module-5 계약 §2).

큐에 넣기 전에 싸게 걸러낸다 — 조합 5,000 초과(GRID_TOO_LARGE), 훑을 변수가 없음, 분봉·틱 모드, 분할·폴드 설정 오류.
결과 저장은 작업 처리기(`studio.application.jobs`)가 한다. 여기서는 조합을 만들지 않고 센다.
"""
from __future__ import annotations

from typing import Any, Mapping

from studio.domain.spec import Spec
from studio.domain.validation import (MAX_COMBOS, WARN_COMBOS, OptimizeConfig, ValidationConfigError, WalkForwardConfig,
                                      grid_axes)

from .optimize_service import count_grid

CONFIG_KEYS = ("train_pct", "split_date", "vary")


class RequestInvalid(Exception):
    """API 가 그대로 오류 봉투로 바꾼다: (HTTP 상태, 코드, 메시지, 세부)."""

    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def _config(spec: Spec, raw: Mapping[str, Any] | None) -> dict[str, Any]:
    cfg = dict(raw or {})
    unknown = sorted(set(cfg) - set(CONFIG_KEYS))
    if unknown:
        raise RequestInvalid(400, "VALIDATION_ERROR", f"config 에서 못 받는 칸: {unknown} (받는 칸: {list(CONFIG_KEYS)} — 목표·거래 수·홀드아웃·판정 기준은 명세의 validation 에 둔다)")
    if cfg.get("vary") is not None:
        bad = [v for v in cfg["vary"] if v not in spec.params]
        if bad:
            raise RequestInvalid(422, "SPEC_INVALID", f"vary 에 없는 변수: {bad}")
    try:  # 값 범위(train_pct 1~99 등)는 도메인 설정 클래스가 검사한다
        OptimizeConfig.from_validation(spec.validation, **{k: v for k, v in cfg.items() if k in ("train_pct",)})
        if cfg.get("split_date") is not None:
            import datetime as dt
            dt.date.fromisoformat(str(cfg["split_date"]))
    except (ValidationConfigError, ValueError) as exc:
        raise RequestInvalid(422, "SPEC_INVALID", str(exc)) from None
    return cfg


def _daily_only(spec: Spec) -> None:
    if spec.mode in ("intraday", "tick"):
        raise RequestInvalid(422, "SPEC_INVALID", "최적화·워크포워드는 일봉 모드만 된다")


def _grid_size(spec: Spec, cfg: Mapping[str, Any]) -> int:
    n = count_grid(spec, cfg.get("vary"))
    if n > MAX_COMBOS:
        raise RequestInvalid(422, "GRID_TOO_LARGE", f"조합이 {n:,}개 — {MAX_COMBOS:,}개를 넘어 실행하지 않는다(간격을 늘리거나 훑는 변수를 줄여라)",
                             {"n": n, "limit": MAX_COMBOS})
    if n < 2:
        raise RequestInvalid(422, "SPEC_INVALID", "훑을 변수가 없다 — 변수 표에서 최소·최대·간격을 다 채운 변수가 하나 이상 필요하다")
    return n


def check_optimize(spec: Spec, raw_config: Mapping[str, Any] | None) -> dict[str, Any]:
    _daily_only(spec)
    cfg = _config(spec, raw_config)
    _grid_size(spec, cfg)
    return cfg


def check_walkforward(spec: Spec, raw_config: Mapping[str, Any] | None, raw_wf: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    _daily_only(spec)
    cfg = _config(spec, raw_config)
    _grid_size(spec, cfg)
    wf = dict(raw_wf or {})
    try:
        WalkForwardConfig(int(wf["train_days"]), int(wf["test_days"]), wf.get("step_days"), wf.get("mode", "rolling"))
    except ValidationConfigError as exc:  # ValueError 의 하위일 수 있어 먼저 잡는다
        raise RequestInvalid(422, "SPEC_INVALID", str(exc)) from None
    except (KeyError, TypeError, ValueError) as exc:
        raise RequestInvalid(400, "VALIDATION_ERROR", "walkforward 에 train_days·test_days(정수)가 필요하다", {"fieldErrors": {"walkforward": str(exc)}}) from None
    return cfg, wf


def check_holdout(spec: Spec, overrides: Mapping[str, Any] | None) -> dict[str, float]:
    _daily_only(spec)
    ov = dict(overrides or {})
    bad = [k for k in ov if k not in spec.params]
    if bad:
        raise RequestInvalid(422, "SPEC_INVALID", f"overrides 에 없는 변수: {bad}")
    try:
        return {k: float(v) for k, v in ov.items()}
    except (TypeError, ValueError):
        raise RequestInvalid(400, "VALIDATION_ERROR", "overrides 값은 숫자여야 한다") from None


def grid_info(spec: Spec, vary: list[str] | None = None) -> dict[str, Any]:
    """화면이 미리 보여줄 조합 수·훑는 변수·상태."""
    n = count_grid(spec, vary)
    axes = grid_axes(spec.params, vary)
    return {"n": n, "limit": MAX_COMBOS, "warn_over": WARN_COMBOS, "axes": {k: len(v) for k, v in axes.items()},
            "too_large": n > MAX_COMBOS, "warn": n > WARN_COMBOS}
