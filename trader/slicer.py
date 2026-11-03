"""Jev 호가 보고 나눠 사기(10-30 사용자 "jev가 호가창 보면서 조금씩 사게 해줘, 시장가로 한방에 위로 사게 하지 말고").

예약 단계가 살 자리에 오면 한 주문으로 다 내지 않고 여기 '일감'으로 넘긴다. 일감마다 몇 초 간격으로:
  10호가(feed.books)를 Jev 에 보여 주고 '매도 몇 호가까지 · 그 잔량의 몇 % · 몇 초 뒤 다시'만 고르게 한다.
  가격 상한(원래 주문 가격)과 남은 수량은 코드가 강제한다 — Jev 가 무엇을 답해도 상한 위로는 안 사고 남은 것보다 많이 안 산다.
  조각 주문은 지정가, 기다린 뒤 안 채워진 몫은 거두고 다음 조각.
Jev 가 2초 안에 답 없음·오류 → 규칙(매도1호가 잔량의 절반, 5초 뒤 다시). 호가가 없거나 10초 넘게 안 바뀜 → 남은 수량을 원래 가격에 한 번에(예전처럼).
10분 안에 다 못 사면 남은 수량을 원래 가격에 걸어 두고 끝 — 예전 방식으로 돌아간다. 조각은 같은 예약 꼬리표라 체결·취소가 예약 단계로 그대로 잡힌다.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from datetime import datetime

from pydantic import BaseModel, Field

from . import engine, feed
from .desk import STATE

LOG = STATE / "slices.jsonl"
MAX_SEC = 600                                                         # 이만큼 안에 다 못 사면 남은 몫을 원래 가격에 걸고 끝
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jev-slice")
_jobs: list[dict] = []
_lock = threading.Lock()
stat = {"jev": 0, "rule": 0, "err": None}


class Slice(BaseModel):
    # Jev 는 0~1 숫자 칸만 받는다(10-30 정수 칸 → UnprocessableEntity) — 코드에서 호가 수·초로 바꾼다
    depth: float = Field(ge=0.0, le=1.0, description="How deep into the ask levels to buy right now: 0 = only the best ask, 1 = up to the third ask level (deeper pushes the price up)")
    fraction: float = Field(ge=0.0, le=1.0, description="Fraction of the shares resting on those ask levels to buy right now")
    patience: float = Field(ge=0.0, le=1.0, description="How long to wait before the next slice: 0 = 2 seconds, 1 = 30 seconds (wait longer when the ask side is thin and the price would jump)")

    @property
    def levels(self) -> int:
        return 1 + round(self.depth * 2)

    @property
    def wait_sec(self) -> int:
        return 2 + round(self.patience * 28)

    @property
    def frac(self) -> float:
        return max(0.05, self.fraction)


def start(D, p: dict, i: int, qty: int, cap: int, tag: str, rule: str | None) -> dict:
    """일감 등록 — 첫 조각은 다음 루프(1초 안). 데스크에는 주문을 낸 것처럼 ok 를 돌려준다."""
    s_ = p["stages"][i]
    with _lock:
        if any(j["pid"] == p["id"] and j["i"] == i for j in _jobs):
            return {"ok": True, "msg": "이미 나눠 사는 중"}
    # 시작 전에 한도·돈부터 — 안 보고 '됨'을 돌려주면 데스크가 그날 그 단계를 끝난 것으로 적어 다시 안 샀다(11-03 점검 안랩)
    need = int(qty * cap)
    avail = int(int((D.deposit or {}).get("order_available_krw") or 0) * max(1.0, D.buy_lev(p["code"])[0]))
    why = D.buy_block(need, p["code"]) or (f"주문가능금액 부족({avail:,}원 < {need:,}원)" if D.deposit and need > avail else None)
    if why:
        if s_.get("why") != why:                                       # 1분마다 다시 해도 알림은 이유가 바뀔 때만
            s_["why"] = why
            D.note(f"매수 막음 · {p['name']} — {why}", "warn")
        return {"ok": False, "msg": why}
    s_.pop("why", None)
    with _lock:
        _jobs.append({"pid": p["id"], "i": i, "code": p["code"], "name": p["name"], "cap": int(cap), "qty": int(qty), "filled0": s_["filled"],
                      "tag": tag, "rule": rule, "t0": time.time(), "next": 0.0, "ord": None, "day": datetime.now().date().isoformat(), "n": 0})   # 데스크가 곧 이 단계 day 를 오늘로 적는다
    D.note(f"{p['name']} {qty:,}주 · 상한 {int(cap):,}원 — Jev 가 호가 보고 나눠 삽니다")
    return {"ok": True, "msg": "나눠 사기 시작"}


def codes() -> set[str]:
    """지금 나눠 사는 중인 종목 — 동시 보유 수에 센다(desk.meta_positions)."""
    with _lock:
        return {j["code"] for j in _jobs}


def _ask_jev(j: dict, book: dict, left: int, px: int) -> tuple[Slice, str]:
    asks = " | ".join(f"{p:,} x {q:,}" for p, q in book["asks"][:5] if p)
    bids = " | ".join(f"{p:,} x {q:,}" for p, q in book["bids"][:5] if p)
    text = (f"You are buying a Korean stock gradually without pushing the price up. Last price {px:,} KRW. "
            f"Hard price cap {j['cap']:,} KRW (never buy above it). Shares still to buy: {left:,}. "
            f"Ask levels (price x shares), best first: {asks}. Bid levels: {bids}. "
            f"Total ask size {book['ask_total']:,}, total bid size {book['bid_total']:,}. Slices done so far: {j['n']}. "
            "Choose how many ask levels to take now, what fraction of the shares on them, and how long to wait before the next slice.")
    try:
        import jev
        r = _pool.submit(jev.decide, text, Slice).result(timeout=2)
        stat["jev"] += 1
        return r, "jev"
    except FutTimeout:
        stat["err"] = "2초 안에 답 없음"
    except Exception as e:                                             # noqa: BLE001 — 키 없음·네트워크 — 규칙으로
        stat["err"] = type(e).__name__
    stat["rule"] += 1
    return Slice(depth=0.0, fraction=0.5, patience=0.1), "rule"


def _step(D, j: dict, now: float) -> bool:
    """일감 한 번 — 끝났으면 True."""
    p = next((x for x in D.plans if x["id"] == j["pid"]), None)
    if not p or j["i"] >= len(p["stages"]):
        return True
    s_ = p["stages"][j["i"]]
    if j["ord"]:                                                        # 지난 조각 — 안 채워진 몫은 거둔다
        if any(o.get("ord_no") == j["ord"] for o in D.pending):
            D.cancel(j["ord"], j["code"])
        j["ord"] = None
    left = j["qty"] - (s_["filled"] - j["filled0"])
    stop = (not p["active"] or p.get("mt_down") or p.get("ma_dead") or s_.get("day") != j["day"]
            or s_.get("t_cxl") == datetime.now().date().isoformat())   # 데스크가 이 단계를 거뒀다(꺾임·60선 아래 마감·시각 끝 등)
    if left <= 0 or stop:
        D.note(f"{j['name']} 나눠 사기 끝 — {'다 삼' if left <= 0 else '예약이 멈춤'} ({j['n']}조각)")
        return True
    book, px = feed.books.get(j["code"]), (feed.quotes.get(j["code"], {}) or {}).get("px") or 0
    if now - j["t0"] > MAX_SEC or not book or now - book.get("t", 0) > 10:
        why = "10분 지남" if now - j["t0"] > MAX_SEC else "호가 없음"
        r = D.buy(j["code"], left, j["cap"], False, j["tag"] + " 나눔끝", rule=j["rule"])
        D.note(f"{j['name']} 나눠 사기 {why} — 남은 {left:,}주를 {j['cap']:,}원에 걸어 둠" + ("" if r["ok"] else f" (실패: {r['msg']})"))
        return True
    asks = [(pr, q) for pr, q in book["asks"] if pr and q and pr <= j["cap"]]
    dec, src = _ask_jev(j, book, left, px)
    if asks:
        take = asks[:dec.levels]
        price = take[-1][0]
        qty = max(1, min(left, int(sum(q for _, q in take) * dec.frac)))
    else:                                                               # 매도1호가가 상한 위 — 상한에 걸어 두고 기다린다(위로 안 쫓아감)
        price, qty = j["cap"], left
    r = D.buy(j["code"], qty, int(price), False, j["tag"] + f" 나눔{j['n'] + 1}", rule=j["rule"])
    j["n"] += 1
    j["ord"] = r.get("ord_no") if r["ok"] else None
    j["next"] = now + (dec.wait_sec if r["ok"] else 30)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "code": j["code"], "plan": j["pid"], "stage": j["i"], "src": src,
                            "levels": dec.levels, "fraction": round(dec.frac, 2), "wait": dec.wait_sec, "price": int(price), "qty": qty, "left": left,
                            "cap": j["cap"], "ask1": book["asks"][0], "ok": r["ok"], "msg": r.get("msg")}, ensure_ascii=False) + "\n")
    return False


def run(D) -> None:
    def loop():
        while True:
            time.sleep(1)
            now = time.time()
            with _lock:
                jobs = [j for j in _jobs if now >= j["next"]]
            for j in jobs:
                try:
                    done = _step(D, j, now)
                except Exception as e:                                  # noqa: BLE001 — 일감 하나가 죽어도 나머지는 돈다
                    D.note(f"나눠 사기 오류 · {j['name']} — {type(e).__name__}: {e}", "error")
                    done = True
                if done:
                    with _lock:
                        _jobs[:] = [x for x in _jobs if x is not j]
    threading.Thread(target=loop, daemon=True, name="slicer").start()


def view() -> dict:
    with _lock:
        return {"jobs": [{k: j[k] for k in ("name", "qty", "cap", "n")} for j in _jobs], **stat}


if __name__ == "__main__":                                            # 강제 확인: 상한·남은 수량 밖으로 못 나간다
    class _D:
        plans = [{"id": "x", "name": "t", "code": "000000", "active": True, "stages": [{"filled": 0, "day": "d"}]}]
        pending: list = []
        sent: list = []

        def buy(self, code, qty, price, market, tag, rule=None):
            self.sent.append((qty, price))
            return {"ok": True, "ord_no": "P1"}

        def cancel(self, *a):
            pass

        def note(self, *a):
            pass

    d = _D()
    feed.books["000000"] = {"asks": [(1010, 100), (1020, 100), (1030, 100)] + [(0, 0)] * 7, "bids": [(1000, 50)] + [(0, 0)] * 9,
                            "ask_total": 300, "bid_total": 50, "t": time.time()}
    _ask_jev = lambda j, b, l, px: (Slice(depth=1.0, fraction=1.0, patience=0.0), "test")   # noqa: E731
    j = {"pid": "x", "i": 0, "code": "000000", "name": "t", "cap": 1020, "qty": 150, "filled0": 0, "tag": "예약:x:0", "rule": None,
         "t0": time.time(), "next": 0, "ord": None, "day": "d", "n": 0}
    _step(d, j, time.time())
    assert d.sent == [(150, 1020)], d.sent                             # 상한 1,020 위(1,030)는 안 사고, 남은 150 보다 많이 안 산다
    print("ok", d.sent)
