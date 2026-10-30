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
import re
import subprocess
import sys
import threading

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from . import desk as desk_mod
from . import card, daily_facts, engine, feed, ontology, outcomes, shadow, tgcmd, themes

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
    shadow.start(D, _chart_fresh)
    from . import slicer
    slicer.run(D)                                                   # Jev 호가 보고 나눠 사기 일감 루프(10-30)
    tgcmd.start(D)                                                     # 텔레그램 말 명령(안전판 — 매도·청산 없음), TRADER_TG_BOT_TOKEN 있을 때만
    _warm(D.watch)


def _warm(codes: list[str]) -> None:
    """고른 종목의 기본 차트(5분·하루 전체)를 미리 받아 둔다 — 화면을 열면 바로 그려지게(10-19 "반응속도 최대한 빠르게")."""
    def run():
        for tf, sess in (("5", "all"), ("1", "all"), ("15", "all"), ("D", "all"), ("5", "reg"), ("1", "reg")):
            for c in list(codes):
                if (c, tf, sess) in _chart_cache:
                    continue
                try:
                    chart(c, tf, sess)
                except Exception:                                        # noqa: BLE001 — 미리 받기는 실패해도 그만
                    pass
                time.sleep(0.3)
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
        sent_bs: dict = {}
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
            bs = {c: feed.books[c] for c in cs if c in feed.books and feed.books[c].get("t") != sent_bs.get(c)}
            if bs:
                out["bs"] = bs
                sent_bs.update({c: v.get("t") for c, v in bs.items()})
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


@app.get("/guide")
def guide():
    return FileResponse(Path(__file__).parent / "static" / "guide.html")


# 고친 것 확인 목록(10-23 사용자 "체크 리스트 하나 만들어서 관리" · "관리 페이지 하나 만들고") — state/trader/checklist.json 하나가 원본
@app.get("/checklist")
def checklist_page():
    return FileResponse(Path(__file__).parent / "static" / "checklist.html")


# 종목 한 장(10-23 사용자 "종목 한 장부터") — 섹터·소피 테마·신고대금·소피 신호·고른 기록·계획·성적을 한 카드에
@app.get("/card")
def card_page():
    return FileResponse(Path(__file__).parent / "static" / "card.html")


@app.get("/api/card")
def card_get(code: str):
    return card.build(_code(code), D, _daily)


# 온톨로지 관리(10-23 사용자) — 이어 놓은 선이 살아 있는지: 자료 신선도·테마 연결률·고른 기록·Jev·허브 경보
@app.get("/ontology")
def ontology_page():
    return FileResponse(Path(__file__).parent / "static" / "ontology.html")


@app.get("/api/ontology")
def ontology_get():
    return ontology.build(D)


@app.get("/api/checklist")
def checklist_get():
    return desk_mod._read("checklist.json", {"items": [], "decide": []})


@app.post("/api/checklist")
def checklist_set(id: str = Body(...), status: str | None = Body(None), note: str | None = Body(None), answer: str | None = Body(None)):
    """항목 상태·메모(id = 숫자) 또는 정할 것의 답(id = d1 …)."""
    with desk_mod._lock:
        c = desk_mod._read("checklist.json", {"items": [], "decide": []})
        x = next((i for i in c["items"] if str(i["id"]) == id), None) or next((d for d in c.get("decide", []) if d["id"] == id), None)
        if not x:
            raise HTTPException(404, "그 항목이 없습니다")
        if status is not None:
            if status not in ("ok", "sim", "fail", "wait", "real"):
                raise HTTPException(400, "상태는 ok·sim·fail·wait·real")
            x["status"] = status
        if note is not None:
            x["note"] = note[:500]
        if answer is not None:
            x["answer"] = answer[:500]
        x["updated"] = time.strftime("%Y-%m-%d %H:%M")
        desk_mod._write("checklist.json", c)
    return c


_primed: set = set()
_priming: set = set()
_prime_fail: dict = {}


