"""매매 데스크 상태·주문 — 고른 종목, 규칙, 보유 종목의 청산 감시, 기준가 대비 분할 매수, 일괄 매도·전체 청산.

앱키는 매매 전용(TRADER_APPKEY / TRADER_SECRETKEY, .env). 비어 있으면 화면은 뜨고 주문·실시간은 꺼진다.
TRADER_IS_MOCK 은 기본 1(모의) — 실전 키를 넣을 때 0 으로 바꾼다. 모의 키를 실전 주소에 쓰면 토큰부터 거부돼 주문이 안 나간다.

REST 는 계정 전체가 한도를 나눠 쓴다(앱키를 나눠도 총량은 그대로 — rest-ratelimit-is-account-wide).
소피증권이 같은 계정이라 여기서는 잔고 20초·미체결 15초 한 번, 기준 종가는 종목당 하루 두 번만 부른다. 가격·호가·체결은 실시간으로만.
주문은 backtesting.order_execution.submit_order(재시도·멱등·감사로그)를 그대로 쓴다.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from . import daily_facts, engine, feed

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "trader"
ORDER_LOG = str(STATE / "orders.jsonl")
_lock = threading.RLock()

DEFAULT_RULES = {
    "rules": [
        {"id": "pullback8", "name": "−8% 눌림 매수", "desc": "코스닥 · 테마 장대양봉 뒤 첫 −8%", "on": False,
         "conds": [["시장", "같음", "코스닥"], ["같은 테마 장대양봉 종목 수", "이상", "3"],
                   ["장대양봉일 52주 고가 돌파폭", "이하", "3.9"], ["최근 장대양봉 고가 대비", "이하", "-8"]],
         "times": [["09:00", "10:30"], ["14:00", "15:30"]], "amount": 0, "how": "limit", "once_per_day": True,
         "ladder": {"on": False, "base": "aft", "levels": [["-3", "50"], ["-5", "50"]]}, "exit": "split58"},
        {"id": "closeladder", "name": "기준일 종가 분할매수", "desc": "기준일 애프터 종가 −3% · −5%에 미리 걸기", "on": False,
         "conds": [], "times": [["08:00", "08:50"], ["09:00", "15:20"]], "amount": 0, "how": "limit", "once_per_day": True,
         "ladder": {"on": True, "base": "aft", "levels": [["-3", "50"], ["-5", "50"]]}, "exit": "split58"},
    ],
    # 청산 규칙은 매수 규칙과 따로(10-19 사용자 "매수규칙 청산규칙 따로 적용할 수 있게") — 매수 규칙·수동 주문·보유 종목이 각자 고른다
    "exits": [{"id": "split58", "name": "손절 −3.5% · 분할 익절 +5/+8%", "exits": {"stop": [True, "3.5"], "take": [True, [["5", "50"], ["8", "50"]]],
               "trail": [False, ""], "days": [False, ""], "close": [False, "15:15"], "breakeven": [True]}}],
    "manual_exit": "split58",
    "safety": {"max_daily_loss": "", "max_weight_pct": "", "max_positions": "", "max_orders": "",
               "confirm_real": True, "halt_on_disconnect": True, "near_pct": "1.5", "telegram": True, "auto_ref_days": "14",
               "buy_mode": "cash", "margin_x": "2.5", "credit_x": "2", "credit_rate": "9.5", "margin_intraday": True,
               "paper": False, "paper_capital": "30000000", "mkt_drop": "", "max_stops": ""},
}


def _lv_ex(lv) -> dict:
    """매수 단계 [pct, 금액%, {옵션}] 에서 예약 단계에 붙일 것 — 60선(ma·band)·살 수 있는 시각(t0·t1 "HHMM"). engine.level_opts 참고."""
    o = engine.level_opts(lv)
    return {**({"ma": True, "band": o["band"]} if o["band"] is not None else {}), **{k: o[k] for k in ("t0", "t1", "src") if o[k]}}


def _absint(v) -> int:
    try:
        return abs(int(str(v).replace("+", "").replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def _split_exits(rules: dict) -> dict:
    """옛 rules.json(규칙마다 exits 를 품은 모양)을 매수 규칙 + 청산 규칙 목록으로 나눈다. 이미 나뉘었으면 그대로."""
    if "exits" in rules:
        return rules
    exits, seen = [], {}
    for r in rules.get("rules", []):
        ex = r.pop("exits", None)
        if not ex:
            continue
        k = json.dumps(ex, sort_keys=True)
        if k not in seen:
            seen[k] = r["id"] + "_x"
            exits.append({"id": seen[k], "name": r["name"] + " 청산", "exits": ex})
        r["exit"] = seen[k]
    man = next((r.get("exit") for r in rules.get("rules", []) if r["id"] == rules.get("manual_rule")), None)
    rules["exits"], rules["manual_exit"] = exits, man or (exits[0]["id"] if exits else None)
    rules.pop("manual_rule", None)
    return rules


def _read(name: str, default):
    try:
        return json.loads((STATE / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return json.loads(json.dumps(default))


def _write(name: str, data) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = STATE / (name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE / name)


def _log(event: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({**event, "ts": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")


class Desk:
    def __init__(self) -> None:
        self.appkey = os.environ.get("TRADER_APPKEY", "").strip()
        self.secret = os.environ.get("TRADER_SECRETKEY", "").strip()
        self.is_mock = os.environ.get("TRADER_IS_MOCK", "1").strip() != "0"
        self.key_src = "매매 전용 키"
        if not (self.appkey and self.secret):
            # 10-19 사용자 "우선 임시배치키 넣어줘" — 매매 키 받기 전까지 배치 키로. 배치 키는 KIWOOM_IS_MOCK 계좌(실전/모의)를 따른다.
            self.appkey = os.environ.get("KIWOOM_BATCH_APPKEY", "").strip()
            self.secret = os.environ.get("KIWOOM_BATCH_SECRETKEY", "").strip()
            self.is_mock = os.environ.get("KIWOOM_IS_MOCK", "true").strip().lower() in ("1", "true", "yes")
            self.key_src = "임시: 배치 키"
        self.client = None
        if self.appkey and self.secret:
            from kiwoom_client import KiwoomClient
            self.client = KiwoomClient(self.appkey, self.secret, is_mock=self.is_mock)
        self.watch: list[str] = _read("watch.json", [])
        self.rules: dict = _split_exits(_read("rules.json", DEFAULT_RULES))
        self._load_mode()                                          # self.meta(청산 감시 상태) · self.day — 가상/실전 파일이 따로
        self.refs: dict = {}                                        # code -> 직전 거래일 {reg, aft, day, nxt}
        self._refc: dict = {}                                       # (code, day) -> 기준 종가
        self.plans: list = _read("plans.json", [])                   # 예약 분할 매수(날을 넘겨 유지)
        # 종목마다 기준일(10-19 사용자 "종목마다 기준일이 다르니까") — {code: "YYYYMMDD"}. 없으면 직전 거래일
        self.ref_days: dict = _read("ref_days.json", {})
        self.viewing: dict = {}                                     # 최근 60초 안에 화면에서 본 종목 -> 시각
        # 선정 일지(10-19 사용자 6번) — 고른 종목·기준일·매수/매도 체결이 쌓인다. 한 종목 한 줄, 다 팔면 닫히고 다시 고르면 새 줄
        self.journal: list = _read("journal.json", [])
        self.no_auto: set = set(_read("no_auto.json", []))
        self.paper_state: dict | None = _read("paper.json", None)   # 가상 매매 계좌(현금·보유·미체결)
        self.mkt: dict = {"chg": None, "t": 0.0}                    # 코스닥 지수 등락률(새 매수 멈춤용)         # 자동 매수 스위치를 끈 종목 — 매수 규칙이 안 본다(10-19 사용자)
        self.credit_codes: set = set(_read("credit_codes.json", []))   # 신용으로 산 종목 — 팔 때 신용 매도(kt10007)로
        self._ci: dict = {}
        self._wi: dict = {}
        self._fi: dict = {}                                        # (code, 기준일) -> (날짜, 고점 따라가기 정보)                                        # code -> (날짜, {credit, margin}) 하루 한 번 조회
        # (10-23) 켤 때 placed_day == 오늘인 계획의 단계를 전부 '오늘 걸림'으로 찍던 근접 발주 전 옮김 코드를 뺐다 — placed_day 는 이제
        # '감시 시작한 날'이라, 장중에 데스크를 다시 켜면 안 걸린 단계가 '주문 걸림'으로 보이고 그날은 안 샀다(엘리스 2차 86,700)
        self.deposit: dict | None = None
        self.holdings: list[dict] = []
        self.pending: list[dict] = []
        self.msgs: list[dict] = []
        self.names: dict = {}
        try:
            self.names = json.loads((ROOT / "data" / "stock_names.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self._new_day()

    # ── 공통 ──────────────────────────────────────────────
    # ── 가상 매매(10-19 사용자) — 규칙·근접 주문·청산은 그대로 돌고, 주문만 키움에 안 내고 이 안에서 체결한다 ──
    # 체결: 지정가 매수는 현재가 ≤ 주문가, 매도는 ≥ 주문가, 시장가는 바로(현재가). 수수료 0.015%·매도세 0.15%. 대기 순번은 안 따진다
    def paper_on(self) -> bool:
        return bool(self.rules["safety"].get("paper"))

    def _paper(self) -> dict:
        if not self.paper_state:
            cap = engine._num(self.rules["safety"].get("paper_capital"), 30_000_000) or 30_000_000
            self.paper_state = {"cash": float(cap), "start": float(cap), "hold": {}, "orders": [], "n": 0}
            _write("paper.json", self.paper_state)
        return self.paper_state

    def paper_reset(self) -> None:
        with _lock:
            self.paper_state = None
            self._paper()
            self._paper_account()
        self.note("가상 계좌를 처음부터 다시 시작")

    def _paper_submit(self, code: str, side: str, qty: int, price: int, market: bool, tag: str) -> dict:
        P = self._paper()
        if qty <= 0:
            return {"ok": False, "msg": "수량 0"}
        if side == "sell":
            held = P["hold"].get(code, {}).get("qty", 0) - sum(o["left"] for o in P["orders"] if o["code"] == code and o["side"] == "sell")
            if qty > held:
                return {"ok": False, "msg": f"가상: 보유 수량 부족({held}주)"}
        else:
            px = price if not market else (feed.quotes.get(code, {}).get("px") or 0)
            reserved = sum(o["left"] * o["price"] for o in P["orders"] if o["side"] == "buy")
            lev = self.buy_lev(code)[0]
            room = P["cash"] - reserved + self._paper_eval() * (lev - 1)   # 미수·신용 배수면 그만큼 더 산다
            if px and qty * px > room:
                return {"ok": False, "msg": f"가상: 주문가능금액 부족({int(room):,}원)"}
        P["n"] += 1
        ord_no = f"P{date.today():%m%d}{P['n']:05d}"
        P["orders"].append({"ord_no": ord_no, "code": code, "side": side, "qty": qty, "price": int(price), "market": market, "left": qty,
                            "time": datetime.now().strftime("%H:%M:%S")})
        tags = _read("tags.json", {})
        tags[ord_no] = tag
        _write("tags.json", tags)
        _write("paper.json", P)
        if market:
            self._paper_match(code)
        self._paper_account()                                       # 미체결 목록에 바로 — 안 그러면 다음 갱신 전 취소·남은 수량 계산이 이 주문을 못 봤다(10-23 점검)
        return {"ok": True, "msg": "가상 접수", "ord_no": ord_no}

    def _paper_eval(self) -> float:
        P = self._paper()
        return P["cash"] + sum(h["qty"] * (feed.quotes.get(c, {}).get("px") or h["avg"]) for c, h in P["hold"].items())

    def _paper_match(self, only: str | None = None) -> None:
        P = self._paper()
        changed = False
        for o in list(P["orders"]):
            if only and o["code"] != only:
                continue
            px = feed.quotes.get(o["code"], {}).get("px") or 0
            if not px or not (o["market"] or (px <= o["price"] if o["side"] == "buy" else px >= o["price"])):
                continue
            fp, q = (px if o["market"] else (min(px, o["price"]) if o["side"] == "buy" else max(px, o["price"]))), o["left"]
            h = P["hold"].setdefault(o["code"], {"qty": 0, "avg": 0.0})
            if o["side"] == "buy":
                P["cash"] -= fp * q * 1.00015
                h["avg"] = (h["avg"] * h["qty"] + fp * q) / (h["qty"] + q)
                h["qty"] += q
            else:
                P["cash"] += fp * q * (1 - 0.00015 - 0.002)       # 가상 매매도 매도 세금 0.20%(백테스트와 같게)
                h["qty"] -= q
                if h["qty"] <= 0:
                    P["hold"].pop(o["code"], None)
            P["orders"].remove(o)
            changed = True
            ev = {"ord_no": o["ord_no"], "code": o["code"], "side": o["side"], "status": "체결", "qty": q, "price": o["price"],
                  "left": 0, "fill_px": int(fp), "fill_qty": q, "t": time.time(), "paper": True}
            feed.order_events.append(ev)
            self.on_order(ev)
        if changed:
            _write("paper.json", P)
            self._paper_account()

    def _paper_account(self) -> None:
        P, tags = self._paper(), _read("tags.json", {})
        hold = []
        for c, h in P["hold"].items():
            px = feed.quotes.get(c, {}).get("px") or int(h["avg"])
            hold.append({"code": c, "name": self.name(c), "quantity": h["qty"], "avg_price": int(round(h["avg"])), "current_price": px,
                         "eval_amount": int(px * h["qty"]), "pl_amount": int((px - h["avg"]) * h["qty"]),
                         "pl_pct": (px / h["avg"] - 1) * 100 if h["avg"] else 0.0})
        reserved = sum(o["left"] * o["price"] for o in P["orders"] if o["side"] == "buy")
        self.deposit = {"deposit_krw": int(P["cash"]), "order_available_krw": int(P["cash"] - reserved), "d2_deposit_krw": int(P["cash"]),
                        "paper": True, "paper_start": int(P.get("start", 0))}
        self.holdings = hold
        self._sync_meta()
        self.pending = [{"ord_no": o["ord_no"], "code": o["code"], "name": self.name(o["code"]), "side": o["side"], "qty": o["qty"],
                         "price": o["price"], "left": o["left"], "time": o.get("time", ""), "mine": tags.get(o["ord_no"], "")}
                        for o in P["orders"]]

    def tg(self, text: str) -> None:
        """텔레그램 알림 — 판단 루프를 막지 않게 따로 보낸다. 토큰·채팅방은 .env(TELEGRAM_BOT_TOKEN/CHAT_ID)."""
        tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
        if not (tok and chat and self.rules["safety"].get("telegram", True)):
            return
        from backtesting.notifier import send_telegram
        threading.Thread(target=send_telegram, args=("[매매 데스크] " + text, tok, chat), daemon=True).start()

    # ── 선정 일지 ─────────────────────────────────────────
    def _jopen(self, code: str) -> dict | None:
        return next((j for j in reversed(self.journal) if j["code"] == code and not j.get("closed")), None)

    def journal_codes(self) -> set:
        return {j["code"] for j in self.journal if not j.get("closed")}

    def pick(self, code: str, ref_day: str | None, src: str) -> None:
        """ref_days 에 그동안의 기준일을 다 남긴다 — 백테스트가 기준일마다 따로 대입(10-22: 마지막 기준일만 남아 HT로보틱스가 0건)."""
        with _lock:
            j = self._jopen(code)
            if j:
                j["ref_day"] = ref_day or j.get("ref_day")
            else:
                j = {"code": code, "name": self.name(code), "picked": datetime.now().isoformat(timespec="minutes"),
                     "ref_day": ref_day, "src": src, "buys": [], "sells": []}
                self.journal.append(j)
            if ref_day:
                j["ref_days"] = sorted({*j.get("ref_days", []), ref_day})
            _write("journal.json", self.journal)

    def unpick(self, code: str) -> None:
        """목록에서 뺀 종목 — 지우지 않고 '뺌'으로 닫는다. 골랐던 종목은 백테스트 '선정 일지' 대상에 남아야 한다(10-22 사용자)."""
        with _lock:
            j = self._jopen(code)
            if j and not j["buys"]:
                j["closed"], j["dropped"] = datetime.now().isoformat(timespec="minutes"), True
                _write("journal.json", self.journal)

    def _jfill(self, ev: dict, tag: str) -> None:
        j = self._jopen(ev["code"])
        if not j:
            if ev["side"] != "buy":
                return
            self.pick(ev["code"], self.ref_day(ev["code"]), "직접 주문")
            j = self._jopen(ev["code"])
        j["buys" if ev["side"] == "buy" else "sells"].append([datetime.now().isoformat(timespec="minutes"), ev["fill_qty"], ev["fill_px"], tag])
        bq, sq = sum(x[1] for x in j["buys"]), sum(x[1] for x in j["sells"])
        if bq and sq >= bq:
            j["closed"] = datetime.now().isoformat(timespec="minutes")
        _write("journal.json", self.journal)

    def note(self, text: str, level: str = "info") -> None:
        with _lock:
            self.msgs = ([{"t": datetime.now().strftime("%H:%M:%S"), "text": text, "level": level}] + self.msgs)[:80]
        _log({"note": text, "level": level})

    # 가상·실전이 positions.json·day.json 을 같이 쓰면 바꿀 때마다 서로의 청산 규칙·손익이 지워지고 섞였다(10-23 점검) — 파일을 나눈다
    def _f(self, name: str) -> str:
        return name.replace(".json", "_paper.json") if self.paper_on() else name

    def _wd(self) -> None:
        _write(self._f("day.json"), self.day)

    def _wm(self) -> None:
        _write(self._f("positions.json"), self.meta)

    def _load_mode(self) -> None:
        self._mode = self.paper_on()
        # 처음 나눌 때 — 지금까지의 파일은 그때 켜져 있던 가상 매매가 쓰던 것이라 가상 쪽으로 옮겨 읽는다
        self.meta = _read(self._f("positions.json"), None)
        if self.meta is None:
            self.meta = _read("positions.json", {}) if self._mode else {}
        self.day = _read(self._f("day.json"), None)
        if self.day is None:
            self.day = _read("day.json", {}) if self._mode else {}

    def _new_day(self) -> None:
        if self.paper_on() != getattr(self, "_mode", None):         # 가상 ↔ 실전을 바꿈 — 그 모드 파일로
            self._load_mode()
            self.holdings, self.pending = [], []
        today = date.today().isoformat()
        if self.day.get("date") != today:
            self.day = {"date": today, "pnl_realized": 0, "orders": 0, "halted": None, "bought": {}}
            self._wd()
            # 키움 지정가는 장이 끝나면 사라진다 — 가상 주문도 같게(10-23 점검: 남은 가상 주문 + 다음 날 새 주문으로 같은 단계를 두 번 샀다)
            P = self.paper_state
            if P and P.get("orders"):
                md = date.today().strftime("%m%d")
                P["orders"] = [o for o in P["orders"] if str(o["ord_no"])[1:5] == md]
                _write("paper.json", P)
            # 익절 주문도 밤새 사라졌다 — 실제로 체결된 단계만 '끝'으로 두고 나머지는 오늘 다시 건다(10-23 점검: 둘째 날 익절이 안 걸렸다)
            for m in self.meta.values():
                m["takes_done"] = sorted(m.get("takes_filled") or [])
            self._wm()
        st = daily_facts._facts
        if st.get("for") != date.today() and not st["building"]:
            threading.Thread(target=daily_facts.build, daemon=True, name="trader-facts").start()

    def sub_codes(self) -> list[str]:
        """실시간 구독 = 고른 종목 + 보유 + 지금 보고 있는 종목(목록에 없어도 호가가 바로 나오게)."""
        now = time.time()
        self.viewing = {c: t for c, t in self.viewing.items() if now - t < 60}   # 화면이 여럿이어도 각자 보는 종목을 다 구독
        return self.watch + [h["code"] for h in self.holdings] + list(self.viewing) + [p["code"] for p in self.plans if p["active"]]

    def ready(self) -> str | None:
        if not self.client:
            return "매매 앱키가 없습니다 — .env 에 TRADER_APPKEY / TRADER_SECRETKEY 를 넣고 다시 켜 주세요"
        return None

    def is_active(self, now: datetime) -> bool:
        return self._is_trading_day(now.date()) and (7 * 60 + 50) <= now.hour * 60 + now.minute < 20 * 60 + 5

    def name(self, code: str) -> str:
        return self.names.get(code, code)

    def rule(self, rid: str | None) -> dict | None:
        return next((r for r in self.rules["rules"] if r["id"] == rid), None)

    def exit_rule(self, eid: str | None) -> dict | None:
        """청산 규칙. 보유 종목 메타의 "rule" 칸과 예약·당일 매수 기록의 "rule" 칸은 이 id 다(10-19 분리 뒤)."""
        return next((r for r in self.rules.get("exits", []) if r["id"] == eid), None)

    # ── 기준 종가(정규장 = KRX 일봉, 애프터 = NXT(_NX) 일봉, 둘 다 '오늘 전' 마지막 봉) ──
    def ref(self, code: str, day: str | None = None) -> dict:
        """기준 종가. day=None 이면 '오늘 전' 마지막 거래일, "YYYYMMDD" 면 그날(10-19 사용자 "기준날 기준으로 날짜도 지정").

        10-19 실측(HT로보틱스·삼성전자·에스엠벡셀)으로 정의를 고쳤다:
        - **정규장 종가 = 15:30 종가 단일가 봉의 값 = 다음 날 기준가**(ka10001 base_pric 와 같다: 9,010 · 215,500 · 3,110).
        - **애프터 종가 = 그날 20:00 까지 마지막 체결 = 키움 일봉(ka10081) 종가**(HT로보틱스 10-16 일봉 8,830 = 19:59 봉).
          키움 일봉 종가는 정규장 종가가 아니다 — 처음엔 일봉을 정규장으로 써서 호가 등락률이 실제(+0.33%)와 달랐다(+2.4%).
        직전 거래일 정규장은 기준가(ka10001) 한 번, 지난 날짜는 1분봉을 그날까지 거슬러 받아 15:30 이하 마지막 봉."""
        today = date.today().strftime("%Y%m%d")
        key = (code, day or "prev:" + today)
        r = self._refc.get(key)
        if r:
            return r
        out = {"day": None, "reg": 0, "aft": 0, "nxt": True}
        if self.client:
            try:
                rows = [x for x in (self.client.get_daily_chart(code).get("stk_dt_pole_chart_qry", []) or []) if x.get("dt")]
                pick = [x for x in rows if (str(x["dt"]) == day if day else str(x["dt"]) < today)]
                if pick:
                    out["day"], out["aft"] = str(pick[0]["dt"]), _absint(pick[0]["cur_prc"])
            except Exception as e:                                      # noqa: BLE001
                self.note(f"{self.name(code)} 애프터 종가(일봉) 조회 실패: {e}", "warn")
            try:
                if not day:
                    out["reg"] = _absint(self.client.request_tr("ka10001", {"stk_cd": code}, path="/api/dostk/stkinfo").get("base_pric"))
                elif out["day"]:
                    out["reg"] = self._local_reg_close(code, out["day"]) or self._close_1530(code, out["day"])
            except Exception as e:                                      # noqa: BLE001
                self.note(f"{self.name(code)} 정규장 종가 조회 실패: {e}", "warn")
        if out["reg"] and out["aft"]:
            self._refc[key] = out
        if not day:
            self.refs[code] = out
        return out

    def _local_reg_close(self, code: str, day: str) -> int:
        """지난 날짜 정규장 종가를 로컬에서 — 신고대금 장부와 같은 표(KRX 1분봉 묶음 'm' 또는 KRX 일봉 'k').
        10-19 실측: 삼성전자 4개 날짜가 키움 15:30 봉과 같고 1초 안(키움 1분봉 거슬러 받기는 16~19초)."""
        try:
            from backtesting.value_ledger import regular_daily_rows
            row = next((r for r in (regular_daily_rows(code) or []) if r[0] == day), None)
        except Exception:                                               # noqa: BLE001 — 없으면 키움으로
            return 0
        return int(row[4]) if row and row[6] in ("m", "k") else 0

    def _close_1530(self, code: str, day: str) -> int:
        """그날 15:30 이하 마지막 1분봉 종가. 1분봉은 최신부터 오므로 그날을 지나칠 때까지 페이지를 넘긴다(최대 12쪽 ≈ 2~4주)."""
        cont, nk, best = "N", "", None
        for _ in range(12):
            pg = self.client.request_tr("ka10080", {"stk_cd": code, "tic_scope": "1", "upd_stkpc_tp": "1"}, cont_yn=cont, next_key=nk)
            rows = pg.get("stk_min_pole_chart_qry", []) or []
            for x in rows:
                t = str(x.get("cntr_tm", ""))
                if t[:8] == day and t[8:12] <= "1530" and (best is None or t > best[0]):
                    best = (t, _absint(x.get("cur_prc")))
            if best or (rows and str(rows[-1].get("cntr_tm", ""))[:8] < day):
                break
            if self.client.last_cont_yn != "Y" or not self.client.last_next_key:
                break
            cont, nk = "Y", self.client.last_next_key
        if not best:
            raise RuntimeError(f"{day} 1분봉이 너무 오래돼 키움에서 못 받습니다(약 2~4주 안만)")
        return best[1]

    def snap(self, code: str) -> dict:
        q, r = feed.quotes.get(code, {}), self.refs.get(code, {})
        h = next((x for x in self.holdings if x["code"] == code), None)
        px = q.get("px") or (h["current_price"] if h else 0)
        reg = r.get("reg") or 0
        # 등락률은 실시간 값(0B 12 = 키움이 기준가로 계산)을 먼저 — 없을 때만 기준가로 계산
        return {"px": px, "chg": q.get("chg") if q.get("chg") is not None and q.get("px") else ((px / reg - 1) * 100 if reg and px else None),
                "high": q.get("high"),
                "value": q.get("value"), "reg": reg, "aft": r.get("aft") or 0, "strength": q.get("strength"),
                "facts": daily_facts.get(code), "vref": self.vref(code),
                "value_reg": self.reg_value(code) if self._need_reg() else None,
                "ma_gap": self._ma_gap(code) if self._need_field("60선 차이(애프터−정규장)") else None}

    def _need_field(self, f: str) -> bool:
        return any(r.get("on") and any(c and c[0] == f for c in (r.get("conds") or [])) for r in self.rules["rules"])

    def _ma_gap(self, code: str) -> float | None:
        """애프터(통합) 15분봉 60선 ÷ 정규장 15분봉 60선 − 1(%) — 둘 다 1분 기억."""
        a, r = self.ma60_15(code, "aft"), self.ma60_15(code, "reg")
        return (a / r - 1) * 100 if a and r else None

    REG_FIELDS = ("거래대금(정규장)", "52주 신고대금 대비(정규장)")

    def _need_reg(self) -> bool:
        """켜진 매수 규칙에 정규장 대금 조건이 있을 때만 정규장 대금을 잰다(키움 1분봉 조회라)."""
        return any(r.get("on") and any(c and c[0] in self.REG_FIELDS for c in (r.get("conds") or [])) for r in self.rules["rules"])

    def reg_value(self, code: str) -> int | None:
        """오늘 정규장(09:00~15:30) 거래대금(원) — 통합(_AL) 1분봉의 종가 × 거래량 합(신고대금 장부 ①과 같은 방식, 10-20 사용자
        "거래대금도 정규장 기준"). 1분 기억, 15:31 뒤 한 번 재면 그날은 고정. 09:00 전은 0, 못 받으면 None."""
        now = datetime.now()
        hm, t = now.strftime("%H%M"), now.strftime("%Y%m%d")
        if hm < "0900":
            return 0
        c = self.__dict__.setdefault("_rv", {})
        hit = c.get(code)
        if hit and hit[0] == t and (hit[3] or time.time() - hit[1] < 60):
            return hit[2]
        v = None
        try:
            for n in (1, 2):                                        # 한 쪽이 09:00 까지 안 닿으면(오늘 봉이 한 쪽보다 많으면) 두 쪽
                rows = [x for pg in self.client.get_minute_chart_pages(code + "_AL", tic_scope="1", max_pages=n) for x in (pg.get("stk_min_pole_chart_qry") or [])]
                old = min((str(x.get("cntr_tm", "")) for x in rows), default="")
                if not old or old[:8] < t or old[8:12] <= "0900":
                    break
            v = sum(_absint(x.get("cur_prc")) * _absint(x.get("trde_qty")) for x in rows
                    if str(x.get("cntr_tm", ""))[:8] == t and "0900" <= str(x.get("cntr_tm", ""))[8:12] <= "1530")
        except Exception:                                           # noqa: BLE001 — 다음 분에 다시
            pass
        c[code] = (t, time.time(), v, v is not None and hm > "1531")
        return v

    # ── 계좌 ──────────────────────────────────────────────
    def refresh_account(self) -> None:
        if self.paper_on():
            with _lock:
                self._paper_account()
            return
        if not self.client:
            return
        from backtesting.account_status import _deposit_snapshot, _holdings_snapshot
        dep, hold = _deposit_snapshot(self.client), _holdings_snapshot(self.client)
        with _lock:
            if dep is not None:
                self.deposit = dep
            if hold is not None:
                self.holdings = [h for h in hold if h["quantity"] > 0]
                self._sync_meta()
                gone = self.credit_codes - {h["code"] for h in self.holdings}
                if gone:
                    self.credit_codes -= gone
                    _write("credit_codes.json", sorted(self.credit_codes))

    def refresh_pending(self) -> None:
        if self.paper_on():
            return                                                  # 가상 미체결은 _paper_account 가 채운다
        if not self.client:
            return
        from backtesting.order_execution import _pending_rows
        try:
            rows = _pending_rows(self.client.get_pending_orders())
        except Exception as e:                                          # noqa: BLE001
            self.note(f"미체결 조회 실패: {e}", "warn")
            return
        mine = self._my_orders()
        out = []
        # ka10075 행 필드명(ord_qty·ord_pric·oso_qty·io_tp_nm·tm)은 실계좌 실측 전 — order_execution._REMAINING_QTY_KEYS 와 같은 사정
        for r in rows:
            ord_no = str(r.get("ord_no") or "")
            code = str(r.get("stk_cd") or "").removeprefix("A")[:6]
            side_raw = str(r.get("io_tp_nm") or r.get("trde_tp") or "")
            out.append({"ord_no": ord_no, "code": code, "name": r.get("stk_nm") or self.name(code),
                        "side": "sell" if "매도" in side_raw else "buy",
                        "qty": abs(int(r.get("ord_qty") or 0)), "price": abs(int(r.get("ord_pric") or 0)),
                        "left": abs(int(r.get("oso_qty") or 0)), "time": str(r.get("tm") or ""),
                        "mine": mine.get(ord_no, {}).get("tag", "")})
        with _lock:
            self.pending = out

    def _my_orders(self) -> dict:
        """orders.jsonl 에서 이 데스크가 낸 주문번호 → 태그(take:1 등). 남이 낸 주문(영웅문)은 건드리지 않는다.
        두 파일이 안 바뀌었으면 읽어 둔 걸 쓴다 — 보유 종목마다 매초 부르는데 주문 기록은 계속 쌓인다(10-20 최적화)."""
        def mt(f):
            try:
                st = os.stat(f)
                return st.st_mtime_ns, st.st_size
            except OSError:
                return None
        key = (mt(ORDER_LOG), mt(STATE / "tags.json"))
        hit = getattr(self, "_mo", None)
        if hit and hit[0] == key:
            return hit[1]
        out = self._my_orders_read()
        self._mo = (key, out)
        return out

    def _my_orders_read(self) -> dict:
        out = {k: {"tag": v, "code": None} for k, v in _read("tags.json", {}).items() if str(k).startswith("P")}   # 가상 주문
        try:
            with open(ORDER_LOG, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    resp = rec.get("response") or {}
                    if rec.get("event") == "submitted" and resp.get("ord_no"):
                        out[str(resp["ord_no"])] = {"tag": rec.get("tag", ""), "code": rec.get("stock_code")}
        except OSError:
            pass
        tags = _read("tags.json", {})
        for k, v in out.items():
            v["tag"] = tags.get(k, v["tag"])
        return out

    def _sync_meta(self) -> None:
        held = {h["code"]: h for h in self.holdings}
        changed = False
        for code, h in held.items():
            m = self.meta.get(code)
            if m is None:
                # 이 데스크로 산 것만 자동 청산을 건다. 원래 있던 종목(영웅문 등)은 화면에서 규칙을 고를 때까지 손대지 않는다
                rid = self.day["bought"].get(code, {}).get("rule")
                self.meta[code] = {"init_qty": h["quantity"], "high": h["current_price"], "opened": date.today().isoformat(),
                                   "takes_done": [], "breakeven": False, "rule": rid, "seen_qty": h["quantity"]}
                changed = True
                continue
            # 추가 매수 — take_sig 를 지우면 tick 이 옛 익절 주문을 거두고 새 평단·수량으로 다시 건다
            # (10-23 점검: 옛 익절이 남고 2차는 '건너뜀', 익절 일부 체결 뒤 추가 매수는 아예 못 알아챘다 — init_qty 가 아니라 마지막 본 수량과 비교)
            if h["quantity"] > m.get("seen_qty", m["init_qty"]):
                m.pop("take_sig", None)
                changed = True
            if m.get("seen_qty") != h["quantity"]:
                m["seen_qty"], changed = h["quantity"], True
        for code in [c for c in self.meta if c not in held]:
            del self.meta[code]
            changed = True
        if changed:
            self._wm()

    # ── 주문 ──────────────────────────────────────────────
    def credit_info(self, code: str) -> dict:
        """종목 신용 가능(kt20017 '< A군 신용융자 가능 >')·미수 증거금률(kt00011 stk_profa_rt '40%') — 하루 한 번 조회해 둔다."""
        today = date.today().isoformat()
        hit = self._ci.get(code)
        if hit and hit[0] == today:
            return hit[1]
        info = {"credit": None, "credit_text": None, "margin": None}
        if self.client:
            try:
                t = str(self.client.request_tr("kt20017", {"stk_cd": code}, path="/api/dostk/stkinfo").get("crd_alow_yn") or "")
                info["credit_text"] = t.strip("<> ").strip() or None
                info["credit"] = None if not t else ("불가" not in t)
            except Exception:                                       # noqa: BLE001 — 모르면 None(화면에 '확인 못 함')
                pass
            try:
                info["margin"] = engine._num(self.client.request_tr("kt00011", {"stk_cd": code}, path="/api/dostk/acnt").get("stk_profa_rt"))
            except Exception:                                       # noqa: BLE001
                pass
        self._ci[code] = (today, info)
        return info

    WARN = {"2": "정리매매", "3": "단기과열", "4": "투자위험", "5": "투자경고"}

    def warn_info(self, code: str) -> dict:
        """시장경보 상태 — 하루 한 번. ka10100 auditInfo('투자주의'·'투자경고'·'투자위험'…, 10-20 에스엠벡셀 실측: orderWarning 은 '0'인데
        auditInfo='투자주의'·state='증거금100%') 를 먼저 보고, 비었으면 orderWarning(2 정리매매 · 3 단기과열 · 4 투자위험 · 5 투자경고)."""
        today = date.today().isoformat()
        hit = self._wi.get(code)
        if hit and hit[0] == today:
            return hit[1]
        info = {"code": None, "text": None}
        if self.client:
            try:
                r = self.client.request_tr("ka10100", {"stk_cd": code}, path="/api/dostk/stkinfo")
                if "orderWarning" in r or "auditInfo" in r:
                    v = str(r.get("orderWarning") or "0").strip()
                    a = str(r.get("auditInfo") or "").strip()
                    info = {"code": v, "text": (a if a and a not in ("정상", "해당없음", "0") else None) or self.WARN.get(v)}
            except Exception:                                       # noqa: BLE001 — 모르면 경고 아닌 걸로(화면에 '확인 못 함')
                pass
        self._wi[code] = (today, info)
        return info

    def levels_for(self, L: dict, code: str) -> list:
        """매수 단계 — 투자경고 종목은 따로 정한 % 한 번에(10-20 사용자 "투자경고 종목은 −5%로")."""
        w = L.get("warn") or {}
        if w.get("on") and self.warn_info(code).get("text") in (w.get("kinds") or ["투자경고"]):
            return [[str(w.get("pct") or "-5"), "100"]]
        # 단계 [pct, 금액%] 또는 [pct, 금액%, "ma", 근접%] — "ma" 면 15분봉 60선 × (1+pct%) ±근접% 안에서 산다(10-20 사용자 1차·2차)
        return L.get("levels", [])

    def ma_band(self, code: str, base: str, s_: dict) -> tuple | None:
        """60선 단계의 (60선, 아래, 위) — 중심 = 60선 × (1+pct%), 그 ±band% 안이면 산다. 60선을 못 받았으면 None."""
        m = self.ma60_15(code, base)
        if not m:
            return None
        c, b = m * (1 + (engine._num(s_.get("pct"), 0) or 0) / 100), abs(engine._num(s_.get("band"), 1) or 0) / 100
        return m, c * (1 - b), c * (1 + b)

    def ma60_15(self, code: str, base: str) -> int:
        return self._ma15_pair(code, base)[0]

    def ma60_15_prev(self, code: str, base: str) -> int:
        """하루(15분봉 26개) 전 60선 — '60선 꺾이면 끝'(10-21 사용자). 못 구하면 0."""
        return self._ma15_pair(code, base)[1]

    def _ma15_pair(self, code: str, base: str) -> tuple:
        """15분봉 60선(10-20 사용자 "1차 매수를 15분봉 60선에"). 차트 15분과 같은 봉: 정규장 기준 = KRX 봉 09:00~15:30만,
        애프터 기준 = 통합(_AL) 08~20시 봉. 만드는 중인 마지막 봉 포함. 1분 기억, 못 받거나 60봉이 안 되면 0(그 단계는 안 삼)."""
        c = self.__dict__.setdefault("_ma15", {})
        hit = c.get((code, base))
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        v = (0, 0)
        try:
            pages = self.client.get_minute_chart_pages(code if base == "reg" else code + "_AL", tic_scope="15", max_pages=1)
            rows = [x for pg in pages for x in (pg.get("stk_min_pole_chart_qry") or [])]
            bars = [(str(x.get("cntr_tm", ""))[:12], _absint(x.get("cur_prc"))) for x in reversed(rows)
                    if base != "reg" or "0900" <= str(x.get("cntr_tm", ""))[8:12] <= "1530"]
            bars = [b for b in bars if b[1]]
            self.__dict__.setdefault("_b15", {})[(code, base)] = bars   # 마지막 = 만드는 중인 봉 — 60선 위 마감 확인용(10-30)
            closes = [b[1] for b in bars]
            if len(closes) >= 60:
                v = (int(sum(closes[-60:]) / 60), int(sum(closes[-86:-26]) / 60) if len(closes) >= 86 else 0)
        except Exception:                                           # noqa: BLE001 — 다음 분에 다시
            pass
        c[(code, base)] = (time.time(), v)
        return v

    def _ma_confirmed(self, p: dict, s_: dict, mb: tuple, px: int) -> int:
        """15분봉 60선 위 마감 N개 확인(10-30 사용자) — 60선 범위에 닿은 봉부터, 끝난 15분봉 종가가 그 봉까지의 60선 위로
        N개 연달아 마감하면 지금가 +0.3% 지정가를 돌려준다. 하나라도 60선 아래 마감이면 처음부터(다시 닿기를 기다림). 아니면 0."""
        src = s_.get("src") or p["base"]
        self._ma15_pair(p["code"], src)
        bars = self.__dict__.get("_b15", {}).get((p["code"], src)) or []
        if len(bars) < 61:
            return 0
        if not s_.get("arm"):
            if mb[1] <= px <= mb[2]:
                s_["arm"] = bars[-1][0]                             # 닿은 봉(만드는 중) — 이 봉부터 마감을 센다
                self.note(f"{p['name']} 15분봉 60선 닿음 — 60선 위 마감 {p['ma_confirm']}개 확인 뒤 삼")
            return 0
        closes = [b[1] for b in bars]
        n = 0
        for j in range(len(bars) - 1):                              # 끝난 봉만
            if bars[j][0] < s_["arm"]:
                continue
            if j < 59 or closes[j] <= sum(closes[j - 59:j + 1]) / 60:
                s_.pop("arm")
                self.note(f"{p['name']} 15분봉 종가 {closes[j]:,}가 60선 아래 마감 — 확인 처음부터")
                return 0
            n += 1
            if n >= p["ma_confirm"]:
                return engine.floor_tick(px * 1.003)
        return 0

    def buy_lev(self, code: str) -> tuple[float, str]:
        sf = self.rules["safety"]
        if (sf.get("buy_mode") or "cash") == "cash":
            return 1.0, "cash"
        ci = self.credit_info(code)
        return engine.leverage(sf, ci.get("margin"), ci.get("credit"))

    def _submit(self, code: str, side: str, qty: int, price: int, market: bool, tag: str, credit: bool = False) -> dict:
        from backtesting.order_execution import submit_order
        if err := self.ready():
            return {"ok": False, "msg": err}
        if self.paper_on():
            r = self._paper_submit(code, side, int(qty), 0 if market else int(price), market, tag)
            how = "시장가" if market else f"{price:,}원"
            self.note(f"{'가상 접수' if r['ok'] else '가상 실패'} · {self.name(code)} {qty:,}주 {how} {'매수' if side == 'buy' else '매도'}"
                      f" ({tag}){'' if r['ok'] else ' — ' + r['msg']}", "info" if r["ok"] else "error")
            if r["ok"] and side == "buy":
                with _lock:
                    self.day["orders"] += 1
                    self._wd()
            return r
        if side == "sell" and code in self.credit_codes:
            credit = True                                           # 신용으로 산 종목은 신용 매도로 갚는다
        t = submit_order(self.client, stock_code=code, side=side, quantity=int(qty), price=0 if market else int(price),
                         approved=True, order_type="3" if market else "0", client_order_id=uuid.uuid4().hex,
                         max_retries=1, log_path=ORDER_LOG, credit=credit)
        if credit:
            tag = f"{tag} [신용]"
        ok = t.status == "pending"
        if ok and t.ord_no:
            tags = _read("tags.json", {})
            tags[str(t.ord_no)] = tag
            _write("tags.json", tags)
            with _lock:                                             # 미체결 조회(15초)를 기다리지 않고 바로 — 같은 이유(10-23 점검)
                self.pending = self.pending + [{"ord_no": str(t.ord_no), "code": code, "name": self.name(code), "side": side, "qty": int(qty),
                                                "price": 0 if market else int(price), "left": int(qty), "time": datetime.now().strftime("%H%M%S"), "mine": tag}]
        how = "시장가" if market else f"{price:,}원"
        self.note(f"{'접수' if ok else '실패'} · {self.name(code)} {qty:,}주 {how} {'매수' if side == 'buy' else '매도'}"
                  f" ({tag}){'' if ok else ' — ' + t.detail}", "info" if ok else "error")
        if ok and side == "buy":
            with _lock:
                self.day["orders"] += 1
                self._wd()
        return {"ok": ok, "msg": t.detail, "ord_no": t.ord_no}

    def equity(self) -> int:
        dep = (self.deposit or {}).get("deposit_krw", 0)
        return dep + sum(h["eval_amount"] for h in self.holdings)

    def day_pnl(self) -> int:
        """오늘 실현 + 지금 보유분 평가손익. ponytail: 평가손익은 산 날부터 누적이라 어제 산 종목은 어제 몫까지 든다 — 하루 손실 한도가 조금 일찍 걸리는 쪽(안전)."""
        return int(self.day.get("pnl_realized", 0)) + sum(h["pl_amount"] for h in self.holdings)

    def buy_block(self, notional: int) -> str | None:
        sf = self.rules["safety"]
        if sf.get("halt_on_disconnect") and not feed.status()["connected"]:
            return "실시간 연결이 끊겨 새 매수를 멈췄습니다"
        md, ms = engine._num(sf.get("mkt_drop"), None), int(engine._num(sf.get("max_stops"), 0) or 0)
        if md and self.mkt["chg"] is not None and self.mkt["chg"] <= -abs(md):
            return f"코스닥 {self.mkt['chg']:+.2f}% — −{abs(md):g}% 이하라 새 매수를 멈췄습니다"
        if ms and int(self.day.get("stops", 0)) >= ms:
            return f"오늘 손절 {self.day.get('stops')}번 — {ms}번이면 그날 새 매수를 멈춥니다"
        return engine.safety_block(self.rules["safety"], {**self.day, "pnl": self.day_pnl()}, self.meta_positions(),
                                   notional, self.equity())

    def meta_positions(self) -> list[dict]:
        return [{"qty": h["quantity"]} for h in self.holdings]

    def buy(self, code: str, qty: int, price: int, market: bool, tag: str = "수동", rule: str | None = None) -> dict:
        notional = qty * (price or self.snap(code)["px"])
        if why := self.buy_block(notional):
            self.note(f"매수 막음 · {self.name(code)} — {why}", "warn")
            return {"ok": False, "msg": why}
        lev, how = self.buy_lev(code)
        # 새로 잡는 자리면 지금 고른 청산 규칙으로 — 그날 처음 산 때만 적던 때는, 다 팔고 다시 사면 아침 규칙이 다시 붙었다
        # (10-23 HT로보틱스: 12:43 '10%' 로 바꿨는데 12:47·12:53 매수에 '10% ~ 20%'). 들고 있는 종목 추가 매수는 그 자리 규칙 그대로.
        # 보내기 전에 적는다 — 가상 시장가는 보내는 중에 체결돼 보유 메타가 먼저 만들어진다(점검: 규칙 None·옛 규칙)
        fresh = not any(h["code"] == code for h in self.holdings)
        b = self.day["bought"].get(code)
        if b is None or fresh:
            self.day["bought"][code] = {"key": "manual", **(b or {}), "rule": rule or self.rules.get("manual_exit"), "t": datetime.now().strftime("%H:%M:%S")}
        r = self._submit(code, "buy", qty, price, market, tag + (" [미수]" if how == "margin" else ""), credit=how == "credit")
        if not r["ok"] and (b is None or fresh):
            if b is None:
                self.day["bought"].pop(code, None)
            else:
                self.day["bought"][code] = b
        self._wd()
        return r

    def set_position_rule(self, code: str, rid: str | None) -> None:
        with _lock:
            m = self.meta.get(code)
            if m is not None:
                m["rule"] = rid if self.exit_rule(rid) else None
                self._wm()

    def sell(self, code: str, qty: int, price: int, market: bool, tag: str = "수동") -> dict:
        return self._submit(code, "sell", qty, price, market, tag)

    def cancel(self, ord_no: str, code: str) -> dict:
        if str(ord_no).startswith("P"):                            # 가상 주문
            P = self._paper()
            P["orders"] = [o for o in P["orders"] if o["ord_no"] != ord_no]
            _write("paper.json", P)
            self._paper_account()
            self.note(f"가상 취소 · {self.name(code)} 주문 {ord_no}")
            return {"ok": True, "msg": ""}
        if err := self.ready():
            return {"ok": False, "msg": err}
        try:
            r = self.client.cancel_order(ord_no, code, quantity=0)
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": str(e)}
        ok = r.get("return_code") == 0
        if ok:
            with _lock:
                self.pending = [x for x in self.pending if x["ord_no"] != ord_no]
        self.note(f"취소 {'접수' if ok else '실패'} · {self.name(code)} 주문 {ord_no}{'' if ok else ' — ' + str(r.get('return_msg'))}",
                  "info" if ok else "error")
        return {"ok": ok, "msg": r.get("return_msg", "")}

    def modify(self, ord_no: str, code: str, price: int) -> dict:
        """지정가 단가 정정(10-23 사용자 "취소하고 다시 매도 거는거 번잡스러워", 매수도) — 남은 수량 그대로, 태그도 이어 붙인다."""
        if price <= 0 or engine.floor_tick(price) != price:
            return {"ok": False, "msg": f"호가 단위에 맞지 않는 가격 {price:,}"}
        if str(ord_no).startswith("P"):                            # 가상 주문 — 그 주문의 가격만 바꾸고 바로 다시 맞춰 본다
            P = self._paper()
            o = next((x for x in P["orders"] if x["ord_no"] == ord_no), None)
            if not o:
                return {"ok": False, "msg": "그 주문이 없습니다(이미 체결·취소)"}
            if o["side"] == "buy":                                   # 올려 사면 돈이 더 묶인다 — 접수 때와 같은 계산
                reserved = sum(x["left"] * x["price"] for x in P["orders"] if x["side"] == "buy" and x is not o)
                room = P["cash"] - reserved + self._paper_eval() * (self.buy_lev(code)[0] - 1)
                if o["left"] * price > room:
                    return {"ok": False, "msg": f"가상: 주문가능금액 부족({int(room):,}원)"}
            old, o["price"], o["market"] = o["price"], int(price), False
            _write("paper.json", P)
            self.note(f"가상 정정 · {self.name(code)} {o['left']:,}주 {old:,} → {price:,}원")
            self._paper_match(code)
            self._paper_account()
            return {"ok": True, "msg": ""}
        if err := self.ready():
            return {"ok": False, "msg": err}
        o = next((x for x in self.pending if x["ord_no"] == ord_no), None)
        if not o:
            return {"ok": False, "msg": "그 주문이 없습니다(이미 체결·취소)"}
        try:
            r = self.client.modify_order(ord_no, code, int(o["left"]), price)
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": str(e)}
        ok, new = r.get("return_code") == 0, str(r.get("ord_no") or "")
        if ok and new:                                                  # 새 주문번호도 이 데스크 주문으로(익절 단계·태그가 이어진다)
            tag = self._my_orders().get(ord_no, {}).get("tag", "")
            tags = _read("tags.json", {})
            tags[new] = tag
            _write("tags.json", tags)
            with open(ORDER_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"event": "submitted", "response": {"ord_no": new}, "tag": tag, "stock_code": code,
                                    "modified_from": ord_no, "t": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
        self.note(f"정정 {'접수' if ok else '실패'} · {self.name(code)} {o['price']:,} → {price:,}원{'' if ok else ' — ' + str(r.get('return_msg'))}",
                  "info" if ok else "error")
        return {"ok": ok, "msg": r.get("return_msg", "")}

    def _cancel_my_sells(self, code: str) -> None:
        mine = self._my_orders()
        for p in list(self.pending):
            if p["code"] == code and p["side"] == "sell" and p["ord_no"] in mine:
                self.cancel(p["ord_no"], code)

    def exit_all(self, code: str, why: str) -> dict:
        """전량 시장가 매도 — 걸어 둔 익절 매도부터 취소한다(안 그러면 수량 부족으로 거부)."""
        h = next((x for x in self.holdings if x["code"] == code), None)
        if not h:
            return {"ok": False, "msg": "보유 없음"}
        self._cancel_my_sells(code)
        self.tg(f"청산 · {self.name(code)} {h['quantity']:,}주 — {why}")
        time.sleep(0.3)
        now = datetime.now()
        if 9 * 60 <= now.hour * 60 + now.minute < 15 * 60 + 20:
            return self.sell(code, h["quantity"], 0, True, why)
        # 정규장 밖(NXT 시간)은 시장가가 막힐 수 있어 2% 아래 지정가로 — 매수호가가 그보다 위면 그 값에 바로 체결된다
        px = self.snap(code)["px"] or h["current_price"]
        return self.sell(code, h["quantity"], engine.floor_tick(px * 0.98), False, why)

    # ── 예약 분할 매수: 기준일 종가 × (1+pct) 지정가를 '유지' 기간 동안 매일 다시 건다 ─────────
    # 키움 지정가는 그날 장이 끝나면 사라진다. 그래서 체결 안 된 단계는 거래일마다 다시 낸다.
    # 기준일을 고르면 가격이 고정, 비우면 매일 '직전 거래일' 종가로 다시 계산한다.
    # 근접 발주(10-19 사용자 2번): 미리 다 걸면 주문 금액이 전부 주문가능금액에서 묶여 종목을 몇 개 못 건다.
    # 그래서 현재가가 단계 가격의 near_pct% 위까지 내려왔을 때만 실제 주문을 낸다 — 돈은 체결 직전에만 묶인다.
    # 장 시작부터 그 아래면 바로 걸려 시가 근처에 체결된다(미리 걸어 둔 것과 같다).
    def create_plan(self, code: str, base: str, ref_day: str | None, stages: list, keep: dict, tag: str = "분할매수",
                    rule: str | None = None, guard: dict | None = None, gap: dict | None = None, drop: dict | None = None,
                    follow: dict | None = None, ma_stop: dict | None = None, peak_stop: dict | None = None,
                    ma_turn: dict | None = None, rebuy: dict | None = None, c_near: dict | None = None,
                    ma_confirm: dict | None = None) -> dict:
        r = self.ref(code, ref_day)
        bp = r.get(base) or 0
        if not bp:
            return {"ok": False, "msg": f"{ref_day or '직전 거래일'} {'정규장' if base == 'reg' else '애프터'} 종가를 못 받았습니다"}
        st = []
        for s_ in stages:
            pct, amt = engine._num(s_.get("pct")), int(engine._num(s_.get("amt"), 0) or 0)
            if pct is None or amt <= 0:
                continue
            ex = {k: s_[k] for k in ("ma", "band", "t0", "t1", "src") if s_.get(k) is not None}
            mb = self.ma_band(code, ex.get("src") or base, {"pct": pct, **ex}) if ex.get("ma") else None   # 60선을 못 받았으면 기준가 %로 자리만 — 주문은 60선이 있을 때만
            price = engine.floor_tick(mb[2] if mb else bp * (1 + pct / 100))
            if amt // price > 0:
                st.append({"pct": pct, "amt": amt, "price": price, "qty": int(amt // price), "filled": 0,
                           **ex, **({"ma_px": mb[0]} if mb else {})})
        if not st:
            return {"ok": False, "msg": "금액이 작아 살 수 있는 수량이 없습니다"}
        today = date.today()
        until = (self._days_after(ref_day, keep) if ref_day and (keep or {}).get("mode") == "days"
                 else engine.keep_until(keep, datetime.now(), self._is_trading_day))
        plan = {"id": uuid.uuid4().hex[:8], "code": code, "name": self.name(code), "base": base, "ref_day": ref_day,
                "base_px": bp, "nxt": r.get("nxt", True), "stages": st, "keep": keep, "until": until, "tag": tag, "rule": rule,
                "created": datetime.now().isoformat(timespec="seconds"), "placed_day": None, "active": True, "status": "대기"}
        if ref_day == today.strftime("%Y%m%d"):
            # 신고대금 당일 예약(10-21 사용자) — 오늘 종가가 아직 없어 기준가는 지금 값(자리만). 오늘은 60선 단계만 사고,
            # 종가 % 단계·급락/갭/버림 판단은 다음 거래일 아침 기준가를 오늘 종가로 고친 뒤부터
            plan["same_day"] = True
        if guard and guard.get("on"):
            # 급락 피하기(10-19 사용자): 기준일 다음 거래일은 정한 시각까지 사지 않고 지켜본다 — 그 사이 저가가 기준가 −pct% 이하면 이 예약을 버린다.
            # 9~10월 통합 분봉으로 정하고 2025-07~2026-08 정규장 1분봉(보지 않은 기간)에서 확인: 조건 없음 −2,657만 → +656만(예산 3,000만, 405건)
            d = datetime.strptime(ref_day, "%Y%m%d").date() if ref_day else date.today() - timedelta(days=1)
            d += timedelta(days=1)
            while not self._is_trading_day(d):
                d += timedelta(days=1)
            if d >= date.today():
                plan["guard"] = {"day": d.isoformat(), "until": (guard.get("until") or "09:30").replace(":", "")[:4],
                                 "pct": abs(engine._num(guard.get("pct"), 5) or 5)}
        if follow and follow.get("on") and ref_day:
            plan["follow_high"] = True                              # 고점이 새로 나면 기준을 그날 종가로 옮긴다(10-19 사용자)
            plan["follow_def"] = follow.get("def") or "prev"            # prev = 전날 고가 돌파 · run = 기준일 뒤 최고가 돌파(예전)
            if follow.get("keep_today"):
                plan["follow_keep_today"] = True                    # 예전처럼: 오늘 장중 고점 갱신 중에도 옛 기준 예약을 그대로 둔다
            if follow.get("once"):
                plan["follow_once"] = True                          # 이 예약으로 산 걸 다 팔면 끝 — 다시 안 따라간다(10-20 사용자, 백테스트 +2.4억 쪽)
            if follow.get("exit"):
                plan["follow_exit"] = follow["exit"]
        if drop and drop.get("on"):
            plan["drop_pct"] = abs(engine._num(drop.get("pct"), 5) or 5)   # 전날 종가가 기준가 −pct% 이하면 남은 예약 버림(10-19 사용자 A)
        if ma_stop and ma_stop.get("on") and any(s_.get("ma") for s_ in st):
            plan["ma_stop"] = abs(engine._num(ma_stop.get("pct"), 6) or 6)   # 60선 −pct%(엔벨로프 하단)을 깨면 60선 단계는 그만 산다(10-20 사용자)
        if ma_confirm and ma_confirm.get("on") and any(s_.get("ma") for s_ in st):
            plan["ma_confirm"] = max(1, int(engine._num(ma_confirm.get("n"), 3) or 3))   # 60선 닿은 뒤 15분봉 60선 위 마감 N개 확인하고 삼(10-30 사용자)
        if c_near and c_near.get("on") and ref_day and any(s_.get("ma") for s_ in st):
            # 60선 단계는 사는 값이 기준일(처음 신고대금 날) 종가 C −pct% 이상일 때만(10-30 사용자 "C 위에 있거나 근접했을 때 60선에서").
            # C 는 고점 따라가기로 기준가가 옮겨져도 그대로 — 당일 예약은 종가가 나온 다음 거래일 아침(_fix_same_day)에 정한다
            plan["c_near"] = abs(engine._num(c_near.get("pct"), 3) if engine._num(c_near.get("pct"), 3) is not None else 3)   # 0 = C 위에서만
            if not plan.get("same_day"):
                plan["c_px"] = bp
            if c_near.get("full"):
                plan["c_full"] = True                               # 사는 값이 C −N% 이상이면 남은 단계를 합쳐 한 번에 다 산다(10-30 사용자)
        if peak_stop and peak_stop.get("on") and ref_day:
            plan["peak_base"] = peak_stop.get("base") or base   # 재매수 금지 선 = 정규장/애프터 종가(고가) — 매수 기준과 따로 고른다(10-22 사용자)
            plan["peak_stop"] = engine.peak_pct(peak_stop, engine.cond_value("시가총액", self.snap(code)))   # 기준일 고가(또는 종가) +pct% 를 넘은 적 있으면 재매수 금지 · 시총 크면 big.pct(10-21 사용자)
            plan["peak_by"] = "close" if peak_stop.get("by") == "close" else "high"   # 10-21 사용자 "신고대금 종가 대비 24% 이상 상승하면"
            if peak_stop.get("first"):                              # 연달아 나온 신고대금의 첫 날 기준(선이 새 신고대금마다 올라가지 않게)
                self.ledger_day(code)
                rd_iso = f"{ref_day[:4]}-{ref_day[4:6]}-{ref_day[6:]}"
                a = engine.peak_anchor([(x[0], x[1]) for x in Desk._ledger[1].get(code, []) if x[2] or not peak_stop.get("first_reg_only")], rd_iso, int(engine._num(peak_stop.get("first_days"), 21) or 21),
                                       engine._num(peak_stop.get("first_min_chg"), None))
                plan["peak_ref"] = a.replace("-", "")
        if ma_turn and ma_turn.get("on") and ref_day:
            plan["ma_turn"] = True                                  # 15분봉 60선이 하루 전보다 낮아지면(꺾임) 예약 끝(10-21 사용자, 7종목 시험)
        if rebuy and rebuy.get("on"):
            plan["rebuy"] = int(engine._num(rebuy.get("n"), 1) or 1)   # 손절로 다 팔리면 다음 거래일부터 같은 단계로 다시(최대 n번, 10-21 사용자 한국콜마)
        if gap and gap.get("on"):
            plan["gap_skip"] = True                                 # 갭 하락한 날은 안 삼(10-19 사용자 B)
        with _lock:
            self.plans.append(plan)
            _write("plans.json", self.plans)
        if not r.get("nxt", True) and base == "aft":
            self.note(f"{plan['name']} 은 NXT 에서 안 사고팔아 애프터 종가 대신 정규장 종가 {bp:,}원 기준", "warn")
        self.note(f"예약 매수 · {plan['name']} {len(st)}단계 · "
                  f"{'오늘만' if until == today.isoformat() else (until or '취소할 때') + '까지 유지'}")
        self._place_plans(datetime.now())
        return {"ok": True, "id": plan["id"], "n": len(st)}

    # 기준일 자동(10-19 사용자 "신고대금 날 기준으로 분할 매수 하니까 약간은 자동매수가 될 수 있어서") —
    # 종목에 날짜를 안 정했으면 신고대금 장부의 가장 최근 신고일(auto_ref_days 달력일 안)을 기준일로. "prev" = 일부러 직전 거래일
    _ledger = (0.0, {})

    def ledger_day(self, code: str, min_chg=None, reg_only: bool = False) -> str | None:
        """최근 신고대금 날. min_chg 를 주면 그날 상승률(정규장, 없으면 통합)이 그 이상인 신고일만(10-19 사용자 "신고대금 12% 이상일 때")."""
        p = ROOT / "static" / "dashboard" / "value_ledger.json"
        try:
            mt = p.stat().st_mtime
            if Desk._ledger[0] != mt:
                days: dict = {}
                hist: dict = {}                                     # 코드 → [(날짜, 하루 전체 신고 비율%, 정규장 신고 비율%)] — 신고대금 '유지 N거래일'용
                J = json.loads(p.read_text(encoding="utf-8"))
                for r in J["rows"]:
                    days.setdefault(r[1], []).append((r[0], r[20] if r[20] is not None else r[7], r[17] is not None))   # 셋째 = 정규장 몫으로도 신고대금
                    if len(r) > 29:
                        full = (r[3] / r[4] - 1) * 100 if r[28] and r[4] else None          # 28 전체신고 · 3 대금 · 4 직전 52주 최대
                        reg = (r[17] / r[29] - 1) * 100 if r[17] is not None and r[29] else None  # 17 정규장_억 · 29 정규장 직전 최대
                        hist.setdefault(r[1], []).append((r[0], full, reg))
                Desk._ledger = (mt, days, {"aft": J.get("refs") or {}, "reg": J.get("rrefs") or {}}, hist)
        except (OSError, ValueError, KeyError):
            return None
        m = engine._num(min_chg, None)
        ok = [dd for dd, chg, reg in Desk._ledger[1].get(code, []) if (m is None or (chg is not None and chg >= m)) and (reg or not reg_only)]
        d, n = (max(ok) if ok else None), engine._num(self.rules["safety"].get("auto_ref_days", "14"), None)
        if not d or not n or (date.today() - date.fromisoformat(d)).days > n:
            return None
        return d.replace("-", "")

    def vref(self, code: str) -> dict:
        """52주 신고대금 기준 — 어제까지 245거래일 최대 대금(억). aft = 하루 전체(통합), reg = 정규장 몫. 신고대금 장부가 밤마다 싣는 값."""
        self.ledger_day(code)                                       # 장부 파일이 바뀌었으면 다시 읽는다
        L = Desk._ledger[2] if len(Desk._ledger) > 2 else {}
        ago = self._td_ago()
        H = [(ago[d], f, r) for d, f, r in (Desk._ledger[3].get(code, []) if len(Desk._ledger) > 3 else []) if d in ago]
        return {**{b: (L.get(b) or {}).get(code) for b in ("aft", "reg")},
                "hist": {"aft": [(k, f) for k, f, _ in H if f is not None], "reg": [(k, r) for k, _, r in H if r is not None]}}

    def _reg_today(self, code: str) -> tuple | None:
        """오늘 정규장(KRX) 누적 대금(억)·등락률% — 정규장 일봉(ka10081, 코드에 _AL 없이) 오늘 줄. 60초 캐시, 실패면 None(10-22 사용자 "당일부터도 정규장 대금으로")."""
        c = self.__dict__.setdefault("_regt", {})
        hit = c.get(code)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        out = None
        try:
            rows = self.client.get_daily_chart(code).get("stk_dt_pole_chart_qry") or []
            n = lambda v: abs(int(str(v).replace("+", "").replace("-", "") or 0))  # noqa: E731
            if len(rows) > 1 and rows[0].get("dt") == date.today().strftime("%Y%m%d"):
                px, prev = n(rows[0].get("cur_prc")), n(rows[1].get("cur_prc"))
                out = (n(rows[0].get("trde_prica")) / 100, (px / prev - 1) * 100 if prev else None)   # trde_prica 는 백만원
        except Exception:                                           # noqa: BLE001 — 못 받으면 오늘은 신고대금 아님으로
            out = None
        c[code] = (time.time(), out)
        return out

    def value_high_now(self, code: str, min_chg=None, reg_only: bool = False) -> bool:
        """오늘 장중 신고대금 — 통합 누적 대금 ≥ 어제까지 245거래일 최대(장부 refs)이고 1,000억 이상(장부 저장 하한).
        min_chg 를 주면 지금 등락률도 그 이상. 장부가 밤에 오늘을 신고일로 올리는 것과 같은 기준(10-21 사용자 "신고대금 당일부터")."""
        q, ref = feed.quotes.get(code, {}), self.vref(code).get("reg" if reg_only else "aft")
        m = engine._num(min_chg, None)
        if reg_only:
            # 정규장 몫이 직전 245거래일 정규장 최대(장부 rrefs)·1,000억 이상 — 장부 '정규장_억'과 같은 기준. 통합 누적이 문턱 아래면 정규장 몫도 아래라 조회 안 함
            if not (q.get("value") and ref and self._is_trading_day(date.today()) and datetime.now().strftime("%H%M") >= "0900"
                    and q["value"] / 1e8 >= max(ref, 1000)):
                return False
            r = self._reg_today(code)
            return bool(r and r[0] >= max(ref, 1000) and (m is None or (r[1] is not None and r[1] >= m)))
        return bool(q.get("value") and ref and self._is_trading_day(date.today())
                    and q["value"] / 1e8 >= max(ref, 1000) and (m is None or (q.get("chg") is not None and q["chg"] >= m)))

    def _td_ago(self) -> dict:
        """최근 60거래일 'YYYY-MM-DD' → 오늘에서 몇 거래일 전(오늘 0). 하루 한 번 계산."""
        t = date.today()
        c = self.__dict__.get("_tda")
        if c and c[0] == t:
            return c[1]
        out, d, k = {}, t, 0
        while k < 60:
            if self._is_trading_day(d):
                out[d.isoformat()] = k
                k += 1
            d -= timedelta(days=1)
        self._tda = (t, out)
        return out

    def ref_src(self, code: str) -> str:
        v = self.ref_days.get(code)
        return "직전" if v == "prev" or (not v and not self.ledger_day(code)) else "직접" if v else "신고대금"

    def ref_day(self, code: str) -> str | None:
        v = self.ref_days.get(code)
        if v == "prev":
            return None
        return v or self.ledger_day(code)

    def set_ref_day(self, code: str, day: str | None) -> None:
        with _lock:
            if day:
                self.ref_days[code] = day
            else:
                self.ref_days.pop(code, None)
            _write("ref_days.json", self.ref_days)

    def _is_trading_day(self, d: date) -> bool:
        """원본은 부를 때마다 휴장일 파일을 다시 읽는다(1.7ms) — 매 초 판단에서 여러 번 부르니 날짜별로 기억(하루 지나면 비운다)."""
        c = self.__dict__.setdefault("_tdc", {})
        if d not in c:
            from backtesting.value_burst_live import _is_market_day
            if len(c) > 400:
                c.clear()
            c[d] = _is_market_day(d)
        return c[d]

    def _place_plans(self, now: datetime) -> None:
        today = now.date().isoformat()
        cur = now.hour * 60 + now.minute
        in_aft = 15 * 60 + 40 <= cur < 20 * 60                       # NXT 애프터마켓(15:40~20:00) — 규칙 주문 가능 시간이 덮고, NXT 종목일 때만(10-30 사용자 HT로보틱스 10-19 17시 자리)
        if not (self.client and self._is_trading_day(now.date()) and (8 * 60 <= cur < 15 * 60 + 20 or in_aft)):
            return
        near = engine._num(self.rules["safety"].get("near_pct"), 1.5)
        near = 1.5 if near is None else max(0.0, near)
        changed = False
        for p in self.plans:
            if not p["active"]:
                continue
            if p.get("same_day") and p["ref_day"] < today.replace("-", ""):
                self._fix_same_day(p)
                changed = True
            if p.get("follow_once") and p.get("bought"):
                # 판 뒤엔 다시 안 따라감: 산 뒤 잔고에 잡힌 걸 본 다음 잔고에서 사라지면(다 팔림) 예약을 끝낸다 — 체결 직후 잔고 갱신 전엔 안 끝낸다
                if any(h["code"] == p["code"] for h in self.holdings):
                    if not p.get("held_seen"):
                        p["held_seen"], changed = True, True
                elif p.get("held_seen"):
                    p.update(active=False, status="다 팖 — 끝 (판 뒤엔 안 따라감)")
                    self.note(f"{p['name']} 다 팔아 예약 끝 — 판 뒤엔 다시 안 따라감")
                    changed = True
                    continue
            if p.get("follow_high") and p["placed_day"] != today:          # 기간 끝 판정 전에 — 고점을 새로 썼으면 그날부터 다시 센다
                self._follow_high(p, now.date())
            if p["until"] and today > p["until"]:
                p.update(active=False, status="기간 끝")
                changed = True
                continue
            if p.get("rebuy_arm"):
                if p["rebuy_arm"] == today or any(h["code"] == p["code"] for h in self.holdings):
                    continue                                                # 손절한 날은 안 삼 · 잔고에서 아직 안 빠졌으면 기다림
                for s_ in p["stages"]:
                    s_.update(filled=0, qty=int(s_["amt"] // s_["price"]) if s_["price"] else 0)
                    s_.pop("day", None)
                    s_.pop("t_cxl", None)
                p.pop("ma_dead", None)
                p.pop("rebuy_arm")
                p.update(rebuy=p["rebuy"] - 1, bought=False, held_seen=False)
                self.note(f"{p['name']} 손절 뒤 다시 사기 — 단계를 처음부터 다시 겁니다(남은 {p['rebuy']}번)")
                changed = True
            g = p.get("guard")
            if g and g["day"] == today and not g.get("passed"):
                q = feed.quotes.get(p["code"], {})
                if now.strftime("%H%M") < g["until"]:
                    if p["status"] != "급락 지켜보는 중":
                        p["status"], changed = "급락 지켜보는 중", True
                    continue
                low = min(x for x in (q.get("low"), q.get("px")) if x) if (q.get("low") or q.get("px")) else 0
                if not low:
                    continue                                                # 아직 가격을 못 받았으면 다음 판단 때
                line = p["base_px"] * (1 - g["pct"] / 100)
                if low <= line:
                    p.update(active=False, status=f"급락 — 버림 (저가 {low:,} ≤ {int(line):,})")
                    self.note(f"예약 버림 · {p['name']} 기준일 다음 날 {g['until'][:2]}:{g['until'][2:]} 전 저가 {low:,} ≤ 기준가 −{g['pct']:g}%", "warn")
                    self.tg(f"예약 버림 · {p['name']} 장 초반 급락(저가 {low:,})")
                    changed = True
                    continue
                g["passed"], changed = True, True
            if p["placed_day"] != today:                                    # 그날 처음: 기준가 다시 계산 + 감시 시작
                p["placed_day"], p["status"], changed = today, "감시 중", True
                if p.get("drop_pct") and not p.get("same_day") and not any(s_["filled"] for s_ in p["stages"]):
                    prev = self.ref(p["code"]).get("reg") or 0                 # 직전 거래일 정규장 종가
                    line = p["base_px"] * (1 - p["drop_pct"] / 100)
                    if prev and prev <= line:
                        p.update(active=False, status=f"전날 종가 {prev:,} ≤ 기준가 −{p['drop_pct']:g}% — 버림")
                        self.note(f"예약 버림 · {p['name']} 전날 종가 {prev:,} ≤ 기준가 −{p['drop_pct']:g}% ({int(line):,})", "warn")
                        self.tg(f"예약 버림 · {p['name']} 전날 종가가 기준가 −{p['drop_pct']:g}% 아래")
                        continue
                if not p["ref_day"] and p["created"][:10] != today:         # 기준일을 안 정했으면 매일 직전 거래일 종가로
                    bp = self.ref(p["code"]).get(p["base"]) or p["base_px"]
                    p["base_px"] = bp
                    for s_ in p["stages"]:
                        s_["price"] = engine.floor_tick(bp * (1 + s_["pct"] / 100))
                        s_["qty"] = max(s_["filled"], int(s_["amt"] // s_["price"]))
            q = feed.quotes.get(p["code"], {})
            px = q.get("px")                                                # 실시간 체결가만 — 오래된 잔고 가격으로 걸지 않는다
            if not px:
                continue
            if p.get("ma_turn") and not p.get("same_day"):
                m, m0 = self.ma60_15(p["code"], p["base"]), self.ma60_15_prev(p["code"], p["base"])
                if m and m0 and m < m0:
                    # 60선이 꺾였다(하락추세로 바뀜) — 7종목: 꺾인 뒤 60선 매수는 손절이 대부분. 예약을 끝내고 걸린 매수도 거둔다
                    mine = self._my_orders()
                    for o in list(self.pending):
                        if o["code"] == p["code"] and o["side"] == "buy" and str(mine.get(o["ord_no"], {}).get("tag", "")).startswith(f"예약:{p['id']}:"):
                            self.cancel(o["ord_no"], p["code"])
                    p.update(active=False, status="15분봉 60선 꺾임 — 재매수 금지")
                    self.note(f"{p['name']} 15분봉 60선이 하루 전({m0:,})보다 낮아짐({m:,}) — 예약 끝, 재매수 금지")
                    changed = True
                    continue
            # 당일 예약도 첫 신고대금 날이 더 앞이면 선을 이미 안다 — 그때도 본다(10-22: HT로보틱스 10-21 당일 예약이 10-14 기준 +24% 넘었는데 삼)
            if p.get("peak_stop") and (not p.get("same_day") or (p.get("peak_ref") and p["peak_ref"] != p["ref_day"])):
                rh, rc, hi = self._peak_since(p["code"], p.get("peak_ref") or p["ref_day"], p.get("peak_base") or p["base"])
                rdh, what = (rc, "종가") if p.get("peak_by") == "close" else (rh, "고가")
                hi = max(hi or 0, q.get("high") or 0, px)
                if rdh and hi >= rdh * (1 + p["peak_stop"] / 100):
                    # 기준일 고가 +N% 를 넘었다 — 오른 뒤 눌림은 사지 않는다(7종목: 넘은 뒤 60선 터치는 손절이 대부분). 예약을 끝내고 걸린 매수도 거둔다
                    mine = self._my_orders()
                    for o in list(self.pending):
                        if o["code"] == p["code"] and o["side"] == "buy" and str(mine.get(o["ord_no"], {}).get("tag", "")).startswith(f"예약:{p['id']}:"):
                            self.cancel(o["ord_no"], p["code"])
                    p.update(active=False, status=f"기준일 {what} +{p['peak_stop']:g}% 넘음 — 재매수 금지")
                    self.note(f"{p['name']} 기준일 {what} {rdh:,} +{p['peak_stop']:g}% 를 넘어(고가 {int(hi):,}) 예약 끝 — 재매수 금지")
                    changed = True
                    continue
            if (p.get("follow_high") and not p.get("follow_keep_today")
                    and ((self.follow_info(p["code"], p["ref_day"], p.get("follow_def") or "prev") or {}).get(p["base"]) or {}).get("live")):
                # 오늘 전날 고가를 넘었다(고점 갱신) — 옛 기준 예약은 취소, 내일 오늘 종가 기준으로 새로 건다(10-20 사용자 "예약은 취소 해야지")
                st = "오늘 고점 갱신 — 예약 취소, 내일 새 기준"
                if p["status"] != st:
                    mine = self._my_orders()
                    for o in list(self.pending):
                        if o["code"] == p["code"] and o["side"] == "buy" and str(mine.get(o["ord_no"], {}).get("tag", "")).startswith(f"예약:{p['id']}:"):
                            self.cancel(o["ord_no"], p["code"])
                    p["status"], changed = st, True
                    self.note(f"{p['name']} 오늘 전날 고가를 넘어 고점 갱신 — 옛 기준 예약 취소, 내일 오늘 종가 기준으로 다시 겁니다")
                continue
            if p.get("ma_stop") and not p.get("ma_dead") and any(s_.get("ma") and s_["filled"] < s_["qty"] for s_ in p["stages"]):
                m = self.ma60_15(p["code"], p["base"])
                line = m * (1 - p["ma_stop"] / 100) if m else 0
                if line and px < line:
                    # 60선 엔벨로프 하단을 깼다 — 60선 단계는 이 예약에선 그만(고점 따라가기로 기준이 옮겨지면 다시). 걸린 60선 주문도 거둔다
                    p["ma_dead"], changed = today, True
                    mine = self._my_orders()
                    ma_i = {i for i, s_ in enumerate(p["stages"]) if s_.get("ma")}
                    for o in list(self.pending):
                        tg = str(mine.get(o["ord_no"], {}).get("tag", ""))
                        if o["code"] == p["code"] and o["side"] == "buy" and any(tg.startswith(f"예약:{p['id']}:{i} ") for i in ma_i):
                            self.cancel(o["ord_no"], p["code"])
                    self.note(f"{p['name']} 15분봉 60선 −{p['ma_stop']:g}% ({int(line):,}) 아래로 깨짐 — 60선 매수 멈춤", "warn")
                    self.tg(f"60선 매수 멈춤 · {p['name']} 60선 −{p['ma_stop']:g}% 하단 {int(line):,} 깨짐 (지금 {px:,})")
            if p.get("gap_skip") and not p.get("same_day"):
                # 갭 하락 피하기: 오늘 시가가 마지막 단계 가격보다 아래면 오늘은 안 산다(내일 다시 본다). 시가를 아직 못 받았으면 기다린다
                op, last = q.get("open") or 0, min(s_["price"] for s_ in p["stages"])
                if not op or op < last:
                    st = "시가 기다리는 중" if not op else f"갭 하락 — 오늘 쉼 (시가 {op:,} < {last:,})"
                    if p["status"] != st:
                        p["status"], changed = st, True
                        if op:
                            self.note(f"오늘 안 삼 · {p['name']} 시가 {op:,}가 마지막 단계 {last:,}보다 아래(갭 하락)", "warn")
                    continue
            hm = now.strftime("%H%M")
            for i, s_ in enumerate(p["stages"]):
                if s_.get("t1") and hm >= s_["t1"] and s_.get("day") == today and s_["filled"] < s_["qty"] and s_.get("t_cxl") != today:
                    # 단계 시각이 지났는데 안 채워진 주문은 거둔다(10-20 사용자 "몇 시 몇 분에 매수 할 수 있게")
                    s_["t_cxl"], changed = today, True
                    mine = self._my_orders()
                    for o in list(self.pending):
                        if o["code"] == p["code"] and o["side"] == "buy" and str(mine.get(o["ord_no"], {}).get("tag", "")).startswith(f"예약:{p['id']}:{i} "):
                            self.cancel(o["ord_no"], p["code"])
                if s_["filled"] >= s_["qty"] or s_.get("day") == today or time.time() < s_.get("wait", 0) or (s_.get("ma") and p.get("ma_dead")):
                    continue
                if p.get("same_day") and not s_.get("ma"):
                    continue                                                # 신고대금 당일 — 종가 % 단계는 오늘 종가가 나와야 값이 정해진다
                if (s_.get("t0") and hm < s_["t0"]) or (s_.get("t1") and hm >= s_["t1"]):
                    continue                                                # 이 단계를 살 수 있는 시각 밖
                if in_aft and not p.get("nxt", True):
                    continue                                                # NXT 에서 안 사고파는 종목 — 애프터엔 못 삼
                if not self._plan_window(p, now, strict=in_aft):
                    continue                                                # 매수 규칙의 주문 가능 시간 밖 — 새 매수 안 함(예약을 만든 뒤 날에도, 10-22 사용자 "9시 30분부터 매수")
                if s_.get("ma"):
                    # 15분봉 60선 × (1+pct%) ±band%(10-20 사용자 "60선에서 몇% 근접일 때, 위아래 모두") — 지금가가 그 안에 들어오면 바로 산다.
                    # 지정가는 범위 위쪽 끝이라 매도호가에 바로 체결되고, 그보다 비싸게는 안 산다
                    mb = self.ma_band(p["code"], s_.get("src") or p["base"], s_)
                    if not mb:
                        continue
                    top = engine.floor_tick(mb[2])
                    if top != s_["price"] or s_.get("ma_px") != mb[0]:
                        s_.update(price=top, ma_px=mb[0], qty=max(s_["filled"], int(s_["amt"] // top)))
                        changed = True
                    if p.get("ma_confirm"):
                        top = self._ma_confirmed(p, s_, mb, px)     # 확인되면 지금가 근처 지정가, 아니면 0
                        changed = True
                        if not top:
                            continue
                        s_.update(price=top, qty=max(s_["filled"], int(s_["amt"] // top)))
                    elif not mb[1] <= px <= mb[2]:
                        continue
                    if p.get("c_px") and top < p["c_px"] * (1 - p["c_near"] / 100):
                        if s_.get("cn_day") != today:               # C 아래로 멀다 — 이 60선에선 안 산다(10-30 사용자). 알림은 하루 한 번
                            s_["cn_day"], changed = today, True
                            self.note(f"{p['name']} 60선 {top:,}이 기준일 종가 {p['c_px']:,} −{p['c_near']:g}% 아래 — 안 삼")
                        continue
                    if p.get("c_full") and p.get("c_px") and top >= p["c_px"] * (1 - p["c_near"] / 100):
                        # C −N% 이상 — 아직 주문 안 낸 다른 단계 금액을 이 단계로 합쳐 한 번에 다 산다(10-30 사용자 "C 를 기준으로 −2% 위로는 다 사지게")
                        oth = [x for j, x in enumerate(p["stages"]) if j != i and not x["filled"] and x.get("day") != today and x["amt"] > 0]
                        if oth:
                            s_["amt"] += sum(x["amt"] for x in oth)
                            for x in oth:
                                x.update(amt=0, qty=0)
                            s_["qty"], changed = max(s_["filled"], int(s_["amt"] // top)), True
                            self.note(f"{p['name']} 60선 {top:,} ≥ 기준일 종가 {p['c_px']:,} −{p['c_near']:g}% — 남은 단계 합쳐 한 번에 삼")
                elif px > s_["price"] * (1 + near / 100):
                    continue
                left = s_["qty"] - s_["filled"]
                if left <= 0:
                    continue
                lab = (f"{'정규장' if (s_.get('src') or p['base']) == 'reg' else '애프터'} 15분봉 60선{s_['pct']:+g}% ±{s_.get('band', 0):g}%"
                       if s_.get("ma") else f"{s_['pct']:g}%")
                r = self.buy(p["code"], left, s_["price"], False, f"예약:{p['id']}:{i} {p['tag']} {lab}", rule=self._plan_rule(p))
                if r["ok"]:
                    s_["day"] = today
                    s_.pop("arm", None)                                 # 60선 위 마감 확인은 이 주문으로 끝
                    self.tg(f"근접 주문 · {p['name']} {lab} {s_['price']:,}원 × {left:,}주 (현재 {px:,}원)")
                    self._catch_missed(p, i, s_["price"], px, today, hm)
                else:
                    s_["wait"] = time.time() + 60                           # 막히거나 거부되면 1분 뒤 다시
                changed = True
            # 실제 걸린 예약 주문으로 센다 — 날짜 표시로 세면 시각이 지나 거둔·60선 깨져 거둔·손으로 취소한 단계도 '주문 걸림'이었다(10-23 점검)
            mine = self._my_orders()
            live = {str(mine.get(o["ord_no"], {}).get("tag", "")).split(" ")[0] for o in self.pending if o["code"] == p["code"] and o["side"] == "buy"}
            n = sum(1 for i, s_ in enumerate(p["stages"]) if f"예약:{p['id']}:{i}" in live)
            st = f"주문 걸림 {n}/{len(p['stages'])}" if n else f"60선 −{p.get('ma_stop', 0):g}% 깨짐 — 60선 매수 멈춤" if p.get("ma_dead") else "감시 중"
            if p["active"] and p["status"] != st:
                p["status"], changed = st, True
        if changed:
            _write("plans.json", self.plans)

    @staticmethod
    def _new_high(code: str, ref_day: str, base: str, before: str, mode: str = "prev"):
        """기준일 뒤 before(YYYYMMDD) 전까지 '전날 고가보다 고가가 높은' 마지막 날의 일봉 [날짜, 시, 고, 저, 종, …](없으면 None)과
        before 전 마지막 날 고가(오늘 장중 갱신 판단용). 10-20 사용자: 고점 갱신 = 전날 고가 돌파(라온시큐어 10-20 21,850 > 10-19 21,100)."""
        from backtesting.value_ledger import daily_al_rows, regular_daily_rows
        rows = [r for r in ((regular_daily_rows(code) if base == "reg" else daily_al_rows(code)) or []) if ref_day <= r[0] < before]
        if not rows or rows[0][0] != ref_day:
            return None, None
        new = None
        if mode == "run":                                           # 예전 정의: 기준일부터의 최고가를 넘은 날(10-20 사용자 "예전으로 따로")
            mx = rows[0][2]
            for cur in rows[1:]:
                if cur[2] > mx:
                    new, mx = cur, cur[2]
            return new, mx
        for prev, cur in zip(rows, rows[1:]):
            if cur[2] > prev[2]:
                new = cur
        return new, rows[-1][2]

    def _follow_def(self) -> str:
        """화면용 고점 정의 — 켜진 매수 규칙 중 고점 따라가기가 켜진 첫 규칙의 정의(없으면 전날 고가 돌파)."""
        return next((((r.get("ladder") or {}).get("follow_high") or {}).get("def") or "prev" for r in self.rules["rules"]
                     if r.get("on") and (r.get("ladder") or {}).get("on") and ((r.get("ladder") or {}).get("follow_high") or {}).get("on")), "prev")

    def follow_info(self, code: str, ref_day: str | None, mode: str | None = None) -> dict | None:
        """화면용 고점 따라가기 — 정규장·애프터 각각 {day, high, close, live}. 어제까지는 하루 한 번 계산(로컬 일봉),
        오늘 장중에 고가를 새로 쓰고 있으면 지금 가격을 '오늘 종가(확정 전)'로 보고 그걸 기준으로 보여 준다(live=True)."""
        if not ref_day:
            return None
        mode = mode or self._follow_def()
        key, t = (code, ref_day, mode), date.today().strftime("%Y%m%d")
        hm = datetime.now().strftime("%H%M")
        done = {"reg": hm > "1530", "aft": hm > "2000"}                # 장이 끝난 세션은 오늘 일봉까지 확정으로 본다
        stamp = t + "".join("1" if done[b] else "0" for b in ("reg", "aft"))
        hit = self._fi.get(key)
        if not (hit and hit[0] == stamp):
            base = {}
            for b in ("reg", "aft"):
                try:
                    n, mx = self._new_high(code, ref_day, b, t + "~" if done[b] else t, mode)
                except Exception:                                   # noqa: BLE001 — 일봉 못 읽으면 표시만 안 함
                    n, mx = None, None
                base[b] = ({"day": n[0], "high": int(n[2]), "close": int(n[4])} if n else None, mx)
            hit = self._fi[key] = (stamp, base)
        q = feed.quotes.get(code, {})
        hi, px = q.get("high") or 0, q.get("px") or 0
        out = {}
        for b, (n, mx) in hit[1].items():
            out[b] = ({"day": t, "high": int(hi), "close": int(px), "live": True}
                      if mx and hi > mx and px and t > ref_day and not (n and n["day"] == t) else n)
        return out

    @staticmethod
    def _peak_since(code: str, ref_day: str, base: str) -> tuple:
        """(기준일 고가, 기준일 종가, 기준일 다음 날부터 어제까지 최고가) — 로컬 일봉(정규장/통합). 기준일 일봉이 아직 없으면 None 셋."""
        from backtesting.value_ledger import daily_al_rows, regular_daily_rows
        today = date.today().strftime("%Y%m%d")
        rows = [r for r in ((regular_daily_rows(code) if base == "reg" else daily_al_rows(code)) or []) if ref_day <= r[0] < today]
        if not rows or rows[0][0] != ref_day:
            return None, None, None
        return rows[0][2], rows[0][4], max((r[2] for r in rows[1:]), default=None)

    def _fix_same_day(self, p: dict) -> None:
        """신고대금 당일 예약의 다음 거래일 — 기준가를 그날 종가로(장중 자리값이었다), 종가 % 단계 가격도 다시. 못 받으면 다음 판단 때."""
        self._refc.pop((p["code"], p["ref_day"]), None)               # 장중에 받아 둔 값(그때 가격)을 버린다
        bp = self.ref(p["code"], p["ref_day"]).get(p["base"]) or 0
        if not bp:
            return
        p["base_px"] = bp
        if "c_near" in p:
            p["c_px"] = bp                                          # C 고정(10-30) — 당일 예약은 이제야 기준일 종가가 나온다
        for s_ in p["stages"]:
            if not s_.get("ma") and not s_["filled"]:
                s_["price"] = engine.floor_tick(bp * (1 + s_["pct"] / 100))
                s_["qty"] = int(s_["amt"] // s_["price"])
        p.pop("same_day")

    def _days_after(self, day: str, keep: dict) -> str:
        """유지 기간 끝 — day(YYYYMMDD: 기준일 또는 고점 갱신 날) 다음 거래일부터 N거래일째(10-20 사용자 "10월 7일부터, 고점 갱신하면 그날부터 다시 6일")."""
        d, n = datetime.strptime(day, "%Y%m%d").date(), max(1, int(engine._num(keep.get("days"), 1) or 1))
        while n:
            d += timedelta(days=1)
            if self._is_trading_day(d):
                n -= 1
        return d.isoformat()

    def _plan_rule(self, p: dict) -> str | None:
        """예약으로 살 때 붙일 청산 규칙 — 고점 따라가기로 기준이 옮겨졌으면 따로 정한 청산(10-20 사용자 "6% 익절로 따로").
        예약에 없으면 켜진 매수 규칙의 설정(주문 칸 스위치·설정 전에 만든 예약)."""
        if p.get("follow_day"):
            fx = p.get("follow_exit") or next((((r.get("ladder") or {}).get("follow_high") or {}).get("exit") for r in self.rules["rules"]
                                               if r.get("on") and (((r.get("ladder") or {}).get("follow_high") or {}).get("exit"))), None)
            if fx and self.exit_rule(fx):
                return fx
        return p.get("rule")

    def _follow_high(self, p: dict, today: date) -> None:
        """고점 따라가기 — 기준일 고가를 시작으로, 그 뒤(오늘 전) 고가를 새로 쓴 날이 있으면 기준가를 그 마지막 날 종가로 옮기고
        유지 기간도 그날부터 다시 센다. 일봉은 로컬(정규장: 장부와 같은 출처 / 애프터: 통합 일봉)."""
        new = self._new_high(p["code"], p["ref_day"], p["base"], today.strftime("%Y%m%d"), p.get("follow_def") or "prev")[0]
        if not new or new[0] == p.get("follow_day"):
            return
        bp = int(new[4])
        p.update(base_px=bp, follow_day=new[0])
        rule = next((r for r in self.rules["rules"] if r.get("name") == p.get("tag") and (r.get("ladder") or {}).get("on")), None)
        if rule:                                                    # 단계를 규칙대로 다시 — 그사이 시장경보(투자주의 등)가 붙었으면 그 %로(10-20 사용자 에스엠벡셀)
            total = sum(s_["amt"] for s_ in p["stages"])
            st = [{"pct": engine._num(x[0]), "amt": total * (engine._num(x[1], 0) or 0) / 100, "price": 0, "qty": 0, "filled": 0,
                   **_lv_ex(x)}
                  for x in self.levels_for(rule["ladder"], p["code"])]
            st = [s_ for s_ in st if s_["pct"] is not None and s_["amt"] > 0]
            if st:
                p["stages"] = st
        for s_ in p["stages"]:
            s_["price"] = engine.floor_tick(bp * (1 + s_["pct"] / 100))   # 60선 단계는 주문 전에 60선으로 다시 잡힌다
            s_["qty"] = int(s_["amt"] // s_["price"])
            s_["filled"] = 0
            s_.pop("day", None)
        p.pop("ma_dead", None)                                      # 새 기준 — 60선 매수 멈춤도 풀린다
        if (p.get("keep") or {}).get("mode") == "days":
            p["until"] = self._days_after(new[0], p["keep"])
        self.note(f"고점 갱신 · {p['name']} {new[0][4:6]}.{new[0][6:]} 고가 {int(new[2]):,} → 기준가 {bp:,}(그날 종가)로 옮김 · {p['until'] or '취소할 때'}까지")

    def _refresh_mkt(self) -> None:
        from backtesting.market_snapshot import _kiwoom_index_snapshot
        self.mkt["t"] = time.time()
        try:
            snap = _kiwoom_index_snapshot(self.client, "101") if self.client else None
        except Exception:                                           # noqa: BLE001 — 못 받으면 멈춤 판단을 안 한다
            snap = None
        if snap:
            self.mkt["chg"] = snap.get("change_pct")

    def preview(self) -> list[dict]:
        """내일(다음 판단) 걸릴 예약 미리 보기 — 켜진 매수 규칙 × 자동 켜진 종목. 조건은 지금 시세로 본 값(장중엔 바뀐다)."""
        out = []
        for rule in self.rules["rules"]:
            if not rule.get("on") or not rule.get("ladder", {}).get("on"):
                continue
            L = rule["ladder"]
            for code in [c for c in self.watch if c not in self.no_auto]:
                row = {"rule": rule["name"], "code": code, "name": self.name(code)}
                rd = self.rule_ref_day(rule, code)
                if rd is False:
                    out.append({**row, "skip": "최근 신고대금 날 없음(또는 상승률 기준 미달)"})
                    continue
                if any(p["code"] == code and p.get("ref_day") == rd and p.get("tag") == rule["name"] for p in self.plans):
                    out.append({**row, "skip": "이 기준일 예약이 이미 있음(종목 계획 탭)"})
                    continue
                ref = self.ref(code, rd)
                bp, src = ref.get(L.get("base", "reg")) or 0, "기준일 종가"
                if (L.get("follow_high") or {}).get("on"):
                    f = (self.follow_info(code, rd, (L.get("follow_high") or {}).get("def") or "prev") or {}).get(L.get("base", "reg"))
                    if f:
                        bp, src = f["close"], f"고점 갱신 {f['day'][4:6]}.{f['day'][6:]} 종가"
                amount = self.rule_amount_for(rule, code)
                stages = []
                for lv in self.levels_for(L, code):
                    pct, w = engine._num(lv[0]), (engine._num(lv[1], 0) or 0) / 100
                    if pct is None or not bp:
                        continue
                    ex = _lv_ex(lv)
                    mb = self.ma_band(code, ex.get("src") or L.get("base", "reg"), {"pct": pct, **ex}) if ex.get("ma") else None
                    price = engine.floor_tick(mb[2] if mb else bp * (1 + pct / 100))
                    stages.append({"pct": pct, "price": price, "qty": int(amount * w // price) if price else 0, **ex, **({"ma_px": mb[0]} if mb else {})})
                ok, _ = engine.conds_met(rule.get("conds", []), self.snap(code))
                out.append({**row, "ref_day": rd, "base": L.get("base", "reg"), "base_px": bp, "src": src, "amount": amount,
                            "stages": stages, "conds_now": ok, "lev": self.buy_lev(code)})
        return out

    def set_auto(self, code: str, on: bool) -> int:
        """종목 자동 매수 켜기/끄기. 끄면 매수 규칙이 만든 그 종목의 예약도 같이 취소한다(손으로 건 예약은 그대로). 취소한 수를 돌려준다."""
        with _lock:
            (self.no_auto.discard if on else self.no_auto.add)(code)
            _write("no_auto.json", sorted(self.no_auto))
        if on:
            return 0
        hit = [p["id"] for p in self.plans if p["active"] and p["code"] == code and any(self._plan_of(p, r) for r in self.rules["rules"])]
        for pid in hit:
            self.cancel_plan(pid)
        self.note(f"자동 매수 끔 · {self.name(code)}" + (f" — 규칙 예약 {len(hit)}건 취소" if hit else ""))
        return len(hit)

    def cancel_plan(self, pid: str) -> dict:
        p = next((x for x in self.plans if x["id"] == pid), None)
        if not p:
            return {"ok": False, "msg": "없는 예약"}
        mine = self._my_orders()
        for o in list(self.pending):
            if o["side"] == "buy" and mine.get(o["ord_no"], {}).get("tag", "").startswith(f"예약:{pid}:"):
                self.cancel(o["ord_no"], o["code"])
        with _lock:
            p.update(active=False, status="취소")
            _write("plans.json", self.plans)
        self.note(f"예약 취소 · {p['name']}")
        return {"ok": True}

    # ── 주문체결(00) — 체결 즉시 반영 ─────────────────────────
    def on_order(self, ev: dict) -> None:
        if not ev.get("fill_qty"):
            return
        mine = self._my_orders().get(ev["ord_no"], {})
        tag = mine.get("tag", "")
        self.note(f"체결 · {self.name(ev['code'])} {ev['fill_qty']:,}주 {ev['fill_px']:,}원 {'매도' if ev['side'] == 'sell' else '매수'}"
                  f"{' (' + tag + ')' if tag else ''}")
        self.tg(f"체결 · {self.name(ev['code'])} {'매도' if ev['side'] == 'sell' else '매수'} {ev['fill_qty']:,}주 {ev['fill_px']:,}원"
                + (f" ({tag})" if tag else "") + (f" · 남은 {ev['left']:,}주" if ev.get("left") else ""))
        with _lock:
            if ev["side"] == "buy" and "[신용]" in tag and ev["code"] not in self.credit_codes:
                self.credit_codes.add(ev["code"])
                _write("credit_codes.json", sorted(self.credit_codes))
            self._jfill(ev, tag)
            if ev["side"] == "buy" and tag.startswith("예약:"):
                _, pid, i = tag.split(" ")[0].split(":")
                p = next((x for x in self.plans if x["id"] == pid), None)
                if p and int(i) < len(p["stages"]):
                    p["stages"][int(i)]["filled"] += ev["fill_qty"]
                    p["bought"] = True                                  # 판 뒤엔 안 따라감 판단용
                    if all(s_["filled"] >= s_["qty"] for s_ in p["stages"]):
                        p.update(active=bool(p.get("follow_high") or p.get("rebuy")),
                                 status="다 삼 · 고점 새로 나면 다시" if p.get("follow_high") else "다 삼 · 손절되면 다시" if p.get("rebuy") else "완료")
                    fx = self._plan_rule(p)
                    if p.get("follow_day") and fx != p.get("rule"):
                        # 기준일 종가로 산 뒤 고점 따라가기로 더 샀으면, 그때부터 그 종목 전체를 고점 따라가기 청산으로(10-20 사용자)
                        if ev["code"] in self.day["bought"]:
                            self.day["bought"][ev["code"]]["rule"] = fx
                        m = self.meta.get(ev["code"])
                        if m and m.get("rule") != fx:
                            m["rule"] = fx
                            self._wm()
                            self.note(f"{self.name(ev['code'])} 고점 따라가기로 더 삼 — 이제부터 '{(self.exit_rule(fx) or {}).get('name', fx)}'로 청산")
                    _write("plans.json", self.plans)
            if ev["side"] == "sell":
                h = next((x for x in self.holdings if x["code"] == ev["code"]), None)
                if h and h["avg_price"]:
                    self.day["pnl_realized"] = int(self.day.get("pnl_realized", 0)) + (ev["fill_px"] - h["avg_price"]) * ev["fill_qty"]
                m = self.meta.get(ev["code"])
                if m and tag.startswith("익절"):
                    m["breakeven"] = True
                    try:                                                # 태그 '익절{단계+1} …' — 다음 날 다시 걸 때 이 단계는 뺀다
                        m["takes_filled"] = sorted({*m.get("takes_filled", []), int(tag[2:].split()[0]) - 1})
                    except ValueError:
                        pass
                    self._wm()
            self._wd()
        self._kick.set()

    # ── 매 초 판단 ─────────────────────────────────────────
    def tick(self, now: datetime) -> None:
        self._new_day()
        if not self.client or not self.is_active(now):
            return
        if self.paper_on():
            self._paper_match()
        for h in list(self.holdings):
            code, m = h["code"], self.meta.get(h["code"])
            rule = self.exit_rule(m.get("rule")) if m else None
            if not m or not rule:
                continue
            s = self.snap(code)
            px = s["px"]
            if px > m.get("high", 0):
                m["high"] = px
            ex = rule["exits"]
            me = ex.get("ma_env") or [False]
            pos = {"qty": h["quantity"], "avg": h["avg_price"], **m,
                   "ma60": self.ma60_15(code, (me + [None, None])[2] or "reg") if me[0] else 0}
            sf = self.rules["safety"]
            if (sf.get("buy_mode") == "margin" and sf.get("margin_intraday", True) and m.get("opened") == date.today().isoformat()
                    and code not in self.credit_codes):
                ex = {**ex, "close": [True, "15:15"]}                  # 미수로 산 날은 15:15 에 정리(밤 넘기는 미수 없음)
            acts = engine.exit_actions(pos, px, now, ex)
            # 손절·되밀림·시각 청산은 익절 쪽 30초 쉬기와 따로 본다 — 같이 묶여 있어 산 직후·규칙을 바꾼 직후 30초 동안 손절이 막혔다(10-23 시험)
            if acts:
                if time.time() - m.get("exit_at", 0) < 30:          # 직전 청산 주문 뒤 체결·잔고 반영까지 30초는 다시 안 낸다
                    continue
                r = self.exit_all(code, f"{acts[0]['kind']} · {acts[0]['why']}")
                if acts[0]["kind"] == "stop" and r.get("ok"):
                    self.day["stops"] = int(self.day.get("stops", 0)) + 1
                    self._wd()
                    # 걸려 있던 예약 매수가 손절 직후 떨어지는 값에 체결될 수 있었다(10-23 점검) — 그 종목 예약 주문은 거둔다
                    mine_ = self._my_orders()
                    for o in list(self.pending):
                        if o["code"] == code and o["side"] == "buy" and str(mine_.get(o["ord_no"], {}).get("tag", "")).startswith("예약:"):
                            self.cancel(o["ord_no"], code)
                    for p in self.plans:                              # 손절 뒤 다시 사기 — 다음 거래일부터(_place_plans)
                        if p["code"] == code and p["active"] and p.get("rebuy", 0) > 0 and p.get("bought"):
                            p.update(rebuy_arm=date.today().isoformat(), status="손절 — 다음 거래일 다시")
                            self.note(f"{p['name']} 손절 — 다음 거래일부터 같은 예약으로 다시 삽니다(남은 {p['rebuy']}번)")
                            _write("plans.json", self.plans)
                m["exit_at"] = time.time()
                self._wm()
                continue
            if time.time() - m.get("retry_at", 0) < 30:                  # 직전 익절 주문이 거부됐으면 30초 쉬고 다시(매 초 반복 주문 방지)
                continue
            sig = json.dumps([m.get("rule"), rule["exits"].get("take")], ensure_ascii=False)
            if m.get("take_sig") != sig:
                # 청산 규칙이 바뀜(규칙 수정·고점 따라가기로 전환) — 걸어 둔 익절 주문을 거두고 남은 수량에 새 규칙으로 다시 건다.
                # 10-20: 옛 '+30% 전량' 주문이 수량을 다 잡고 있어 새 '+12%' 익절이 30초마다 '보유 수량 부족'으로 거부됐다
                self._cancel_my_sells(code)
                m.update(take_sig=sig, takes_done=[], init_qty=h["quantity"], retry_at=time.time())
                self._wm()
                self.note(f"{self.name(code)} 청산 규칙 '{rule['name']}' 기준으로 익절 주문을 다시 겁니다")
                continue
            mine = self._my_orders()
            free = h["quantity"] - sum(int(o.get("left", o.get("qty")) or 0) for o in self.pending
                                       if o["code"] == code and o["side"] == "sell" and o["ord_no"] in mine)
            for t in engine.take_orders(pos, rule["exits"]):
                if t["qty"] > free:                                     # 익절 비중 합이 100%를 넘으면 남은 수량만큼만(10-20: 합 120%로 30초마다 거부)
                    t["qty"] = free
                if t["qty"] <= 0:
                    m["takes_done"] = sorted(set(m["takes_done"]) | {t["stage"]})
                    self._wm()
                    self.note(f"{self.name(code)} 익절{t['stage'] + 1} 건너뜀 — 남은 수량이 없음(익절 비중 합이 100%를 넘음)", "warn")
                    continue
                free -= t["qty"]
                r = self.sell(code, t["qty"], t["price"], False, f"익절{t['stage'] + 1} {t['why']}")
                if r["ok"]:
                    m["takes_done"] = sorted(set(m["takes_done"]) | {t["stage"]})
                else:
                    m["retry_at"] = time.time()
                    break
                self._wm()
        self._place_plans(now)
        self._auto_buy(now)

    def _auto_buy(self, now: datetime) -> None:
        for rule in self.rules["rules"]:
            if not rule.get("on") or not engine.in_windows(now, rule.get("times")):
                continue
            amount = self.rule_amount(rule)
            if amount <= 0:
                continue
            for code in [c for c in self.watch if c not in self.no_auto]:
                rd = self.rule_ref_day(rule, code)
                key = f"{rule['id']}:{code}" + (f":{rd}" if rd else "")
                if self.day["bought"].get(code, {}).get("key") == key or (rule.get("once_per_day") and code in self.day["bought"]):
                    continue
                if rd is False:                                          # '신고대금 날' 규칙인데 최근 신고일이 없는 종목은 건너뛴다
                    continue
                if rule["ladder"].get("on") and (any(h["code"] == code for h in self.holdings) or any(
                        p["code"] == code and p.get("ref_day") == rd and self._plan_of(p, rule) for p in self.plans)):
                    continue                                             # 같은 기준일 예약은 한 번만(버려졌거나 끝났어도) · 보유 중이면 안 건다
                self.ref(code)
                ok, unsupported = engine.conds_met(rule.get("conds", []), self.snap(code))
                if not ok or time.time() - self.__dict__.setdefault("_plan_fail", {}).get(key, 0) < 60:
                    continue
                prev = self.day["bought"].get(code)
                self.day["bought"][code] = {"key": key, "rule": rule.get("exit"), "t": now.strftime("%H:%M:%S")}
                self._wd()
                amount = self.rule_amount_for(rule, code)            # 미수·신용이면 종목마다 배수가 다르다
                if amount <= 0:
                    self._undo_key(code, prev, key, f"{rule['name']} · {self.name(code)} 살 금액이 0 — 1분 뒤 다시")
                    continue
                if rule["ladder"].get("on"):
                    L = rule["ladder"]
                    stages = [{"pct": lv[0], "amt": amount * (engine._num(lv[1], 0) or 0) / 100, **_lv_ex(lv)}
                              for lv in self.levels_for(L, code)]
                    made = self.create_plan(code, L["base"], rd, stages,
                                     L.get("keep") or {"mode": "today"}, rule["name"], rule.get("exit"), L.get("guard"), L.get("gap"), L.get("drop"), L.get("follow_high"), L.get("ma_stop"), L.get("peak_stop"), L.get("ma_turn"), L.get("rebuy"), L.get("c_near"), L.get("ma_confirm"))
                    if not made.get("ok"):                           # 기준 종가 조회 실패 등 — 그날 막혀 버리지 않게(10-23 점검)
                        self._undo_key(code, prev, key, f"{rule['name']} · {self.name(code)} 예약 못 만듦 — {made.get('msg', '')} · 1분 뒤 다시")
                        continue
                    if made.get("ok"):
                        np_ = next((x for x in self.plans if x["id"] == made.get("id")), None)
                        if np_ is not None:
                            np_["buy_rule"] = rule["id"]                # 주문 가능 시간을 이 규칙에서 본다(10-22)
                            # 바로 저장 — create_plan 이 저장·첫 발주까지 한 뒤라, 다른 변화 없이 재시작하면 이 칸이 사라졌다.
                            # 그러면 규칙 이름을 바꾼 다음 날 같은 예약이 하나 더 생겼다(10-23 시험 #13)
                            _write("plans.json", self.plans)
                        self._retire_plans(code, rule, rd)
                else:
                    px = self.snap(code)["px"]
                    qty = int(amount // px) if px else 0
                    if qty:
                        self.buy(code, qty, px, rule.get("how") == "market", rule["name"], rule=rule.get("exit"))

    @staticmethod
    def _plan_of(p: dict, rule: dict) -> bool:
        """이 매수 규칙이 만든 예약인가 — 규칙 id 로(이름을 바꾸면 같은 기준일 예약이 하나 더 생겼다, 10-23 점검). 옛 예약은 이름으로."""
        return p.get("buy_rule") == rule["id"] or (not p.get("buy_rule") and p.get("tag") == rule["name"])

    def _retire_plans(self, code: str, rule: dict, rd) -> None:
        """같은 규칙으로 이 종목에 걸린 옛 기준일 예약을 끝내고 걸린 주문도 거둔다 — 새 신고대금 날 예약과 겹치지 않게(10-21)."""
        mine = None
        for p in self.plans:
            if p["active"] and p["code"] == code and self._plan_of(p, rule) and p.get("ref_day") != rd:
                p.update(active=False, status="새 신고대금 날 — 새 예약으로")
                mine = mine if mine is not None else self._my_orders()
                for o in list(self.pending):
                    if o["code"] == code and o["side"] == "buy" and str(mine.get(o["ord_no"], {}).get("tag", "")).startswith(f"예약:{p['id']}:"):
                        self.cancel(o["ord_no"], code)

    def _undo_key(self, code: str, prev, key: str, why: str) -> None:
        if prev is None:
            self.day["bought"].pop(code, None)
        else:
            self.day["bought"][code] = prev
        self._wd()
        self._plan_fail[key] = time.time()
        self.note(why, "warn")

    def rule_amount(self, rule: dict) -> int:
        """1종목당 금액 — 비어 있으면 평가금 × 비중. 비중 = 종목당 최대 비중과 100 ÷ 동시 보유 최대 중 작은 것
        (10-19 사용자 "동시 보유 2종목에 비중 100% 면 나누기 2") — 둘 다 비어 있으면 0(안 삼)."""
        return engine.per_stock_amount(rule.get("amount"), self.rules["safety"], self.equity())

    def rule_amount_for(self, rule: dict, code: str) -> int:
        return engine.per_stock_amount(rule.get("amount"), self.rules["safety"], self.equity(), self.buy_lev(code)[0])

    def rule_ref_day(self, rule: dict, code: str):
        """매수 규칙의 기준일 — 종목에 직접 정한 날이 먼저, 없으면 규칙의 방식(10-19 사용자 "매수규칙에도 만들어줘").
        ledger = 최근 신고대금 날(없으면 False = 이 종목은 안 산다) · prev = 직전 거래일 · date = 규칙에 적은 날."""
        if not rule.get("ladder", {}).get("on"):
            return None
        L, v = rule["ladder"], self.ref_days.get(code)
        if v:
            return None if v == "prev" else v
        mode = L.get("ref_mode") or ("date" if L.get("ref_day") else "ledger")
        if mode == "ledger":
            if L.get("ref_today") and self.value_high_now(code, L.get("ref_min_chg"), bool(L.get("ref_reg_only"))):
                return date.today().strftime("%Y%m%d")              # 신고대금 당일부터(10-21 사용자) — 장중에 오늘 대금이 52주 최대를 넘었다
            return self.ledger_day(code, L.get("ref_min_chg"), bool(L.get("ref_reg_only"))) or False
        if mode == "date":
            return (L.get("ref_day") or "").replace("-", "") or None
        return None

    def _catch_missed(self, p: dict, i: int, price: int, px: int, today: str, hm: str) -> None:
        """놓친 60선 단계 — 지금가가 이미 그 범위 아래면(시각 밖이었거나 건너뛰었거나) 방금 낸 단계와 같은 값에 같이 산다
        (10-22 사용자: 라온시큐어 10-08 1차는 09:30 전에 지나가 2차만 사짐 → '다음 매수 자리에 같이'). 백테스트 catch 와 같다."""
        for j, t_ in enumerate(p["stages"]):
            if j == i or not t_.get("ma") or t_["filled"] >= t_["qty"] or t_.get("day") == today or p.get("ma_dead"):
                continue
            if (t_.get("t0") and hm < t_["t0"]) or (t_.get("t1") and hm >= t_["t1"]):
                continue
            mb = self.ma_band(p["code"], t_.get("src") or p["base"], t_)
            if not mb or px >= mb[1]:
                continue
            left = max(0, int(t_["amt"] // price) - t_["filled"])
            if left <= 0:
                continue
            r = self.buy(p["code"], left, price, False, f"예약:{p['id']}:{j} {p['tag']} {j + 1}차 몫(놓친 단계, {i + 1}차와 같이)", rule=self._plan_rule(p))
            if r["ok"]:
                t_.update(day=today, qty=t_["filled"] + left, price=price)
                self.note(f"{p['name']} {j + 1}차는 이미 범위 아래로 지나가 {i + 1}차 {price:,}원에 같이 삽니다 ({left:,}주)")

    def _plan_window(self, p: dict, now: datetime, strict: bool = False) -> bool:
        """예약을 만든 매수 규칙의 '주문 가능 시간' 안인가 — 지금 규칙 값을 본다(고치면 바로). 규칙을 못 찾으면 막지 않는다.
        strict(애프터 시간) 면 규칙의 주문 가능 시간이 덮을 때만 — 손으로 건 예약·시간 없는 규칙은 예전처럼 15:20 까지만."""
        rs = self.rules.get("rules") or []
        r = next((x for x in rs if x["id"] == p.get("buy_rule")), None) or next((x for x in rs if x.get("name") == p.get("tag")), None)
        if not r or not r.get("times"):
            return not strict
        return engine.in_windows(now, r["times"])

    def rule_problems(self, rule: dict) -> list[str]:
        out = [f"'{c[0]}' 조건은 아직 데이터가 연결되지 않았습니다" for c in rule.get("conds", []) if c[0] not in engine.SUPPORTED]
        sf = self.rules["safety"]
        if not int(engine._num(rule.get("amount"), 0) or 0) and not (engine._num(sf.get("max_weight_pct"), 0) or engine._num(sf.get("max_positions"), 0)):
            out.append("1종목당 금액·종목당 최대 비중·동시 보유 최대가 다 비어 있습니다 — 살 금액이 없습니다")
        if not self.exit_rule(rule.get("exit")):
            out.append("청산 규칙을 고르지 않았습니다 — 산 뒤 자동 청산이 안 걸립니다")
        if not rule.get("times"):
            out.append("주문 가능 시간이 없습니다")
        return out

    # ── 배경 스레드 ─────────────────────────────────────────
    def start(self) -> None:
        self._kick = threading.Event()
        if not self.client:
            self.note(self.ready(), "warn")
            return
        feed.set_codes(self.sub_codes())
        feed.start(self.client, self.is_active, self.on_order)
        threading.Thread(target=self._loop, daemon=True, name="trader-desk").start()

    def _loop(self) -> None:
        last_acct = last_pend = 0.0
        while True:
            now, mono = datetime.now(), time.monotonic()
            try:
                if self.is_active(now) or not self.deposit:
                    if mono - last_acct > 20 or self._kick.is_set():
                        self._kick.clear()
                        self.refresh_account()
                        feed.set_codes(self.sub_codes())
                        last_acct = mono
                    if self.rules["safety"].get("mkt_drop") and time.time() - self.mkt["t"] > 60:
                        self._refresh_mkt()
                    if mono - last_pend > 15:
                        self.refresh_pending()
                        last_pend = mono
                with _lock:
                    self.tick(now)
            except Exception as e:                                      # noqa: BLE001 — 루프가 죽으면 청산 감시가 멈춘다
                self.note(f"판단 루프 오류: {type(e).__name__}: {e}", "error")
            time.sleep(1)
