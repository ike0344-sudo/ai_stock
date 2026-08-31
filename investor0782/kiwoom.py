"""키움 REST 최소 클라이언트 — 이 폴더만으로 돌게 하려고 따로 둔다.

소피증권(kospi-theme-engine)의 app/ingest/rest.py 를 임포트하면 그쪽이 죽거나 옮겨질 때
같이 죽는다. 여기서 쓰는 건 TR 하나(ka10051)뿐이라 토큰 발급 + POST 가 전부다.

API 키는 .env 에서만 온다 — 코드에 넣지 않는다.
"""
import os
import threading
import time
from pathlib import Path

import requests

REAL = "https://api.kiwoom.com"
MOCK = "https://mockapi.kiwoom.com"
TIMEOUT = 10
TOKEN_TTL = 3600 * 6          # 문서상 하루지만 넉넉히 앞당겨 재발급한다


def load_env(path: Path | None = None) -> None:
    """python-dotenv 없이 읽는다 — 의존성 하나 줄이자고 열 줄이면 싸다."""
    path = path or Path(__file__).with_name(".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Kiwoom:
    def __init__(self) -> None:
        load_env()
        self.appkey = os.environ.get("KIWOOM_APPKEY", "").strip()
        self.secretkey = os.environ.get("KIWOOM_SECRETKEY", "").strip()
        self.base = MOCK if os.environ.get("KIWOOM_IS_MOCK", "").lower() == "true" else REAL
        self._token: str | None = None
        self._token_at = 0.0
        self._lock = threading.RLock()

    @property
    def ok(self) -> bool:
        return bool(self.appkey and self.secretkey)

    def token(self) -> str:
        with self._lock:
            if self._token and time.time() - self._token_at < TOKEN_TTL:
                return self._token
            res = requests.post(
                f"{self.base}/oauth2/token",
                headers={"Content-Type": "application/json;charset=UTF-8"},
                json={"grant_type": "client_credentials",
                      "appkey": self.appkey, "secretkey": self.secretkey},
                timeout=TIMEOUT)
            res.raise_for_status()
            data = res.json()
            # 응답 필드명이 token / access_token 중 무엇인지 문서로 확정되지 않아 둘 다 본다.
            tok = data.get("token") or data.get("access_token")
            if not tok:
                raise RuntimeError(f"토큰 없음: {data}")
            self._token, self._token_at = tok, time.time()
            return tok

    def tr(self, api_id: str, body: dict, path: str) -> dict:
        res = requests.post(
            f"{self.base}{path}",
            headers={"Content-Type": "application/json;charset=UTF-8",
                     "authorization": f"Bearer {self.token()}",
                     "api-id": api_id},
            json=body, timeout=TIMEOUT)
        res.raise_for_status()
        return res.json()