def _ready(c: str) -> bool:
    """종목 첫 조회(기준 종가·신용·고점 — 키움 REST 4~5번, 10-20 실측 7.8초)는 뒤에서 한다. 끝나기 전엔 화면을 빈 칸으로 바로 그린다
    (10-20 사용자 "종목 추가·삭제가 느리고 매끄럽지 못해")."""
    k = (c, time.strftime("%Y%m%d"))
    if k in _primed:
        return True
    if c not in _priming and time.time() - _prime_fail.get(c, 0) > 60:   # 실패하면 1분 뒤 다시(2초 폴마다 키움을 두드리지 않게)
        _priming.add(c)

        def run():
            try:
                rd = D.ref_day(c)
                D.ref(c)
                if rd:
                    D.ref(c, rd)
                D.credit_info(c)
                D.warn_info(c)
                D.follow_info(c, rd)
                _primed.add(k)
            except Exception:                                       # noqa: BLE001 — 1분 뒤 다시
                _prime_fail[c] = time.time()
            finally:
                _priming.discard(c)
        threading.Thread(target=run, daemon=True, name="trader-prime").start()
    return False


def _env_line(code: str, ex: dict):
    """화면용 60선 엔벨로프 하단 — 매 초 판단(desk.tick)이 같은 값을 1분 기억해 두므로 보통 키움을 다시 부르지 않는다."""
    me = (ex.get("ma_env") or [False]) + [None, None]
    m = D.ma60_15(code, me[2] or "reg") if me[0] else 0
    return engine.floor_tick(m * (1 - abs(engine._num(me[1], 6) or 0) / 100)) if m else None


@app.get("/api/state")
def state(code: str = ""):
    held = {h["code"]: h for h in D.holdings}
    pend = {p["code"] for p in D.pending}
    watch = []
    for c in D.watch:
        r, s = D.refs.get(c, {}), D.snap(c)
        ok = _ready(c)
        rd = D.ref_day(c)
        rr = D.ref(c, rd) if rd and ok else None                               # 처음 한 번만 받고 그다음은 저장된 값
        watch.append({"code": c, "name": D.name(c), "px": s["px"], "chg": s["chg"], "reg": r.get("reg"), "aft": r.get("aft"),
                      "nxt": r.get("nxt", True), "ref_day": rd, "ref_src": D.ref_src(c), "ref_reg": (rr or {}).get("reg"), "ref_aft": (rr or {}).get("aft"),
                      "status": "보유" if c in held else "주문중" if c in pend else "대기", "follow": D.follow_info(c, rd) if ok else None, "auto": c not in D.no_auto,
                      "warn": D.warn_info(c).get("text") if ok else None})
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
                         "takes": takes, "breakeven": m.get("breakeven", False), "env": _env_line(h["code"], ex)})
    out = {"ready": D.ready(), "mock": D.is_mock, "key_src": D.key_src, "feed": feed.status(), "facts": daily_facts.status(), "now": time.strftime("%H:%M:%S"),
           "paper": D.paper_on(), "mkt": D.mkt, "stops": int(D.day.get("stops", 0)),
           "account": {"deposit": D.deposit, "equity": D.equity(), "pnl_realized": D.day.get("pnl_realized", 0),
                       "pnl_eval": sum(h["pl_amount"] for h in D.holdings), "day_pnl": D.day_pnl(),
                       "loss_limit": D.rules["safety"].get("max_daily_loss"), "halted": D.buy_block(0)},
           "watch": watch, "books": {c: feed.books.get(c) for c in D.watch}, "holdings": holdings, "pending": D.pending, "msgs": D.msgs[:40],
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
        ok = _ready(c)
        out["book"] = feed.books.get(c)
        out["active"] = {"code": c, "name": D.name(c), **D.snap(c), "loading": not ok}
        rd = D.ref_day(c)
        rr = (D.ref(c, rd) if rd else D.ref(c)) if ok else D.refs.get(c, {})
        ci = D.credit_info(c) if ok else {}
        lev, how = D.buy_lev(c) if ok else (1.0, "cash")
        out["active"].update(credit=ci.get("credit"), credit_text=ci.get("credit_text"), margin_rate=ci.get("margin"), lev=lev, lev_how=how)
        out["active"]["follow"] = D.follow_info(c, rd) if ok else None
        out["active"]["warn"] = D.warn_info(c).get("text") if ok else None
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
    if hit and not _refreshing.get(key):                            # 묵은 값은 바로 주고 뒤에서 새로(10-20 "반응 속도") — 화면은 실시간 가격으로 끝 봉을 고친다
        _refreshing[key] = True

        def bg():
            try:
                _chart_fetch(c, tf, sess, key)
            except Exception:                                       # noqa: BLE001
                pass
            finally:
                _refreshing.pop(key, None)
        threading.Thread(target=bg, daemon=True, name="trader-chart").start()
        return hit[1]
    return _chart_fetch(c, tf, sess, key)


_refreshing: dict = {}


def _chart_fresh(code: str) -> list:
    """Jev 그림자용 1분봉 — 묵은 값을 먼저 주지 않는다. chart() 는 화면용이라 오래된 캐시를 바로 주고 뒤에서 새로 받는데,
    10-23 엘리스 09:55 에 데스크 켤 때 받아 둔 어젯밤 애프터 1분봉이 그대로 Jev 에 갔다(떨어지는 중인데 '평평'으로 보임)."""
    key = (code, "1", "all")
    hit = _chart_cache.get(key)
    return hit[1] if hit and time.time() - hit[0] < 30 else _chart_fetch(code, "1", "all", key)


def _chart_fetch(c: str, tf: str, sess: str, key: tuple):
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
    _ready(c)
    return {"ok": True}


@app.post("/api/watch/order")
def watch_order(codes: list[str] = Body(..., embed=True)):
    """고른 종목 순서 바꾸기(10-30 사용자 '드래그해서 순서') — 보낸 순서대로, 빠진 종목은 뒤에 그대로."""
    want = [c for c in dict.fromkeys(_code(x) for x in codes) if c in D.watch]
    D.watch = want + [c for c in D.watch if c not in want]
    desk_mod._write("watch.json", D.watch)
    return {"ok": True}


@app.post("/api/auto")
def auto(code: str = Body(...), on: bool = Body(...)):
    """종목 자동 매수 스위치."""
    return {"ok": True, "cancelled": D.set_auto(_code(code), on)}


@app.delete("/api/watch/{code}")
def watch_del(code: str):
    c = _code(code)
    D.watch = [x for x in D.watch if x != c]
    desk_mod._write("watch.json", D.watch)
    D.unpick(c)
    for p in [p for p in D.plans if p["active"] and p["code"] == c]:   # 목록에서 빼면 그 종목 예약도 끝(10-23 점검: 빼도 계속 샀다)
        D.cancel_plan(p["id"])
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
         rule: str | None = Body(None), tag: str = Body("분할매수"), follow: bool = Body(False)):
    """예약 분할 매수 — 기준일 종가 × (1+pct) 지정가, keep 동안 매일 체결 안 된 단계만 다시 건다."""
    if base not in ("reg", "aft"):
        raise HTTPException(400, "기준은 reg / aft")
    d = ref_day.replace("-", "").strip() or None
    return D.create_plan(_code(code), base, d, stages, keep, tag[:20] or "분할매수", rule or D.rules.get("manual_exit"),
                         follow={"on": follow})


