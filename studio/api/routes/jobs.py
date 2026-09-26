"""작업 공통 API (설계서 §4.1, §4.2) — 목록·상태·로그 이어받기·취소 + 백테스트 제출.

쓰는 주체 분리(§3.3): API 는 job.json 을 **만들기만** 하고(고치지 않는다) 취소는 cancel.flag 만 만든다.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError

from jobrunner.dispatcher import Dispatcher
from jobrunner.mask import Masker
from jobrunner.store import GROUPS, JOB_ID_RE, STATUSES, TERMINAL, JobStore, new_id
from studio.domain.spec import Spec, bind_params

from studio.application import validation_requests as vr

from ..deps import get_dispatcher, get_store
from ..errors import ApiError, field_errors, not_found

router = APIRouter(prefix="/api/jobs")

BACKTEST_HANDLER = "studio.application.jobs:run_backtest_job"
OPTIMIZE_HANDLER = "studio.application.jobs:run_optimize_job"
WALKFORWARD_HANDLER = "studio.application.jobs:run_walkforward_job"
HOLDOUT_HANDLER = "studio.application.jobs:run_holdout_check_job"


def _job_or_404(store: JobStore, job_id: str) -> dict[str, Any]:
    if not JOB_ID_RE.fullmatch(job_id):
        raise not_found()
    job = store.read(job_id)
    if job is None:
        raise not_found()
    return job


def _summary(job: dict[str, Any]) -> dict[str, Any]:
    """payload·handler·pid 같은 내부 값은 빼고 화면이 쓰는 필드만."""
    keys = ("job_id", "kind", "group", "status", "scheduled_at", "created_at", "started_at", "finished_at",
            "run_id", "lock", "trigger", "error")
    return {k: job.get(k) for k in keys}


def _progress(store: JobStore, job: dict[str, Any]) -> dict[str, Any]:
    stored = store.read_progress(job["job_id"]) or {}
    progress = {"pct": None, "stage": None, "message": None, "eta_sec": None, "paused": False,
                "waiting_lock": None} | {k: v for k, v in stored.items() if k != "updated_at"}
    if job["status"] == "succeeded":
        progress["pct"] = 100.0
    return progress


def _detail(store: JobStore, job: dict[str, Any]) -> dict[str, Any]:
    return _summary(job) | {"progress": _progress(store, job), "ledger_run": job.get("ledger_run"),
                            "cancel_requested": store.cancel_requested(job["job_id"])}


@router.get("")
def list_jobs(
    status: str | None = Query(None), kind: str | None = Query(None, max_length=60),
    group: str | None = Query(None), limit: int = Query(50, ge=1, le=200),
    store: JobStore = Depends(get_store),
) -> dict[str, Any]:
    fields: dict[str, str] = {}
    if status is not None and status not in STATUSES:
        fields["status"] = f"{'|'.join(STATUSES)} 중 하나"
    if group is not None and group not in GROUPS:
        fields["group"] = f"{'|'.join(GROUPS)} 중 하나"
    if fields:
        raise ApiError(400, "VALIDATION_ERROR", "요청 형식이 올바르지 않음", {"fieldErrors": fields})
    # 작업 표(허브 수집 탭)가 행마다 상세를 다시 부르지 않게 진행률을 같이 준다
    rows = store.list_jobs(status=status, kind=kind, group=group, limit=limit)
    return {"data": [_summary(j) | {"progress": _progress(store, j), "cancel_requested": store.cancel_requested(j["job_id"])}
                     for j in rows]}


@router.get("/{job_id}")
def get_job(job_id: str, store: JobStore = Depends(get_store)) -> dict[str, Any]:
    return {"data": _detail(store, _job_or_404(store, job_id))}


@router.get("/{job_id}/log")
def get_log(job_id: str, offset: int = Query(0, ge=0), store: JobStore = Depends(get_store)) -> dict[str, Any]:
    _job_or_404(store, job_id)
    raw, next_offset, eof = store.read_log(job_id, offset)
    # 쓸 때 이미 가렸지만(child.py) 워커 자신의 출력(트레이스백 등)은 원문이라 읽을 때 한 번 더 가린다
    text = Masker.from_env(store.root).mask(raw.decode("utf-8", errors="replace"))
    return {"data": {"text": text, "next_offset": next_offset, "eof": eof}}


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, store: JobStore = Depends(get_store),
               dispatcher: Dispatcher | None = Depends(get_dispatcher)) -> dict[str, Any]:
    job = _job_or_404(store, job_id)
    if job["status"] in TERMINAL:
        raise ApiError(409, "JOB_NOT_CANCELLABLE", "이미 끝난 작업은 취소할 수 없음", {"status": job["status"]})
    store.request_cancel(job_id)
    if dispatcher is not None:
        dispatcher.tick()  # 예약·대기 작업은 이 자리에서 바로 cancelled 로 확정된다(실행 중이면 워커가 곧 멈춤)
    current = store.read(job_id) or job
    return {"data": {"job_id": job_id, "status": current["status"], "cancel_requested": True}}


@router.post("/backtest", status_code=202)
async def submit_backtest(request: Request, store: JobStore = Depends(get_store)) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        raise ApiError(400, "VALIDATION_ERROR", "JSON 본문이 아님") from None
    try:
        spec = Spec.model_validate(body)
    except ValidationError as exc:
        raise ApiError(400, "VALIDATION_ERROR", "명세 형식이 올바르지 않음", {
            "fieldErrors": field_errors(exc.errors(include_url=False, include_context=False, include_input=False))
        }) from None
    try:
        bind_params(spec)  # 변수 기본값을 채워 다시 검증 — 범위 밖 기본값 같은 의미 오류
    except ValueError as exc:
        raise ApiError(422, "SPEC_INVALID", str(exc)) from None
    run_id = new_id()  # 실행 결과 ID(=results/studio/<run_id>) — 형식이 job ID 와 같다(§3.3)
    job = store.create("backtest", "compute", BACKTEST_HANDLER,
                       {"spec": spec.model_dump(mode="json"), "run_id": run_id}, run_id=run_id)
    return {"data": {"job_id": job["job_id"], "run_id": run_id}}


# --------------------------------------------------------------------------- 검증 작업 (module-5)


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        raise ApiError(400, "VALIDATION_ERROR", "JSON 본문이 아님") from None
    if not isinstance(body, dict):
        raise ApiError(400, "VALIDATION_ERROR", "JSON 객체여야 함")
    return body


def parse_spec(raw: Any) -> Spec:
    """요청의 spec 을 검증하고 변수 기본값을 채워 본다(백테스트 제출과 같은 규칙)."""
    try:
        spec = Spec.model_validate(raw)
    except ValidationError as exc:
        raise ApiError(400, "VALIDATION_ERROR", "명세 형식이 올바르지 않음", {
            "fieldErrors": field_errors(exc.errors(include_url=False, include_context=False, include_input=False))
        }) from None
    try:
        bind_params(spec)
    except ValueError as exc:
        raise ApiError(422, "SPEC_INVALID", str(exc)) from None
    return spec


def _submit(store: JobStore, kind: str, handler: str, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = new_id()
    job = store.create(kind, "compute", handler, {**payload, "run_id": run_id}, run_id=run_id)
    return {"data": {"job_id": job["job_id"], "run_id": run_id}}


def _invalid(exc: vr.RequestInvalid) -> ApiError:
    return ApiError(exc.status, exc.code, exc.message, exc.details)


@router.post("/optimize", status_code=202)
async def submit_optimize(request: Request, store: JobStore = Depends(get_store)) -> dict[str, Any]:
    body = await _body(request)
    spec = parse_spec(body.get("spec"))
    try:
        cfg = vr.check_optimize(spec, body.get("config"))
    except vr.RequestInvalid as exc:
        raise _invalid(exc) from None
    return _submit(store, "optimize", OPTIMIZE_HANDLER, {"spec": spec.model_dump(mode="json"), "config": cfg})


@router.post("/walkforward", status_code=202)
async def submit_walkforward(request: Request, store: JobStore = Depends(get_store)) -> dict[str, Any]:
    body = await _body(request)
    spec = parse_spec(body.get("spec"))
    try:
        cfg, wf = vr.check_walkforward(spec, body.get("config"), body.get("walkforward"))
    except vr.RequestInvalid as exc:
        raise _invalid(exc) from None
    return _submit(store, "walkforward", WALKFORWARD_HANDLER, {"spec": spec.model_dump(mode="json"), "config": cfg, "walkforward": wf})


@router.post("/holdout-check", status_code=202)
async def submit_holdout(request: Request, store: JobStore = Depends(get_store)) -> dict[str, Any]:
    body = await _body(request)
    spec = parse_spec(body.get("spec"))
    try:
        overrides = vr.check_holdout(spec, body.get("overrides"))
    except vr.RequestInvalid as exc:
        raise _invalid(exc) from None
    src = body.get("source_run_id")
    payload: dict[str, Any] = {"spec": spec.model_dump(mode="json"), "overrides": overrides}
    if isinstance(src, str) and JOB_ID_RE.fullmatch(src):  # 출처 결과 번호(형식이 job ID 와 같다) — 기록용
        payload["source_run_id"] = src
    return _submit(store, "holdout_check", HOLDOUT_HANDLER, payload)
