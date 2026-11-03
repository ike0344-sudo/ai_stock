"""근접 발주 — 현재가가 단계 가격 near_pct% 위로 내려와야만 주문, 같은 날 두 번 안 낸다."""
from datetime import date, datetime

from trader import desk as d
from trader import feed


def _desk(monkeypatch, px):
    k = object.__new__(d.Desk)
    k.client, k.rules = object(), {"safety": {"near_pct": "1.5", "telegram": False}}
    k.plans = [{"id": "p1", "code": "000001", "name": "가", "active": True, "until": None, "placed_day": None,
                "ref_day": "20261014", "created": "2026-10-19T08:00:00", "tag": "t", "rule": None, "status": "대기",
                "stages": [{"pct": -3, "price": 9700, "qty": 10, "filled": 0}, {"pct": -5, "price": 9500, "qty": 10, "filled": 0}]}]
    k.bought, k.pending, tags = [], [], {}
    k._my_orders = lambda: {o: {"tag": t} for o, t in tags.items()}

    def buy(code, qty, price, market, tag, rule=None):              # 실제처럼 미체결에 올라간다('주문 걸림' 은 미체결로 센다)
        k.bought.append(price)
        no = f"P{len(k.bought)}"
        tags[no] = tag
        k.pending.append({"ord_no": no, "code": code, "side": "buy", "left": qty, "price": price})
        return {"ok": True}
    k.buy = buy
    k._is_trading_day = lambda _d: True
    monkeypatch.setattr(d, "_write", lambda *a: None)
    monkeypatch.setitem(feed.quotes, "000001", {"px": px})
    return k


def test_far_price_places_nothing(monkeypatch):
    k = _desk(monkeypatch, 10000)
    k._place_plans(datetime(2026, 10, 20, 9, 5))
    assert k.bought == [] and k.plans[0]["status"] == "감시 중"


def test_near_places_only_close_stage_once(monkeypatch):
    k = _desk(monkeypatch, 9800)                      # 9700×1.015=9845 안 · 9500×1.015=9642 밖
    now = datetime(2026, 10, 20, 9, 5)
    k._place_plans(now)
    k._place_plans(now)
    assert k.bought == [9700] and k.plans[0]["status"] == "주문 걸림 1/2"
    feed.quotes["000001"]["px"] = 9600
    k._place_plans(now)
    assert k.bought == [9700, 9500]


def test_ref_day_auto_from_ledger(monkeypatch, tmp_path):
    import json
    from datetime import date, timedelta
    p = tmp_path / "static" / "dashboard"
    p.mkdir(parents=True)
    recent, old = (date.today() - timedelta(days=3)).isoformat(), (date.today() - timedelta(days=60)).isoformat()
    (p / "value_ledger.json").write_text(json.dumps({"rows": [[old, "A"] + [None] * 19, [recent, "A"] + [None] * 18 + [15.0], [old, "B"] + [None] * 19]}), encoding="utf-8")
    monkeypatch.setattr(d, "ROOT", tmp_path)
    monkeypatch.setattr(d.Desk, "_ledger", (0.0, {}))
    k = object.__new__(d.Desk)
    k.rules, k.ref_days = {"safety": {"auto_ref_days": "14"}}, {}
    assert k.ref_day("A") == recent.replace("-", "") and k.ref_src("A") == "신고대금"
    assert k.ledger_day("A", "12") == recent.replace("-", "") and k.ledger_day("A", "20") is None   # 그날 상승률 15% — 20% 이상만이면 없음
    assert k.ref_day("B") is None and k.ref_src("B") == "직전"            # 60일 전 신고일은 너무 오래됨
    k.ref_days = {"A": "prev"}
    assert k.ref_day("A") is None
    k.ref_days = {"A": "20261001"}
    assert k.ref_day("A") == "20261001" and k.ref_src("A") == "직접"


def test_rule_ref_day_modes(monkeypatch):
    k = object.__new__(d.Desk)
    k.ref_days = {}
    monkeypatch.setattr(d.Desk, "ledger_day", lambda self, c, m=None, reg_only=False: "20261016" if c == "A" else None)
    rule = lambda **L: {"ladder": {"on": True, **L}}
    assert k.rule_ref_day(rule(), "A") == "20261016"                  # 기본 = 신고대금 날
    assert k.rule_ref_day(rule(), "B") is False                       # 신고일 없으면 안 삼
    assert k.rule_ref_day(rule(ref_mode="prev"), "B") is None
    assert k.rule_ref_day(rule(ref_mode="date", ref_day="2026-10-01"), "B") == "20261001"
    k.ref_days = {"B": "20261002"}
    assert k.rule_ref_day(rule(), "B") == "20261002"                  # 종목에 직접 정한 날이 먼저