@app.post("/api/plan/cancel")
def plan_cancel(id: str = Body(..., embed=True)):
    return D.cancel_plan(id)


@app.post("/api/cancel")
def cancel(ord_no: str = Body(...), code: str = Body(...)):
    return D.cancel(ord_no, _code(code))


@app.post("/api/modify")
def modify(ord_no: str = Body(...), code: str = Body(...), price: int = Body(...)):
    return D.modify(ord_no, _code(code), price)


@app.post("/api/sell_all")
def sell_all(codes: list[str] = Body(..., embed=True)):
    """체크한 종목 일괄 매도 — 보유 수량 전부."""
    res = [D.exit_all(_code(c), "일괄 매도") for c in codes if any(h["code"] == c for h in D.holdings)]
    return {"ok": all(r["ok"] for r in res), "n": len(res)}


@app.post("/api/liquidate")
def liquidate():
    """전체 청산 — 보유 전부 매도. 새 매수는 오늘 하루 멈춘다."""
    D.day["halted"] = "전체 청산을 눌러 오늘 새 매수를 멈췄습니다"
    D._wd()
    res = [D.exit_all(h["code"], "전체 청산") for h in list(D.holdings)]
    return {"ok": all(r["ok"] for r in res), "n": len(res)}


@app.post("/api/resume")
def resume():
    D.day["halted"] = None
    D._wd()
    return {"ok": True}


