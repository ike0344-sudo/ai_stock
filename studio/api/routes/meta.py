"""GET /api/meta/status — 상단 상태 바 + 워치독 생존 확인 대상 (설계서 §4.1, §11.4).

가볍게 유지한다: 워치독이 5분마다 이 주소를 두드려 서버가 살아 있는지 본다.
지금은 실행 중 작업 수만 — 허브 요약(일봉 기준일·알림 수)은 허브 API 가 붙은 뒤 여기에 더해진다.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from studio import ENGINE_VERSION

router = APIRouter(prefix="/api/meta")


def _scan(store) -> dict[str, int]:
    counts = {"scheduled": 0, "queued": 0, "running": 0}
    for job in store.list_active():
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    return counts


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    """워치독이 5초 프로브 한 번 실패로 서버를 재기동하므로 **이벤트 루프에서 바로** 답한다 — 스레드풀 대기·디스크 조회 없음.
    작업 수는 dispatcher 가 tick 마다(2초) 세어 둔 값. dispatcher 가 없거나 아직 tick 전이면 스레드풀에서 직접 센다.
    (허브 API 의 무거운 pandas 계산이 GIL 을 오래 쥐면 이 응답도 늦어진다 — 실측은 hub_wiring 보고서.)"""
    disp = request.app.state.dispatcher
    counts = disp.last_counts if disp is not None else None
    if counts is None:
        counts = await run_in_threadpool(_scan, request.app.state.store)
    return {"data": {"engine_version": ENGINE_VERSION, "server_time": dt.datetime.now().isoformat(timespec="seconds"),
                     "jobs": dict(counts)}}
