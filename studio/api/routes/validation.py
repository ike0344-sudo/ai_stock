"""검증 화면 보조 API (module-5) — 조합 수 미리보기 · 홀드아웃 열람 이력.

둘 다 읽기 전용이다. 조합 수는 조합을 만들지 않고 센다(즉시), 이력은 장부(holdout_ledger.json)를 읽기만 한다.
홀드아웃을 여는 것 자체는 `POST /api/jobs/holdout-check` 뿐이다.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from studio.application import validation_requests as vr
from studio.application.backtest_service import family_hash
from studio.application.services import Services

from ..deps import get_services
from ..errors import ApiError
from .jobs import _body, parse_spec

router = APIRouter(prefix="/api/validation")


@router.post("/grid-info")
async def grid_info(request: Request) -> dict[str, Any]:
    body = await _body(request)
    spec = parse_spec(body.get("spec"))
    vary = body.get("vary")
    if vary is not None and (not isinstance(vary, list) or any(v not in spec.params for v in vary)):
        raise ApiError(422, "SPEC_INVALID", "vary 는 명세 변수 이름 목록이어야 한다")
    return {"data": vr.grid_info(spec, vary)}


@router.post("/holdout-history")
async def holdout_history(request: Request, svc: Services = Depends(get_services)) -> dict[str, Any]:
    """이 전략 골격(family_hash)으로 홀드아웃을 연 적이 있나 — 열기 확인 대화상자가 먼저 보여 준다."""
    body = await _body(request)
    spec = parse_spec(body.get("spec"))
    fh = family_hash(spec)
    opens = svc.holdout_ledger.family_history(fh) if svc.holdout_ledger is not None else []
    return {"data": {"family_hash": fh, "opens": opens, "count": len(opens), "ledger_connected": svc.holdout_ledger is not None}}