# ── 규칙 백테스트(10-19 사용자 "매수규칙과 청산규칙으로 바로 스튜디오에서 백테스트") ──
# 데스크 판단 루프를 막지 않게 따로 띄운 프로세스가 돌고, 결과는 스튜디오 실행 기록(results/studio)으로 저장된다
_bt: dict = {"proc": None}


@app.post("/api/backtest")
def backtest_run(rule: str = Body(...), start: str = Body(...), end: str = Body(...),
                 capital: float = Body(30_000_000), session: str = Body("reg"), universe: str = Body("ledger")):
    if _bt["proc"] and _bt["proc"].poll() is None:
        try:
            _bt["proc"].wait(timeout=5)                             # 결과는 썼고 끝나는 중이면 잠깐 기다린다
        except subprocess.TimeoutExpired:
            raise HTTPException(409, "백테스트가 이미 돌고 있습니다") from None
    import datetime as _dt
    try:
        s, e = _dt.date.fromisoformat(start), _dt.date.fromisoformat(end)
    except ValueError:
        raise HTTPException(400, "날짜는 YYYY-MM-DD") from None
    if s > e or session not in ("reg", "all") or universe not in ("ledger", "journal") or capital <= 0 or not any(r["id"] == rule for r in D.rules["rules"]):
        raise HTTPException(400, "기간·데이터·원금·규칙을 확인해 주세요")
    (ROOT / "logs").mkdir(exist_ok=True)
    try:
        (desk_mod.STATE / "backtest_status.json").write_text(json.dumps({"state": "running", "stage": "시작", "pct": 0}), encoding="utf-8")
    except OSError:
        pass
    _bt["proc"] = subprocess.Popen(
        [sys.executable, "-m", "trader.backtest", "--rule", rule, "--start", start, "--end", end,
         "--capital", str(int(capital)), "--session", session, "--universe", universe],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=open(ROOT / "logs" / "trader_backtest.log", "w", encoding="utf-8"),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"ok": True}


@app.get("/api/backtest")
def backtest_status():
    try:
        st = json.loads((desk_mod.STATE / "backtest_status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    alive = bool(_bt["proc"] and _bt["proc"].poll() is None)
    if st.get("state") == "running" and not alive and _bt["proc"] is not None:
        st = {**st, "state": "error", "error": st.get("error") or "중간에 멈췄습니다 — logs/trader_backtest.log"}
    st.pop("trace", None)
    return st


@app.get("/api/credit")
def credit(code: str):
    """종목 신용 가능·미수 증거금률(조회만)."""
    c = _code(code)
    return {**D.credit_info(c), "warn": D.warn_info(c)}


_daily = lambda c: chart(c, "D", "all")                             # 성적표·그림자 채점용 통합 일봉(5분 기억)


@app.get("/api/shadow")
def shadow_get():
    """Jev 그림자 — 매수 자리에서만 묻는다. 상태·기록·채점(10-22). 주문엔 안 쓴다."""
    rs = shadow.rows()
    ge = shadow.graded_entry(rs)                                        # 채점이 줄에 결과를 달아야 모델을 학습할 수 있다
    shadow.fit(rs, "entry")
    return {"stat": shadow.stat, "key": bool(os.environ.get("TYPESAFE_API_KEY")), "grade_entry": ge, "models": shadow.models_view(),
            "rows": rs[-60:][::-1]}


@app.get("/api/outcomes")
def outcomes_get():
    """성적표 — 산 것·막은 것·안 사고 끝난 것이 그 뒤 어떻게 됐나(10-22)."""
    rs = outcomes.rows(list(D.plans), _daily)
    by: dict = {}
    for r in rs:                                                       # 테마별 성적(10-23 테마 잇기) — 그날까지 인포스탁 최근 테마, 없으면 소피 판정
        r["theme"] = themes.label(r["code"], f"{r['day'][:4]}-{r['day'][4:6]}-{r['day'][6:]}") or "테마 모름"
        by.setdefault(r["theme"], []).append(r)
    return {"rows": rs, "summary": outcomes.summary(rs), "by_theme": {t: outcomes.summary(x) for t, x in by.items()}}


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
        # 덮어쓰기 막기(10-19): 화면이 읽은 판(rev)과 지금 판이 다르면 다른 곳(다른 화면·폰)에서 바꾼 것 — 저장을 거부한다
        if "rev" in body and int(body.get("rev") or 0) != int(D.rules.get("rev") or 0):
            raise HTTPException(409, "다른 화면에서 규칙이 바뀌었습니다 — 새로고침해서 지금 규칙을 보고 다시 고쳐 주세요")
        hist = desk_mod.STATE / "rules_history"
        hist.mkdir(parents=True, exist_ok=True)
        (hist / time.strftime("rules-%Y%m%d-%H%M%S.json")).write_text(json.dumps(D.rules, ensure_ascii=False, indent=1), encoding="utf-8")
        for old in sorted(hist.glob("rules-*.json"))[:-60]:          # 최근 60판만 남긴다
            old.unlink(missing_ok=True)
        D.rules = {**D.rules, **rules, "rev": int(D.rules.get("rev") or 0) + 1}
        desk_mod._write("rules.json", D.rules)
    D.note("규칙 저장")
    return rules_get()


@app.get("/api/rules/history")
def rules_history():
    """저장하기 전 판들(최근 60) — 이름 · 시각 · 켜진 매수 규칙."""
    out = []
    for p in sorted((desk_mod.STATE / "rules_history").glob("rules-*.json"), reverse=True):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"name": p.name, "t": p.stem[6:], "on": [x["name"] for x in r.get("rules", []) if x.get("on")], "rev": r.get("rev")})
    return out


