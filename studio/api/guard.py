"""요청 방어 미들웨어 (설계서 §7) — 순수 ASGI.

1. Host 가 루프백(127.0.0.1·localhost·[::1])이 아니면 403 — **DNS 리바인딩 방어**. 서버가 127.0.0.1 에만 열려 있어도
   악성 웹페이지가 자기 도메인을 127.0.0.1 로 되돌려 같은 출처처럼 요청할 수 있다. 그때는 Origin == Host 가 참이라
   Origin 검사만으로는 못 막는다(설계서 §7 에 없는 추가 — Host 검사가 그 구멍을 막는다).
2. 상태 변경(POST·PUT·PATCH·DELETE)은 Origin 이 있으면 Host 와 같아야 한다(다르면 403 ORIGIN_FORBIDDEN).
   `Sec-Fetch-Site: cross-site` 도 거부. Origin 이 아예 없으면(curl·서버 간 호출) 통과 — 브라우저는 교차 출처 POST 에
   항상 Origin 을 붙인다. 개발 중 Vite(5173)만 `STUDIO_DEV_ORIGIN` 으로 허용.
3. 본문 256KB 상한 — Content-Length 로 먼저, 스트림(chunked)은 읽으면서 센다. 초과는 413 PAYLOAD_TOO_LARGE.
CORS 헤더는 어디서도 붙이지 않는다.
"""
from __future__ import annotations

import os

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

MAX_BODY_BYTES = 256 * 1024
_LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": {}}}, status_code=status)


def _host_only(host: str) -> str:
    if host.startswith("["):
        return host[: host.find("]") + 1]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class _TooLarge(Exception):
    pass


class GuardMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        if _host_only(host).lower() not in _LOOPBACK:
            await _err(403, "ORIGIN_FORBIDDEN", "허용되지 않은 Host")(scope, receive, send)
            return
        if scope["method"] in _UNSAFE:
            origin = headers.get("origin")
            dev = os.environ.get("STUDIO_DEV_ORIGIN")
            if headers.get("sec-fetch-site") == "cross-site" or (
                origin is not None and origin != f"http://{host}" and origin != dev
            ):
                await _err(403, "ORIGIN_FORBIDDEN", "다른 출처의 요청은 허용되지 않음")(scope, receive, send)
                return
            declared = headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
                await _err(413, "PAYLOAD_TOO_LARGE", "요청 본문이 256KB 를 넘음")(scope, receive, send)
                return

        seen = 0

        async def limited_receive() -> dict:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > MAX_BODY_BYTES:
                    raise _TooLarge()
            return message

        started = False

        async def tracking_send(message: dict) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await _err(413, "PAYLOAD_TOO_LARGE", "요청 본문이 256KB 를 넘음")(scope, receive, send)
