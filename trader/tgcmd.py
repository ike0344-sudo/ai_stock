"""텔레그램으로 데스크에 말로 지시한다(10-22 사용자) — "HT로보틱스 예약 취소해", "오늘 매수 멈춰".

안전판: **매도·청산은 없다.** 조회와 되돌릴 수 있는 명령(예약 취소 · 자동 매수 끄기/켜기 · 오늘 새 매수 멈춤/다시)만.
- 봇은 **데스크 전용**(.env TRADER_TG_BOT_TOKEN). 소피증권 봇(sophie_bot.py)이 TELEGRAM_BOT_TOKEN 으로 getUpdates 를
  돌고 있어 같은 봇을 쓰면 메시지를 서로 뺏는다.
- .env TELEGRAM_CHAT_ID 와 정확히 같은 발신자만 처리, 그 외엔 답하지 않는다.
- 말은 Jev 가 '무슨 명령인지'만 고른다. 종목은 이름·코드를 글자로 맞춘다(지어내지 않게). /명령 은 Jev 없이 바로.
- 바꾸는 명령은 [실행] 버튼을 눌러야 실행(2분 지나면 무효). 조회는 바로 답한다.
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from typing import Literal

import requests
from pydantic import BaseModel, Field

from . import desk as desk_mod

API = "https://api.telegram.org"
TTL = 120
_pending: dict = {}                                                    # 확인 대기 id -> (만든 시각, 실행 함수, 설명)

ACTIONS = {                                                            # 이름 -> (한국어, 종목 필요, 바꾸는 명령)
    "status": ("상태 보기", False, False),
    "plans": ("예약 목록", False, False),
    "cancel_plan": ("예약 취소", True, True),
    "auto_off": ("자동 매수 끄기", True, True),
    "auto_on": ("자동 매수 켜기", True, True),
    "halt_buying": ("오늘 새 매수 멈춤", False, True),
    "resume_buying": ("새 매수 다시", False, True),
}
SLASH = {"상태": "status", "예약": "plans", "취소": "cancel_plan", "자동끔": "auto_off", "자동켬": "auto_on", "멈춤": "halt_buying", "재개": "resume_buying"}
HELP = ("말로 보내면 됩니다. 예) 상태 알려줘 · 예약 뭐 걸려 있어? · HT로보틱스 예약 취소해 · 에스엠벡셀 자동매수 꺼 · "
        "오늘 매수 멈춰 · 다시 사도 돼\n바로 쓰는 명령: " + " ".join("/" + k for k in SLASH) + "\n(매도·청산은 데스크 화면에서만)")


class Cmd(BaseModel):
    action: Literal["status", "plans", "cancel_plan", "auto_off", "auto_on", "halt_buying", "resume_buying", "unknown"] = Field(
        description="Which command does this Korean chat message to a stock trading desk ask for? "
                    "status = show holdings/P&L/state; plans = list pending limit-buy reservations; cancel_plan = cancel the buy reservation of a stock; "
                    "auto_off = stop automatic buying for a stock; auto_on = re-enable automatic buying for a stock; "
                    "halt_buying = stop all new buying today; resume_buying = allow new buying again; "
                    "unknown = anything else, unclear, or a request to sell.")


def _names(D) -> dict:
    """데스크가 아는 종목 이름 -> 코드(고른 종목·예약·보유)."""
    codes = set(D.watch) | {p["code"] for p in D.plans} | {h["code"] for h in D.holdings}
    return {D.name(c): c for c in codes if D.name(c)}


def find_code(D, text: str) -> str | None:
    m = re.search(r"\b(\d{6})\b", text)
    if m:
        return m.group(1)
    t = text.replace(" ", "")
    hits = [(n, c) for n, c in _names(D).items() if n.replace(" ", "") in t]
    return max(hits, key=lambda x: len(x[0]))[1] if hits else None   # 긴 이름 먼저(삼성전자 vs 삼성전자우)


def classify(text: str) -> str:
    t = text.strip()
    if t.startswith("/"):
        return SLASH.get(t[1:].split()[0] if t[1:] else "", "unknown")
    import jev
    return jev.decide(t, Cmd).action


def _status(D) -> str:
    h = D.holdings
    lines = [f"보유 {len(h)}종목" + (" · " + " · ".join(f"{x['name']} {x['quantity']:,}주 {x.get('pl_pct') or 0:+.1f}%" for x in h) if h else "")]
    lines.append(f"걸린 예약 {sum(bool(p['active']) for p in D.plans)}건 · 미체결 {len(D.pending)}건")
    lines.append(f"오늘 실현손익 {int(D.day.get('pnl_realized', 0)):+,}원")
    if D.day.get("halted"):
        lines.append(f"새 매수 멈춤: {D.day['halted']}")
    return "\n".join(lines)


def _plans(D) -> str:
    act = [p for p in D.plans if p["active"]]
    if not act:
        return "걸린 예약이 없습니다"
    return "\n".join(f"{p['name']} · {', '.join(f'{s['price']:,}' for s in p['stages'])}원 · {p['status']}" for p in act)


def _halt(D, msg) -> None:
    D.day["halted"] = msg
    desk_mod._write("day.json", D.day)


def _do(D, action: str, code: str | None):
    """(실행 함수, 설명) — 확인 버튼을 누르면 부른다. 실행할 게 없으면 함수 자리에 None."""
    nm = D.name(code) if code else ""
    if action == "cancel_plan":
        ids = [p["id"] for p in D.plans if p["active"] and p["code"] == code]
        if not ids:
            return None, f"{nm}에 걸린 예약이 없습니다"
        return (lambda: f"{nm} 예약 {sum(bool(D.cancel_plan(i).get('ok')) for i in ids)}건 취소했습니다"), f"{nm} 걸린 예약 {len(ids)}건 취소"
    if action == "auto_off":
        return (lambda: f"{nm} 자동 매수 끔 — 규칙 예약 {D.set_auto(code, False)}건 같이 취소"), f"{nm} 자동 매수 끄기(규칙 예약도 취소)"
    if action == "auto_on":
        return (lambda: (D.set_auto(code, True), f"{nm} 자동 매수 다시 켬")[1]), f"{nm} 자동 매수 켜기"
    if action == "halt_buying":
        return (lambda: (_halt(D, "텔레그램으로 오늘 새 매수를 멈췄습니다"), "오늘 새 매수를 멈췄습니다(보유는 그대로)")[1]), "오늘 새 매수 멈춤(파는 건 안 함)"
    if action == "resume_buying":
        return (lambda: (_halt(D, None), "새 매수를 다시 켰습니다")[1]), "새 매수 다시 켜기"
    return None, "모르는 명령"


def handle(D, text: str) -> tuple[str, str | None]:
    """메시지 하나 → (답장, 확인 id 또는 None)."""
    try:
        action = classify(text)
    except Exception as e:                                             # noqa: BLE001 — Jev 가 안 되면 /명령 으로
        return f"말 해석 실패({type(e).__name__}) — /명령 으로 보내 주세요\n{HELP}", None
    if action not in ACTIONS:
        return f"무슨 명령인지 모르겠습니다.\n{HELP}", None
    label, need_code, change = ACTIONS[action]
    code = find_code(D, text) if need_code else None
    if need_code and not code:
        return f"'{label}' — 어느 종목인지 못 찾았습니다. 데스크에 있는 종목 이름이나 6자리 코드를 같이 보내 주세요", None
    if not change:
        return (_status(D) if action == "status" else _plans(D)), None
    fn, desc = _do(D, action, code)
    if not fn:
        return desc, None
    cid = uuid.uuid4().hex[:10]
    _pending[cid] = (time.time(), fn, desc)
    return f"이렇게 할까요?\n▶ {desc}\n(2분 안에 [실행]을 눌러야 합니다)", cid


def confirm(D, cid: str, ok: bool) -> str:
    item = _pending.pop(cid, None)
    if not item:
        return "이미 처리했거나 없는 요청입니다"
    t, fn, desc = item
    if not ok:
        return f"안 했습니다 — {desc}"
    if time.time() - t > TTL:
        return f"2분이 지나 무효입니다 — 다시 보내 주세요 ({desc})"
    msg = fn()
    D.note(f"텔레그램 명령 · {desc} → {msg}")
    return msg


def start(D) -> None:
    tok, chat = os.environ.get("TRADER_TG_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not (tok and chat):
        return                                                         # 데스크 전용 봇이 없으면 끈다

    def send(text, cid=None, edit=None):
        kb = {"inline_keyboard": [[{"text": "실행", "callback_data": f"ok:{cid}"}, {"text": "취소", "callback_data": f"no:{cid}"}]]} if cid else None
        body = {"chat_id": chat, "text": text, **({"reply_markup": kb} if kb else {})}
        if edit:
            requests.post(f"{API}/bot{tok}/editMessageText", json={**body, "message_id": edit}, timeout=10)
        else:
            requests.post(f"{API}/bot{tok}/sendMessage", json=body, timeout=10)

    def loop():
        off = None
        while True:
            try:
                r = requests.get(f"{API}/bot{tok}/getUpdates", params={"timeout": 25, **({"offset": off} if off else {})}, timeout=35).json()
                for u in r.get("result", []):
                    off = u["update_id"] + 1
                    if "callback_query" in u:
                        cq = u["callback_query"]
                        if str(cq["from"]["id"]) != chat:
                            continue
                        requests.post(f"{API}/bot{tok}/answerCallbackQuery", json={"callback_query_id": cq["id"]}, timeout=10)
                        kind, cid = (cq.get("data") or ":").split(":", 1)
                        send(confirm(D, cid, kind == "ok"), edit=cq["message"]["message_id"])
                        continue
                    m = u.get("message") or {}
                    if str(m.get("chat", {}).get("id")) != chat or not m.get("text"):
                        continue                                       # 남이 보낸 건 답도 안 한다
                    reply, cid = handle(D, m["text"])
                    send(reply, cid)
            except Exception:                                          # noqa: BLE001 — 네트워크 끊김 등: 잠깐 쉬고 다시
                time.sleep(5)
    threading.Thread(target=loop, daemon=True, name="trader-tgcmd").start()