def _guarded(monkeypatch, low, px):
    k = _desk(monkeypatch, px)
    k.note = lambda *a, **kw: None
    k.plans[0].update(base_px=10000, guard={"day": "2026-10-20", "until": "0930", "pct": 5})
    feed.quotes["000001"] = {"px": px, "low": low}
    return k


def test_guard_waits_then_drops_plan_on_early_crash(monkeypatch):
    k = _guarded(monkeypatch, 9400, 9690)              # 09:30 전 저가 9,400 ≤ 10,000×0.95
    k._place_plans(datetime(2026, 10, 20, 9, 10))
    assert k.bought == [] and k.plans[0]["status"] == "급락 지켜보는 중"
    k._place_plans(datetime(2026, 10, 20, 9, 31))
    assert k.bought == [] and not k.plans[0]["active"] and k.plans[0]["status"].startswith("급락")


def test_guard_passes_then_buys(monkeypatch):
    k = _guarded(monkeypatch, 9600, 9690)              # 저가 9,600 > 9,500 → 급락 아님
    k._place_plans(datetime(2026, 10, 20, 9, 31))
    assert k.bought == [9700] and k.plans[0]["active"]


def test_rule_amount_falls_back_to_weight():
    k = object.__new__(d.Desk)
    k.rules = {"safety": {"max_weight_pct": "50"}}
    k.equity = lambda: 30_000_000
    assert k.rule_amount({"amount": ""}) == 15_000_000
    assert k.rule_amount({"amount": "20000000"}) == 20_000_000
    k.rules = {"safety": {"max_weight_pct": "100", "max_positions": "2"}}
    assert k.rule_amount({"amount": ""}) == 15_000_000                # 100% ÷ 2종목
    k.rules = {"safety": {"max_weight_pct": "", "max_positions": "3"}}
    assert k.rule_amount({"amount": ""}) == 10_000_000
    k.rules = {"safety": {"max_weight_pct": "", "max_positions": ""}}
    assert k.rule_amount({"amount": ""}) == 0


def test_rule_amount_percent_split_by_positions():
    k = object.__new__(d.Desk)
    k.equity = lambda: 30_000_000
    k.rules = {"safety": {"max_weight_pct": "50", "max_positions": "2"}}
    assert k.rule_amount({"amount": "100%"}) == 15_000_000            # 100% ÷ 2
    k.rules = {"safety": {"max_weight_pct": "30", "max_positions": "2"}}
    assert k.rule_amount({"amount": "100%"}) == 9_000_000             # 50% 지만 최대 비중 30% 로
    k.rules = {"safety": {"max_weight_pct": "", "max_positions": ""}}
    assert k.rule_amount({"amount": "40%"}) == 12_000_000


def test_gap_skip_waits_for_open_and_skips_gap_down(monkeypatch):
    k = _desk(monkeypatch, 9400)
    k.note = lambda *a, **kw: None
    k.plans[0]["gap_skip"] = True
    feed.quotes["000001"] = {"px": 9400}                 # 시가를 아직 못 받음
    k._place_plans(datetime(2026, 10, 20, 9, 1))
    assert k.bought == [] and k.plans[0]["status"] == "시가 기다리는 중"
    feed.quotes["000001"] = {"px": 9400, "open": 9300}   # 시가 9,300 < 마지막 단계 9,500 → 오늘 쉼
    k._place_plans(datetime(2026, 10, 20, 9, 2))
    assert k.bought == [] and k.plans[0]["status"].startswith("갭 하락")
    feed.quotes["000001"] = {"px": 9400, "open": 9800}   # 갭 아님 → 산다
    k._place_plans(datetime(2026, 10, 20, 9, 3))
    assert k.bought == [9700, 9500]


def test_drop_cancels_when_prev_close_below(monkeypatch):
    k = _desk(monkeypatch, 9400)
    k.note = lambda *a, **kw: None
    k.plans[0].update(base_px=10000, drop_pct=5)
    k.ref = lambda code, day=None: {"reg": 9480}       # 전날 종가 9,480 ≤ 9,500
    k._place_plans(datetime(2026, 10, 21, 9, 5))
    assert k.bought == [] and not k.plans[0]["active"] and "버림" in k.plans[0]["status"]
    k = _desk(monkeypatch, 9400)
    k.plans[0].update(base_px=10000, drop_pct=5)
    k.ref = lambda code, day=None: {"reg": 9600}
    k._place_plans(datetime(2026, 10, 21, 9, 5))
    assert k.bought == [9700, 9500]


