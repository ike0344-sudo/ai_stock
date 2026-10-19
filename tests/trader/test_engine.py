from datetime import datetime

from trader import engine as e
from trader import feed

EXITS = {"stop": [True, "3.5"], "take": [True, [["5", "50"], ["8", "50"]]], "trail": [False, ""],
         "days": [False, ""], "close": [False, "15:15"], "breakeven": [True]}
NOON = datetime(2026, 10, 20, 12, 0)


def test_ticks():
    assert e.floor_tick(8567) == 8560 and e.ceil_tick(8561) == 8570
    assert e.floor_tick(68_850) == 68_800 and e.tick_size(193_900) == 100 and e.tick_size(600_000) == 1000


def test_ladder_floors_price_and_splits_amount():
    o = e.ladder_orders(10_000, [["-3", "50"], ["-5", "50"], ["-7", "0"]], 1_000_000)
    assert [(x["price"], x["qty"]) for x in o] == [(9700, 51), (9500, 52)]      # 0% 단계는 빠진다


def test_windows():
    w = [["09:00", "10:30"], ["14:00", "15:30"]]
    assert e.in_windows(datetime(2026, 10, 20, 9, 0), w) and not e.in_windows(datetime(2026, 10, 20, 10, 30), w)
    assert e.in_windows(datetime(2026, 10, 20, 15, 29), w) and not e.in_windows(NOON, w) and not e.in_windows(NOON, [])


def test_stop_and_breakeven():
    pos = {"qty": 100, "avg": 10_000, "init_qty": 100}
    assert e.exit_actions(pos, 9660, NOON, EXITS) == []
    assert e.exit_actions(pos, 9650, NOON, EXITS)[0]["kind"] == "stop"
    be = {**pos, "breakeven": True}
    assert e.exit_actions(be, 9990, NOON, EXITS)[0]["qty"] == 100               # 1차 익절 뒤엔 본전 아래면 전량


def test_take_orders_split_and_last_takes_rest():
    pos = {"qty": 101, "avg": 10_000, "init_qty": 101, "takes_done": []}
    t = e.take_orders(pos, EXITS)
    assert [(x["price"], x["qty"]) for x in t] == [(10_500, 50), (10_800, 51)]
    assert e.take_orders({**pos, "qty": 51, "takes_done": [0, 1]}, EXITS) == []
    assert [x["qty"] for x in e.take_orders({**pos, "qty": 51, "takes_done": [0]}, EXITS)] == [51]


def test_close_time_and_trail():
    ex = {**EXITS, "close": [True, "15:15"], "trail": [True, "4"]}
    pos = {"qty": 10, "avg": 10_000, "high": 11_000}
    assert e.exit_actions(pos, 10_600, NOON, ex) == []                           # 11,000 × 0.96 = 10,560 — 아직 위
    assert e.exit_actions(pos, 10_560, NOON, ex)[0]["kind"] == "trail"
    assert e.exit_actions(pos, 10_600, NOON, {**ex, "trail": [True, "3"]})[0]["kind"] == "trail"
    assert e.exit_actions({**pos, "high": 0}, 10_100, datetime(2026, 10, 20, 15, 15), ex)[0]["kind"] == "close"


def test_safety():
    sf = {"max_daily_loss": "300000", "max_positions": "2", "max_orders": "", "max_weight_pct": "25"}
    assert e.safety_block(sf, {"pnl": -300_000}, [], 0, 1) .startswith("하루 최대 손실")
    assert e.safety_block(sf, {"pnl": 0}, [{"qty": 1}, {"qty": 3}], 0, 1).startswith("동시 보유")
    assert e.safety_block(sf, {"pnl": 0}, [], 3_000_000, 10_000_000).startswith("종목당")
    assert e.safety_block(sf, {"pnl": 0}, [], 2_000_000, 10_000_000) is None


def test_conds():
    snap = {"px": 9_700, "reg": 10_000, "aft": 10_100, "high": 10_600, "chg": -3.0, "value": 50e8}
    ok, _ = e.conds_met([["정규장 종가 대비", "이하", "-3"], ["거래대금", "이상", "30"]], snap)
    assert ok
    ok, uns = e.conds_met([["시장", "같음", "코스닥"]], snap)
    assert not ok and uns == []                                                 # 일봉 사실이 없으면 만족 안 함
    assert e.conds_met([["없는 조건", "이상", "1"]], snap) == (False, ["없는 조건"])
    assert not e.conds_met([["애프터 종가 대비", "이하", "-5"]], snap)[0]


