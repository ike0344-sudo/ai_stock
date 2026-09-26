"""데이터 허브 핵심 — 공유 데이터의 카탈로그·달력·쓰기 관문·장부·잠금·보관소.

    from datahub import write, catalog
    with write("daily_minute", writer="my_script"): ...

FastAPI·studio 를 import 하지 않는다(설계 §9.3).
"""
from . import catalog
from .gate import write
from .locks import wait_quiet

__all__ = ["write", "catalog", "wait_quiet"]
