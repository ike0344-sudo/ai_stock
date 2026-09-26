from __future__ import annotations

from fastapi import Request

from jobrunner.dispatcher import Dispatcher
from jobrunner.store import JobStore
from studio.application.services import Services

from .errors import ApiError


def get_store(request: Request) -> JobStore:
    return request.app.state.store


def get_dispatcher(request: Request) -> Dispatcher | None:
    return request.app.state.dispatcher


def get_services(request: Request) -> Services:
    svc = getattr(request.app.state, "services", None)
    if svc is None:
        raise ApiError(503, "SERVICES_UNAVAILABLE", "이 서버에는 실행 기록·조건 서비스가 연결되지 않았다")
    return svc
