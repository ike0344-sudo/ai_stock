"""작업 처리기의 실제 의존 조립 (composition root) — studio.application.jobs 가 이름으로 불러온다."""
from __future__ import annotations

import datetime as dt
import os

from studio.application.jobs import Deps

from .holdout_ledger import FileHoldoutLedger
from .legacy_adapter import LegacyAdapter
from .market_data import LocalMarketData
from .run_store import FileRunStore

BOOTSTRAP = "studio.infrastructure.wiring:default_deps"


class HubCalendar:
    """TradingCalendar 포트 — datahub.calendar(지수 일봉이 있는 날 + 휴장일 표)."""

    def __init__(self) -> None:
        from datahub.calendar import Calendar
        self._cal = Calendar()

    def trading_days(self, start: dt.date, end: dt.date) -> list[dt.date]:
        return self._cal.trading_days(start, end)


def parallel_workers() -> int:
    """그리드 병렬 수 — 소피증권 가동 시간(정규장·접속 구간) cpu//4, 야간·휴장 cpu//2 (datahub.policy 규칙 그대로)."""
    from datahub import policy
    return policy.cpu_workers(policy.window(dt.datetime.now()))


RESERVE_BYTES = 6 * 1024 ** 3  # 다른 프로그램(소피증권·8765·나스닥 감시·Claude 세션들)을 위해 남겨 둘 메모리


def available_bytes() -> int:
    """지금 새로 쓸 수 있는 메모리 — 물리 여유와 **커밋 여유(가상 메모리 한도 − 사용량)** 중 작은 쪽.
    Windows 에선 물리가 남아도 커밋이 바닥나면 다른 프로세스가 할당 실패로 죽는다(2026-09-25 실사고)."""
    import psutil
    avail = psutil.virtual_memory().available
    if os.name == "nt":
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = _MS()
        m.dwLength = ctypes.sizeof(_MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            avail = min(avail, int(m.ullAvailPageFile))
    return int(avail)


def plan_workers(avail_bytes: int, per_worker_bytes: int, reserve_bytes: int = RESERVE_BYTES) -> int:
    """(가용 메모리 − 예비) ÷ 워커당 메모리, 최소 1. 순수 함수 — 테스트가 가짜 값으로 검증한다."""
    return max(1, int((avail_bytes - reserve_bytes) // max(1, per_worker_bytes)))


def workers_for_memory(per_worker_bytes: int) -> int:
    """Deps.memory_limit — 지금 메모리 여유가 허락하는 최대 워커 수. 예비는 STUDIO_MEM_RESERVE_GB 로 조정."""
    gb = os.environ.get("STUDIO_MEM_RESERVE_GB")
    reserve = int(float(gb) * 1024 ** 3) if gb else RESERVE_BYTES
    return plan_workers(available_bytes(), per_worker_bytes, reserve)


def lower_priority() -> None:
    """프로세스 풀 워커의 우선순위를 낮춘다(소피증권 실시간 CPU 보호, 설계서 §2.4.6)."""
    import psutil
    p = psutil.Process(os.getpid())
    p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)


def default_deps() -> Deps:
    return Deps(market_data=LocalMarketData(), run_store=FileRunStore(), legacy=LegacyAdapter(),
                holdout_ledger=FileHoldoutLedger(), calendar=HubCalendar(), parallel_workers=parallel_workers,
                worker_bootstrap=BOOTSTRAP, memory_limit=workers_for_memory)
