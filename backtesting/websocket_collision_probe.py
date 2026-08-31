"""**2026-08-31 08:20~08:50 세션충돌 테스트 전용, 1회용 진단 도구.** 소피증권
(kospi-theme-engine)과 **같은 appkey**로 두 번째 키움 WebSocket 연결을 열어, 같은
계정으로 연결이 2개 공존하는지/나중 것이 먼저 것을 끊는지 확인한다.

절차 문서: docs/WEBSOCKET_SESSION_TEST_20260831.md 를 같이 본다.

**안전장치가 핵심이다** — 09:00 장 시작 때 이 연결이 남아있으면 안 된다:
    1. --hard-stop-hhmm(기본 "0850") — 지정 시각이 되면 무엇을 하고 있든 즉시 종료.
       --minutes 를 얼마나 크게 줘도 이 시각을 못 넘는다.
    2. Ctrl+C 로 언제든 즉시 종료(정상 종료 경로와 동일하게 close 로그를 남긴다).
    3. 실행 중 상태를 state/websocket_probe/heartbeat.json 에 남겨, 이 프로세스가
       죽지 않고 8:50을 넘겨 계속 도는 사고를 밖에서도 확인할 수 있게 한다.

기존 backtesting/realtime_feed.py 의 재연결 로직은 **일부러 재사용하지 않는다** —
이 테스트는 "붙었다 끊기면 그걸 그대로 관찰"하는 게 목적이라, 자동 재연결이 끼면
관찰이 오염된다(끊긴 게 서버 때문인지 내 재연결 때문인지 구분 불가).

프로토콜은 kospi-theme-engine/app/ingest/feed.py 의 실측 기록과 동일:
    LOGIN -> REG(0B) -> PING 은 그대로 echo -> 그 외 메시지는 data 배열이 있으면 푸시.
"""
import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import websocket
from dotenv import load_dotenv

from kiwoom_client import KiwoomClient

SEOUL = ZoneInfo("Asia/Seoul")
WS_URL = "wss://api.kiwoom.com:10000/api/dostk/websocket"  # 실전 — 모의는 이 계정에 앱키가 없다(data-agent 확인)
DEFAULT_LOG_PATH = "state/websocket_probe/probe_log.jsonl"
DEFAULT_HEARTBEAT_PATH = "state/websocket_probe/heartbeat.json"
DEFAULT_CODES = ["005930"]  # 삼성전자 하나면 충분 — 종목 수는 이 테스트의 관심사가 아니다


def _now() -> datetime:
    return datetime.now(SEOUL)


def resolve_hard_stop(hhmm: str, now: datetime | None = None) -> datetime:
    """"0850" 같은 문자열을 오늘(또는 이미 지났으면 내일) 그 시각으로 바꾼다."""
    now = now or _now()
    hh, mm = int(hhmm[:2]), int(hhmm[2:])
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _append_jsonl(path: str, record: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_heartbeat(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time()}, f)


