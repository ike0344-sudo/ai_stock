"""조건 검증·미리보기 API (설계서 §4.1, §4.2): `POST /api/conditions/validate` · `/preview`.

validate 는 항상 200 — 오류는 본문 `errors[]`(경로 포함)로 돌려줘 화면이 조건 행을 강조한다(§8.4 #8).
preview 는 명세가 유효해야 하고, 최신 거래일 기준으로 오늘 진입 조건을 만족하는 종목을 준다.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from studio.application import condition_service, formula_service, screener_service
from studio.application.backtest_service import BacktestError
from studio.application.services import Services
from studio.domain.spec import Spec

from ..deps import get_services
from ..errors import ApiError

router = APIRouter(prefix="/api/conditions")


async def _spec_body(request: Request) -> tuple[Any, dict[str, Any]]:
    try:
        body = await request.json()
    except ValueError:
        raise ApiError(400, "VALIDATION_ERROR", "JSON 본문이 아님") from None
    if not isinstance(body, dict) or "spec" not in body:
        raise ApiError(400, "VALIDATION_ERROR", "본문은 {\"spec\": ...} 형식이어야 함", {"fieldErrors": {"spec": "필수"}})
    return body["spec"], body


@router.post("/validate")
async def validate(request: Request, svc: Services = Depends(get_services)) -> dict[str, Any]:
    try:  # 수식 검사: {"formula": "..."} — 문법 오류도 200 본문(error: line·col·expected)으로 준다(스펙 검증과 같은 규칙)
        body = await request.json()
    except ValueError:
        body = None  # 아래 _spec_body 가 "JSON 본문이 아님" 을 낸다
    if isinstance(body, dict) and "formula" in body and "spec" not in body:
        return {"data": formula_service.check(body["formula"])}
    raw, _ = await _spec_body(request)
    return {"data": condition_service.validate_spec(raw, svc.market_data())}


@router.post("/preview")
async def preview(request: Request, svc: Services = Depends(get_services)) -> dict[str, Any]:
    raw, body = await _spec_body(request)
    limit = body.get("limit", 50)
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ApiError(400, "VALIDATION_ERROR", "limit 는 1~500", {"fieldErrors": {"limit": "1~500"}})
    try:
        spec = Spec.model_validate(raw)
    except ValidationError as exc:
        raise ApiError(400, "VALIDATION_ERROR", "명세 형식이 올바르지 않음",
                       {"fieldErrors": {e["path"] or "_": e["message"] for e in condition_service.field_errors(exc, raw)}}) from None
    from starlette.concurrency import run_in_threadpool  # 무거운 계산은 스레드풀 — 이벤트 루프(하트비트)를 막지 않는다
    try:
        return {"data": await run_in_threadpool(screener_service.preview, spec, svc.market_data(), svc.legacy, limit)}
    except (BacktestError, ValueError) as exc:  # ModeNotSupportedError 는 BacktestError 의 하위
        raise ApiError(422, "SPEC_INVALID", str(exc)) from None
