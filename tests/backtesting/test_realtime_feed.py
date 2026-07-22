import json

import pandas as pd
import pytest

from backtesting.realtime_feed import CandleAggregator, RealtimeFeed, parse_tick


# ---- parse_tick ----

def test_parse_tick_extracts_price_volume_and_time():
    tick = parse_tick({"10": "+70000", "13": "12345", "20": "093015"})

    assert tick == {"price": 70000.0, "cum_volume": 12345, "time_hms": "093015", "bid": None}


def test_parse_tick_extracts_bid_when_present():
    tick = parse_tick({"10": "+70000", "13": "100", "20": "093015", "28": "+69900"})

    assert tick["bid"] == 69900.0


def test_parse_tick_strips_sign_from_price():
    tick = parse_tick({"10": "-70000", "13": "100", "20": "093015"})

    assert tick["price"] == 70000.0


def test_parse_tick_returns_none_when_price_missing():
    assert parse_tick({"20": "093015"}) is None


def test_parse_tick_returns_none_when_time_missing():
    assert parse_tick({"10": "+70000"}) is None


def test_parse_tick_returns_none_when_time_malformed():
    assert parse_tick({"10": "+70000", "20": "9:30"}) is None


def test_parse_tick_handles_missing_cum_volume():
    tick = parse_tick({"10": "+70000", "20": "093015"})

    assert tick["cum_volume"] is None


# ---- CandleAggregator ----

def test_add_tick_creates_new_minute_candle():
    agg = CandleAggregator()
    agg.add_tick({"price": 70000.0, "cum_volume": None, "time_hms": "093015"}, "2026-07-22")

    df = agg.to_dataframe()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["open"] == row["high"] == row["low"] == row["close"] == 70000.0
    assert df.index[0] == pd.Timestamp("2026-07-22 09:30:00")


def test_add_tick_updates_high_low_close_within_same_minute():
    agg = CandleAggregator()
    agg.add_tick({"price": 70000.0, "cum_volume": None, "time_hms": "093001"}, "2026-07-22")
    agg.add_tick({"price": 70500.0, "cum_volume": None, "time_hms": "093030"}, "2026-07-22")
    agg.add_tick({"price": 69800.0, "cum_volume": None, "time_hms": "093045"}, "2026-07-22")

    df = agg.to_dataframe()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["open"] == 70000.0
    assert row["high"] == 70500.0
    assert row["low"] == 69800.0
    assert row["close"] == 69800.0


def test_add_tick_in_new_minute_creates_separate_candle():
    agg = CandleAggregator()
    agg.add_tick({"price": 70000.0, "cum_volume": None, "time_hms": "093059"}, "2026-07-22")
    agg.add_tick({"price": 70200.0, "cum_volume": None, "time_hms": "093100"}, "2026-07-22")

    df = agg.to_dataframe()
    assert len(df) == 2
    assert list(df.index) == [pd.Timestamp("2026-07-22 09:30:00"), pd.Timestamp("2026-07-22 09:31:00")]


def test_add_tick_accumulates_volume_from_cumulative_delta():
    agg = CandleAggregator()
    agg.add_tick({"price": 70000.0, "cum_volume": 1000, "time_hms": "093001"}, "2026-07-22")  # 기준선(delta=0)
    agg.add_tick({"price": 70100.0, "cum_volume": 1050, "time_hms": "093010"}, "2026-07-22")  # +50
    agg.add_tick({"price": 70200.0, "cum_volume": 1080, "time_hms": "093020"}, "2026-07-22")  # +30

    df = agg.to_dataframe()
    assert df.iloc[0]["volume"] == 80


def test_add_tick_ignores_zero_or_negative_price():
    agg = CandleAggregator()
    agg.add_tick({"price": 0.0, "cum_volume": None, "time_hms": "093015"}, "2026-07-22")

    assert agg.to_dataframe().empty


def test_to_dataframe_empty_when_no_ticks():
    df = CandleAggregator().to_dataframe()

    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_to_dataframe_sorted_even_if_ticks_processed_out_of_order():
    agg = CandleAggregator()
    agg.add_tick({"price": 70200.0, "cum_volume": None, "time_hms": "093100"}, "2026-07-22")
    agg.add_tick({"price": 70000.0, "cum_volume": None, "time_hms": "093000"}, "2026-07-22")

    df = agg.to_dataframe()
    assert list(df.index) == sorted(df.index)


# ---- RealtimeFeed._on_message (network-free) ----

class _FakeWs:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


@pytest.fixture
def feed(monkeypatch):
    monkeypatch.setattr(
        "backtesting.realtime_feed.KiwoomClient",
        lambda appkey, secretkey, is_mock: type("_C", (), {"issue_token": lambda self: "tok123"})(),
    )
    return RealtimeFeed("appkey", "secret", True, ["005930", "000660"])