class CollisionProbe:
    """WebSocketApp 콜백에서 로그만 남긴다 — 재연결·백오프 없음(의도적, 위 docstring 참고)."""

    def __init__(self, token: str, codes: list[str], exchange: str, log_path: str):
        self.token = token
        self.codes = codes
        self.suffix = f"_{exchange}" if exchange.upper() != "KRX" else ""
        self.log_path = log_path
        self.ws: websocket.WebSocketApp | None = None
        self.push_count = 0
        self.closed_event = threading.Event()

    def _log(self, event: str, **fields) -> None:
        record = {"t": _now().strftime("%H:%M:%S"), "event": event, **fields}
        print(json.dumps(record, ensure_ascii=False), flush=True)
        _append_jsonl(self.log_path, record)

    def _on_open(self, ws):
        self._log("open")
        ws.send(json.dumps({"trnm": "LOGIN", "token": self.token}))

    def _on_message(self, ws, message):
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            self._log("unparseable_message", raw=message[:200])
            return
        trnm = msg.get("trnm")

        if trnm == "PING":
            ws.send(message)  # 그대로 echo — feed.py와 동일 근거
            return

        if trnm == "LOGIN":
            self._log("login_response", return_code=msg.get("return_code"), return_msg=msg.get("return_msg"))
            if msg.get("return_code") != 0:
                ws.close()
                return
            ws.send(json.dumps({
                "trnm": "REG", "grp_no": "1", "refresh": "1",
                "data": [{"item": [c + self.suffix for c in self.codes], "type": ["0B"]}],
            }))
            return

        if trnm == "REG":
            self._log("reg_response", return_code=msg.get("return_code"), return_msg=msg.get("return_msg"))
            return

        # PING/LOGIN/REG가 아닌데 data가 있으면 0B 푸시로 본다(feed.py와 같은 판단 기준).
        data = msg.get("data")
        if data:
            self.push_count += 1
            self._log("push", trnm=trnm, item=[e.get("item") for e in data], n=len(data))
        else:
            self._log("other_message", trnm=trnm, raw=msg)

    def _on_error(self, ws, error):
        self._log("error", detail=str(error))

    def _on_close(self, ws, status_code, close_msg):
        self._log("close", status_code=status_code, close_msg=close_msg, push_count=self.push_count)
        self.closed_event.set()

    def run_until(self, hard_stop_at: datetime, heartbeat_path: str) -> None:
        self.ws = websocket.WebSocketApp(
            WS_URL,
            on_open=self._on_open, on_message=self._on_message,
            on_error=self._on_error, on_close=self._on_close,
        )
        thread = threading.Thread(
            target=lambda: self.ws.run_forever(ping_interval=20.0, ping_timeout=10.0),
            daemon=True,
        )
        thread.start()
        try:
            while not self.closed_event.is_set() and _now() < hard_stop_at:
                _write_heartbeat(heartbeat_path)
                time.sleep(2.0)
        except KeyboardInterrupt:
            self._log("keyboard_interrupt")
        finally:
            if _now() >= hard_stop_at:
                self._log("hard_stop_reached", hard_stop_at=hard_stop_at.strftime("%H:%M:%S"))
            self.ws.close()
            self.closed_event.wait(timeout=5.0)
            _write_heartbeat(heartbeat_path)  # 종료 후에도 "이 프로세스가 언제 끝났는지" 마지막 흔적을 남김


def main() -> None:
    # cp949 콘솔에서 em dash(—) 등 한글/특수문자로 죽는 걸 막는다 — cli.py:main()과 같은
    # 이유(2026-08-30 계열 사고, 이 스크립트도 사람이 직접 터미널에서 돌린다).
    if sys.stdout.encoding is not None and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codes", default=",".join(DEFAULT_CODES), help="쉼표로 구분한 종목코드(접미어 없이)")
    parser.add_argument("--exchange", default="AL", help="구독 접미어 기준 — 소피증권과 같은 AL(통합)을 기본값으로 맞춘다")
    parser.add_argument("--minutes", type=float, default=30.0, help="목표 실행 시간(분) — hard-stop-hhmm을 못 넘는다")
    parser.add_argument("--hard-stop-hhmm", default="0850", help="이 시각(KST, HHMM)이 되면 무조건 종료 — 09:00 장 시작 전 필수 안전장치")
    parser.add_argument("--log-path", default=DEFAULT_LOG_PATH)
    parser.add_argument("--heartbeat-path", default=DEFAULT_HEARTBEAT_PATH)
    args = parser.parse_args()

    load_dotenv()
    appkey = os.environ.get("KIWOOM_APPKEY", "")
    secretkey = os.environ.get("KIWOOM_SECRETKEY", "")
    if not appkey or not secretkey:
        print("KIWOOM_APPKEY/KIWOOM_SECRETKEY가 .env에 없습니다 — 소피증권과 같은 appkey가 필요한 테스트라 중단합니다.")
        return

    client = KiwoomClient(appkey, secretkey, is_mock=False)  # 모의는 이 계정에 앱키가 없음(data-agent 확인) — 실전 필수
    token = client.issue_token()

    hard_stop_at = resolve_hard_stop(args.hard_stop_hhmm)
    soft_stop_at = min(_now() + timedelta(minutes=args.minutes), hard_stop_at)
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]

    print(f"세션충돌 테스트 시작 — 종목 {codes}({args.exchange}), "
          f"목표종료 {soft_stop_at:%H:%M:%S}, 하드종료(무조건) {hard_stop_at:%H:%M:%S}. Ctrl+C로 즉시 종료 가능.", flush=True)

    probe = CollisionProbe(token, codes, args.exchange, args.log_path)
    probe.run_until(soft_stop_at, args.heartbeat_path)


if __name__ == "__main__":
    main()
