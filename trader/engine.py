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


def keep_until(keep: dict, now: datetime, is_trading) -> str | None:
    """예약 매수를 언제까지 다시 걸지(마지막 날 ISO). None = 취소할 때까지.

    keep: {"mode": "today"} | {"mode": "days", "days": N} | {"mode": "until", "until": "YYYY-MM-DD"} | {"mode": "forever"}.
    '첫날'은 오늘이 거래일이고 15:20 전이면 오늘, 아니면 다음 거래일 — 장 끝나고 걸어도 '오늘만'이 내일 하루가 된다."""
    from datetime import timedelta
    mode = (keep or {}).get("mode", "today")
    if mode == "forever":
        return None
    if mode == "until":
        return str(keep.get("until") or "")[:10] or None
    d = now.date()
    if not (is_trading(d) and now.hour * 60 + now.minute < 15 * 60 + 20):
        d += timedelta(days=1)
        while not is_trading(d):
            d += timedelta(days=1)
    n = max(1, int(_num(keep.get("days"), 1) or 1)) if mode == "days" else 1
    for _ in range(n - 1):
        d += timedelta(days=1)
        while not is_trading(d):
            d += timedelta(days=1)
    return d.isoformat()


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


def level_opts(lv) -> dict:
    """매수 단계 [pct, 금액%, {옵션}] 의 옵션(10-20 사용자) — ma: 15분봉 60선 근접 %(있으면 60선 단계, pct 는 60선 대비 %),
    from/to: 그 단계를 살 수 있는 시각 "HH:MM"(to 는 그 시각 전까지). → {"band": 근접%|None, "t0": "HHMM"|None, "t1": "HHMM"|None}"""
    o = lv[2] if len(lv) > 2 and isinstance(lv[2], dict) else {}
    t = lambda k: str(o.get(k) or "").replace(":", "").strip()[:4] or None   # noqa: E731
    return {"band": abs(_num(o.get("ma"), 1) or 0) if "ma" in o else None, "t0": t("from"), "t1": t("to"),
            "src": o.get("src") if o.get("src") in ("reg", "aft") else None}   # 60선 봉 — 단계마다 정규장/애프터(10-21 사용자 "나눠 사기"), 없으면 규칙 기준


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
    # 15분봉 60선 엔벨로프 하단 이탈(10-20 사용자 "60선 엔벨로프 6% 하단을 깰 때") — ma_env: [on, pct, "reg"|"aft"], 60선 값은 desk 가 pos["ma60"] 로
    if on("ma_env") and pos.get("ma60"):
        env = float(pos["ma60"]) * (1 - abs(_num(exits["ma_env"][1], 6) or 0) / 100)
        if price < env:
            return [{"kind": "stop", "qty": qty, "market": True, "why": f"15분봉 60선 엔벨로프 −{abs(_num(exits['ma_env'][1], 6) or 0):g}% 하단 {env:,.0f} 이탈", "line": env}]

    # 되밀림이 켜지는 때(10-19 사용자) — trail[2]: take1 = 1차 익절이 체결된 뒤(기본, 분할 익절이 꺼져 있으면 평단 위로 오른 뒤)
    # · gain = 고가가 평단 +trail[3]% 를 넘은 뒤 · always = 평단 위로 한 번이라도 오른 뒤. breakeven = 익절 매도가 실제로 체결됐다는 표시(desk.on_order)
    if on("trail"):
        tr = list(exits["trail"]) + [None, None]
        tp, high, when = _num(tr[1]), float(pos.get("high") or 0), tr[2] or "take1"
        armed = (bool(pos.get("breakeven")) if when == "take1" and on("take") else
                 high >= avg * (1 + abs(_num(tr[3], 0) or 0) / 100) if when == "gain" else True)
        if tp is not None and armed and high > avg and price <= high * (1 - abs(tp) / 100):
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
             "최근 장대양봉 고가 대비", "장대양봉일 52주 고가 돌파폭", "52주 신고대금 대비(애프터)", "52주 신고대금 대비(정규장)",
             "거래대금(애프터)", "거래대금(정규장)", "60선 차이(애프터−정규장)"}
TEXT_FIELDS = {"시장"}


def cond_value(field: str, snap: dict, days=None) -> float | str | None:
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
    if field in ("거래대금", "거래대금(애프터)"):                   # 오늘 누적 — 통합(_AL) 08:00~20:00 하루 전체
        return (snap.get("value") or 0) / 1e8                     # 억원
    if field == "거래대금(정규장)":                                # 오늘 09:00~15:30 몫(desk.reg_value) — 못 쟀으면 판단 안 함
        return snap["value_reg"] / 1e8 if snap.get("value_reg") is not None else None
    if field == "60선 차이(애프터−정규장)":
        # 통합(애프터) 15분봉 60선 ÷ 정규장 15분봉 60선 − 1(%) — 1% 넘게 위면 장 마감 뒤에도 사는 힘이 셌던 종목(10-21 장부 52건: +4.0% vs −2.8%)
        return snap.get("ma_gap")
    if field.startswith("52주 신고대금 대비"):
        # 오늘 누적 대금 ÷ 어제까지 245거래일 최대 − 1(%) — 0 이상이면 신고대금(10-20 사용자). 애프터 = 하루 전체(통합) 최대와,
        # 정규장 = 정규장 몫 최대와 견준다. 장중엔 정규장 몫을 못 갈라 통합 누적 대금을 쓴다(신고대금 장부 장중 화면과 같은 추정 — 장전 NXT 포함)
        # days = '신고대금 난 뒤 N거래일까지 유지'(10-20 사용자) — 지난 N거래일 안 신고일(장부, 1,000억 이상)의 비율도 같이 보고 큰 값
        vr, b = snap.get("vref") or {}, "reg" if field.endswith("(정규장)") else "aft"
        ref = vr.get(b)
        today = snap.get("value_reg") if b == "reg" and snap.get("value_reg") is not None else snap.get("value")   # 정규장 몫을 쟀으면 그걸로
        live = ((today or 0) / 1e8 / ref - 1) * 100 if ref else None
        n = int(_num(days, 0) or 0)
        past = [x for k, x in (vr.get("hist") or {}).get(b, []) if 1 <= k <= n]
        return max([x for x in [live, *past] if x is not None], default=None)
    return None


