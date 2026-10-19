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
               "confirm_real": True, "halt_on_disconnect": True, "near_pct": "1.5", "telegram": True, "auto_ref_days": "14"},
}


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
            # 배치 키 WebSocket 은 세션이 하나라 강한 종목 보드 체결 점(board_ticks)과 서로 끊는다 — 매매 키가 오면 바로 바꿀 것
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
        self.meta: dict = _read("positions.json", {})               # code -> 청산 감시 상태
        self.day: dict = _read("day.json", {})
        self.refs: dict = {}                                        # code -> 직전 거래일 {reg, aft, day, nxt}
        self._refc: dict = {}                                       # (code, day) -> 기준 종가
        self.plans: list = _read("plans.json", [])                   # 예약 분할 매수(날을 넘겨 유지)
        # 종목마다 기준일(10-19 사용자 "종목마다 기준일이 다르니까") — {code: "YYYYMMDD"}. 없으면 직전 거래일
        self.ref_days: dict = _read("ref_days.json", {})
        self.viewing: dict = {}                                     # 최근 60초 안에 화면에서 본 종목 -> 시각
        # 선정 일지(10-19 사용자 6번) — 고른 종목·기준일·매수/매도 체결이 쌓인다. 한 종목 한 줄, 다 팔면 닫히고 다시 고르면 새 줄
        self.journal: list = _read("journal.json", [])
        today = date.today().isoformat()
        for p in self.plans:                                        # 근접 발주 전 예약: 오늘 이미 다 걸렸으면 단계마다 걸린 날 표시(두 번 안 걸게)
            if p.get("placed_day") == today:
                for s_ in p["stages"]:
                    s_.setdefault("day", today)
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
        with _lock:
            j = self._jopen(code)
            if j:
                j["ref_day"] = ref_day or j.get("ref_day")
            else:
                self.journal.append({"code": code, "name": self.name(code), "picked": datetime.now().isoformat(timespec="minutes"),
                                     "ref_day": ref_day, "src": src, "buys": [], "sells": []})
            _write("journal.json", self.journal)

    def unpick(self, code: str) -> None:
        """목록에서 뺀 종목 — 한 주도 안 샀으면 고른 게 아니었던 걸로 일지에서 지운다(산 뒤면 그대로 남긴다)."""
        with _lock:
            j = self._jopen(code)
            if j and not j["buys"]:
                self.journal.remove(j)
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

    def _new_day(self) -> None:
        today = date.today().isoformat()
        if self.day.get("date") != today:
            self.day = {"date": today, "pnl_realized": 0, "orders": 0, "halted": None, "bought": {}}
            _write("day.json", self.day)
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
        from backtesting.value_burst_live import _is_market_day
        return _is_market_day(now.date()) and (7 * 60 + 50) <= now.hour * 60 + now.minute < 20 * 60 + 5

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

    def buy(self, code: str, qty: int, price: int, market: bool, tag: str = "수동", rule: str | None = None) -> dict:
        notional = qty * (price or self.snap(code)["px"])
        if why := self.buy_block(notional):
            self.note(f"매수 막음 · {self.name(code)} — {why}", "warn")
            return {"ok": False, "msg": why}
        r = self._submit(code, "buy", qty, price, market, tag)
        if r["ok"] and code not in self.day["bought"]:
            self.day["bought"][code] = {"key": "manual", "rule": rule or self.rules.get("manual_exit"), "t": datetime.now().strftime("%H:%M:%S")}
            _write("day.json", self.day)
        return r

    def set_position_rule(self, code: str, rid: str | None) -> None:
        with _lock:
            m = self.meta.get(code)
            if m is not None:
                m["rule"] = rid if self.exit_rule(rid) else None
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
                    rule: str | None = None) -> dict:
        r = self.ref(code, ref_day)
        bp = r.get(base) or 0
        if not bp:
            return {"ok": False, "msg": f"{ref_day or '직전 거래일'} {'정규장' if base == 'reg' else '애프터'} 종가를 못 받았습니다"}
        st = []
        for s_ in stages:
            pct, amt = engine._num(s_.get("pct")), int(engine._num(s_.get("amt"), 0) or 0)
            if pct is None or amt <= 0:
                continue
            price = engine.floor_tick(bp * (1 + pct / 100))
            if amt // price > 0:
                st.append({"pct": pct, "amt": amt, "price": price, "qty": int(amt // price), "filled": 0})
        if not st:
            return {"ok": False, "msg": "금액이 작아 살 수 있는 수량이 없습니다"}
        today = date.today()
        until = engine.keep_until(keep, datetime.now(), self._is_trading_day)
        plan = {"id": uuid.uuid4().hex[:8], "code": code, "name": self.name(code), "base": base, "ref_day": ref_day,
                "base_px": bp, "nxt": r.get("nxt", True), "stages": st, "keep": keep, "until": until, "tag": tag, "rule": rule,
                "created": datetime.now().isoformat(timespec="seconds"), "placed_day": None, "active": True, "status": "대기"}
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

    def ledger_day(self, code: str) -> str | None:
        p = ROOT / "static" / "dashboard" / "value_ledger.json"
        try:
            mt = p.stat().st_mtime
            if Desk._ledger[0] != mt:
                last: dict = {}
                for r in json.loads(p.read_text(encoding="utf-8"))["rows"]:
                    last[r[1]] = max(last.get(r[1], ""), r[0])
                Desk._ledger = (mt, last)
        except (OSError, ValueError, KeyError):
            return None
        d, n = Desk._ledger[1].get(code), engine._num(self.rules["safety"].get("auto_ref_days", "14"), None)
        if not d or not n or (date.today() - date.fromisoformat(d)).days > n:
            return None
        return d.replace("-", "")

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
        from backtesting.value_burst_live import _is_market_day
        return _is_market_day(d)

    def _place_plans(self, now: datetime) -> None:
        today = now.date().isoformat()
        cur = now.hour * 60 + now.minute
        if not (self.client and self._is_trading_day(now.date()) and 8 * 60 <= cur < 15 * 60 + 20):
            return
        near = engine._num(self.rules["safety"].get("near_pct"), 1.5)
        near = 1.5 if near is None else max(0.0, near)
        changed = False
        for p in self.plans:
            if not p["active"]:
                continue
            if p["until"] and today > p["until"]:
                p.update(active=False, status="기간 끝")
                changed = True
                continue
            if p["placed_day"] != today:                                    # 그날 처음: 기준가 다시 계산 + 감시 시작
                p["placed_day"], p["status"], changed = today, "감시 중", True
                if not p["ref_day"] and p["created"][:10] != today:         # 기준일을 안 정했으면 매일 직전 거래일 종가로
                    bp = self.ref(p["code"]).get(p["base"]) or p["base_px"]
                    p["base_px"] = bp
                    for s_ in p["stages"]:
                        s_["price"] = engine.floor_tick(bp * (1 + s_["pct"] / 100))
                        s_["qty"] = max(s_["filled"], int(s_["amt"] // s_["price"]))
            px = feed.quotes.get(p["code"], {}).get("px")                   # 실시간 체결가만 — 오래된 잔고 가격으로 걸지 않는다
            if not px:
                continue
            for i, s_ in enumerate(p["stages"]):
                left = s_["qty"] - s_["filled"]
                if left <= 0 or s_.get("day") == today or time.time() < s_.get("wait", 0):
                    continue
                if px > s_["price"] * (1 + near / 100):
                    continue
                r = self.buy(p["code"], left, s_["price"], False, f"예약:{p['id']}:{i} {p['tag']} {s_['pct']:g}%", rule=p.get("rule"))
                if r["ok"]:
                    s_["day"] = today
                    self.tg(f"근접 주문 · {p['name']} {s_['pct']:g}% {s_['price']:,}원 × {left:,}주 (현재 {px:,}원)")
                else:
                    s_["wait"] = time.time() + 60                           # 막히거나 거부되면 1분 뒤 다시
                changed = True
            n = sum(1 for s_ in p["stages"] if s_.get("day") == today and s_["filled"] < s_["qty"])
            st = f"주문 걸림 {n}/{len(p['stages'])}" if n else "감시 중"
            if p["active"] and p["status"] != st:
                p["status"], changed = st, True
        if changed:
            _write("plans.json", self.plans)

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
            self._jfill(ev, tag)
            if ev["side"] == "buy" and tag.startswith("예약:"):
                _, pid, i = tag.split(" ")[0].split(":")
                p = next((x for x in self.plans if x["id"] == pid), None)
                if p and int(i) < len(p["stages"]):
                    p["stages"][int(i)]["filled"] += ev["fill_qty"]
                    if all(s_["filled"] >= s_["qty"] for s_ in p["stages"]):
                        p.update(active=False, status="완료")
                    _write("plans.json", self.plans)
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
            rule = self.exit_rule(m.get("rule")) if m else None
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
        self._place_plans(now)
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
                rd = self.rule_ref_day(rule, code)
                if rd is False:                                          # '신고대금 날' 규칙인데 최근 신고일이 없는 종목은 건너뛴다
                    continue
                self.ref(code)
                ok, unsupported = engine.conds_met(rule.get("conds", []), self.snap(code))
                if not ok:
                    continue
                self.day["bought"][code] = {"key": key, "rule": rule.get("exit"), "t": now.strftime("%H:%M:%S")}
                _write("day.json", self.day)
                if rule["ladder"].get("on"):
                    L = rule["ladder"]
                    stages = [{"pct": lv[0], "amt": amount * (engine._num(lv[1], 0) or 0) / 100} for lv in L["levels"]]
                    self.create_plan(code, L["base"], rd, stages,
                                     L.get("keep") or {"mode": "today"}, rule["name"], rule.get("exit"))
                else:
                    px = self.snap(code)["px"]
                    qty = int(amount // px) if px else 0
                    if qty:
                        self.buy(code, qty, px, rule.get("how") == "market", rule["name"], rule=rule.get("exit"))

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
            return self.ledger_day(code) or False
        if mode == "date":
            return (L.get("ref_day") or "").replace("-", "") or None
        return None

    def rule_problems(self, rule: dict) -> list[str]:
        out = [f"'{c[0]}' 조건은 아직 데이터가 연결되지 않았습니다" for c in rule.get("conds", []) if c[0] not in engine.SUPPORTED]
        if not int(engine._num(rule.get("amount"), 0) or 0):
            out.append("1종목당 금액이 비어 있습니다")
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
                    if mono - last_pend > 15:
                        self.refresh_pending()
                        last_pend = mono
                with _lock:
                    self.tick(now)
            except Exception as e:                                      # noqa: BLE001 — 루프가 죽으면 청산 감시가 멈춘다
                self.note(f"판단 루프 오류: {type(e).__name__}: {e}", "error")
            time.sleep(1)
