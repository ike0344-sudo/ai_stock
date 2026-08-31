"""내일(2026-08-31) 08:20~08:50 이중 웹소켓 연결 실험용 — 소피증권이 이미 붙어있는
상태에서 **같은 앱키로 두 번째 연결**을 열어 0B(체결)를 구독했을 때:
  (a) 소피증권 쪽 연결이 끊기는지(websocket.log로 관찰 — 이 스크립트 밖에서 확인)
  (b) 이 두 번째 연결 자체가 REG 거부를 당하는지
를 실측한다. 결과 세 갈래: 둘 다 생존(세션 제한 없음) / 소피증권 끊김(제한 있음,
앱키 추가 필요) / 이 연결이 거부됨(제한 있음).

부수 목적: 08:00~08:20 사이(소피증권 단독) NXT 장전시간외(08:00~09:00) 체결이
0B로 실제로 오는지도 이 스크립트로 별도 확인 가능(연결 시각을 앞당기면 됨) —
사용법 참고.

**안전 설계**: 정해진 시간(기본 20분)이 지나면 자동으로 연결을 끊는다 — 09:00
장 시작 때 이 두 번째 연결이 살아남아 소피증권과 계속 경합하는 사고를 막기
위함(사용자 지시: "08:50에 반드시 종료"). 수동으로도 Ctrl+C면 즉시 종료된다.

data/stocks/tick_al 등 공유 데이터에는 전혀 손대지 않는다 — 이 스크립트만의
로그 파일(state/ws_probe/)에만 기록한다. 진행 중인 통합(_AL) 재수집(REST)과는
완전히 별개 통로(WebSocket)라 API 경합도 없다.

사용법:
    python ws_dual_connection_probe.py                  # 기본 20분, 종목 005930,000660
    python ws_dual_connection_probe.py --minutes 30 --codes 005930,000660,035420
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, "C:/Users/ike03/Desktop/code/ai_stock")
os.chdir("C:/Users/ike03/Desktop/code/ai_stock")

from dotenv import load_dotenv
import websocket

from kiwoom_client import KiwoomClient

LOG_DIR = "state/ws_probe"
LOG_PATH = f"{LOG_DIR}/probe_log.txt"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=20.0, help="자동 종료까지 분(기본 20분)")
    parser.add_argument("--codes", type=str, default="005930,000660", help="구독 종목코드 콤마구분(기본 대형주 2개)")
    args = parser.parse_args()
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]

    load_dotenv(".env")
    appkey = os.environ["KIWOOM_APPKEY"]
    secret = os.environ["KIWOOM_SECRETKEY"]
    is_mock = os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true"

    client = KiwoomClient(appkey, secret, is_mock=is_mock)
    log(f"토큰 발급 시도 (is_mock={is_mock}) — 주의: 이 발급 자체가 같은 appkey의 다른 프로세스(소피증권) 토큰을 무효화할 수 있음(기존에 확인된 관례)")
    client.issue_token()
    log("토큰 발급 완료")

    push_count = {c: 0 for c in codes}
    first_push_at: dict[str, str] = {}
    last_push_at: dict[str, str] = {}
    state = {"registered": False, "login_ok": False}

    def on_open(ws):
        log("연결 열림 — LOGIN 전송")
        ws.send(json.dumps({"trnm": "LOGIN", "token": client.token}))

    def on_message(ws, message):
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            log(f"JSON 파싱 실패: {message[:200]}")
            return
        trnm = msg.get("trnm")

        if trnm == "PING":
            ws.send(message)  # 그대로 echo
            return

        if trnm == "LOGIN":
            if msg.get("return_code") != 0:
                state["login_ok"] = False
                log(f"LOGIN 실패: {msg}")
                ws.close()
                return
            state["login_ok"] = True
            log("LOGIN 성공 — REG 전송(0B, 두 번째 연결)")
            ws.send(json.dumps({
                "trnm": "REG", "grp_no": "1", "refresh": "1",
                "data": [{"item": codes, "type": ["0B"]}],
            }))
            return

        if trnm == "REG":
            if msg.get("return_code") == 0:
                state["registered"] = True
                log(f"REG 성공 — 구독 {codes} 시작됨. 이제 push 대기.")
            else:
                state["registered"] = False
                log(f"REG 거부됨: return_code={msg.get('return_code')} msg={msg.get('return_msg','')} "
                    "-> 이 자체가 '두 번째 연결 거부' 시나리오일 수 있음")
            return

        for entry in msg.get("data", []) or []:
            item = str(entry.get("item") or "").split("_")[0]
            values = entry.get("values") or {}
            if item not in push_count:
                push_count[item] = 0
            push_count[item] += 1
            now_str = time.strftime("%H:%M:%S")
            if item not in first_push_at:
                first_push_at[item] = now_str
            last_push_at[item] = now_str
            log(f"PUSH {item} 시각필드(FID20)={values.get('20')} 현재가(FID10)={values.get('10')} "
                f"매도호가(27)={values.get('27')} 매수호가(28)={values.get('28')}")

    def on_error(ws, error):
        log(f"소켓 오류: {type(error).__name__}: {error}")

    def on_close(ws, code, reason):
        log(f"연결 닫힘 code={code} reason={reason}")

    host = "mockapi" if is_mock else "api"
    url = f"wss://{host}.kiwoom.com:10000/api/dostk/websocket"
    log(f"연결 시도: {url}, 구독예정 종목: {codes}, 자동종료까지 {args.minutes}분")

    ws = websocket.WebSocketApp(
        url, on_open=on_open, on_message=on_message,
        on_error=on_error, on_close=on_close,
    )

    import threading
    thread = threading.Thread(target=lambda: ws.run_forever(ping_interval=20, ping_timeout=10), daemon=True)
    thread.start()

    deadline = time.time() + args.minutes * 60
    try:
        while time.time() < deadline:
            time.sleep(5)
    except KeyboardInterrupt:
        log("Ctrl+C로 수동 종료")
    finally:
        log("자동/수동 종료 시각 도달 — 연결을 끊는다")
        try:
            ws.close()
        except Exception:
            pass
        thread.join(timeout=5)

    log("=== 최종 요약 ===")
    log(f"LOGIN 성공: {state['login_ok']}, REG 성공: {state['registered']}")
    for c in codes:
        log(f"  {c}: push {push_count.get(c,0)}건, 첫={first_push_at.get(c)}, 마지막={last_push_at.get(c)}")
    log("종료 완료 — 이 연결은 더 이상 살아있지 않음(다음에 확인할 것)")


if __name__ == "__main__":
    main()