def peak_pct(peak_stop: dict | None, cap_eok: float | None) -> float | None:
    """오른 뒤 재매수 금지 % — 시총(억)이 big.cap 이상이면 big.pct(10-21 사용자 "시총에 따라 바꾸자"). 꺼져 있으면 None."""
    ps = peak_stop or {}
    if not ps.get("on"):
        return None
    big = ps.get("big") or {}
    cap_min = _num(big.get("cap"), None)
    if cap_min is not None and cap_eok is not None and cap_eok >= cap_min and _num(big.get("pct"), None) is not None:
        return abs(_num(big["pct"]))
    return abs(_num(ps.get("pct"), 10) or 10)


def peak_anchor(days: list, rd: str, window: int = 21, min_chg: float | None = None) -> str:
    """오른 뒤 재매수 금지의 기준일 — 연달아 나온 신고대금의 첫 날(10-21 사용자 "10/16 → 10/20 → 10/21 신고대금이 자꾸 올라가서 높은 데서 사게 된다").
    rd 앞 window 달력일 안의 신고대금 날 중 가장 이른 날, 그 앞으로도 window 안에 이어지면 계속 거슬러 간다. days·rd 는 'YYYY-MM-DD'.
    days 가 (날짜, 그날 상승률) 이면 min_chg 이상 오른 신고대금만 잇는다(10-21 사용자 "9월 28일(−1.3%)은 빼야") — rd 자신은 늘 포함."""
    from datetime import date as _d, timedelta as _td
    pairs = [x if isinstance(x, (tuple, list)) else (x, None) for x in days]
    ds = sorted({d for d, ch in pairs if d <= rd and (min_chg is None or (ch is not None and ch >= min_chg))})
    cur = rd
    for x in reversed(ds):
        if _d.fromisoformat(cur) - _d.fromisoformat(x) <= _td(days=window):
            cur = min(cur, x)
    return cur


def conds_met(conds: list, snap: dict) -> tuple[bool, list[str]]:
    """(모두 만족, 미지원 조건 이름들). 미지원이 하나라도 있으면 만족으로 치지 않는다."""
    unsupported = [c[0] for c in conds if c[0] not in SUPPORTED]
    if unsupported:
        return False, unsupported
    for c in conds:
        field, op, raw = c[0], c[1], c[2]
        v = cond_value(field, snap, c[3] if len(c) > 3 else None)
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


def per_stock_amount(amount, safety: dict, equity: float, lev: float = 1.0) -> int:
    """1종목당 금액(원) — 매매 데스크와 백테스트가 같이 쓴다.
    "15000000" = 그 금액 · "100%" = 평가금의 100% ÷ 동시 보유 최대(종목당 최대 비중이 상한) ·
    비움 = 평가금 × min(종목당 최대 비중, 100 ÷ 동시 보유 최대). 다 비어 있으면 0(안 삼).
    lev = 미수·신용 배수(10-19 사용자) — 평가금 대신 평가금 × lev 를 기준으로 쓴다(원 금액은 그대로)."""
    raw = str(amount or "").strip()
    equity = equity * max(1.0, lev)
    w, n = _num(safety.get("max_weight_pct"), 0) or 0, int(_num(safety.get("max_positions"), 0) or 0)
    if raw.endswith("%"):
        p = (_num(raw, 0) or 0) / (n if n > 0 else 1)
        p = min(p, w) if w > 0 else p
        return int(equity * p / 100) if p > 0 else 0
    amt = int(_num(raw, 0) or 0)
    if amt > 0:
        return amt
    ws = [x for x in (w, 100 / n if n > 0 else 0) if x > 0]
    return int(equity * min(ws) / 100) if ws else 0


def leverage(safety: dict, margin_rate: float | None = None, credit_ok: bool | None = None) -> tuple[float, str]:
    """(배수, 방식) — 매수 방식(현금/미수/신용)과 종목 사정으로 정한다. 종목이 안 되면 현금(1배)로 돌아간다.
    미수: 100 ÷ 종목 증거금률(키움 kt00011), 최대 '미수 최대 배수'까지 · 신용: '신용 배수'(신용 가능 종목만, 키움 kt20017)."""
    mode = safety.get("buy_mode") or "cash"
    if mode == "margin":
        cap = _num(safety.get("margin_x"), 2.5) or 2.5
        if margin_rate is None:
            return cap, "margin"
        return (min(cap, 100 / margin_rate), "margin") if 0 < margin_rate < 100 else (1.0, "cash")
    if mode == "credit":
        if credit_ok is False:
            return 1.0, "cash"
        return max(1.0, _num(safety.get("credit_x"), 2.0) or 2.0), "credit"
    return 1.0, "cash"
