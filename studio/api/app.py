"""FastAPI 앱 조립 (설계서 §2.1, §4, §6, §7).

    create_app(root=..., dispatcher=..., static_dir=...)

`/api/*` 라우터 → 없는 `/api/*` 는 JSON 404 → `static/studio/`(React 빌드)를 `/` 에 정적 제공.
dispatcher 를 넘기면 취소 직후 즉시 반영(tick)에 쓴다 — `python -m studio` 가 스레드로 돌리는 그 인스턴스.
"""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from datahub.api import router as hub_router
from jobrunner.dispatcher import Dispatcher
from jobrunner.store import JobStore, default_root
from studio.application.services import Services

from . import errors
from .guard import GuardMiddleware
from .heartbeat import INTERVAL_SECONDS, run_heartbeat
from .routes import catalog, conditions, formulas, jobs, meta, presets, runs, templates, validation


def create_app(root: Path | str | None = None, *, dispatcher: Dispatcher | None = None,
               static_dir: Path | str | None = None, services: Services | None = None,
               heartbeat_path: Path | str | None = None,
               heartbeat_interval: float = INTERVAL_SECONDS) -> FastAPI:
    """heartbeat_path 를 주면 lifespan 에서 이벤트 루프 안 asyncio 작업으로 하트비트를 쓴다(주지 않으면 안 씀 — 테스트 기본)."""
    root = Path(root) if root is not None else default_root()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if heartbeat_path is not None:
            task = asyncio.create_task(run_heartbeat(Path(heartbeat_path), heartbeat_interval), name="studio-heartbeat")
            app.state.heartbeat_task = task
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    # 문서 UI(/docs)는 끈다 — 이 서버는 사람 화면(React) 하나만 연다
    app = FastAPI(title="backtest-studio", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store = dispatcher.store if dispatcher else JobStore(root)
    app.state.dispatcher = dispatcher
    app.state.root = root
    app.state.services = services
    errors.install(app)
    app.add_middleware(GuardMiddleware)
    app.include_router(meta.router)
    app.include_router(jobs.router)
    for r in (catalog.router, runs.router, conditions.router, presets.router, validation.router, formulas.router, templates.router):
        app.include_router(r)
    app.include_router(hub_router)  # /api/data/* (datahub/api.py) — 아래 /api/{rest} 404 캐치올보다 앞에

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def _api_not_found(rest: str) -> None:
        raise errors.not_found()

    static = Path(static_dir) if static_dir is not None else root / "static" / "studio"
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app
