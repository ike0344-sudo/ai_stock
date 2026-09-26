"""`python -m studio` — 백테스트 스튜디오 서버 (설계서 §2.1, §7, §10.3).

127.0.0.1 **고정**(코드에 박아 둠 — 환경변수로도 못 바꾼다). 포트만 STUDIO_PORT(기본 8780).
dispatcher 스레드(예약·대기열·한도)와 허브 일정 스레드(datahub.scheduler)를 같이 띄운다. 워치독이 이 서버를 상시 가동한다(등록은 안정화 뒤 따로).
"""
from __future__ import annotations

import logging
import os
import sys

import uvicorn

from datahub import scheduler
from jobrunner.dispatcher import Dispatcher
from jobrunner.store import JobStore, default_root

from .api.app import create_app
from .infrastructure.services_factory import default_services

HOST = "127.0.0.1"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        port = int(os.environ.get("STUDIO_PORT", "8780"))
        compute = int(os.environ.get("STUDIO_MAX_COMPUTE_JOBS", "2"))
    except ValueError:
        print("STUDIO_PORT·STUDIO_MAX_COMPUTE_JOBS 는 숫자여야 한다", file=sys.stderr)
        return 2
    root = default_root()
    store = JobStore(root)
    dispatcher = Dispatcher(store, limits={"compute": compute})
    dispatcher.start()
    # 허브 일정(야간 체결 수집·아침 일봉 따라잡기·보관 병합·신선도 알림). 끄려면 STUDIO_NO_SCHEDULER=1 (재기동 필요)
    sched = None if os.environ.get("STUDIO_NO_SCHEDULER") == "1" else scheduler.start(root, store)
    try:
        uvicorn.run(create_app(root, dispatcher=dispatcher, services=default_services(), heartbeat_path=root / "state" / "studio" / "heartbeat.json"),
                    host=HOST, port=port, log_level="info")
    finally:
        if sched is not None:
            sched.stop()
        dispatcher.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
