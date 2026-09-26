"""프리셋 API (설계서 §4.1): GET/PUT/DELETE `/api/presets`·`/api/presets/{name}`.

이름은 `^[\\w가-힣\\- ]{1,40}$`(§7). 저장할 때 명세를 검증하고 정규화(기본값 채움)해서 쓴다. 삭제는 그 파일 하나 —
기본 프리셋은 저장소에 커밋돼 있어 git 으로 되살릴 수 있다.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from studio.application import condition_service
from studio.application.services import PresetNotFound, Services
from studio.domain.spec import Spec

from ..deps import get_services
from ..errors import ApiError, not_found

router = APIRouter(prefix="/api/presets")
_NAME = re.compile(r"^[\w가-힣\- ]{1,40}$")


def _name(name: str, *, missing_is_400: bool = False) -> str:
    if not _NAME.fullmatch(name):
        if missing_is_400:
            raise ApiError(400, "VALIDATION_ERROR", "프리셋 이름 형식 오류", {"fieldErrors": {"name": "한글·영문·숫자·_·-·공백 1~40자"}})
        raise not_found()
    return name


@router.get("")
def list_presets(svc: Services = Depends(get_services)) -> dict[str, Any]:
    return {"data": svc.presets.list()}


@router.get("/{name}")
def get_preset(name: str, svc: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        raw = svc.presets.get(_name(name))
    except PresetNotFound:
        raise not_found() from None
    try:  # 프리셋 파일은 기본값을 생략해도 된다(손으로 쓴 것) — 화면에는 기본값이 채워진 완전한 명세를 준다
        spec: dict[str, Any] = Spec.model_validate(raw).model_dump(mode="json")
    except ValidationError:
        spec = raw  # 깨진 프리셋은 원문 그대로 — 화면의 [검증]이 오류를 보여준다
    return {"data": {"name": name, "spec": spec}}


@router.put("/{name}")
async def put_preset(name: str, request: Request, svc: Services = Depends(get_services)) -> dict[str, Any]:
    _name(name, missing_is_400=True)
    try:
        body = await request.json()
    except ValueError:
        raise ApiError(400, "VALIDATION_ERROR", "JSON 본문이 아님") from None
    try:
        spec = Spec.model_validate(body)
    except ValidationError as exc:
        raise ApiError(400, "VALIDATION_ERROR", "명세 형식이 올바르지 않음",
                       {"fieldErrors": {e["path"] or "_": e["message"] for e in condition_service.field_errors(exc, body)}}) from None
    svc.presets.put(name, spec.model_dump(mode="json"))
    return {"data": {"name": name, "title": spec.name, "mode": spec.mode}}


@router.delete("/{name}")
def delete_preset(name: str, svc: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        svc.presets.delete(_name(name))
    except PresetNotFound:
        raise not_found() from None
    return {"data": {"name": name, "deleted": True}}
