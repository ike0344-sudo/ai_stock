"""사용자 수식 API (설계서 §4): GET/PUT/DELETE `/api/formulas`·`/api/formulas/{name}`.

이름은 `^[가-힣A-Za-z0-9_\\- ]{1,40}$`(§7). 저장은 문법이 맞는 수식만 — 틀리면 422 `FORMULA_INVALID`(details: line·col·expected).
GET 한 건은 저장된 원문과 **지금 컴파일한 AST** 를 함께 준다(화면이 명세에 박아 넣는다). 검사만 하려면 `POST /api/conditions/validate` 에 `{"formula": ...}`.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Request

from studio.application import formula_service
from studio.application.formula_service import FormulaNotFound
from studio.application.services import Services
from studio.domain.conditions.formula import FormulaError

from ..deps import get_services
from ..errors import ApiError, not_found

router = APIRouter(prefix="/api/formulas")
_NAME = re.compile(r"^[가-힣A-Za-z0-9_\- ]{1,40}$")


def _store(svc: Services) -> Any:
    if svc.formulas is None:
        raise ApiError(503, "NOT_CONFIGURED", "수식 저장소가 연결되지 않았습니다")
    return svc.formulas


def _name(name: str, *, missing_is_400: bool = False) -> str:
    if not _NAME.fullmatch(name):
        if missing_is_400:
            raise ApiError(400, "VALIDATION_ERROR", "수식 이름 형식 오류", {"fieldErrors": {"name": "한글·영문·숫자·_·-·공백 1~40자"}})
        raise not_found()
    return name


@router.post("/check")
async def check_formula(request: Request) -> dict[str, Any]:
    """수식만 검사(저장소 불필요) — 본문 `{text, mode?}`. 문법 오류는 422 FORMULA_INVALID(details: line·col·expected), 명세 형식 오류는
    400 VALIDATION_ERROR, 통과하면 `{ok, ast, narration}`. 모드·봉 길이에 맞는 시간 단위 검사는 명세 검증(`/api/conditions/validate`)이 한다."""
    try:
        body = await request.json()
    except ValueError:
        raise ApiError(400, "VALIDATION_ERROR", "JSON 본문이 아님") from None
    if not isinstance(body, dict) or not isinstance(body.get("text"), str):
        raise ApiError(400, "VALIDATION_ERROR", "본문은 {\"text\": 수식} 형식이어야 함", {"fieldErrors": {"text": "필수(문자열)"}})
    unit = "봉" if body.get("mode") in ("intraday", "tick") else "일"
    res = formula_service.check(body["text"], unit)
    if res["error"]:
        raise ApiError(422, "FORMULA_INVALID", res["error"]["message"], res["error"])
    if res["errors"]:
        raise ApiError(400, "VALIDATION_ERROR", "수식은 맞지만 명세 형식에 맞지 않음", {"fieldErrors": {e["path"] or "_": e["message"] for e in res["errors"]}})
    return {"data": {"ok": True, "ast": res["ast"], "narration": res["narration"]}}


@router.get("")
def list_formulas(svc: Services = Depends(get_services)) -> dict[str, Any]:
    return {"data": formula_service.list_all(_store(svc))}


@router.get("/{name}")
def get_formula(name: str, svc: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        return {"data": formula_service.load(_store(svc), _name(name))}
    except FormulaNotFound:
        raise not_found() from None


@router.put("/{name}")
async def put_formula(name: str, request: Request, svc: Services = Depends(get_services)) -> dict[str, Any]:
    _name(name, missing_is_400=True)
    try:
        body = await request.json()
    except ValueError:
        raise ApiError(400, "VALIDATION_ERROR", "JSON 본문이 아님") from None
    if not isinstance(body, dict) or not isinstance(body.get("text"), str):
        raise ApiError(400, "VALIDATION_ERROR", "본문은 {\"text\": 수식, \"description\": 설명} 형식이어야 함", {"fieldErrors": {"text": "필수(문자열)"}})
    desc = body.get("description", "")
    if not isinstance(desc, str) or len(desc) > 500:
        raise ApiError(400, "VALIDATION_ERROR", "설명은 500자 이하 문자열", {"fieldErrors": {"description": "500자 이하"}})
    try:
        rec = formula_service.save(_store(svc), name, body["text"], desc)
    except FormulaError as exc:
        raise ApiError(422, "FORMULA_INVALID", exc.message, exc.to_dict()) from None
    return {"data": rec}


@router.delete("/{name}")
def delete_formula(name: str, svc: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        _store(svc).delete(_name(name))
    except FormulaNotFound:
        raise not_found() from None
    return {"data": {"name": name, "deleted": True}}
