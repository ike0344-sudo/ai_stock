"""매매 데스크 실시간 — 체결(0B)·호가(0D)는 고른 종목만, 주문체결(00)은 계좌 전체. 매매 전용 앱키(TRADER_APPKEY)로 따로 연다.

소피증권·대시보드와 앱키를 나눈다: 앱키 하나당 WebSocket 세션이 하나라(kiwoom_client.batch_keys 주석)
같은 키를 쓰면 먼저 연 쪽이 끊기고, 토큰을 새로 받으면 그 키의 다른 프로세스 토큰이 죽는다(공유 앱키 8005, 09-28).
프로토콜(LOGIN → REG → PING 되돌려 보내기, refresh="0" 교체)은 backtesting/board_ticks.py 와 같다.

FID 번호는 키움 REST 실시간 문서 기준이고 **10-19 현재 이 앱으로는 실측 전**이다. 첫 장에서 raw 를 보고 확정할 것.
  0B: 10 현재가 · 12 등락률 · 14 누적거래대금(백만원) · 17 고가 · 20 체결시간 · 228 체결강도
  0D: 41~50 매도호가1~10 · 51~60 매수호가1~10 · 61~70 매도잔량 · 71~80 매수잔량 · 121 매도총잔량 · 125 매수총잔량
  00: 9203 주문번호 · 9001 종목코드 · 905 주문구분(+매수/−매도) · 913 주문상태 · 900 주문수량 · 901 주문가격 · 902 미체결 · 910 체결가 · 911 체결량
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import datetime

# 0B 는 통합(_AL)으로 받아야 NXT 시간대(08:00~09:00, 15:30~20:00)에도 값이 온다(board_ticks 와 같음).
# 0D 호가도 통합이 맞는지는 실측 전 — 정규장에 KRX 와 같은지부터 볼 것.
QUOTE_SUFFIX = "_AL"
BOOK_SUFFIX = "_AL"

quotes: dict[str, dict] = {}
books: dict[str, dict] = {}
order_events: deque = deque(maxlen=2000)
_state = {"codes": (), "connected": False, "err": None, "since": None, "raw_samples": {}}
_lock = threading.Lock()
_thread: threading.Thread | None = None
_ws = None
_on_order = None                      # desk 가 꽂는 콜백(체결 즉시 청산 주문 걸기)


def _int(raw) -> int:
    try:
        return int(str(raw).strip().replace("+", "").replace(",", ""))
    except (TypeError, ValueError):
        return 0


def _float(raw) -> float:
    try:
        return float(str(raw).strip().replace("+", "").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def parse_quote(values: dict) -> dict | None:
    px = abs(_int(values.get("10")))
    if not px:
        return None
    return {"px": px, "chg": _float(values.get("12")), "high": abs(_int(values.get("17"))),
            "value": abs(_int(values.get("14"))) * 1_000_000,
            "strength": abs(_float(values.get("228"))), "t": time.time()}


def parse_book(values: dict) -> dict | None:
    asks = [(abs(_int(values.get(str(41 + i)))), abs(_int(values.get(str(61 + i))))) for i in range(10)]
    bids = [(abs(_int(values.get(str(51 + i)))), abs(_int(values.get(str(71 + i))))) for i in range(10)]
    if not any(p for p, _ in asks + bids):
        return None
    return {"asks": asks, "bids": bids, "ask_total": abs(_int(values.get("121"))),
            "bid_total": abs(_int(values.get("125"))), "t": time.time()}


def parse_order(values: dict) -> dict:
    side_raw = str(values.get("905") or "")
    return {"ord_no": str(values.get("9203") or "").strip(), "code": str(values.get("9001") or "").strip().removeprefix("A")[:6],
            "side": "sell" if "매도" in side_raw or side_raw.startswith("-") else "buy",
            "status": str(values.get("913") or "").strip(), "qty": abs(_int(values.get("900"))),
            "price": abs(_int(values.get("901"))), "left": abs(_int(values.get("902"))),
            "fill_px": abs(_int(values.get("910"))), "fill_qty": abs(_int(values.get("911"))), "t": time.time()}


def _on_message(ws, message: str) -> None:
    try:
        msg = json.loads(message)
    except ValueError:
        return
    trnm = msg.get("trnm")
    if trnm == "PING":
        ws.send(message)
        return
    if trnm == "LOGIN":
        if msg.get("return_code") != 0:
            _state["err"] = f"로그인 실패 {msg.get('return_msg')}"
            ws.close()
            return
        _state["connected"], _state["err"] = True, None
        _reg(ws)
        return
    if trnm == "REG":
        if msg.get("return_code") not in (0, None):
            _state["err"] = f"구독 실패 {msg.get('return_msg')}"
        return
    for entry in msg.get("data", []) or []:
        kind, values = entry.get("type"), entry.get("values")
        if not isinstance(values, dict):
            continue
        _state["raw_samples"].setdefault(kind, values)          # 종류마다 첫 raw 하나 — FID 실측 확인용
        code = str(entry.get("item") or "").split("_")[0].removeprefix("A")
        with _lock:
            if kind == "0B":
                q = parse_quote(values)
                if q:
                    quotes[code] = {**quotes.get(code, {}), **q}
            elif kind == "0D":
                b = parse_book(values)
                if b:
                    books[code] = b
            elif kind == "00":
                ev = parse_order(values)
                order_events.append(ev)
        if kind == "00" and _on_order:
            try:
                _on_order(ev)
            except Exception as e:                               # noqa: BLE001 — 콜백 오류로 수신이 멈추면 안 된다
                _state["err"] = f"주문체결 처리 오류: {e}"


def _reg(ws) -> None:
    ws.send(json.dumps({"trnm": "REG", "grp_no": "9", "refresh": "0", "data": [{"item": [""], "type": ["00"]}]}))
    codes = list(_state["codes"])
    if codes:
        ws.send(json.dumps({"trnm": "REG", "grp_no": "1", "refresh": "0", "data": [
            {"item": [c + QUOTE_SUFFIX for c in codes], "type": ["0B"]},
            {"item": [c + BOOK_SUFFIX for c in codes], "type": ["0D"]}]}))


def set_codes(codes: list[str]) -> None:
    codes = tuple(sorted({c for c in codes if len(c) == 6 and c.isalnum()}))[:90]
    if codes == _state["codes"]:
        return
    _state["codes"] = codes
    if _ws is not None and _state["connected"]:
        try:
            _reg(_ws)
        except Exception:                                        # noqa: BLE001 — 재연결 때 새 목록으로 다시 건다
            pass


def _run(client, is_active) -> None:
    global _ws
    import websocket
    url = f"wss://{'mockapi' if client.is_mock else 'api'}.kiwoom.com:10000/api/dostk/websocket"
    while True:
        if not is_active(datetime.now()):
            _state["connected"] = False
            time.sleep(20)
            continue
        try:
            token = client.issue_token()
            _ws = websocket.WebSocketApp(url, on_open=lambda w: w.send(json.dumps({"trnm": "LOGIN", "token": token})),
                                         on_message=_on_message)
            stop = threading.Event()

            def watchdog(w=_ws):
                while not stop.wait(10):
                    if not is_active(datetime.now()):
                        w.close()
                        return
            threading.Thread(target=watchdog, daemon=True).start()
            _state["since"] = time.time()
            _ws.run_forever(ping_interval=0)
            stop.set()
        except Exception as e:                                    # noqa: BLE001 — 실패는 화면에 알리고 다시
            _state["err"] = f"{type(e).__name__}: {e}"
        _state["connected"] = False
        _ws = None
        time.sleep(5)


def start(client, is_active, on_order) -> None:
    global _thread, _on_order
    _on_order = on_order
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_run, args=(client, is_active), daemon=True, name="trader-feed")
        _thread.start()


def status() -> dict:
    return {"connected": _state["connected"], "err": _state["err"], "codes": len(_state["codes"])}
