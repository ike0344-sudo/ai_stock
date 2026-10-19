"""매매 데스크 서버 — python -m trader.app (이 PC http://127.0.0.1:8790 · Tailscale http://100.126.113.127:8790).

주문 API 에 로그인이 없다. 그래서 모든 주소로 열되(0.0.0.0) 들어온 쪽이 이 PC(127.0.0.1) 또는 Tailscale 망
(100.64.0.0/10) 일 때만 받는다 — 집 와이파이 같은 같은 공유기 망에서는 403(10-19 사용자 "tailscale 에서 다 접속").
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv
import asyncio
import ipaddress
import json
import threading

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from . import desk as desk_mod
from . import daily_facts, engine, feed

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
os.chdir(ROOT)                                   # 일봉·테마 캐시가 저장소 기준 상대경로
app = FastAPI(title="매매 데스크")
D = desk_mod.Desk()
_chart_cache: dict = {}
_ALLOWED = (ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128"), ipaddress.ip_network("100.64.0.0/10"),
            ipaddress.ip_network("fd7a:115c:a1e0::/48"))                  # 이 PC · Tailscale(IPv4 CGNAT · IPv6)


@app.middleware("http")
async def _only_local_or_tailnet(request: Request, call_next):
    try:
        ip = ipaddress.ip_address((request.client.host if request.client else "").split("%")[0])
        ok = any(ip in n for n in _ALLOWED)
    except ValueError:
        ok = False
    if not ok:
        return JSONResponse({"detail": "이 PC 또는 Tailscale 에서만 열 수 있습니다"}, status_code=403)
    return await call_next(request)


def _code(code: str) -> str:
    code = str(code).strip().upper()
    if len(code) != 6 or not code.isalnum():
        raise HTTPException(400, "종목코드는 6자리")
    return code


@app.on_event("startup")
def _start() -> None:
    D.start()
    _warm(D.watch)


def _warm(codes: list[str]) -> None:
    """고른 종목의 기본 차트(5분·하루 전체)를 미리 받아 둔다 — 화면을 열면 바로 그려지게(10-19 "반응속도 최대한 빠르게")."""
    def run():
        for c in list(codes):
            try:
                chart(c, "5", "all")
            except Exception:                                            # noqa: BLE001 — 미리 받기는 실패해도 그만
                pass
    if D.client:
        threading.Thread(target=run, daemon=True, name="trader-warm").start()


@app.get("/api/stream")
async def stream(codes: str = "", active: str = ""):
    """실시간 밀어주기(SSE) — 체결가·호가·주문체결을 들어오는 대로(0.1초마다 모아) 보낸다. 화면은 1초 폴링을 기다리지 않는다."""
    cs = [c for c in codes.split(",") if len(c) == 6 and c.isalnum()][:90]
    act = active if len(active) == 6 and active.isalnum() else ""

    async def gen():
        sent_q: dict = {}
        sent_b = 0.0
        sent_f = time.time()
        idle = 0
        yield "retry: 1000\n\n"
        while True:
            out: dict = {}
            q = {c: feed.quotes[c] for c in cs if c in feed.quotes and feed.quotes[c].get("t") != sent_q.get(c)}
            if q:
                out["q"] = {c: {k: v[k] for k in ("px", "chg", "high", "cum", "t") if k in v} for c, v in q.items()}
                sent_q.update({c: v.get("t") for c, v in q.items()})
            b = feed.books.get(act) if act else None
            if b and b.get("t") != sent_b:
                out["b"], sent_b = {"code": act, "book": b}, b.get("t")
            f = [e for e in list(feed.order_events) if e.get("t", 0) > sent_f and e.get("fill_qty")]
            if f:
                out["f"], sent_f = f, f[-1]["t"]
            if out:
                idle = 0
                yield "data: " + json.dumps(out, ensure_ascii=False) + "\n\n"
            else:
                idle += 1
                if idle >= 150:                                          # 15초마다 살아 있음 표시(프록시가 끊지 않게)
                    idle = 0
                    yield ": ping\n\n"
            await asyncio.sleep(0.1)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
        rd = D.ref_day(c)
        rr = D.ref(c, rd) if rd else None                               # 처음 한 번만 받고 그다음은 저장된 값
        watch.append({"code": c, "name": D.name(c), "px": s["px"], "chg": s["chg"], "reg": r.get("reg"), "aft": r.get("aft"),
                      "nxt": r.get("nxt", True), "ref_day": rd, "ref_src": D.ref_src(c), "ref_reg": (rr or {}).get("reg"), "ref_aft": (rr or {}).get("aft"),
                      "status": "보유" if c in held else "주문중" if c in pend else "대기"})
    holdings = []
    for h in D.holdings:
        m = D.meta.get(h["code"], {})
        rule = D.exit_rule(m.get("rule"))
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
    out = {"ready": D.ready(), "mock": D.is_mock, "key_src": D.key_src, "feed": feed.status(), "facts": daily_facts.status(), "now": time.strftime("%H:%M:%S"),
           "account": {"deposit": D.deposit, "equity": D.equity(), "pnl_realized": D.day.get("pnl_realized", 0),
                       "pnl_eval": sum(h["pl_amount"] for h in D.holdings), "day_pnl": D.day_pnl(),
                       "loss_limit": D.rules["safety"].get("max_daily_loss"), "halted": D.buy_block(0)},
           "watch": watch, "holdings": holdings, "pending": D.pending, "msgs": D.msgs[:40],
           "fills": [e for e in list(feed.order_events) if e.get("fill_qty")][-200:],
           "rules": [{"id": r["id"], "name": r["name"], "on": r.get("on")} for r in D.rules["rules"]],
           "exits": [{"id": r["id"], "name": r["name"]} for r in D.rules.get("exits", [])],
           "plans": [p for p in D.plans if p["active"] or p["created"][:10] >= time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 86400))][-60:],
           "manual_exit": D.rules.get("manual_exit")}
    if code:
        c = _code(code)
        new = c not in D.viewing
        D.viewing[c] = time.time()
        if new:
            feed.set_codes(D.sub_codes())
        D.ref(c)
        out["book"] = feed.books.get(c)
        out["active"] = {"code": c, "name": D.name(c), **D.snap(c)}
        rd = D.ref_day(c)
        rr = D.ref(c, rd) if rd else D.refs.get(c, {})
        out["active"].update(ref_day=rd, ref_src=D.ref_src(c), ref_date=rr.get("day"), ref_reg=rr.get("reg"), ref_aft=rr.get("aft"), nxt=rr.get("nxt", True))
    return out


@app.get("/api/chart")
def chart(code: str, tf: str = "5", sess: str = "all"):
    """봉 + 이동평균 계산용 앞쪽 봉까지(최대 400). 신고대금 장부 차트와 같은 기준(10-16):
    sess=all 하루 전체(통합 _AL 08~20시) · reg 정규장(KRX 09:00~15:30) · after 애프터(통합 분봉 15:30~20:00만, 분봉 전용)."""
    c = _code(code)
    if tf not in ("1", "5", "15", "D") or sess not in ("all", "reg", "after"):
        raise HTTPException(400, "tf=1|5|15|D, sess=all|reg|after")
    if tf == "D" and sess == "after":
        raise HTTPException(400, "애프터는 분봉으로만 볼 수 있습니다")
    if err := D.ready():
        raise HTTPException(503, err)
    key, ttl = (c, tf, sess), (300 if tf == "D" else 30)            # 분봉 마지막 봉은 화면이 실시간 가격으로 고쳐 그린다
    hit = _chart_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    stk = c if sess == "reg" else c + "_AL"
    try:
        if tf == "D":
            rows, tkey = D.client.get_daily_chart(stk).get("stk_dt_pole_chart_qry", []), "dt"
        else:
            pages = D.client.get_minute_chart_pages(stk, tic_scope=tf, max_pages=3 if sess == "after" else 1)
            rows, tkey = [r for p in pages for r in p.get("stk_min_pole_chart_qry", [])], "cntr_tm"
    except Exception as e:                                               # noqa: BLE001
        raise HTTPException(502, f"차트 조회 실패: {e}") from e

    def n(v):
        try:
            return abs(int(str(v).replace("+", "")))
        except (TypeError, ValueError):
            return 0
    bars = [{"t": str(r.get(tkey, "")), "o": n(r.get("open_pric")), "h": n(r.get("high_pric")), "l": n(r.get("low_pric")),
             "c": n(r.get("cur_prc")), "v": n(r.get("trde_qty"))} for r in (rows or [])]
    bars = [b for b in reversed(bars) if b["c"]]                      # 오래된 것 → 최신
    # 신고대금 장부와 같은 경계(value_ledger: between_time 09:00~15:30 양끝 포함) — 애프터는 15:30 뒤 ~ 20:00.
    # 정규장 보기는 정규장 봉만으로 이동평균(장부와 같다). 애프터는 이어진 하루 전체 봉으로 계산한 뒤 애프터 봉만 남긴다 —
    # 애프터만 이어 붙여 계산하면 날 사이 빈 시간을 건너뛰어 선이 엉뚱해진다(10-19 HT로보틱스).
    if tf != "D" and sess == "reg":
        bars = [b for b in bars if "0900" <= b["t"][8:12] <= "1530"]
    closes = [b["c"] for b in bars]
    for per in ((5, 10, 20, 60, 120) if tf == "D" else (60, 120)):
        run = 0.0
        for i, c in enumerate(closes):
            run += c - (closes[i - per] if i >= per else 0)
            if i >= per - 1:
                bars[i][f"m{per}"] = round(run / per, 2)
    if tf != "D" and sess == "after":
        bars = [b for b in bars if "1530" < b["t"][8:12] <= "2000"]
    bars = bars[-400:]
    _chart_cache[key] = (time.time(), bars)
    return bars


@app.get("/api/search")
def search(q: str):
    q = q.strip().upper()                                            # 'ht로보틱스' 도 'HT로보틱스' 로 찾게(10-19)
    if not q:
        return []
    hits = [(c, n) for c, n in D.names.items() if q in n.upper() or c.startswith(q)]
    hits.sort(key=lambda x: (x[1].upper() != q, not x[1].upper().startswith(q), len(x[1])))   # 정확히 같은 이름 → 앞이 같은 이름 → 짧은 이름
    return [{"code": c, "name": n} for c, n in hits[:20]]


@app.post("/api/pick")
def pick(items: list = Body(..., embed=True)):
    """신고대금 장부에서 보낸 종목들 — [{code, day}] 를 관심 종목 + 종목별 기준일(신고일)로 한 번에 넣는다."""
    out = []
    for it in items[:40]:
        c, d = _code(str(it.get("code", ""))), str(it.get("day", "")).replace("-", "").strip() or None
        if d and (len(d) != 8 or not d.isdigit()):
            continue
        D.set_ref_day(c, d)
        D.pick(c, d, "신고대금 장부")
        watch_add(c)
        out.append(c)
    return {"ok": True, "codes": out}


@app.get("/api/journal")
def journal():
    rows = D.journal[-300:]
    return {"rows": rows, "px": {j["code"]: (feed.quotes.get(j["code"], {}).get("px") or 0) for j in rows}}


@app.post("/api/watch")
def watch_add(code: str = Body(..., embed=True)):
    c = _code(code)
    if c not in D.journal_codes():
        D.pick(c, D.ref_day(c), "직접 고름")
    if c not in D.watch:
        D.watch.append(c)
        desk_mod._write("watch.json", D.watch)
        feed.set_codes(D.sub_codes())
        _warm([c])
    return {"ok": True}


@app.delete("/api/watch/{code}")
def watch_del(code: str):
    c = _code(code)
    D.watch = [x for x in D.watch if x != c]
    desk_mod._write("watch.json", D.watch)
    D.unpick(c)
    return {"ok": True}


@app.post("/api/order")
def order(code: str = Body(...), side: str = Body(...), qty: int = Body(...), price: int = Body(0), market: bool = Body(False)):
    c = _code(code)
    if qty <= 0 or (not market and price <= 0) or side not in ("buy", "sell"):
        raise HTTPException(400, "수량·가격을 확인해 주세요")
    if not market and price != engine.floor_tick(price):
        raise HTTPException(400, f"호가 단위({engine.tick_size(price)}원)에 맞지 않습니다")
    return D.buy(c, qty, price, market) if side == "buy" else D.sell(c, qty, price, market)


@app.get("/api/ref")
def ref(code: str, day: str = ""):
    """기준 종가 — day 비우면 직전 거래일, YYYY-MM-DD/YYYYMMDD 면 그날."""
    d = day.replace("-", "").strip() or None
    if d and (len(d) != 8 or not d.isdigit()):
        raise HTTPException(400, "날짜는 YYYY-MM-DD")
    return D.ref(_code(code), d)


@app.post("/api/ref_day")
def ref_day(code: str = Body(...), day: str = Body("")):
    """종목별 기준일 저장 — 비우면 자동(최근 신고대금 날, 없으면 직전 거래일), "prev" 면 직전 거래일. 그날 종가를 미리 받아 둔다."""
    c, d = _code(code), day.replace("-", "").strip() or None
    if d == "prev":
        D.set_ref_day(c, d)
        return D.ref(c)
    if d and (len(d) != 8 or not d.isdigit()):
        raise HTTPException(400, "날짜는 YYYY-MM-DD")
    D.set_ref_day(c, d)
    return D.ref(c, D.ref_day(c))


@app.post("/api/plan")
def plan(code: str = Body(...), base: str = Body(...), ref_day: str = Body(""), stages: list = Body(...), keep: dict = Body(...),
         rule: str | None = Body(None), tag: str = Body("분할매수")):
    """예약 분할 매수 — 기준일 종가 × (1+pct) 지정가, keep 동안 매일 체결 안 된 단계만 다시 건다."""
    if base not in ("reg", "aft"):
        raise HTTPException(400, "기준은 reg / aft")
    d = ref_day.replace("-", "").strip() or None
    return D.create_plan(_code(code), base, d, stages, keep, tag[:20] or "분할매수", rule or D.rules.get("manual_exit"))


@app.post("/api/plan/cancel")
def plan_cancel(id: str = Body(..., embed=True)):
    return D.cancel_plan(id)


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
    rules = {k: body[k] for k in ("rules", "exits", "manual_exit", "safety", "sets") if k in body}
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
    uvicorn.run(app, host=os.environ.get("TRADER_HOST", "0.0.0.0"), port=int(os.environ.get("TRADER_PORT", "8790")), log_level="warning")