def test_follow_high_moves_base_to_new_high_close(monkeypatch):
    import backtesting.value_ledger as vl
    rows = [["20261014", 0, 7000, 0, 6870, 0, "m"], ["20261015", 0, 6950, 0, 6900, 0, "m"],   # 기준일 고가 7,000 · 15일은 못 넘음
            ["20261016", 0, 9180, 0, 9010, 0, "m"], ["20261019", 0, 9500, 0, 9120, 0, "m"]]   # 16일 새 고가 → 기준 9,010 (19일은 '오늘'이라 안 봄)
    monkeypatch.setattr(vl, "regular_daily_rows", lambda code: rows)
    k = object.__new__(d.Desk)
    k._is_trading_day = lambda dd: dd.weekday() < 5
    k.note = lambda *a, **kw: None
    k.rules = {"rules": [], "exits": [{"id": "f6"}]}
    k.exit_rule = lambda i: i == "f6"
    p = {"code": "396300", "name": "HT", "base": "reg", "ref_day": "20261014", "base_px": 6870, "keep": {"mode": "days", "days": "5"},
         "until": "2026-10-21", "stages": [{"pct": -3, "amt": 1_000_000, "price": 6660, "qty": 150, "filled": 150}], "rule": "main", "follow_exit": "f6"}
    k._follow_high(p, date(2026, 10, 19))
    assert p["base_px"] == 9010 and p["stages"][0]["price"] == 8730 and p["follow_day"] == "20261016" and p["until"] == "2026-10-23"
    assert p["stages"][0]["filled"] == 0                             # 산 뒤에도 옮기면 단계를 새로 건다(10-20)
    assert k._plan_rule(p) == "f6" and k._plan_rule({**p, "follow_day": None}) == "main"                                        # 옮긴 뒤 산 건 고점 따라가기용 청산(10-20)


def test_paper_fill_and_block(monkeypatch, tmp_path):
    monkeypatch.setattr(d, "STATE", tmp_path)
    k = object.__new__(d.Desk)
    k.rules = {"safety": {"paper": True, "paper_capital": "1000000", "max_stops": "2"}}
    k.paper_state, k.no_auto, k._ci = None, set(), {}
    k.meta, k.holdings, k.pending, k.names = {}, [], [], {}
    got = []
    k.on_order = got.append
    k._sync_meta = lambda: None
    feed.quotes["000002"] = {"px": 10_000}
    r = k._paper_submit("000002", "buy", 50, 9_900, False, "t")          # 지정가 9,900 — 현재가 10,000 이라 아직 안 됨
    assert r["ok"] and not got
    assert not k._paper_submit("000002", "buy", 200, 9_900, False, "t")["ok"]   # 100만 원으로 200주 × 9,900 은 안 됨
    feed.quotes["000002"]["px"] = 9_850
    k._paper_match()
    assert got[0]["fill_px"] == 9_850 and k.holdings[0]["quantity"] == 50 and k.deposit["deposit_krw"] < 1_000_000 - 9_850 * 50
    assert not k._paper_submit("000002", "sell", 60, 0, True, "t")["ok"]      # 50주뿐
    k.day = {"stops": 2}
    monkeypatch.setattr(feed, "status", lambda: {"connected": True})
    k.mkt = {"chg": None, "t": 0}
    assert "손절 2번" in k.buy_block(1)


def test_ma60_stage_buys_inside_band_both_sides(monkeypatch):
    """1차 = 15분봉 60선 ±1% — 60선 위·아래 1% 안에 들어오면 60선 +1% 지정가로 산다, 밖이면 안 산다(10-20 사용자)."""
    k = _desk(monkeypatch, 10300)
    k.plans[0]["stages"][0].update(ma=True, band=1.0, amt=100_000, pct=0.0); k.plans[0]["base"] = "reg"
    k.ma60_15 = lambda code, base: 10000
    now = datetime(2026, 10, 20, 9, 5)
    k._place_plans(now)                               # 10,300 > 10,100 — 위로 범위 밖
    assert k.bought == [] and k.plans[0]["stages"][0]["price"] == 10100
    feed.quotes["000001"]["px"] = 9850                # 9,850 < 9,900 — 아래로 범위 밖
    k._place_plans(now)
    assert k.bought == []
    feed.quotes["000001"]["px"] = 10080               # 위쪽 범위 안
    k._place_plans(now)
    assert k.bought == [10100] and k.plans[0]["stages"][0]["qty"] == 9
    k2 = _desk(monkeypatch, 9920)                     # 아래쪽 범위 안
    k2.plans[0]["stages"][0].update(ma=True, band=1.0, amt=100_000, pct=0.0); k2.plans[0]["base"] = "reg"
    k2.ma60_15 = lambda code, base: 10000
    k2._place_plans(now)
    assert k2.bought == [10100]


