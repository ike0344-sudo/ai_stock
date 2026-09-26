"""서버 생존 하트비트 — 이벤트 루프 안의 asyncio 작업 (2026-09-25 lead 판정).

워치독이 이 파일의 나이(120초)로 8780 의 생존을 판정한다(5초 HTTP 프로브 한 번 실패로 죽이던 것을 대체 — 허브의 무거운
pandas 계산이 GIL 을 몇 초 쥐면 프로브가 실패해 멀쩡한 서버를 죽일 수 있었다).

**반드시 이벤트 루프 안에서 쓴다** — 별도 스레드가 쓰면 루프가 멈춰도(=HTTP 를 못 받아도) 하트비트는 계속 나가서
"먹통인데 살아 있음"이 된다. HTTP 를 실제로 답하는 루프가 돌 때만 갱신돼야 한다. 몇 초짜리 정지는 120초 문턱이 견딘다.

형식은 워치독 `Test-HeartbeatFresh` 가 읽는 그대로: {"updated_at": 유닉스초, "pid": ...}. tmp + 교체.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

log = logging.getLogger("studio.heartbeat")
INTERVAL_SECONDS = 15.0


def write_beat(path: Path) -> bool:
    """한 번 쓴다. 실패(교체 중 공유위반 등)는 이번 박자만 건너뛴다 — 15초 뒤 다시, 문턱(120초)이 8번 여유."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(3)}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"updated_at": time.time(), "pid": os.getpid()}), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)  # 교체가 실패하면 tmp 가 남는다 — 치운다
        log.warning("하트비트 쓰기 실패(다음 박자에 재시도): %s", exc)
        return False


async def run_heartbeat(path: Path, interval: float = INTERVAL_SECONDS) -> None:
    while True:
        write_beat(path)  # 작은 파일 하나 — 루프에서 직접(스레드로 빼면 위 원칙이 깨진다)
        await asyncio.sleep(interval)
