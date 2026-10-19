"""매매 데스크의 판단 로직 — 호가 단위, 기준가 대비 분할 매수 가격, 청산 판정, 안전장치, 매수 조건.

전부 순수 함수다(네트워크·파일 없음). 주문을 실제로 내는 쪽은 trader/desk.py.
시안: claude.ai/artifact/VDtngcoSFJ78wsP1MCy76Q (10-19 사용자 확정 "이대로 만들어줘").
"""
from __future__ import annotations

import math
from datetime import date, datetime

# 2023-01-25 개편 뒤 코스피·코스닥 공통 호가 단위
_TICKS = ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500))


def tick_size(price: float) -> int:
    for bound, tick in _TICKS:
        if price < bound:
            return tick
    return 1000


def floor_tick(price: float) -> int:
    """매수 지정가는 내려서 맞춘다 — 올리면 정한 % 보다 비싸게 산다."""
    t = tick_size(price)
    return int(math.floor(price / t + 1e-9) * t)


def ceil_tick(price: float) -> int:
    """익절 지정가는 올려서 맞춘다 — 내리면 정한 % 보다 싸게 판다."""
    t = tick_size(price)
    return int(math.ceil(price / t - 1e-9) * t)


def ladder_orders(base: float, levels: list, amount: int) -> list[dict]:
    """기준가(정규장/애프터 종가) × (1+pct) 에 1종목 금액 × 비율씩. 수량 0 인 단계는 뺀다.

    levels: [[pct, ratio%], ...] — 예 [["-3","50"],["-5","50"]]."""
    out = []
    for i, (pct, ratio) in enumerate(levels):
        try:
            p, r = float(pct), float(ratio)
        except (TypeError, ValueError):
            continue
        price = floor_tick(base * (1 + p / 100))
        qty = int(amount * r / 100 // price) if price > 0 else 0
        if qty > 0:
            out.append({"stage": i, "pct": p, "price": price, "qty": qty})
    return out


def _hm(text: str) -> int:
    h, m = str(text).split(":")[:2]
    return int(h) * 60 + int(m)


def in_windows(now: datetime, windows: list) -> bool:
    """주문 가능 시간 구간들 중 하나라도 안에 있으면 True. 구간이 없으면 언제나 False(새 매수 안 함)."""
    cur = now.hour * 60 + now.minute
    for w in windows or []:
        try:
            if _hm(w[0]) <= cur < _hm(w[1]):
                return True
        except (ValueError, IndexError, TypeError):
            continue
    return False


def _num(v, default=None):
    try:
        return float(str(v).replace("%", "").replace("−", "-").replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def exit_actions(pos: dict, price: float, now: datetime, exits: dict) -> list[dict]:
    """보유 종목 하나에 지금 내야 할 청산 주문들. 먼저 닿는 것부터 — 전량 청산이 나오면 그것 하나만.

    pos: {"qty", "avg", "init_qty", "high", "opened", "takes_done": [단계], "breakeven": bool}
    exits: 규칙의 exits — {"stop": [on, pct], "take": [on, [[pct, ratio], ...]], "trail": [on, pct],
            "days": [on, n], "close": [on, "HH:MM"], "breakeven": [on]}
    """
    qty, avg = int(pos.get("qty") or 0), float(pos.get("avg") or 0)
    if qty <= 0 or avg <= 0 or price <= 0:
        return []

    def on(key):
        v = exits.get(key)
        return bool(v and v[0])

    stop_pct = _num(exits["stop"][1]) if on("stop") else None
    stop_px = avg * (1 - abs(stop_pct) / 100) if stop_pct is not None else None
    if pos.get("breakeven") and on("breakeven"):
        stop_px = max(stop_px or 0, avg)
    if stop_px is not None and price <= stop_px:
        return [{"kind": "stop", "qty": qty, "market": True, "why": f"손절선 {stop_px:,.0f} 이탈"}]

    if on("trail"):
        tp, high = _num(exits["trail"][1]), float(pos.get("high") or 0)
        if tp is not None and high > avg and price <= high * (1 - abs(tp) / 100):
            return [{"kind": "trail", "qty": qty, "market": True, "why": f"고점 {high:,.0f} 대비 −{abs(tp)}%"}]

    if on("close"):
        try:
            if now.hour * 60 + now.minute >= _hm(exits["close"][1]):
                return [{"kind": "close", "qty": qty, "market": True, "why": f"{exits['close'][1]} 장 마감 전 청산"}]
        except (ValueError, IndexError):
            pass

    if on("days") and pos.get("opened"):
        n = _num(exits["days"][1])
        try:
            held = (now.date() - date.fromisoformat(pos["opened"])).days
        except ValueError:
            held = 0
        if n is not None and held >= n and now.hour * 60 + now.minute >= 15 * 60 + 15:
            return [{"kind": "days", "qty": qty, "market": True, "why": f"보유 {held}일"}]

    return []


def take_orders(pos: dict, exits: dict) -> list[dict]:
    """분할 익절 지정가 매도 — 체결 즉시 단계마다 미리 걸어 둔다(시안 "체결 즉시 걸기").

    이미 건 단계(takes_done)는 다시 안 건다. 마지막 단계는 남은 수량 전부라 비율 반올림 찌꺼기가 안 남는다."""
    v = exits.get("take")
    qty, avg = int(pos.get("qty") or 0), float(pos.get("avg") or 0)
    if not (v and v[0]) or qty <= 0 or avg <= 0 or not isinstance(v[1], list):
        return []
    stages = [(i, _num(s[0]), _num(s[1])) for i, s in enumerate(v[1])]
    stages = [(i, p, r) for i, p, r in stages if p is not None and r]
    done, init = set(pos.get("takes_done") or []), int(pos.get("init_qty") or qty)
    left, out = qty - int(pos.get("take_working") or 0), []
    todo = [s for s in stages if s[0] not in done]
    for n, (i, pct, ratio) in enumerate(todo):
        q = left if n == len(todo) - 1 else min(left, max(1, round(init * ratio / 100)))
        if q <= 0:
            break
        out.append({"kind": "take", "stage": i, "qty": q, "price": ceil_tick(avg * (1 + pct / 100)),
                    "why": f"{i + 1}차 익절 +{pct:g}%"})
        left -= q
    return out


def safety_block(safety: dict, day: dict, positions: list, notional: int, equity: int) -> str | None:
    """새 매수를 막아야 하면 이유 문자열, 괜찮으면 None. 청산 주문에는 쓰지 않는다(청산은 언제나 허용).

    day: {"pnl": 오늘 실현+평가 손익, "orders": 오늘 낸 매수 주문 수, "halted": 이유|None}"""
    if day.get("halted"):
        return day["halted"]
    lim = _num(safety.get("max_daily_loss"))
    if lim and day.get("pnl", 0) <= -abs(lim):
        return f"하루 최대 손실 {abs(lim):,.0f}원 도달"
    mo = _num(safety.get("max_orders"))
    if mo and day.get("orders", 0) >= mo:
        return f"하루 최대 주문 {int(mo)}건 도달"
    mp = _num(safety.get("max_positions"))
    if mp and len([p for p in positions if p.get("qty")]) >= mp:
        return f"동시 보유 최대 {int(mp)}종목"
    mw = _num(safety.get("max_weight_pct"))
    if mw and equity > 0 and notional > equity * mw / 100:
        return f"종목당 최대 비중 {mw}% 초과"
    return None


# 계산할 수 있는 조건. 일봉에서 오는 것(시장·테마·52주·장대양봉)은 trader/daily_facts.py, 체결강도는 실시간(0B 228),
# 시가총액은 상장주식수 캐시 × 현재가. 값을 못 구하면(일봉 백필 전 등) 그 조건은 '만족 안 함'.
SUPPORTED = {"정규장 종가 대비", "애프터 종가 대비", "고점 대비 하락률(첫 도달)", "등락률", "거래대금",
             "시장", "같은 테마 장대양봉 종목 수", "52주 신고가 대비", "체결강도", "시가총액",
             "최근 장대양봉 고가 대비", "장대양봉일 52주 고가 돌파폭"}
TEXT_FIELDS = {"시장"}


def cond_value(field: str, snap: dict) -> float | str | None:
    f = snap.get("facts") or {}
    big = f.get("big")
    if field == "시장":
        return f.get("market")
    if field == "같은 테마 장대양봉 종목 수":            # 장대양봉이 있으면 그날 기준(규칙 원문), 없으면 직전 거래일 기준
        return (big or f).get("movers")
    if field == "장대양봉일 52주 고가 돌파폭":
        if not big:
            return None
        return -999.0 if big["break52"] is None else big["break52"]   # 신규상장(52주 고가 없음)은 통과 — 규칙 원문과 같음
    if field == "체결강도":
        return snap.get("strength") or None
    px = snap.get("px") or 0
    if not px:
        return None
    if field == "최근 장대양봉 고가 대비":                 # 매수 창 안이고 아직 −8% 에 안 닿은 장대양봉만
        return (px / big["high"] - 1) * 100 if big and not big["touched"] else None
    if field == "52주 신고가 대비":
        return (max(px, snap.get("high") or 0) / f["hi52"] - 1) * 100 if f.get("hi52") else None
    if field == "시가총액":
        return f["shares"] * px / 1e8 if f.get("shares") else None              # 억원
    if field == "정규장 종가 대비":
        return (px / snap["reg"] - 1) * 100 if snap.get("reg") else None
    if field == "애프터 종가 대비":
        return (px / snap["aft"] - 1) * 100 if snap.get("aft") else None
    if field == "고점 대비 하락률(첫 도달)":
        return (px / snap["high"] - 1) * 100 if snap.get("high") else None
    if field == "등락률":
        return snap.get("chg")
    if field == "거래대금":
        return (snap.get("value") or 0) / 1e8                     # 억원
    return None


def conds_met(conds: list, snap: dict) -> tuple[bool, list[str]]:
    """(모두 만족, 미지원 조건 이름들). 미지원이 하나라도 있으면 만족으로 치지 않는다."""
    unsupported = [c[0] for c in conds if c[0] not in SUPPORTED]
    if unsupported:
        return False, unsupported
    for field, op, raw in conds:
        v = cond_value(field, snap)
        if field in TEXT_FIELDS:
            if v is None or (op == "같음") != (str(v) == str(raw).strip()):
                return False, []
            continue
        target = _num(raw)
        if v is None or target is None:
            return False, []
        if op == "이상" and not v >= target:
            return False, []
        if op == "이하" and not v <= target:
            return False, []
        if op == "같음" and not abs(v - target) < 1e-9:
            return False, []
        if op in ("사이", "아님"):
            return False, [f"{field} {op}"]
    return True, []