def test_ma_stage_offset_and_marker():
    """2차도 60선 — 60선 −3% 자리 ±1% 안이면 산다(10-20 사용자 "2차 매수도 1차처럼")."""
    k = object.__new__(d.Desk)
    k.ma60_15 = lambda code, base: 10000
    m, lo, hi = k.ma_band("000001", "reg", {"pct": -3, "band": 1})
    assert m == 10000 and round(lo) == 9603 and round(hi) == 9797
    assert d._lv_ex(["-3", "50", {"ma": "2"}]) == {"ma": True, "band": 2.0} and d._lv_ex(["-3", "50"]) == {}
    assert d._lv_ex(["-3", "50", {"from": "09:30", "to": "10:00"}]) == {"t0": "0930", "t1": "1000"}


def test_stage_time_window(monkeypatch):
    """단계 시각 — 1차는 09:30~10:00 에만 산다(10-20 사용자 "1차·2차 매수 시간")."""
    k = _desk(monkeypatch, 9600)                      # 두 단계 다 닿는 가격
    k.plans[0]["stages"][0].update(t0="0930", t1="1000")
    k._place_plans(datetime(2026, 10, 20, 9, 5))
    assert k.bought == [9500]                         # 1차는 아직 시각 전
    k._place_plans(datetime(2026, 10, 20, 9, 31))
    assert k.bought == [9500, 9700]


def test_ma_env_stop_breaks_lower_band():
    """60선 엔벨로프 −6% 하단을 깨면 전량 손절 — 60선 10,000 이면 9,400 아래(10-20 사용자)."""
    from trader import engine
    ex = {"stop": [False, "3.5"], "take": [False, []], "trail": [False, ""], "days": [False, ""], "close": [False, "15:15"], "ma_env": [True, "6", "reg"]}
    pos = {"qty": 10, "avg": 10000, "ma60": 10000}
    now = datetime(2026, 10, 20, 10, 0)
    assert engine.exit_actions(pos, 9400, now, ex) == []
    a = engine.exit_actions(pos, 9390, now, ex)
    assert a and a[0]["kind"] == "stop" and "엔벨로프" in a[0]["why"]
    assert engine.exit_actions({**pos, "ma60": 0}, 9000, now, ex) == []          # 60선을 못 받았으면 판단 안 함
    assert engine.exit_actions(pos, 9000, now, {**ex, "ma_env": [False, "6", "reg"]}) == []


def test_ma_stop_after_envelope_break(monkeypatch):
    """60선 −6% 하단을 깨면 그 예약의 60선 단계는 그만 산다 — 다시 범위에 들어와도 안 산다(10-20 사용자)."""
    k = _desk(monkeypatch, 9300)                      # 60선 10,000 · 하단 9,400 아래
    k.note = k.tg = lambda *a, **kw: None
    k._my_orders = lambda: {}
    k.pending = []
    k.plans[0].update(base="reg", ma_stop=6.0)
    k.plans[0]["stages"][0].update(ma=True, band=1.0, amt=100_000, pct=0.0)
    k.plans[0]["stages"] = k.plans[0]["stages"][:1]
    k.ma60_15 = lambda code, base: 10000
    now = datetime(2026, 10, 20, 9, 5)
    k._place_plans(now)
    assert k.bought == [] and k.plans[0].get("ma_dead") and "60선" in k.plans[0]["status"]
    feed.quotes["000001"]["px"] = 10000               # 다시 60선 범위 안
    k._place_plans(now)
    assert k.bought == []


def test_follow_once_ends_plan_after_sold(monkeypatch):
    """판 뒤엔 다시 안 따라감 — 산 뒤 잔고에서 본 종목이 사라지면(다 팖) 예약을 끝낸다. 체결 직후 잔고에 아직 없을 땐 안 끝낸다(10-20 사용자)."""
    k = _desk(monkeypatch, 10000)
    k.note = lambda *a, **kw: None
    k.plans[0].update(follow_once=True, bought=True)
    k.holdings = []                                   # 체결 직후 — 잔고 갱신 전
    now = datetime(2026, 10, 20, 9, 5)
    k._place_plans(now)
    assert k.plans[0]["active"]
    k.holdings = [{"code": "000001"}]
    k._place_plans(now)
    assert k.plans[0]["active"] and k.plans[0]["held_seen"]
    k.holdings = []                                   # 다 팖
    k._place_plans(now)
    assert not k.plans[0]["active"] and "판 뒤" in k.plans[0]["status"]


def test_new_high_definitions(monkeypatch):
    """고점 갱신 정의 — 전날 고가 돌파(기본) vs 기준일 뒤 최고가 돌파(예전). 고가 100 → 90 → 95 → 105."""
    import backtesting.value_ledger as V
    rows = [["20261001", 0, 100, 0, 98], ["20261002", 0, 90, 0, 88], ["20261005", 0, 95, 0, 94], ["20261006", 0, 105, 0, 104]]
    monkeypatch.setattr(V, "regular_daily_rows", lambda code: rows)
    assert d.Desk._new_high("A", "20261001", "reg", "20261006")[0][0] == "20261005"          # 전날 고가: 10-05(95 > 90)
    assert d.Desk._new_high("A", "20261001", "reg", "20261006", "run") == (None, 100)         # 예전: 100 을 아직 못 넘음
    assert d.Desk._new_high("A", "20261001", "reg", "20261007", "run")[0][0] == "20261006"   # 105 > 100