@app.post("/api/rules/restore")
def rules_restore(name: str = Body(..., embed=True)):
    p = desk_mod.STATE / "rules_history" / name
    if not p.name.startswith("rules-") or p.parent.name != "rules_history" or not p.exists():
        raise HTTPException(404, "그 판이 없습니다")
    old = json.loads(p.read_text(encoding="utf-8"))
    body = {k: old[k] for k in ("rules", "exits", "manual_exit", "safety", "sets") if k in old}
    out = rules_put(body)
    D.note(f"규칙 되돌림 · {p.stem[6:]} 판")
    return out


@app.post("/api/paper/reset")
def paper_reset():
    D.paper_reset()
    return {"ok": True}


@app.get("/api/preview")
def preview():
    return D.preview()


_LEDGER_ORIGIN = re.compile(r"^https?://[^/]+:8765$")


def _ledger_cors(request: Request, data) -> JSONResponse:
    """신고대금 장부(8765)에서 바로 부르게 — 채점 API 에만, 그 포트 화면에만 연다."""
    r = JSONResponse(data)
    o = request.headers.get("origin", "")
    if _LEDGER_ORIGIN.match(o):
        r.headers["Access-Control-Allow-Origin"] = o
    return r


@app.get("/api/grades")
def grades_get(request: Request):
    """장부 줄 채점(10-21 사용자 "내가 매매할 종목과 아닌 걸로 나누게") — {"코드:YYYY-MM-DD": {"g": "buy"|"skip", "t": 시각}}."""
    return _ledger_cors(request, desk_mod._read("grades.json", {}))


@app.post("/api/grades")
async def grades_post(request: Request):
    # 본문은 text/plain JSON — 장부(다른 포트)에서 미리 묻기(preflight) 없이 보내려고. 한 줄 또는 {"items": [...]}(매매 누르면 같은 날 나머지 자동 제외).
    # g 가 buy/skip 이 아니면 지운다. auto = 자동 제외(매매를 풀면 같이 풀린다)
    try:
        b = json.loads(await request.body())
        items = b["items"] if isinstance(b, dict) and "items" in b else [b]
        keys = []
        for x in items:
            d = str(x["d"])
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
                raise ValueError
            keys.append((f"{_code(x['code'])}:{d}", x.get("g"), bool(x.get("auto"))))
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "code·d(YYYY-MM-DD) 필요")
    G, t = desk_mod._read("grades.json", {}), time.strftime("%Y-%m-%dT%H:%M:%S")
    for key, g, auto in keys:
        if g in ("buy", "skip"):
            G[key] = {"g": g, "t": t, **({"auto": True} if auto else {})}
        else:
            G.pop(key, None)
    desk_mod._write("grades.json", G)
    return _ledger_cors(request, {"ok": True, "n": len(keys)})


@app.post("/api/position_rule")
def position_rule(code: str = Body(...), rule: str | None = Body(None)):
    D.set_position_rule(_code(code), rule)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("TRADER_HOST", "0.0.0.0"), port=int(os.environ.get("TRADER_PORT", "8790")), log_level="warning")
