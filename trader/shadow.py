"""Jev 그림자 모드 — 매수 자리(걸려 있는 예약의 가격에 지금가가 닿을 때)에서만 '지금 받을까, 30분 기다릴까'를 물어 기록만 한다(10-22 사용자).

주문엔 절대 안 쓴다. 데스크 코드는 안 건드리고 옆에서 plans 를 3초마다 훑는다 — Jev 가 느리거나 죽어도 데스크는 그대로.
매수 자리가 아닌 때(예약 걸림·막음, 억지 시험)는 묻지 않는다 — 상황과 질문이 안 맞아 판단이 의미 없다(10-22 사용자 "현재 매수 규칙에 왔을 때만").
채점: 30분 안에 예약가 −1% 이하로 더 내려왔으면 '기다림이 나음' — Jev·항상 받기(지금 데스크)·작은 질문 모델 각각 맞힌 수.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from . import feed
from .desk import STATE

LOG = STATE / "shadow.jsonl"
COST = 0.00015 * 2 + 0.0020
WON_PER_TOKEN = 0.042 / 1e6 * 1400                                    # $0.042/1M 입력 토큰 · 출력 무료 · 1달러 1,400원
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jev")
stat = {"on": False, "err": None, "err_t": None, "day": None, "calls": 0, "ms": 0, "won": 0.0}


class Entry(BaseModel):
    prob: float = Field(ge=0.0, le=1.0, description="Probability that buying right now at the limit price is better than waiting 30 minutes to buy at least 1% cheaper")
    # 작은 질문들(10-22 사용자) — 한 번 호출에 같이 묻는다. 나중에 우리 모델의 입력(어느 질문이 실제로 맞히는지 채점)
    knife: float = Field(ge=0.0, le=1.0, description="Is the price still falling sharply right now (a falling knife), judging by the last 10 one-minute bars?")
    exhausted: float = Field(ge=0.0, le=1.0, description="Has selling pressure faded: volume shrinking and the price no longer making new lows in the last few minutes?")
    bids_strong: float = Field(ge=0.0, le=1.0, description="Are buyers clearly stronger than sellers in the order book (much larger bid size than ask size)?")
    ask_wall: float = Field(ge=0.0, le=1.0, description="Is there a thick wall of ask orders just above the current price that will cap a bounce?")
    buyers_trading: float = Field(ge=0.0, le=1.0, description="Are actual trades dominated by buyers (trade strength above 100)?")
    program_support: float = Field(ge=0.0, le=1.0, description="Is program trading net buying the stock today in a meaningful size (at least about 1% of today's trading value)?")
    near_low: float = Field(ge=0.0, le=1.0, description="Is the current price at or near today's low?")


NEAR = 0.003                                                          # 지금가가 예약가 +0.3% 안으로 오면 '도착'
_entry_asked: set = set()
_eg: dict = {}                                                        # 채점 끝난 도착 판정(ts+pid) -> 결과
_bars1 = None                                                         # code -> 1분봉(app 이 넣어 준다)


def _two(pairs: list) -> tuple:
    """(한국어, 영어) 줄들 → (화면용 한국어, Jev 에 보낼 영어). Jev 는 영어가 가장 정확하다(docs.typesafe.ai/models, 10-22)."""
    pairs = [x for x in pairs if x]
    return "\n".join(k for k, _ in pairs), "\n".join(e for _, e in pairs)


def _ctx_result(fut, t0: float) -> dict:
    """두 번 묻기의 B(배경 넣은 질문) 답 — A 와 같은 2초 한도 안에서."""
    try:
        r = fut.result(timeout=max(0.1, 2 - (time.time() - t0)))
        return {"prob": round(r.prob, 3), "take": r.prob >= 0.5, "parts": {k: round(v, 3) for k, v in r.model_dump().items() if k != "prob"},
                "ms": int((time.time() - t0) * 1000)}
    except FutTimeout:
        return {"err": "2초 안에 답 없음"}
    except Exception as e:                                             # noqa: BLE001
        msg = str(e)[:120]
        return {"err": type(e).__name__ + ("" if "apikey" in msg.lower() else ": " + msg)}


def _call(text: str, model, row: dict, key: str, ctx: tuple | None = None) -> dict:
    """ctx = (B 질문 영어, 배경 줄 한국어) — 주면 같은 순간 B 도 같이 보내 row['ctx'] 에 따로 적는다(10-23 두 번 묻기)."""
    t0 = time.time()
    fb = None
    try:
        import jev
        if ctx:
            fb = _pool.submit(jev.decide, ctx[0], model)                 # A 와 동시에 — 같은 순간이어야 차이가 배경 때문이라고 말할 수 있다
        r = _pool.submit(jev.decide, text, model).result(timeout=2)
        row.update(prob=round(r.prob, 3), **{key: r.prob >= 0.5}, parts={k: round(v, 3) for k, v in r.model_dump().items() if k != "prob"})
        mp = predict(_kind(row), row["parts"])                         # 우리 모델이 있으면 그 순간 판단도 같이(나중에 진짜 채점)
        if mp is not None:
            row["model_prob"] = mp
        stat.update(on=True, err=None)
    except FutTimeout:
        row["err"] = "2초 안에 답 없음"
    except Exception as e:                                             # noqa: BLE001 — 키 없음·크레딧 없음·네트워크 — 기록만
        msg = str(e)[:120]
        row["err"] = type(e).__name__ + ("" if "apikey" in msg.lower() else ": " + msg)   # 키가 섞인 메시지는 버린다
    row["ms"] = int((time.time() - t0) * 1000)
    if fb is not None:
        row.update(ctx=_ctx_result(fb, t0), sent_ctx=ctx[0], state_ctx=ctx[1])
    if row.get("err"):
        stat.update(on=False, err=row["err"], err_t=row["ts"])
    today = row["day"]
    if stat["day"] != today:
        stat.update(day=today, calls=0, ms=0, won=0.0)
    stat["calls"] += 1
    stat["ms"] += row["ms"]
    stat["won"] += (len(text) + (len(ctx[0]) if fb is not None else 0)) * 0.7 * WON_PER_TOKEN   # ponytail: 토큰 수는 글자 수로 어림 — 콘솔 Usage 가 정답
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _program(D, code: str):
    """당일 프로그램 순매수(억원) — ka90008 최신 행, 도착 판정 때만 한 번(데스크 키). 못 받으면 None."""
    try:
        pl = D.client.request_tr("ka90008", {"amt_qty_tp": "1", "stk_cd": code + "_AL", "date": time.strftime("%Y%m%d")}, "/api/dostk/mrkcond")
        r = (pl.get("stk_tm_prm_trde_trnsn") or [])[0]
        return round((abs(int(str(r["prm_buy_amt"]).strip() or 0)) - abs(int(str(r["prm_sell_amt"]).strip() or 0))) / 100, 1)
    except Exception:                                                  # noqa: BLE001
        return None


def _context(D, code: str) -> list:
    """두 번 묻기(10-23 사용자)의 B 에만 붙이는 종목 배경(온톨로지) — 신고대금 이력 · 테마 · 소피 프로그램 신호 · 지난 매매.
    전부 지금 이전 기록이다(신고대금 장부는 어제까지, 소피 신호는 지금까지). 앞날 값(5일 뒤 등)은 넣지 않는다."""
    from . import card
    out, today = [], date.today()
    led = [r for r in card.ledger_rows(code) if r["day"] < today.isoformat()]
    if led:
        r = led[0]
        ago = (today - date.fromisoformat(r["day"])).days
        x = f"{r['x']:.2f}" if r["x"] is not None else "?"
        chg = f"{r['chg']:+.1f}%" if r["chg"] is not None else "?"
        out.append((f"신고대금(52주 최대 거래대금 경신) {len(led)}번 · 최근 {r['day']}({ago}일 전) 대금 {r['eok']:,}억 · 직전 최대의 {x}배 · 그날 {chg}",
                    f"Record trading-value days (trading value above its 52-week max) so far: {len(led)} · latest {r['day']} ({ago} calendar days ago): "
                    f"{r['eok'] / 10:,.1f} billion KRW, {x}x the previous max, price change that day {chg}"))
    else:
        out.append(("신고대금 이력 없음", "No record trading-value day in our ledger"))
    from . import themes
    th, sec = card.theme(code), (card._cached(card.SECTORS, card._sectors) or {}).get(code)
    t_ko = f"{th['theme']} · {th.get('sub') or ''}".strip(" ·") if th.get("theme") else "모름"
    s_ko = f"{sec['sector']} · {sec['sub_sector']}" if sec else "모름(신규 상장 등)"
    info = themes.recent(code, (today - timedelta(days=1)).isoformat())[:3]          # 어제 글까지(오늘 글은 장 마감 뒤라 아직 없음)
    i_ko = ", ".join(f"{x['theme']}({x['last'][5:]})" for x in info) or "없음"
    out.append((f"테마(소피) {t_ko} · 인포스탁 최근 20거래일 {i_ko} · 섹터 {s_ko}",
                f"Theme (Korean labels): our theme engine says {t_ko if th.get('theme') else 'unknown'}; daily market-theme reports in the last 20 trading days: "
                f"{i_ko if info else 'none'}; sector: {s_ko if sec else 'unknown (e.g. newly listed)'}"))
    since = (today - timedelta(days=3)).isoformat()
    sig = [s for s in card.program(code, 60) if (s.get("d") or "") >= since]
    if sig:
        ent = sum(1 for s in sig if s.get("pnl") is None)
        done = [s["pnl"] for s in sig if s.get("pnl") is not None]
        last = sig[0]
        out.append((f"소피 프로그램 주도 신호 최근 3일 {len(sig)}번(진입 {ent}번) · 끝난 신호 평균 {sum(done) / len(done):+.2f}%" if done else f"소피 프로그램 주도 신호 최근 3일 {len(sig)}번(진입 {ent}번)",
                    f"Our program-trading-led rally detector fired {len(sig)} times in the last 3 days ({ent} entries)"
                    + (f"; closed signals averaged {sum(done) / len(done):+.2f}%" if done else "") + f"; latest {last.get('d')} {str(last.get('t'))[:5]}"))
    else:
        out.append(("소피 프로그램 주도 신호 최근 3일 없음", "Our program-trading-led rally detector did not fire in the last 3 days"))
    past = [card.trade_pnl(j) for j in D.journal if j["code"] == code and j.get("closed")]
    past = [x for x in past if x][-3:]
    if past:
        pcts = ", ".join(f"{x['pct']:+.2f}%" for x in past)
        out.append((f"이 종목 지난 매매(비용 뺀 값) {pcts}", f"Our past trades in this stock (net of costs), oldest first: {pcts}"))
    return out


def ask_entry(D, p: dict, st: dict, px: int, test: bool = False) -> dict:
    """예약가 도착 — '지금 받을까, 30분 기다릴까'(10-22 사용자). 데스크는 항상 받는다(지정가) — 그것과 비교."""
    code, price = p["code"], st["price"]
    q, b = feed.quotes.get(code, {}), feed.books.get(code, {})
    r = lambda a: f"{(a / price - 1) * 100:+.2f}%" if a else "?"
    pairs = [
        (f"한국 주식 · 지금 {datetime.now():%H:%M:%S} · 종목 {p['name']}({code})", f"Korean stock · now {datetime.now():%H:%M:%S} KST · stock code {code}"),
        ("질문: 매수 예약가에 가격이 내려왔다. 지금 바로 받는 게 나은가, 30분 기다려 더 싸게 사는 게 나은가?",
         "Question: the price has come down to our limit buy price. Is it better to buy right now, or to wait 30 minutes and buy cheaper?"),
        (f"매수 예약가 {price:,}원 · 지금가 {px:,}원 (예약가 대비 {r(px)})", f"Limit buy price {price:,} KRW · current price {px:,} KRW ({r(px)} vs limit)"),
        (f"오늘 등락률 {q.get('chg', '?')}% · 오늘 고가 {r(q.get('high'))} · 저가 {r(q.get('low'))} · 시가 {r(q.get('open'))} (모두 예약가 대비)",
         f"Today's change {q.get('chg', '?')}% · today's high {r(q.get('high'))} · low {r(q.get('low'))} · open {r(q.get('open'))} (all vs limit)"),
        (f"체결강도 {q.get('strength', '?')} (100 넘으면 매수 체결이 더 많음)",
         f"Trade strength {q.get('strength', '?')} (buyer-initiated volume / seller-initiated volume x 100; above 100 means buyers dominate)"),
    ]
    if b:
        if b.get("ask_total"):
            pairs.append((f"호가 잔량: 매도 총 {b['ask_total']:,}주 · 매수 총 {b.get('bid_total', 0):,}주 (매수/매도 {b.get('bid_total', 0) / b['ask_total']:.2f}배)",
                          f"Order book: total ask size {b['ask_total']:,} shares · total bid size {b.get('bid_total', 0):,} shares (bid/ask {b.get('bid_total', 0) / b['ask_total']:.2f}x)"))
        asks, bids = " ".join(f"{a:,}({n:,})" for a, n in b["asks"][:5]), " ".join(f"{a:,}({n:,})" for a, n in b["bids"][:5])
        pairs.append((f"매도 1~5호가 {asks} | 매수 1~5호가 {bids}", f"Best 5 asks price(size): {asks} | best 5 bids price(size): {bids}"))
    pg = _program(D, code)
    share = f"{pg * 1e8 / q['value'] * 100:+.2f}%" if pg is not None and q.get("value") else "?"   # 오늘 거래대금 대비 — 크기 감을 주려고(+0.2억을 '프로그램 매수'로 읽었다, 10-22)
    # 부호(+/−)를 Jev 가 놓친다(10-22 HT로보틱스 −25.8억을 '프로그램 매수' 96%) — 사는지 파는지를 말로 쓴다
    side = "net BUYING" if (pg or 0) > 0 else "net SELLING" if (pg or 0) < 0 else "flat (no net buying or selling)"
    pairs.append((f"오늘 프로그램 순매수 {pg:+,.1f}억원 (오늘 거래대금의 {share})",
                  f"Program traders today are {side}: {abs(pg) * 100:,.0f} million KRW ({share.lstrip('+-')} of today's trading value)") if pg is not None
                 else ("프로그램 순매수: 모름", "Program trading net buying: unknown"))
    try:
        last = [x for x in _bars1(code) if x["t"][:8] == date.today().strftime("%Y%m%d")][-10:] if _bars1 else []   # 오늘 봉만 — 장 초반에 어제 봉이 '최근 10분'으로 섞이지 않게
        if last:
            seq = " ".join(f"{r(x['c'])}·{x['v']:,}" for x in last)
            pairs.append((f"최근 10분 1분봉(예약가 대비 종가 · 거래량): {seq}", f"Last 10 one-minute bars, oldest first (close vs limit · volume): {seq}"))
    except Exception:                                                  # noqa: BLE001
        pass
    ko, en = _two(pairs)
    row = {"ts": datetime.now().isoformat(timespec="seconds"), "day": date.today().strftime("%Y%m%d"), "kind": "entry", "pid": p["id"], "code": code,
           "name": p["name"], "event": "예약가 도착", "price": price, "px": px, "program": pg, "test": test, "state": ko, "sent": en}
    ctx = None
    try:                                                               # 배경을 못 만들면 A 만 묻는다
        cp = _context(D, code)
        ctx = (_two(pairs + [("배경(우리 기록)", "Background from our own records:")] + cp)[1], _two(cp)[0])
    except Exception:                                                  # noqa: BLE001
        pass
    return _call(en, Entry, row, "take", ctx)


def _arrivals(D) -> None:
    today = date.today().strftime("%Y%m%d")
    for p in list(D.plans):
        if not p["active"]:
            continue
        px = feed.quotes.get(p["code"], {}).get("px")
        left = [(i, s) for i, s in enumerate(p["stages"]) if s.get("filled", 0) < s.get("qty", 0) and s.get("price")]
        if not px or not left:
            continue
        i, st = max(left, key=lambda x: x[1]["price"])                # 가장 먼저 닿는 단계
        k = (p["id"], i, today)
        if px <= st["price"] * (1 + NEAR) and k not in _entry_asked:
            _entry_asked.add(k)
            ask_entry(D, p, st, px)


def start(D, bars1=None) -> None:
    global _bars1
    _bars1 = bars1
    today = date.today().strftime("%Y%m%d")
    for r in rows(1000):                                               # 다시 켜도 오늘 이미 물은 도착은 또 안 묻는다 · 오늘 호출 수·비용도 이어서
        if r["day"] == today:
            stat.update(on=not r.get("err"), day=today, calls=stat["calls"] + 1, ms=stat["ms"] + r.get("ms", 0), won=stat["won"] + len(r.get("state", "")) * 0.7 * WON_PER_TOKEN)
        if r.get("kind") == "entry" and r["day"] == today and not r.get("test"):
            p = next((x for x in D.plans if x["id"] == r["pid"]), None)
            if p:
                _entry_asked.update((p["id"], i, today) for i, s in enumerate(p["stages"]) if s.get("price") == r["price"])

    def loop():
        while True:
            time.sleep(3)
            try:
                _arrivals(D)
            except Exception:                                          # noqa: BLE001 — 그림자는 죽어도 데스크와 무관
                pass
    threading.Thread(target=loop, daemon=True, name="trader-shadow").start()


def rows(limit: int = 200) -> list:
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    return [json.loads(x) for x in lines if x.strip()]


def graded_entry(rs: list) -> dict:
    """도착 판정 채점 — 30분 안에 예약가 −1% 이하로 더 내려왔으면 '기다림이 나음', 아니면 '받기가 나음'.
    데스크(항상 받기)와 Jev 를 같은 기준으로. 30분이 안 지났으면 대기."""
    now, cache, n, jv, tk, take, skip, parts, mh = datetime.now(), {}, 0, 0, 0, [], [], {}, []
    cn = cj = ca = 0                                                   # 두 번 묻기 — 같은 순간 B(배경)와 A 를 같은 줄에서만 비교
    for r in rs:
        if r.get("kind") != "entry" or r.get("test") or "take" not in r:
            continue
        k = r["ts"] + r["pid"]
        if k not in _eg:
            t0 = datetime.fromisoformat(r["ts"])
            if (now - t0).total_seconds() < 31 * 60 or not _bars1:
                continue
            try:
                if r["code"] not in cache:
                    cache[r["code"]] = _bars1(r["code"])
                t = t0.strftime("%Y%m%d%H%M%S")
                after = [b for b in cache[r["code"]] if b["t"] > t]
                win, day = after[:30], [b for b in after if b["t"][:8] == t[:8]]
            except Exception:                                          # noqa: BLE001
                continue
            if len(win) < 30:
                continue
            low = min(b["l"] for b in win)
            # 그날 마지막 봉 — 장이 안 끝났으면 지금까지의 마지막(나중에 다시 계산되도록 확정은 다음 날)
            done = t[:8] < now.strftime("%Y%m%d")
            res = {"low30": round(low / r["price"] - 1, 4), "after30": round(win[-1]["c"] / r["price"] - 1, 4), "wait_better": low <= r["price"] * 0.99,
                   "close": round(day[-1]["c"] / r["price"] - 1 - COST, 4) if day else None}
            if not done:
                r.update(res)                                          # 오늘 것은 매번 다시(종가가 아직 안 정해짐)
            else:
                _eg[k] = res
        if k in _eg:
            r.update(_eg[k])
        n += 1
        tk += not r["wait_better"]
        jv += r["take"] == (not r["wait_better"])
        c = r.get("ctx") or {}
        if "take" in c:
            cn += 1
            cj += c["take"] == (not r["wait_better"])
            ca += r["take"] == (not r["wait_better"])
        if "model_prob" in r:
            mh.append((r["model_prob"] >= 0.5) == (not r["wait_better"]))
        (take if r["take"] else skip).append(r.get("close"))
        for q, v in (r.get("parts") or {}).items():
            parts.setdefault(q, {"wait": [], "take": []})["wait" if r["wait_better"] else "take"].append(v)
    avg = lambda v: round(sum(x for x in v if x is not None) / len([x for x in v if x is not None]), 4) if any(x is not None for x in v) else None
    # 손실 피하기(10-22 사용자 "안 사서 손실 안 보는 게 중요"): Jev 가 말린 것을 그냥 샀다면 그날 종가에 몇 %였나 — 음수면 피한 손실
    return {"n": n, "jev": jv, "always_take": tk, "model_n": len(mh), "model": sum(mh), "ctx_n": cn, "ctx": cj, "ctx_base": ca, "skip_n": len(skip), "skip_close": avg(skip), "take_n": len(take), "take_close": avg(take),
            "skip_loss_n": sum(1 for x in skip if x is not None and x < 0),
            # 작은 질문마다: 기다림이 나았던 때와 받기가 나았던 때의 평균 답 — 차이가 클수록 쓸모 있는 질문
            "parts": {q: {"wait": avg(v["wait"]), "take": avg(v["take"]), "n": len(v["wait"]) + len(v["take"])} for q, v in parts.items()}}


# ── 작은 질문 모델(10-22 사용자 "작은 질문 답으로 판단하는 모델") ──────────────
# Jev 전체 판정은 어느 종목이든 55~63% 에 몰렸다(매수 잔량 하나에 끌림). 작은 질문 답을 우리 결과로 학습한 로지스틱이 대신 판단한다.
# 시간 순 앞 70% 학습 → 뒤 30% 채점(사후 분할 아님: 학습 구간 뒤만 채점), 그다음 전부로 다시 학습해 새 판단에 기록(주문엔 안 씀).
MIN_N = 40                                                            # ponytail: 고정 최소 표본 — 질문 수(7)의 ~6배, 늘면 교차검증으로
_models: dict = {}


def _kind(r: dict) -> str:
    return r.get("kind") or "call"


def _label(r: dict):
    if _kind(r) == "entry":
        return None if "wait_better" not in r else not r["wait_better"]   # 받기가 나았나
    return None if "ret" not in r else r["ret"] > 0                        # 샀으면 이익이었나


def fit(rs: list, kind: str) -> dict:
    xs = sorted((r for r in rs if _kind(r) == kind and not r.get("test") and r.get("parts") and _label(r) is not None and "prob" in r),
                key=lambda r: r["ts"])
    n = len(xs)
    if n < MIN_N or len({_label(r) for r in xs}) < 2:
        _models[kind] = {"n": n, "need": MIN_N}
        return _models[kind]
    from sklearn.linear_model import LogisticRegression
    keys = sorted({k for r in xs for k in r["parts"]})
    X = [[r["parts"].get(k, 0.5) for k in keys] for r in xs]
    y = [_label(r) for r in xs]
    cut = int(n * 0.7)
    clf = LogisticRegression().fit(X[:cut], y[:cut])
    te = range(cut, n)
    acc = lambda pred: round(sum(pred[i - cut] == y[i] for i in te) / len(te), 3)
    ev = {"test_n": len(te), "model": acc(list(clf.predict(X[cut:]))), "jev": acc([xs[i]["prob"] >= 0.5 for i in te]),
          "always": acc([True] * len(te))}                             # entry: 항상 받기(지금 데스크) · call: 항상 사기
    clf = LogisticRegression().fit(X, y)
    _models[kind] = {"n": n, "keys": keys, "clf": clf, "eval": ev, "w": dict(zip(keys, [round(float(c), 2) for c in clf.coef_[0]]))}
    return _models[kind]


def predict(kind: str, parts: dict):
    m = _models.get(kind) or {}
    if not m.get("clf") or not parts:
        return None
    return round(float(m["clf"].predict_proba([[parts.get(k, 0.5) for k in m["keys"]]])[0][1]), 3)


def models_view() -> dict:
    return {k: {x: v for x, v in m.items() if x != "clf"} for k, m in _models.items()}