def test_same_day_value_high(monkeypatch):
    """신고대금 당일부터(10-21 사용자) — 장중 누적 대금 ≥ 52주 최대·1,000억이면 오늘이 기준일, 아니면 장부 날."""
    k = object.__new__(d.Desk)
    k.ref_days, k._is_trading_day = {}, lambda _d: True
    monkeypatch.setattr(d.Desk, "ledger_day", lambda self, c, m=None, reg_only=False: "20261016")
    monkeypatch.setattr(d.Desk, "vref", lambda self, c: {"aft": 2000})
    rule = {"ladder": {"on": True, "ref_today": True, "ref_min_chg": "10"}}
    monkeypatch.setitem(feed.quotes, "A", {"value": 1500e8, "chg": 20.0})
    assert k.rule_ref_day(rule, "A") == "20261016"                    # 1,500억 < 2,000억
    feed.quotes["A"] = {"value": 2100e8, "chg": 5.0}
    assert k.rule_ref_day(rule, "A") == "20261016"                    # 등락률 5% < 10%
    feed.quotes["A"] = {"value": 2100e8, "chg": 12.0}
    assert k.rule_ref_day(rule, "A") == date.today().strftime("%Y%m%d")
    assert k.rule_ref_day({"ladder": {"on": True}}, "A") == "20261016"   # 체크 안 하면 예전대로
    monkeypatch.setattr(d.Desk, "vref", lambda self, c: {"aft": 500})
    feed.quotes["A"] = {"value": 900e8, "chg": 12.0}
    assert k.rule_ref_day(rule, "A") == "20261016"                    # 1,000억 아래는 신고대금 아님(장부 하한)


def test_same_day_plan_buys_only_ma_then_fixes_base(monkeypatch):
    """당일 예약 — 오늘은 60선 단계만, 다음 거래일엔 기준가를 신고일 종가로 고친 뒤 종가 % 단계도."""
    k = _desk(monkeypatch, 9600)
    p = k.plans[0]
    p.update(ref_day="20261020", same_day=True, base="aft", base_px=10500, drop_pct=5.0)
    p["stages"][0].update(ma=True, band=1.0, amt=100_000, pct=0.0)
    p["stages"][1].update(amt=100_000)
    k.ma60_15 = lambda code, base: 9600
    k.ref = lambda code, day=None: {"aft": 10000, "reg": 9900}
    k._refc, k.note = {}, lambda *a, **kw: None
    k._place_plans(datetime(2026, 10, 20, 14, 0))       # 9,600 은 −5%(9,975) 단계 근처지만 당일이라 60선만
    assert k.bought == [9690] and p["same_day"]
    p["stages"][0]["filled"] = p["stages"][0]["qty"]                # 체결됨
    k._place_plans(datetime(2026, 10, 21, 9, 5))
    assert "same_day" not in p and p["base_px"] == 10000 and p["stages"][1]["price"] == 9500 and k.bought == [9690, 9500]


def test_peak_stop_ends_plan_after_rise(monkeypatch):
    """오른 뒤 재매수 금지(10-21 사용자) — 기준일 고가 +10% 를 넘은 적 있으면 예약 끝, 안 넘었으면 그대로 산다."""
    k = _desk(monkeypatch, 9700)
    k.note = lambda *a, **kw: None
    k.plans[0].update(peak_stop=10.0, base="reg")
    monkeypatch.setattr(d.Desk, "_peak_since", staticmethod(lambda c, rd, b: (10000, 9000, 10900)))
    k._place_plans(datetime(2026, 10, 20, 9, 5))
    assert k.bought == [9700] and k.plans[0]["active"]           # 최고 10,900 < 11,000
    k2 = _desk(monkeypatch, 9700)
    k2.note = lambda *a, **kw: None
    k2.plans[0].update(peak_stop=10.0, base="reg"); k2.pending, k2._my_orders = [], lambda: {}
    monkeypatch.setattr(d.Desk, "_peak_since", staticmethod(lambda c, rd, b: (10000, 9000, 11050)))
    k2._place_plans(datetime(2026, 10, 20, 9, 5))
    assert k2.bought == [] and not k2.plans[0]["active"] and "재매수 금지" in k2.plans[0]["status"]


