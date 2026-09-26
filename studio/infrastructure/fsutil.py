"""파일 조작의 Windows 공유 위반 재시도 — 다른 스레드·프로세스가 열어 두었거나 교체 중인 파일에 대한 open·replace 는
`PermissionError` 로 실패한다(FastAPI 동기 라우트는 스레드풀이라 같은 파일을 동시에 만질 수 있다). 짧게 재시도하고, 끝내 안 되면 그 예외를 던진다."""
from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def retry_perm(fn: Callable[..., T], *args: Any, tries: int = 100, delay: float = 0.02) -> T:
    for i in range(tries):
        try:
            return fn(*args)
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
