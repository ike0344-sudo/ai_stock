"""로그 비밀값 가림 — `.env` 값과 `Bearer` 토큰을 `****` 로 바꾼다 (설계서 §7).

`.env` 는 값이 6자 미만이면 건너뛴다(`true`·`8780` 같은 값까지 가리면 로그가 읽히지 않고, 짧은 값은 비밀이 아니다).
환경변수는 이름에 KEY·SECRET·TOKEN 이 든 것만 더한다 — 앱키가 `.env` 가 아니라 시스템 환경에서 오는 경우.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

MASK = "****"
MIN_SECRET_LEN = 6
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=\-]{8,}")
_SECRET_ENV_NAME = re.compile(r"(?i)KEY|SECRET|TOKEN")


def _dotenv_values(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:  # 값 뒤 인라인 주석
            value = value.split(" #", 1)[0].strip()
        out.append(value)
    return out


class Masker:
    def __init__(self, secrets: list[str] | tuple[str, ...] = ()) -> None:
        # 긴 것부터 — 다른 비밀의 부분 문자열이면 짧은 것이 먼저 지워져 긴 쪽이 조각으로 남는다
        self._secrets = sorted({s for s in secrets if len(s) >= MIN_SECRET_LEN}, key=len, reverse=True)

    @classmethod
    def from_env(cls, root: Path | str | None = None) -> "Masker":
        values: list[str] = []
        if root is not None:
            values += _dotenv_values(Path(root) / ".env")
        values += [v for k, v in os.environ.items() if _SECRET_ENV_NAME.search(k)]
        return cls(values)

    def mask(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, MASK)
        return _BEARER.sub(lambda m: f"{m.group(1)} {MASK}", text)