def test_peak_stop_by_close(monkeypatch):
    """종가 대비(10-21 사용자 "신고대금 종가 대비 24% 이상 상승하면") — 고가 대비로는 안 넘어도 종가 +24% 를 넘으면 끝."""
    k = _desk(monkeypatch, 9700)
    k.note, k.pending, k._my_orders = (lambda *a, **kw: None), [], (lambda: {})
    k.plans[0].update(peak_stop=24.0, peak_by="close", base="reg")
    monkeypatch.setattr(d.Desk, "_peak_since", staticmethod(lambda c, rd, b: (11000, 9000, 11200)))   # 종가 9,000 × 1.24 = 11,160 < 11,200
    k._place_plans(datetime(2026, 10, 20, 9, 5))
    assert k.bought == [] and "종가 +24%" in k.plans[0]["status"]


def test_ma_turn_ends_plan(monkeypatch):
    """60선 꺾이면 끝(10-21 사용자) — 15분봉 60선이 하루 전보다 낮으면 예약 끝, 높으면 그대로 산다."""
    k = _desk(monkeypatch, 9700)
    k.note, k.pending, k._my_orders = (lambda *a, **kw: None), [], (lambda: {})
    k.plans[0].update(ma_turn=True, base="reg")
    k.ma60_15, k.ma60_15_prev = (lambda c, b: 10100), (lambda c, b: 10000)
    k._place_plans(datetime(2026, 10, 20, 9, 5))
    assert k.bought == [9700] and k.plans[0]["active"]
    k2 = _desk(monkeypatch, 9700)
    k2.note, k2.pending, k2._my_orders = (lambda *a, **kw: None), [], (lambda: {})
    k2.plans[0].update(ma_turn=True, base="reg")
    k2.ma60_15, k2.ma60_15_prev = (lambda c, b: 9990), (lambda c, b: 10000)
    k2._place_plans(datetime(2026, 10, 20, 9, 5))
    assert k2.bought == [] and "꺾임" in k2.plans[0]["status"]


def test_stage_src_picks_its_own_ma(monkeypatch):
    """단계마다 60선 봉(10-21 사용자 "나눠 사기") — src=aft 단계는 애프터 60선, 없으면 규칙 기준(정규장) 60선으로 산다."""
    k = _desk(monkeypatch, 10500)
    k.plans[0]["base"] = "reg"
    k.plans[0]["stages"][0].update(ma=True, band=0.6, amt=100_000, pct=0.0, src="aft")
    k.plans[0]["stages"][1].update(ma=True, band=0.6, amt=100_000, pct=0.0)
    k.ma60_15 = lambda code, base: 10500 if base == "aft" else 10000
    k._place_plans(datetime(2026, 10, 20, 9, 5))
    assert k.bought == [10560]                        # 애프터 60선 10,500 ±0.6% 위쪽 끝 · 정규장 60선 10,000 단계는 범위 밖
    from trader import engine
    assert engine.level_opts(["0", "50", {"ma": "0.6", "src": "aft"}])["src"] == "aft" and engine.level_opts(["0", "50", {"ma": "1"}])["src"] is None


def test_rebuy_after_stop_resets_stages_next_day(monkeypatch):
    """손절 뒤 다시 사기 — 손절한 날·잔고에 남은 동안은 안 사고, 다음 거래일에 단계를 처음부터 다시 건다(최대 n번, 10-21 사용자 한국콜마)."""
    k = _desk(monkeypatch, 9800)
    k.note = lambda *a, **kw: None
    for s_ in k.plans[0]["stages"]:
        s_.update(amt=s_["price"] * 10, filled=10)
    k.plans[0].update(rebuy=1, bought=True, rebuy_arm="2026-10-20", ma_dead="2026-10-20")
    k.holdings = []
    k._place_plans(datetime(2026, 10, 20, 9, 5))                     # 손절한 날 — 안 삼
    assert k.bought == [] and k.plans[0]["rebuy_arm"]
    k.holdings = [{"code": "000001"}]
    k._place_plans(datetime(2026, 10, 21, 9, 5))                     # 잔고에서 아직 안 빠짐 — 기다림
    assert k.bought == []
    k.holdings = []
    k._place_plans(datetime(2026, 10, 21, 9, 6))
    p = k.plans[0]
    assert k.bought == [9700] and p["rebuy"] == 0 and "rebuy_arm" not in p and "ma_dead" not in p
    assert [s_["filled"] for s_ in p["stages"]] == [0, 0]


def test_rule_window_blocks_reservation_buy(monkeypatch):
    """매수 규칙 주문 가능 시간 밖이면 예약도 안 산다 — 만든 뒤 날에도(10-22 사용자 "9시 30분부터 매수")."""
    k = _desk(monkeypatch, 9800)
    k.rules["rules"] = [{"id": "r1", "name": "t", "times": [["09:30", "15:20"]]}]
    k.plans[0]["buy_rule"] = "r1"
    k._place_plans(datetime(2026, 10, 20, 9, 5))
    assert k.bought == []
    k._place_plans(datetime(2026, 10, 20, 9, 35))
    assert k.bought == [9700]


