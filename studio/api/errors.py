"""오류 봉투 (설계서 §6.2) — 모든 실패는 `{"error": {"code", "message", "details"}}`."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("studio.api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def not_found(what: str = "찾을 수 없음") -> ApiError:
    return ApiError(404, "NOT_FOUND", what)


def envelope(status: int, code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}}, status_code=status)


def field_errors(errors: list[dict[str, Any]]) -> dict[str, str]:
    """pydantic/FastAPI 오류 목록 → {"칸 경로": 메시지}. 화면이 칸을 강조하는 데 쓴다."""
    out: dict[str, str] = {}
    for e in errors:
        loc = ".".join(str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path"))
        out.setdefault(loc or "_", str(e.get("msg", "")))
    return out


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return envelope(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return envelope(400, "VALIDATION_ERROR", "요청 형식이 올바르지 않음",
                        {"fieldErrors": field_errors(exc.errors())})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return envelope(404, "NOT_FOUND", "찾을 수 없음")
        return envelope(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(Exception)
    async def _internal(request: Request, exc: Exception) -> JSONResponse:
        log.exception("처리 못 한 오류: %s %s", request.method, request.url.path)
        return envelope(500, "INTERNAL", "서버 내부 오류 — 서버 로그(studio_server.err.log)를 확인")
