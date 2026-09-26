"""실행 기록 API (설계서 §4.1 `/api/runs*`, §4.2 `GET /api/runs/{id}`).

목록은 가볍게(parquet 을 열지 않음), 상세는 meta·spec·summary + 읽을 때 계산한 분해(analysis) + 풀이 문장.
PATCH 는 이름·메모·별표만 — **명세는 실행 뒤 못 고친다**(사전 판정 기준 보호). DELETE 는 실행 결과 폴더 하나(데이터 아님).
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from studio.application import run_queries as rq
from studio.application.services import Services

from ..deps import get_services
from ..errors import ApiError, not_found

router = APIRouter(prefix="/api/runs")
_RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


def _id(run_id: str) -> str:
    if not _RUN_ID.fullmatch(run_id):
        raise not_found()
    return run_id


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        raise ApiError(400, "VALIDATION_ERROR", "JSON 본문이 아님") from None
    if not isinstance(body, dict):
        raise ApiError(400, "VALIDATION_ERROR", "JSON 객체여야 함")
    return body


@router.get("")
def list_runs(q: str | None = Query(None, max_length=100), mode: str | None = None, kind: str | None = None,
              starred: bool | None = None, limit: int = Query(500, ge=1, le=2000),
              svc: Services = Depends(get_services)) -> dict[str, Any]:
    return {"data": rq.list_runs(svc, q=q, mode=mode, kind=kind, starred=starred)[:limit]}


@router.post("/compare")
async def compare(request: Request, svc: Services = Depends(get_services)) -> dict[str, Any]:
    body = await _json(request)
    ids = body.get("ids")
    if isinstance(ids, list):
        for i in ids:
            if not isinstance(i, str) or not _RUN_ID.fullmatch(i):
                raise not_found()
    try:
        return {"data": rq.compare_runs(svc, ids)}
    except rq.RunInputError as exc:
        raise ApiError(400, "VALIDATION_ERROR", exc.message, {"fieldErrors": {exc.field: exc.message}}) from None
    except rq.RunNotFound:
        raise not_found() from None


@router.get("/{run_id}")
def run_detail(run_id: str, svc: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        return {"data": rq.run_detail(svc, _id(run_id))}
    except rq.RunNotFound:
        raise not_found() from None


@router.get("/{run_id}/equity")
def run_equity(run_id: str, svc: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        return {"data": rq.run_equity(svc, _id(run_id))}
    except rq.RunNotFound:
        raise not_found() from None


@router.get("/{run_id}/trades")
def run_trades(run_id: str, svc: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        return {"data": rq.run_trades(svc, _id(run_id))}
    except rq.RunNotFound:
        raise not_found() from None


@router.get("/{run_id}/grid")
def run_grid(run_id: str, svc: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        return {"data": rq.run_grid(svc, _id(run_id))}
    except (rq.RunNotFound, rq.NoSuchPart):
        raise not_found() from None


@router.get("/{run_id}/folds")
def run_folds(run_id: str, svc: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        return {"data": rq.run_folds(svc, _id(run_id))}
    except (rq.RunNotFound, rq.NoSuchPart):
        raise not_found() from None


@router.get("/{run_id}/export/trades.csv")
def export_trades(run_id: str, svc: Services = Depends(get_services)) -> Response:
    try:
        data = rq.trades_csv(svc, _id(run_id))
    except rq.RunNotFound:
        raise not_found() from None
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="trades_{run_id}.csv"'})


@router.patch("/{run_id}")
async def patch_run(run_id: str, request: Request, svc: Services = Depends(get_services)) -> dict[str, Any]:
    body = await _json(request)
    try:
        return {"data": rq.patch_run(svc, _id(run_id), body)}
    except rq.RunNotFound:
        raise not_found() from None
    except rq.RunInputError as exc:
        raise ApiError(400, "VALIDATION_ERROR", exc.message, {"fieldErrors": {exc.field: exc.message}}) from None


@router.delete("/{run_id}")
def delete_run(run_id: str, svc: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        rq.delete_run(svc, _id(run_id))
    except rq.RunNotFound:
        raise not_found() from None
    return {"data": {"run_id": run_id, "deleted": True}}
