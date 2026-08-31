"""**2026-08-31 08:00~08:50 세션충돌·NXT프리마켓 테스트 전용 관찰 도구.** 소피증권
(kospi-theme-engine)을 전혀 건드리지 않고 밖에서만 본다 — websocket_collision_probe.py와
달리 이 스크립트는 **KiwoomClient를 import하지 않는다**(monitoring-agent 원칙 준수,
읽기 전용).

절차 문서: docs/WEBSOCKET_SESSION_TEST_20260831.md.

보는 것 세 가지:
    1. dist/logs/websocket.log — 연결/끊김 상태 전이(구독 200종목 (연결됨) / 연결 끊김 등).
       두 번째 연결(websocket_collision_probe.py)이 08:20에 뜰 때 소피증권이 끊기는지
       보는 게 이 테스트의 핵심 관찰 지점이다.
    2. dist/logs/app.log — 30초 주기 "가동 중 · 틱 N" 하트비트. 08:05~08:15에 N이
       늘면 장 시작 전인데 체결(추정: NXT)이 들어온다는 뜻.
    3. /api/market — 어떤 종목이 움직이는지(chg/dchg) 스냅샷 폴링. 틱이 어느 종목에서
       왔는지 대략 짚을 수 있는 유일한 외부 관찰 수단(feed.py가 틱 단위 로그를
       안 남기므로 이것 말고는 종목 단위 추정 방법이 없다).
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")
DEFAULT_APP_LOG = "kospi-theme-engine/dist/logs/app.log"
DEFAULT_WS_LOG = "kospi-theme-engine/dist/logs/websocket.log"
DEFAULT_ENV_PATH = "kospi-theme-engine/.env"
DEFAULT_LOG_PATH = "state/sophie_prelaunch_watch/observations.jsonl"
DEFAULT_MARKET_URL = "http://127.0.0.1:8770/api/market"

_TICK_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s.*가동 중 · 틱 (\d+)")
_STATUS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+.*상태: (.+)$")


def _now() -> datetime:
    return datetime.now(SEOUL)


def _read_sophie_password(env_path: str) -> str:
    path = Path(env_path)
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("SOPHIE_WEB_PASSWORD="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def new_lines_since(path: str, offset: int) -> tuple[list[str], int]:
    """path의 offset 바이트 이후 새로 추가된 줄만 읽는다(매번 전체를 다시 읽지 않기
    위함 — 로그가 수 MB라 매 사이클 전체를 파싱하면 느려진다). 반환: (새 줄들, 새 offset)."""
    if not os.path.exists(path):
        return [], offset
    size = os.path.getsize(path)
    if size < offset:  # 로그가 회전(rotate)돼 작아졌다 — 처음부터 다시 본다
        offset = 0
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read()
    text = chunk.decode("utf-8", errors="replace")
    lines = text.splitlines()
    # 마지막 줄이 개행으로 안 끝났으면(쓰는 도중 읽었을 수 있음) 다음 번에 다시 읽도록 offset을 그만큼 뺀다.
    new_offset = offset + len(chunk)
    if chunk and not chunk.endswith(b"\n"):
        last_len = len(lines[-1].encode("utf-8", errors="replace"))
        new_offset -= last_len
        lines = lines[:-1]
    return lines, new_offset


def poll_market(url: str, auth: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
        return json.loads(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))
    except Exception as exc:
        return {"_error": str(exc)}


def _append_jsonl(path: str, record: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_watch(
    until_hhmm: str = "0850",
    app_log_path: str = DEFAULT_APP_LOG,
    ws_log_path: str = DEFAULT_WS_LOG,
    env_path: str = DEFAULT_ENV_PATH,
    market_url: str = DEFAULT_MARKET_URL,
    out_path: str = DEFAULT_LOG_PATH,
    poll_interval_seconds: float = 5.0,
    market_poll_interval_seconds: float = 15.0,
) -> None:
    now = _now()
    hh, mm = int(until_hhmm[:2]), int(until_hhmm[2:])
    stop_at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if stop_at <= now:
        stop_at += timedelta(days=1)

    pw = _read_sophie_password(env_path)
    auth = base64.b64encode(f"sophie:{pw}".encode()).decode()

    app_offset = os.path.getsize(app_log_path) if os.path.exists(app_log_path) else 0
    ws_offset = os.path.getsize(ws_log_path) if os.path.exists(ws_log_path) else 0
    last_market_poll = 0.0
    last_movers: dict[str, float] = {}

    def emit(event: str, **fields):
        record = {"t": _now().strftime("%H:%M:%S"), "event": event, **fields}
        print(json.dumps(record, ensure_ascii=False), flush=True)
        _append_jsonl(out_path, record)

    emit("watch_start", stop_at=stop_at.strftime("%H:%M:%S"))

    while _now() < stop_at:
        ws_lines, ws_offset = new_lines_since(ws_log_path, ws_offset)
        for line in ws_lines:
            m = _STATUS_RE.search(line)
            if m:
                emit("ws_status", raw=m.group(2))
            elif "오류" in line or "WARNING" in line:
                emit("ws_warning", raw=line[:200])

        app_lines, app_offset = new_lines_since(app_log_path, app_offset)
        for line in app_lines:
            m = _TICK_RE.search(line)
            if m:
                emit("tick_heartbeat", ts=m.group(1), tick=int(m.group(2)))

        if pw and time.time() - last_market_poll >= market_poll_interval_seconds:
            last_market_poll = time.time()
            snap = poll_market(market_url, auth)
            if snap and "_error" not in snap:
                movers = []
                for row in snap.get("marketTop") or []:
                    code = row.get("code")
                    chg = row.get("chg")
                    if code and chg is not None and last_movers.get(code) != chg:
                        movers.append({"code": code, "name": row.get("name"), "chg": chg, "dchg": row.get("dchg")})
                        last_movers[code] = chg
                if movers:
                    emit("market_movers", movers=movers[:10])
            elif snap:
                emit("market_poll_failed", detail=snap.get("_error"))

        time.sleep(poll_interval_seconds)

    emit("watch_end")


def main() -> None:
    if sys.stdout.encoding is not None and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--until-hhmm", default="0850", help="이 시각(KST)까지 관찰(기본 08:50)")
    parser.add_argument("--app-log-path", default=DEFAULT_APP_LOG)
    parser.add_argument("--ws-log-path", default=DEFAULT_WS_LOG)
    parser.add_argument("--env-path", default=DEFAULT_ENV_PATH)
    parser.add_argument("--market-url", default=DEFAULT_MARKET_URL)
    parser.add_argument("--out-path", default=DEFAULT_LOG_PATH)
    args = parser.parse_args()

    print(f"08:00~08:50 사전관찰 시작 — {args.until_hhmm}까지. Ctrl+C로 중단 가능(관찰만 하므로 아무 것도 안 끊김).", flush=True)
    try:
        run_watch(
            until_hhmm=args.until_hhmm, app_log_path=args.app_log_path, ws_log_path=args.ws_log_path,
            env_path=args.env_path, market_url=args.market_url, out_path=args.out_path,
        )
    except KeyboardInterrupt:
        print("중단됨", flush=True)


if __name__ == "__main__":
    main()
