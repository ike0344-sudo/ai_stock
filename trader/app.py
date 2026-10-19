"""매매 데스크 서버 — python -m trader.app (기본 http://127.0.0.1:8790).

주문 API 에 로그인이 없으므로 기본은 이 PC(127.0.0.1)에서만 열린다. 다른 기기(Tailscale)에서 열려면
TRADER_HOST=0.0.0.0 을 직접 넣어야 한다 — 그 망에 있는 누구나 주문을 낼 수 있게 된다는 뜻이다.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

from . import desk as desk_mod
from . import daily_facts, engine, feed

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
os.chdir(ROOT)                                   # 일봉·테마 캐시가 저장소 기준 상대경로
app = FastAPI(title="매매 데스크")
D = desk_mod.Desk()
_chart_cache: dict = {}


def _code(code: str) -> str:
    code = str(code).strip().upper()
    if len(code) != 6 or not code.isalnum():
        raise HTTPException(400, "종목코드는 6자리")
    return code


@app.on_event("startup")
def _start() -> None:
    D.start()


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/state")
def state(code: str = ""):
    held = {h["code"]: h for h in D.holdings}
    pend = {p["code"] for p in D.pending}
    watch = []
    for c in D.watch:
        r, s = D.refs.get(c, {}), D.snap(c)
        watch.append({"code": c, "name": D.name(c), "px": s["px"], "chg": s["chg"], "reg": r.get("reg"), "aft": r.get("aft"),
                      "status": "보유" if c in held else "주문중" if c in pend else "대기"})
    holdings = []
    for h in D.holdings:
        m = D.meta.get(h["code"], {})
        rule = D.rule(m.get("rule"))
        ex = (rule or {}).get("exits", {})
        stop = None
        if ex.get("stop", [False])[0]:
            stop = h["avg_price"] * (1 - abs(engine._num(ex["stop"][1], 0)) / 100)
            if m.get("breakeven") and ex.get("breakeven", [False])[0]:
                stop = max(stop, h["avg_price"])
        takes = [engine.ceil_tick(h["avg_price"] * (1 + engine._num(t[0], 0) / 100)) for t in (ex.get("take", [False, []])[1] or [])] \
            if ex.get("take", [False])[0] else []
        holdings.append({**h, "px": D.snap(h["code"])["px"] or h["current_price"], "rule": m.get("rule"),
                         "rule_name": (rule or {}).get("name"), "stop": engine.floor_tick(stop) if stop else None,
                         "takes": takes, "breakeven": m.get("breakeven", False)})
    out = {"ready": D.ready(), "mock": D.is_mock, "feed": feed.status(), "facts": daily_facts.status(), "now": time.strftime("%H:%M:%S"),
           "account": {"deposit": D.deposit, "equity": D.equity(), "pnl_realized": D.day.get("pnl_realized", 0),
                       "pnl_eval": sum(h["pl_amount"] for h in D.holdings), "day_pnl": D.day_pnl(),
                       "loss_limit": D.rules["safety"].get("max_daily_loss"), "halted": D.buy_block(0)},
           "watch": watch, "holdings": holdings, "pending": D.pending, "msgs": D.msgs[:40],
           "fills": [e for e in list(feed.order_events) if e.get("fill_qty")][-200:],
           "rules": [{"id": r["id"], "name": r["name"], "on": r.get("on")} for r in D.rules["rules"]],
           "manual_rule": D.rules.get("manual_rule")}
    if code:
        c = _code(code)
        D.ref(c)
        out["book"] = feed.books.get(c)
        out["active"] = {"code": c, "name": D.name(c), **D.snap(c)}
    return out


@app.get("/api/chart")
def chart(code: str, tf: str = "5"):
    c = _code(code)
    if err := D.ready():
        raise HTTPException(503, err)
    key, ttl = (c, tf), (300 if tf == "D" else 15)
    hit = _chart_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        if tf == "D":
            rows, tkey = D.client.get_daily_chart(c).get("stk_dt_pole_chart_qry", []), "dt"
        else:
            rows, tkey = D.client.get_minute_chart(c + "_AL", tic_scope=tf).get("stk_min_pole_chart_qry", []), "cntr_tm"
    except Exception as e:                                               # noqa: BLE001
        raise HTTPException(502, f"차트 조회 실패: {e}") from e

    def n(v):
        try:
            return abs(int(str(v).replace("+", "")))
        except (TypeError, ValueError):
            return 0
    bars = [{"t": str(r.get(tkey, "")), "o": n(r.get("open_pric")), "h": n(r.get("high_pric")), "l": n(r.get("low_pric")),
             "c": n(r.get("cur_prc")), "v": n(r.get("trde_qty"))} for r in (rows or [])[:120]]
    bars = [b for b in reversed(bars) if b["c"]]
    _chart_cache[key] = (time.time(), bars)
    return bars


@app.get("/api/search")
def search(q: str):
    q = q.strip()
    if not q:
        return []
    return [{"code": c, "name": n} for c, n in D.names.items() if q in n or c.startswith(q)][:20]


@app.post("/api/watch")
def watch_add(code: str = Body(..., embed=True)):
    c = _code(code)
    if c not in D.watch:
        D.watch.append(c)
        desk_mod._write("watch.json", D.watch)
        feed.set_codes(D.watch + [h["code"] for h in D.holdings])
    return {"ok": True}


@app.delete("/api/watch/{code}")
def watch_del(code: str):
    c = _code(code)
    D.watch = [x for x in D.watch if x != c]
    desk_mod._write("watch.json", D.watch)
    return {"ok": True}


@app.post("/api/order")
def order(code: str = Body(...), side: str = Body(...), qty: int = Body(...), price: int = Body(0), market: bool = Body(False)):
    c = _code(code)
    if qty <= 0 or (not market and price <= 0) or side not in ("buy", "sell"):
        raise HTTPException(400, "수량·가격을 확인해 주세요")
    if not market and price != engine.floor_tick(price):
        raise HTTPException(400, f"호가 단위({engine.tick_size(price)}원)에 맞지 않습니다")
    return D.buy(c, qty, price, market) if side == "buy" else D.sell(c, qty, price, market)


@app.post("/api/ladder")
def ladder(code: str = Body(...), base: str = Body(...), levels: list = Body(...), amount: int = Body(...)):
    if base not in ("reg", "aft"):
        raise HTTPException(400, "기준은 reg / aft")
    return D.ladder(_code(code), base, levels, amount)


@app.post("/api/cancel")
def cancel(ord_no: str = Body(...), code: str = Body(...)):
    return D.cancel(ord_no, _code(code))


@app.post("/api/sell_all")
def sell_all(codes: list[str] = Body(..., embed=True)):
    """체크한 종목 일괄 매도 — 보유 수량 전부."""
    res = [D.exit_all(_code(c), "일괄 매도") for c in codes if any(h["code"] == c for h in D.holdings)]
    return {"ok": all(r["ok"] for r in res), "n": len(res)}


@app.post("/api/liquidate")
def liquidate():
    """전체 청산 — 보유 전부 매도. 새 매수는 오늘 하루 멈춘다."""
    D.day["halted"] = "전체 청산을 눌러 오늘 새 매수를 멈췄습니다"
    desk_mod._write("day.json", D.day)
    res = [D.exit_all(h["code"], "전체 청산") for h in list(D.holdings)]
    return {"ok": all(r["ok"] for r in res), "n": len(res)}


@app.post("/api/resume")
def resume():
    D.day["halted"] = None
    desk_mod._write("day.json", D.day)
    return {"ok": True}


@app.get("/api/rules")
def rules_get():
    return {**D.rules, "problems": {r["id"]: D.rule_problems(r) for r in D.rules["rules"]},
            "supported": sorted(engine.SUPPORTED)}


@app.put("/api/rules")
def rules_put(body: dict = Body(...)):
    rules = {k: body[k] for k in ("rules", "manual_rule", "safety") if k in body}
    if not isinstance(rules.get("rules"), list):
        raise HTTPException(400, "rules 가 없습니다")
    with desk_mod._lock:
        D.rules = {**D.rules, **rules}
        desk_mod._write("rules.json", D.rules)
    D.note("규칙 저장")
    return rules_get()


@app.post("/api/position_rule")
def position_rule(code: str = Body(...), rule: str | None = Body(None)):
    D.set_position_rule(_code(code), rule)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("TRADER_HOST", "127.0.0.1"), port=int(os.environ.get("TRADER_PORT", "8790")), log_level="warning")
