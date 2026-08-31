"""**1회용 진단 도구, 2026-08-31.** 실시간체결(0B) 푸시의 "values" 딕셔너리에
FID 27(매도최우선호가)/28(매수최우선호가)이 실제로 오는지 실측한다.

realtime_feed.py의 parse_tick은 이미 field 28(bid)만 뽑고 있었지만 27(ask)은 코드가
아예 안 건드리고 있었다 — 둘 다 실제로 오는지, 오면 몇 초 안에 채워지는지 눈으로
확인하는 게 이 스크립트의 유일한 목적이다. websocket_collision_probe.py와 같은
LOGIN->REG(0B)->PING echo 프로토콜을 그대로 재사용한다(같은 파일 docstring 근거).

측정만 하고 저장 동작은 바꾸지 않는다 — 저장에 반영하는 건 이 실측 결과를 보고
lead 승인 후 별도로 한다(agent_queue/data-agent.md 조건과 동일)."""
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
WS_URL = "wss://api.kiwoom.com:10000/api/dostk/websocket"
LOG_PATH = "state/websocket_probe/field_probe_log.jsonl"
CODES = ["005930_AL", "000660_AL", "247540_AL"]  # 삼성전자·SK하이닉스(유동성) + 에코프로비엠(변동성 큰 종목 하나 섞음)
DURATION_SECONDS = 90.0


def _now():
    return datetime.now(SEOUL)


def _append_jsonl(record: dict) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class FieldProbe:
    def __init__(self, token: str):
        self.token = token
        self.ws: websocket.WebSocketApp | None = None
        self.closed_event = threading.Event()
        self.seen_27 = 0
        self.seen_28 = 0
        self.total_ticks = 0
        self.sample_keys: set[str] = set()

    def _on_open(self, ws):
        ws.send(json.dumps({"trnm": "LOGIN", "token": self.token}))

    def _on_message(self, ws, message):
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            return
        trnm = msg.get("trnm")
        if trnm == "PING":
            ws.send(message)
            return
        if trnm == "LOGIN":
            print("login_response", msg.get("return_code"), msg.get("return_msg"), flush=True)
            if msg.get("return_code") != 0:
                ws.close()
                return
            ws.send(json.dumps({
                "trnm": "REG", "grp_no": "1", "refresh": "1",
                "data": [{"item": CODES, "type": ["0B"]}],
            }))
            return
        if trnm == "REG":
            print("reg_response", msg.get("return_code"), msg.get("return_msg"), flush=True)
            return

        for entry in msg.get("data", []):
            values = entry.get("values")
            if not values:
                continue
            self.total_ticks += 1
            self.sample_keys |= set(values.keys())
            has_27 = "27" in values and values["27"] not in ("", None)
            has_28 = "28" in values and values["28"] not in ("", None)
            self.seen_27 += int(has_27)
            self.seen_28 += int(has_28)
            record = {
                "t": _now().strftime("%H:%M:%S"), "item": entry.get("item"),
                "10": values.get("10"), "27": values.get("27"), "28": values.get("28"),
            }
            print(json.dumps(record, ensure_ascii=False), flush=True)
            _append_jsonl(record)

    def _on_close(self, ws, status_code, close_msg):
        print("close", status_code, close_msg, flush=True)
        self.closed_event.set()

    def _on_error(self, ws, error):
        print("error", str(error), flush=True)

    def run(self, duration_seconds: float) -> None:
        self.ws = websocket.WebSocketApp(
            WS_URL, on_open=self._on_open, on_message=self._on_message,
            on_error=self._on_error, on_close=self._on_close,
        )
        thread = threading.Thread(
            target=lambda: self.ws.run_forever(ping_interval=20.0, ping_timeout=10.0), daemon=True,
        )
        thread.start()
        deadline = _now() + timedelta(seconds=duration_seconds)
        while not self.closed_event.is_set() and _now() < deadline:
            time.sleep(1.0)
        self.ws.close()
        self.closed_event.wait(timeout=5.0)


def main() -> None:
    if sys.stdout.encoding is not None and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv()
    appkey = os.environ.get("KIWOOM_APPKEY", "")
    secretkey = os.environ.get("KIWOOM_SECRETKEY", "")
    if not appkey or not secretkey:
        print("KIWOOM_APPKEY/KIWOOM_SECRETKEY가 .env에 없습니다.")
        return

    client = KiwoomClient(appkey, secretkey, is_mock=False)
    token = client.issue_token()

    probe = FieldProbe(token)
    print(f"필드 실측 시작 — {CODES}, {DURATION_SECONDS}초", flush=True)
    probe.run(DURATION_SECONDS)
    print(
        f"결과: 총 {probe.total_ticks}틱, 27(매도호가) 존재 {probe.seen_27}건, "
        f"28(매수호가) 존재 {probe.seen_28}건, 관측된 전체 필드 키: {sorted(probe.sample_keys)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