def test_missed_ma_stage_bought_with_next(monkeypatch):
    """60선 1차가 이미 범위 아래로 지나갔으면 2차가 살 때 1차 몫도 같은 값에(10-22 사용자 '다음 매수 자리에 같이')."""
    k = _desk(monkeypatch, 9500)
    k.plans[0]["stages"] = [{"pct": 0, "amt": 97000, "price": 10000, "qty": 9, "filled": 0, "ma": True, "band": 0.6, "src": "aft"},
                            {"pct": 0, "amt": 95000, "price": 9550, "qty": 9, "filled": 0, "ma": True, "band": 0.6, "src": "reg"}]
    k.ma_band = lambda code, src, s_: (10000, 9940, 10060) if src == "aft" else (9500, 9443, 9557)
    k._my_orders, k.pending, k.note, k.tg = (lambda: {}), [], (lambda *a, **kw: None), (lambda *a, **kw: None)
    k._plan_rule = lambda p: None
    k._place_plans(datetime(2026, 10, 20, 9, 40))
    assert k.bought == [9550, 9550]                         # 2차 9,550 + 놓친 1차 몫도 9,550


def test_held_code_not_counted_in_max_positions(monkeypatch):
    """11-02 지니언스: 6주 산 뒤 '동시 보유 최대 2종목'에 막힘 — 이미 가진 종목 더 사기는 새 종목이 아니다."""
    k = object.__new__(d.Desk)
    k.holdings = [{"code": "A", "quantity": 1}, {"code": "B", "quantity": 6}]
    assert len(k.meta_positions("B")) == 1 and len(k.meta_positions("C")) == 2


def test_sync_puts_rule_gates_on_old_plan(monkeypatch):
    """11-02 안랩: 버팀 확인 전에 만든 예약이 옛 방식으로 삼 — 켤 때·규칙 저장 때 지금 규칙의 관문을 입힌다."""
    k = object.__new__(d.Desk)
    k.rules = {"rules": [{"id": "r", "ladder": {"c_near": {"on": True, "pct": "-2", "full": True, "src": "reg"},
                                                 "ma_confirm": {"on": True, "n": "2", "hold": "2"}, "slice": {"on": True}}}]}
    k.plans = [{"active": True, "buy_rule": "r", "name": "가", "base": "aft", "ref_day": "20261028", "ref_cl": {"reg": 110900, "aft": 111600},
                "stages": [{"ma": True}]}]
    k.note = lambda *a, **kw: None
    monkeypatch.setattr(d, "_write", lambda *a: None)
    k.sync_c_src()
    p = k.plans[0]
    assert (p["ma_confirm"], p["ma_hold"], p["c_near"], p["c_src"], p["c_px"], p["c_full"], p["slice"]) == (2, 2, 2, "reg", 110900, True, True)
    k.rules["rules"][0]["ladder"] = {}                               # 규칙에서 끄면 예약에서도 빠진다
    k.sync_c_src()
    assert not {"ma_confirm", "c_near", "c_px", "slice"} & set(p)


def test_seed_fills_from_journal(monkeypatch):
    """11-02: 재시작하면 체결 목록(메모리)이 비어 차트 매수·매도 표시가 사라졌다 — 오늘 일지에서 되살린다."""
    from collections import deque
    today = date.today().isoformat()
    j = [{"code": "A", "buys": [[f"{today}T09:02", 114, 114300, "t"], ["2026-01-01T09:00", 1, 1, "old"]], "sells": [[f"{today}T14:05", 114, 120000, "s"]]}]
    monkeypatch.setattr(d, "_read", lambda n, dflt=None: j if n == "journal.json" else dflt)
    monkeypatch.setattr(feed, "order_events", deque(maxlen=10))
    object.__new__(d.Desk)._seed_fills()
    assert [(e["side"], e["fill_px"]) for e in feed.order_events] == [("buy", 114300), ("sell", 120000)]


def test_prev_ref_prefers_local_regular_close(monkeypatch):
    """자정에 ka10001 기준가가 전전날 값(118,100)이어도 로컬 정규장 종가(116,200)를 쓴다 — 11-03 안랩 호가 등락률."""
    from trader import desk as dk

    class C:
        def get_daily_chart(self, code): return {"stk_dt_pole_chart_qry": [{"dt": "20261102", "cur_prc": "115900"}]}
        def request_tr(self, *a, **k): return {"base_pric": "118100"}
    d = dk.Desk.__new__(dk.Desk)
    d.client, d._refc, d.refs, d.note = C(), {}, {}, lambda *a: None
    monkeypatch.setattr(dk.Desk, "_local_reg_close", lambda self, c, day: 116200 if day == "20261102" else 0)
    assert d.ref("053800")["reg"] == 116200