def test_daily_facts_fields():
    snap = {"px": 9_100, "high": 9_500, "strength": 132.5, "facts": {
        "market": "코스닥", "shares": 10_000_000, "hi52": 9_000, "movers": 1,
        "big": {"high": 10_000, "break52": 2.0, "movers": 4, "touched": False}}}
    ok, uns = e.conds_met([["시장", "같음", "코스닥"], ["같은 테마 장대양봉 종목 수", "이상", "3"],
                           ["장대양봉일 52주 고가 돌파폭", "이하", "3.9"], ["최근 장대양봉 고가 대비", "이하", "-8"],
                           ["체결강도", "이상", "120"], ["시가총액", "이하", "1000"]], snap)
    assert ok and not uns                                                       # 9,100 / 10,000 = −9%, 시총 910억
    assert not e.conds_met([["시장", "아님", "코스닥"]], snap)[0]
    assert round(e.cond_value("52주 신고가 대비", snap), 2) == 5.56             # 오늘 고가 9,500 / 9,000
    touched = {**snap, "facts": {**snap["facts"], "big": {**snap["facts"]["big"], "touched": True}}}
    assert e.cond_value("최근 장대양봉 고가 대비", touched) is None             # 이미 −8% 닿음 = 매수 창 닫힘
    assert e.cond_value("같은 테마 장대양봉 종목 수", {"facts": {"movers": 2}}) == 2


def test_compute_matches_rule():
    import pandas as pd

    from trader.daily_facts import compute
    idx = pd.bdate_range("2026-01-01", periods=30)
    base = pd.Series(10_000.0, index=idx)
    close = pd.DataFrame({"A": base, "B": base, "C": base, "D": base})
    high, low, vol = close * 1.01, close * 0.99, close * 0 + 20_000_000
    for c in "BCD":                                       # 같은 테마 B·C·D 가 최근 +10% 마감
        close.loc[idx[-3]:, c] = 11_000.0
    close.loc[idx[-2]:, "A"] = 11_600.0                   # A: 이틀 전 장대양봉(종가 +16%, 고가 +21%, 대금 2,320억)
    high.loc[idx[-2], "A"] = 12_100.0
    low.loc[idx[-1], "A"] = 11_500.0                      # 아직 12,100 × 0.92 = 11,132 에 안 닿음
    themes = pd.DataFrame({"stock_code": list("ABCD"), "theme": ["T"] * 4, "theme_size": [4] * 4})
    f = compute(close, high, low, vol, themes, {"A": "코스닥"}, {"A": 1_000_000})["A"]
    assert f["big"]["high"] == 12_100 and f["big"]["movers"] == 3 and not f["big"]["touched"]
    assert f["big"]["break52"] == round((12_100 / 10_100 - 1) * 100, 2) and f["market"] == "코스닥"


def test_keep_until():
    from datetime import date as _d
    trading = lambda d: d.weekday() < 5 and d != _d(2026, 10, 21)               # 수요일 하루 쉰다고 치고
    mon_am, mon_pm = datetime(2026, 10, 19, 10, 0), datetime(2026, 10, 19, 16, 0)
    assert e.keep_until({"mode": "today"}, mon_am, trading) == "2026-10-19"
    assert e.keep_until({"mode": "today"}, mon_pm, trading) == "2026-10-20"       # 장 끝나고 걸면 다음 거래일 하루
    assert e.keep_until({"mode": "days", "days": "3"}, mon_am, trading) == "2026-10-22"   # 월·화·(수 휴장)·목
    assert e.keep_until({"mode": "until", "until": "2026-10-30"}, mon_am, trading) == "2026-10-30"
    assert e.keep_until({"mode": "forever"}, mon_am, trading) is None


def test_feed_parsers():
    q = feed.parse_quote({"10": "-9700", "12": "-3.00", "14": "5000", "17": "+10600"})
    assert q["px"] == 9700 and q["chg"] == -3.0 and q["value"] == 5_000_000_000 and q["high"] == 10600
    b = feed.parse_book({"41": "9710", "61": "120", "51": "9700", "71": "300", "121": "1000", "125": "2000"})
    assert b["asks"][0] == (9710, 120) and b["bids"][0] == (9700, 300) and b["bid_total"] == 2000
    o = feed.parse_order({"9203": "0012345", "9001": "A005930", "905": "-매도", "910": "70000", "911": "3"})
    assert o["code"] == "005930" and o["side"] == "sell" and o["fill_qty"] == 3
