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
from datetime import date, datetime
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
         "ladder": {"on": False, "base": "aft", "levels": [["-3", "50"], ["-5", "50"]]},
         "exits": {"stop": [True, "3.5"], "take": [True, [["5", "50"], ["8", "50"]]], "trail": [False, ""],
                   "days": [False, ""], "close": [False, "15:15"], "breakeven": [True]}},
        {"id": "closeladder", "name": "종가 대비 분할 매수", "desc": "애프터 종가 −3% · −5%에 미리 걸기", "on": False,
         "conds": [], "times": [["08:00", "08:50"], ["09:00", "15:20"]], "amount": 0, "how": "limit", "once_per_day": True,
         "ladder": {"on": True, "base": "aft", "levels": [["-3", "50"], ["-5", "50"]]},
         "exits": {"stop": [True, "3.5"], "take": [True, [["5", "50"], ["8", "50"]]], "trail": [False, ""],
                   "days": [False, ""], "close": [False, "15:15"], "breakeven": [True]}},
    ],
    "manual_rule": "pullback8",
    "safety": {"max_daily_loss": "", "max_weight_pct": "", "max_positions": "", "max_orders": "",
               "confirm_real": True, "halt_on_disconnect": True},
}


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
        self.client = None
        if self.appkey and self.secret:
            from kiwoom_client import KiwoomClient
            self.client = KiwoomClient(self.appkey, self.secret, is_mock=self.is_mock)
        self.watch: list[str] = _read("watch.json", [])
        self.rules: dict = _read("rules.json", DEFAULT_RULES)
        self.meta: dict = _read("positions.json", {})               # code -> 청산 감시 상태
        self.day: dict = _read("day.json", {})
        self.refs: dict = {}                                        # code -> {reg, aft, day}
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
    def note(self, text: str, level: str = "info") -> None:
        with _lock:
            self.msgs = ([{"t": datetime.now().strftime("%H:%M:%S"), "text": text, "level": level}] + self.msgs)[:80]
        _log({"note": text, "level": level})

    def _new_day(self) -> None:
        today = date.today().isoformat()
        if self.day.get("date") != today:
            self.day = {"date": today, "pnl_realized": 0, "orders": 0, "halted": None, "bought": {}}
            _write("day.json", self.day)
        st = daily_facts._facts
        if st.get("for") != date.today() and not st["building"]:
            threading.Thread(target=daily_facts.build, daemon=True, name="trader-facts").start()

    def ready(self) -> str | None:
        if not self.client:
            return "매매 앱키가 없습니다 — .env 에 TRADER_APPKEY / TRADER_SECRETKEY 를 넣고 다시 켜 주세요"
        return None

    def is_active(self, now: datetime) -> bool:
        from backtesting.value_burst_live import _is_market_day
        return _is_market_day(now.date()) and (7 * 60 + 50) <= now.hour * 60 + now.minute < 20 * 60 + 5

    def name(self, code: str) -> str:
        return self.names.get(code, code)

    def rule(self, rid: str | None) -> dict | None:
        return next((r for r in self.rules["rules"] if r["id"] == rid), None)

    # ── 기준 종가(정규장 = KRX 일봉, 애프터 = NXT(_NX) 일봉, 둘 다 '오늘 전' 마지막 봉) ──
    def ref(self, code: str) -> dict:
        today = date.today().strftime("%Y%m%d")
        r = self.refs.get(code)
        if r and r.get("day") == today:
            return r
        out = {"day": today, "reg": 0, "aft": 0}
        if self.client:
            for key, stk in (("reg", code), ("aft", code + "_NX")):
                try:
                    rows = self.client.get_daily_chart(stk).get("stk_dt_pole_chart_qry", []) or []
                    prev = [x for x in rows if str(x.get("dt", "")) < today]
                    out[key] = abs(int(str(prev[0]["cur_prc"]).replace("+", ""))) if prev else 0
                except Exception as e:                                  # noqa: BLE001
                    self.note(f"{self.name(code)} {'정규장' if key == 'reg' else '애프터'} 종가 조회 실패: {e}", "warn")
        self.refs[code] = out
        return out

    def snap(self, code: str) -> dict:
        q, r = feed.quotes.get(code, {}), self.refs.get(code, {})
        h = next((x for x in self.holdings if x["code"] == code), None)
        px = q.get("px") or (h["current_price"] if h else 0)
        reg = r.get("reg") or 0
        return {"px": px, "chg": (px / reg - 1) * 100 if reg and px else q.get("chg"), "high": q.get("high"),
                "value": q.get("value"), "reg": reg, "aft": r.get("aft") or 0, "strength": q.get("strength"),
                "facts": daily_facts.get(code)}

    # ── 계좌 ──────────────────────────────────────────────
    def refresh_account(self) -> None:
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

    def refresh_pending(self) -> None:
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
        """orders.jsonl 에서 이 데스크가 낸 주문번호 → 태그(take:1 등). 남이 낸 주문(영웅문)은 건드리지 않는다."""
        out = {}
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
                                   "takes_done": [], "breakeven": False, "rule": rid}
                changed = True
            elif h["quantity"] > m["init_qty"]:                         # 추가 매수 — 익절 단계를 새 수량으로 다시 건다
                m.update(init_qty=h["quantity"], takes_done=[])
                changed = True
        for code in [c for c in self.meta if c not in held]:
            del self.meta[code]
            changed = True
        if changed:
            _write("positions.json", self.meta)

    # ── 주문 ──────────────────────────────────────────────
    def _submit(self, code: str, side: str, qty: int, price: int, market: bool, tag: str) -> dict:
        from backtesting.order_execution import submit_order
        if err := self.ready():
            return {"ok": False, "msg": err}
        t = submit_order(self.client, stock_code=code, side=side, quantity=int(qty), price=0 if market else int(price),
                         approved=True, order_type="3" if market else "0", client_order_id=uuid.uuid4().hex,
                         max_retries=1, log_path=ORDER_LOG)
        ok = t.status == "pending"
        if ok and t.ord_no:
            tags = _read("tags.json", {})
            tags[str(t.ord_no)] = tag
            _write("tags.json", tags)
        how = "시장가" if market else f"{price:,}원"
        self.note(f"{'접수' if ok else '실패'} · {self.name(code)} {qty:,}주 {how} {'매수' if side == 'buy' else '매도'}"
                  f" ({tag}){'' if ok else ' — ' + t.detail}", "info" if ok else "error")
        if ok and side == "buy":
            with _lock:
                self.day["orders"] += 1
                _write("day.json", self.day)
        return {"ok": ok, "msg": t.detail, "ord_no": t.ord_no}

    def equity(self) -> int:
        dep = (self.deposit or {}).get("deposit_krw", 0)
        return dep + sum(h["eval_amount"] for h in self.holdings)

    def day_pnl(self) -> int:
        """오늘 실현 + 지금 보유분 평가손익. ponytail: 평가손익은 산 날부터 누적이라 어제 산 종목은 어제 몫까지 든다 — 하루 손실 한도가 조금 일찍 걸리는 쪽(안전)."""
        return int(self.day.get("pnl_realized", 0)) + sum(h["pl_amount"] for h in self.holdings)

    def buy_block(self, notional: int) -> str | None:
        if self.rules["safety"].get("halt_on_disconnect") and not feed.status()["connected"]:
            return "실시간 연결이 끊겨 새 매수를 멈췄습니다"
        return engine.safety_block(self.rules["safety"], {**self.day, "pnl": self.day_pnl()}, self.meta_positions(),
                                   notional, self.equity())

    def meta_positions(self) -> list[dict]:
        return [{"qty": h["quantity"]} for h in self.holdings]

    def buy(self, code: str, qty: int, price: int, market: bool, tag: str = "수동") -> dict:
        notional = qty * (price or self.snap(code)["px"])
        if why := self.buy_block(notional):
            self.note(f"매수 막음 · {self.name(code)} — {why}", "warn")
            return {"ok": False, "msg": why}
        r = self._submit(code, "buy", qty, price, market, tag)
        if r["ok"] and code not in self.day["bought"]:
            self.day["bought"][code] = {"key": "manual", "rule": self.rules.get("manual_rule"), "t": datetime.now().strftime("%H:%M:%S")}
            _write("day.json", self.day)
        return r

    def set_position_rule(self, code: str, rid: str | None) -> None:
        with _lock:
            m = self.meta.get(code)
            if m is not None:
                m["rule"] = rid if self.rule(rid) else None
                _write("positions.json", self.meta)

    def sell(self, code: str, qty: int, price: int, market: bool, tag: str = "수동") -> dict:
        return self._submit(code, "sell", qty, price, market, tag)

    def cancel(self, ord_no: str, code: str) -> dict:
        if err := self.ready():
            return {"ok": False, "msg": err}
        try:
            r = self.client.cancel_order(ord_no, code, quantity=0)
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": str(e)}
        ok = r.get("return_code") == 0
        self.note(f"취소 {'접수' if ok else '실패'} · {self.name(code)} 주문 {ord_no}{'' if ok else ' — ' + str(r.get('return_msg'))}",
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
        time.sleep(0.3)
        now = datetime.now()
        if 9 * 60 <= now.hour * 60 + now.minute < 15 * 60 + 20:
            return self.sell(code, h["quantity"], 0, True, why)
        # 정규장 밖(NXT 시간)은 시장가가 막힐 수 있어 2% 아래 지정가로 — 매수호가가 그보다 위면 그 값에 바로 체결된다
        px = self.snap(code)["px"] or h["current_price"]
        return self.sell(code, h["quantity"], engine.floor_tick(px * 0.98), False, why)

    def ladder(self, code: str, base: str, levels: list, amount: int, tag: str = "분할매수") -> dict:
        r = self.ref(code)
        bp = r.get(base) or 0
        if not bp:
            return {"ok": False, "msg": f"{'정규장' if base == 'reg' else '애프터'} 종가를 못 받았습니다"}
        orders = engine.ladder_orders(bp, levels, int(amount))
        if not orders:
            return {"ok": False, "msg": "금액이 작아 살 수 있는 수량이 없습니다"}
        res = [self.buy(code, o["qty"], o["price"], False, f"{tag} {o['pct']:g}%") for o in orders]
        return {"ok": all(x["ok"] for x in res), "n": sum(x["ok"] for x in res), "of": len(res)}

    # ── 주문체결(00) — 체결 즉시 반영 ─────────────────────────
    def on_order(self, ev: dict) -> None:
        if not ev.get("fill_qty"):
            return
        mine = self._my_orders().get(ev["ord_no"], {})
        tag = mine.get("tag", "")
        self.note(f"체결 · {self.name(ev['code'])} {ev['fill_qty']:,}주 {ev['fill_px']:,}원 {'매도' if ev['side'] == 'sell' else '매수'}"
                  f"{' (' + tag + ')' if tag else ''}")
        with _lock:
            if ev["side"] == "sell":
                h = next((x for x in self.holdings if x["code"] == ev["code"]), None)
                if h and h["avg_price"]:
                    self.day["pnl_realized"] = int(self.day.get("pnl_realized", 0)) + (ev["fill_px"] - h["avg_price"]) * ev["fill_qty"]
                m = self.meta.get(ev["code"])
                if m and tag.startswith("익절"):
                    m["breakeven"] = True
                    _write("positions.json", self.meta)
            _write("day.json", self.day)
        self._kick.set()

    # ── 매 초 판단 ─────────────────────────────────────────
    def tick(self, now: datetime) -> None:
        self._new_day()
        if not self.client or not self.is_active(now):
            return
        for h in list(self.holdings):
            code, m = h["code"], self.meta.get(h["code"])
            rule = self.rule(m.get("rule")) if m else None
            if not m or not rule:
                continue
            s = self.snap(code)
            px = s["px"]
            if px > m.get("high", 0):
                m["high"] = px
            pos = {"qty": h["quantity"], "avg": h["avg_price"], **m}
            acts = engine.exit_actions(pos, px, now, rule["exits"])
            if time.time() - m.get("retry_at", 0) < 30:                  # 직전 주문이 거부됐으면 30초 쉬고 다시(매 초 반복 주문 방지)
                continue
            if acts:
                r = self.exit_all(code, f"{acts[0]['kind']} · {acts[0]['why']}")
                m["retry_at"] = time.time()                              # 접수돼도 체결·잔고 반영까지 30초는 다시 안 낸다
                _write("positions.json", self.meta)
                continue
            for t in engine.take_orders(pos, rule["exits"]):
                r = self.sell(code, t["qty"], t["price"], False, f"익절{t['stage'] + 1} {t['why']}")
                if r["ok"]:
                    m["takes_done"] = sorted(set(m["takes_done"]) | {t["stage"]})
                else:
                    m["retry_at"] = time.time()
                    break
                _write("positions.json", self.meta)
        self._auto_buy(now)

    def _auto_buy(self, now: datetime) -> None:
        for rule in self.rules["rules"]:
            if not rule.get("on") or not engine.in_windows(now, rule.get("times")):
                continue
            amount = int(engine._num(rule.get("amount"), 0) or 0)
            if amount <= 0:
                continue
            for code in self.watch:
                key = f"{rule['id']}:{code}"
                if self.day["bought"].get(code, {}).get("key") == key or (rule.get("once_per_day") and code in self.day["bought"]):
                    continue
                self.ref(code)
                ok, unsupported = engine.conds_met(rule.get("conds", []), self.snap(code))
                if not ok:
                    continue
                self.day["bought"][code] = {"key": key, "rule": rule["id"], "t": now.strftime("%H:%M:%S")}
                _write("day.json", self.day)
                if rule["ladder"].get("on"):
                    self.ladder(code, rule["ladder"]["base"], rule["ladder"]["levels"], amount, rule["name"])
                else:
                    px = self.snap(code)["px"]
                    qty = int(amount // px) if px else 0
                    if qty:
                        self.buy(code, qty, px, rule.get("how") == "market", rule["name"])

    def rule_problems(self, rule: dict) -> list[str]:
        out = [f"'{c[0]}' 조건은 아직 데이터가 연결되지 않았습니다" for c in rule.get("conds", []) if c[0] not in engine.SUPPORTED]
        if not int(engine._num(rule.get("amount"), 0) or 0):
            out.append("1종목당 금액이 비어 있습니다")
        if not rule.get("times"):
            out.append("주문 가능 시간이 없습니다")
        return out

    # ── 배경 스레드 ─────────────────────────────────────────
    def start(self) -> None:
        self._kick = threading.Event()
        if not self.client:
            self.note(self.ready(), "warn")
            return
        feed.set_codes(self.watch + [h["code"] for h in self.holdings])
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
                        feed.set_codes(self.watch + [h["code"] for h in self.holdings])
                        last_acct = mono
                    if mono - last_pend > 15:
                        self.refresh_pending()
                        last_pend = mono
                with _lock:
                    self.tick(now)
            except Exception as e:                                      # noqa: BLE001 — 루프가 죽으면 청산 감시가 멈춘다
                self.note(f"판단 루프 오류: {type(e).__name__}: {e}", "error")
            time.sleep(1)