def test_live_tick_fixes_stale_reg(monkeypatch):
    """refs 기준가가 전전날 값(118,100)이어도 오늘 틱(116,500 · 전일대비 +300)이 오면 116,200 으로 — 11-03 안랩."""
    import time
    from trader import desk as dk, feed
    q = feed.parse_quote({"10": "+116500", "11": "+300", "12": "+0.26"})
    assert q["base"] == 116200
    monkeypatch.setitem(feed.quotes, "053800", q)
    d = dk.Desk.__new__(dk.Desk)
    d.refs, d.holdings = {"053800": {"reg": 118100, "aft": 115900}}, []
    monkeypatch.setattr(dk.daily_facts, "get", lambda c: None)
    monkeypatch.setattr(dk.Desk, "vref", lambda self, c: {}, raising=False)
    try:
        s = d.snap("053800")
    except Exception:     # snap 뒤쪽(고점·60선 등)은 이 테스트 밖 — 기준가 고친 것만 본다
        s = None
    assert d.refs["053800"]["reg"] == 116200
    if s:
        assert s["reg"] == 116200
    q["t"] = time.time() - 86400 * 2                                  # 어제 틱이면 안 믿는다
    d.refs["053800"]["reg"] = 118100
    try:
        d.snap("053800")
    except Exception:
        pass
    assert d.refs["053800"]["reg"] == 118100


def test_notes_reload_from_events(tmp_path, monkeypatch):
    """다시 켜면 events.jsonl 의 오늘 알림을 다시 읽는다 — 어제 것은 뺌(11-03 사용자)."""
    from trader import desk as dk
    monkeypatch.setattr(dk, "STATE", tmp_path)
    (tmp_path / "events.jsonl").write_text('{"note": "옛날", "level": "info", "ts": "2000-01-01T09:00:00"}\n', encoding="utf-8")
    dk._log({"note": "안랩 과열 매수", "level": "warn"})
    dk._log({"other": 1})
    assert [(m["text"], m["level"]) for m in dk._today_notes()] == [("안랩 과열 매수", "warn")]


def test_note_code_to_name(monkeypatch):
    from trader import desk as dk
    monkeypatch.setattr(dk, "_log", lambda e: None)
    d = dk.Desk.__new__(dk.Desk)
    d.msgs, d.names = [], {"180640": "한진칼"}
    d.note("180640 과열 매수 — 평소의 102.9배", "warn")
    d.note("1806405 그대로")
    assert [m["text"] for m in d.msgs] == ["1806405 그대로", "한진칼 과열 매수 — 평소의 102.9배"]


def test_same_day_ma_buy_blocked_below_live_close(monkeypatch):
    """신고대금 당일(BC 모름)은 지금 15분봉 종가(현재가)가 임시 BC — 60선이 그 −N% 위면 산다, 아래면 안 산다(11-03 사용자)."""
    for top, want in ((9500, [9500]), (9300, [])):                  # 60선 위 버팀 종가 — 지금가 9,600 의 −2%(9,408) 위/아래
        k = _desk(monkeypatch, 9600)
        p = k.plans[0]
        p.update(ref_day="20261020", same_day=True, base="aft", base_px=10500, c_near=2.0, c_src="reg", ma_confirm=2)
        p["stages"][0].update(ma=True, band=1.0, amt=100_000, pct=0.0)
        p["stages"][1].update(amt=0, qty=0)
        k.ma60_15 = lambda code, base: 9200
        k._ma_confirmed = lambda p_, s_, _t=top: (_t,)
        k.ref = lambda code, day=None: {"aft": 10000, "reg": 9900}
        k._refc, k.note = {}, lambda *a, **kw: None
        k._place_plans(datetime(2026, 10, 20, 14, 0))
        assert k.bought == want, top


def test_same_day_after_hours_bc_is_regular_close(monkeypatch):
    """당일 신고대금 뒤 애프터로 넘어가면 BC = 오늘 정규장 종가(11-03 사용자) — 지금가가 아니다."""
    k = _desk(monkeypatch, 9600)
    p = k.plans[0]
    p.update(ref_day="20261020", same_day=True, base="aft", base_px=10500, c_near=2.0, c_src="reg", ma_confirm=2)
    p["stages"][0].update(ma=True, band=1.0, amt=100_000, pct=0.0)
    p["stages"][1].update(amt=0, qty=0)
    k.ma60_15 = lambda code, base: 9200
    k._ma_confirmed = lambda p_, s_: (9500,)                       # 지금가 기준이면 사지만(9,408 위) 정규장 종가 10,000 −2% 아래
    k._close_1530 = lambda code, day: 10000
    k._plan_window = lambda p_, now, strict=False: True              # 애프터 주문 시간은 이 테스트 밖
    k._refc, k.note = {}, lambda *a, **kw: None
    k._place_plans(datetime(2026, 10, 20, 16, 0))
    assert p["c_px"] == 10000 and k.bought == []