def test_on_open_sends_login_with_issued_token(feed):
    ws = _FakeWs()
    feed._on_open(ws)

    assert json.loads(ws.sent[0]) == {"trnm": "LOGIN", "token": "tok123"}


def test_on_message_login_success_sends_reg_with_all_codes(feed):
    ws = _FakeWs()
    feed._on_message(ws, json.dumps({"trnm": "LOGIN", "return_code": 0}))

    assert len(ws.sent) == 1
    reg = json.loads(ws.sent[0])
    assert reg["trnm"] == "REG"
    assert reg["data"] == [{"item": ["005930", "000660"], "type": ["0B"]}]


def test_on_message_login_failure_does_not_send_reg(feed):
    ws = _FakeWs()
    feed._on_message(ws, json.dumps({"trnm": "LOGIN", "return_code": 1, "return_msg": "실패"}))

    assert ws.sent == []


def test_on_message_reg_success_sets_connected_event(feed):
    ws = _FakeWs()
    assert not feed._connected.is_set()

    feed._on_message(ws, json.dumps({"trnm": "REG", "return_code": 0}))

    assert feed._connected.is_set()


def test_on_message_ping_echoes_back_verbatim(feed):
    ws = _FakeWs()
    ping_message = json.dumps({"trnm": "PING"})

    feed._on_message(ws, ping_message)

    assert ws.sent == [ping_message]


def test_on_message_data_push_updates_correct_stock_candle(feed):
    ws = _FakeWs()
    feed._on_message(ws, json.dumps({
        "data": [{"item": "005930", "values": {"10": "+70000", "13": "100", "20": "093015"}}],
    }))

    df = feed.get_minute_df("005930")
    assert len(df) == 1
    assert df.iloc[0]["close"] == 70000.0
    assert feed.get_minute_df("000660").empty


def test_on_message_data_push_ignores_unknown_stock_code(feed):
    ws = _FakeWs()
    feed._on_message(ws, json.dumps({
        "data": [{"item": "999999", "values": {"10": "+70000", "13": "100", "20": "093015"}}],
    }))

    assert feed.get_minute_df("999999").empty  # 애초에 감시종목이 아니므로 조회해도 빈 결과


def test_on_message_ignores_invalid_json():
    RealtimeFeed("appkey", "secret", True, ["005930"])._on_message(_FakeWs(), "not json")  # 예외 없이 무시


def test_get_minute_df_returns_empty_for_unsubscribed_code(feed):
    df = feed.get_minute_df("005930")

    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_on_message_data_push_updates_latest_bid(feed):
    ws = _FakeWs()
    feed._on_message(ws, json.dumps({
        "data": [{"item": "005930", "values": {"10": "+70000", "13": "100", "20": "093015", "28": "+69900"}}],
    }))

    assert feed.get_latest_bid("005930") == 69900.0


def test_get_latest_bid_returns_none_before_any_tick(feed):
    assert feed.get_latest_bid("005930") is None


def test_get_latest_bid_returns_none_for_unknown_code(feed):
    assert feed.get_latest_bid("999999") is None


# ---- RealtimeFeed.seed_from_dataframe ----

def test_seed_from_dataframe_populates_minute_df(feed):
    backfill = pd.DataFrame(
        {"open": [70000.0], "high": [70200.0], "low": [69900.0], "close": [70100.0], "volume": [500.0]},
        index=[pd.Timestamp("2026-07-22 09:15:00")],
    )

    feed.seed_from_dataframe("005930", backfill)

    df = feed.get_minute_df("005930")
    assert len(df) == 1
    assert df.iloc[0]["close"] == 70100.0
    assert df.index[0] == pd.Timestamp("2026-07-22 09:15:00")


def test_seed_from_dataframe_then_live_tick_appends_new_minute(feed):
    backfill = pd.DataFrame(
        {"open": [70000.0], "high": [70200.0], "low": [69900.0], "close": [70100.0], "volume": [500.0]},
        index=[pd.Timestamp("2026-07-22 09:15:00")],
    )
    feed.seed_from_dataframe("005930", backfill)

    feed._on_message(_FakeWs(), json.dumps({
        "data": [{"item": "005930", "values": {"10": "+70500", "13": "600", "20": "093100"}}],
    }))

    df = feed.get_minute_df("005930")
    assert len(df) == 2
    assert df.iloc[-1]["close"] == 70500.0


def test_seed_from_dataframe_ignores_unknown_code(feed):
    backfill = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
        index=[pd.Timestamp("2026-07-22 09:15:00")],
    )

    feed.seed_from_dataframe("999999", backfill)  # 예외 없이 무시

    assert feed.get_minute_df("999999").empty


def test_seed_from_dataframe_noop_on_empty_dataframe(feed):
    feed.seed_from_dataframe("005930", pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))

    assert feed.get_minute_df("005930").empty
