import json
from datetime import date, datetime

import pandas as pd
import pytest

from backtesting import oversold_trading_loop
from backtesting.oversold_trading_loop import (
    OversoldEpisodeState,
    compute_current_ma,
    load_episode_state,
    process_oversold_entry_once,
    process_oversold_exit_once,
    run_oversold_trading_loop,
    save_episode_state,
)
from backtesting.risk_manager import RiskState, record_position_opened


@pytest.fixture(autouse=True)
def stub_log_order(monkeypatch):
    # oversold_trading_loop.py는 trading_loop._log_order를 import해서 자기 네임스페이스에
    # 바인딩해 쓰므로, trading_loop._log_order를 패치해도 이쪽엔 영향이 없다 — 이 모듈
    # 자신의 참조를 no-op으로 바꿔서 실제 프로젝트 디렉터리에 파일을 만들지 않게 한다.
    monkeypatch.setattr(oversold_trading_loop, "_log_order", lambda *a, **k: None)


class _StubClient:
    def __init__(self, raise_on_order=False, quote_price=None, raise_on_quote=False, reject_order=False):
        self.orders = []
        self.raise_on_order = raise_on_order
        self.quote_price = quote_price
        self.raise_on_quote = raise_on_quote
        self.reject_order = reject_order
        self.appkey, self.secretkey, self.is_mock = "appkey", "secret", True

    def place_order(self, stock_code, side, quantity, **kwargs):
        if self.raise_on_order:
            raise RuntimeError("주문 실패")
        self.orders.append({"code": stock_code, "side": side, "quantity": quantity})
        if self.reject_order:
            return {"ord_no": "", "return_code": 20, "return_msg": "주문 거부"}
        return {"ord_no": "1", "return_code": 0}

    def get_stock_quote(self, stock_code):
        if self.raise_on_quote:
            raise RuntimeError("조회 실패")
        return {"buy_fpr_bid": f"-{self.quote_price}"}


# ---- OversoldEpisodeState load/save ----

def test_save_and_load_episode_state_round_trip(tmp_path):
    risk_state_path = str(tmp_path / "risk_state.json")
    episode = OversoldEpisodeState(filled_tier_count=2, entry_date="2026-07-20")

    save_episode_state(episode, risk_state_path)
    loaded = load_episode_state(risk_state_path)

    assert loaded == episode


def test_load_episode_state_returns_fresh_when_file_missing(tmp_path):
    loaded = load_episode_state(str(tmp_path / "risk_state.json"))

    assert loaded == OversoldEpisodeState(filled_tier_count=0, entry_date=None)


# ---- _filter_regular_session ----

def test_filter_regular_session_excludes_after_hours_bars():
    df = pd.DataFrame(
        {"open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0], "close": [1.0, 2.0], "volume": [1, 1]},
        index=[pd.Timestamp("2026-07-21 15:29"), pd.Timestamp("2026-07-21 15:35")],
    )

    filtered = oversold_trading_loop._filter_regular_session(df)

    assert list(filtered.index) == [pd.Timestamp("2026-07-21 15:29")]


def test_filter_regular_session_includes_boundary_close_time():
    # is_market_open과 동일하게 09:00/15:30은 경계 포함(양끝 포함)
    df = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]},
        index=[pd.Timestamp("2026-07-21 15:30")],
    )

    assert len(oversold_trading_loop._filter_regular_session(df)) == 1


def test_filter_regular_session_returns_empty_for_empty_input():
    assert oversold_trading_loop._filter_regular_session(pd.DataFrame()).empty


# ---- compute_current_ma ----

def test_compute_current_ma_combines_historical_and_live_resampled(monkeypatch):
    monkeypatch.setattr(oversold_trading_loop, "MA_WINDOW", 2)
    historical = pd.DataFrame(
        {"open": [100.0] * 15, "high": [100.0] * 15, "low": [100.0] * 15, "close": [100.0] * 15, "volume": [1000] * 15},
        index=pd.date_range("2026-07-21 09:00", periods=15, freq="1min"),
    )
    today_1min = pd.DataFrame(
        {"open": [200.0] * 15, "high": [200.0] * 15, "low": [200.0] * 15, "close": [200.0] * 15, "volume": [10] * 15},
        index=pd.date_range("2026-07-22 09:00", periods=15, freq="1min"),
    )

    ma = compute_current_ma(historical, today_1min)

    # 15분봉 2개(100.0, 200.0) 평균
    assert ma == pytest.approx((100.0 + 200.0) / 2)


def test_compute_current_ma_excludes_after_hours_ticks(monkeypatch):
    # 회귀 테스트 — 예전엔 정규장 필터가 전혀 없어서 시간외(15:31~) 체결이 60선
    # 계산에 그대로 섞여 들어갔다(실측: data/stocks/minute/000660.csv에 15:35 부근
    # 시간외단일가 체결 313행 포함). 완전히 다른 가격대로 섞어 넣어 걸러지는지 확인.
    monkeypatch.setattr(oversold_trading_loop, "MA_WINDOW", 1)
    regular = pd.DataFrame(
        {"open": [100.0] * 15, "high": [100.0] * 15, "low": [100.0] * 15, "close": [100.0] * 15, "volume": [1000] * 15},
        index=pd.date_range("2026-07-21 09:00", periods=15, freq="1min"),
    )
    after_hours = pd.DataFrame(
        {"open": [99999.0] * 10, "high": [99999.0] * 10, "low": [99999.0] * 10, "close": [99999.0] * 10, "volume": [10] * 10},
        index=pd.date_range("2026-07-21 15:35", periods=10, freq="1min"),
    )
    historical = pd.concat([regular, after_hours])

    ma = compute_current_ma(historical, pd.DataFrame())

    assert ma == pytest.approx(100.0)  # 99999.0이 섞였으면 MA가 훨씬 커졌을 것


def test_compute_current_ma_returns_none_when_insufficient_history():
    historical = pd.DataFrame(
        {"open": [100.0] * 5, "high": [100.0] * 5, "low": [100.0] * 5, "close": [100.0] * 5, "volume": [1000] * 5},
        index=pd.date_range("2026-07-21 09:00", periods=5, freq="1min"),
    )

    assert compute_current_ma(historical, pd.DataFrame()) is None


def test_compute_current_ma_returns_none_for_empty_input():
    assert compute_current_ma(pd.DataFrame(), pd.DataFrame()) is None


# ---- process_oversold_entry_once ----

def test_entry_fires_tier_1_when_price_touches_first_band():
    client = _StubClient()
    risk_state = RiskState(trading_date="2026-07-22")
    episode = OversoldEpisodeState()
    now = datetime(2026, 7, 22, 10, 0)

    episode = process_oversold_entry_once(
        client, risk_state, episode, ma_value=100.0, current_price=90.0, tier_capital_krw=900_000,
        bot_token="", chat_id="", now=now,
    )

    assert episode.filled_tier_count == 1
    assert episode.entry_date == "2026-07-22"
    assert len(risk_state.open_positions) == 1
    assert risk_state.open_positions[0].entry_price == 90.0
    assert client.orders == [{"code": "000660", "side": "buy", "quantity": 10_000}]


def test_entry_does_not_fire_when_price_above_first_band():
    client = _StubClient()
    risk_state = RiskState(trading_date="2026-07-22")
    episode = OversoldEpisodeState()

    episode = process_oversold_entry_once(
        client, risk_state, episode, ma_value=100.0, current_price=95.0, tier_capital_krw=900_000,
        bot_token="", chat_id="",
    )

    assert episode.filled_tier_count == 0
    assert risk_state.open_positions == []
    assert client.orders == []


def test_entry_fires_tier_2_and_averages_into_existing_position():
    client = _StubClient()
    risk_state = RiskState(trading_date="2026-07-22")
    episode = OversoldEpisodeState(filled_tier_count=1, entry_date="2026-07-22")
    record_position_opened(risk_state, "000660", "2026-07-22T10:00", 900_000, 91.0, total_quantity=9890)

    episode = process_oversold_entry_once(
        client, risk_state, episode, ma_value=100.0, current_price=87.0, tier_capital_krw=900_000,
        bot_token="", chat_id="",
    )

    assert episode.filled_tier_count == 2
    assert len(risk_state.open_positions) == 1  # 새 포지션이 아니라 기존 포지션 갱신
    assert risk_state.open_positions[0].total_quantity == 9890 + 10_344


def test_entry_never_fires_beyond_three_tiers():
    client = _StubClient()
    risk_state = RiskState(trading_date="2026-07-22")
    episode = OversoldEpisodeState(filled_tier_count=3, entry_date="2026-07-22")
    record_position_opened(risk_state, "000660", "2026-07-22T10:00", 2_700_000, 88.0, total_quantity=30000)

    episode = process_oversold_entry_once(
        client, risk_state, episode, ma_value=100.0, current_price=50.0, tier_capital_krw=900_000,
        bot_token="", chat_id="",
    )

    assert episode.filled_tier_count == 3
    assert client.orders == []


def test_entry_handles_order_failure_without_mutating_state(monkeypatch):
    client = _StubClient(raise_on_order=True)
    monkeypatch.setattr(oversold_trading_loop, "notify_error", lambda *a, **k: None)
    risk_state = RiskState(trading_date="2026-07-22")
    episode = OversoldEpisodeState()

    episode = process_oversold_entry_once(
        client, risk_state, episode, ma_value=100.0, current_price=90.0, tier_capital_krw=900_000,
        bot_token="", chat_id="",
    )

    assert episode.filled_tier_count == 0
    assert risk_state.open_positions == []


def test_entry_handles_order_rejection_without_mutating_state(monkeypatch):
    client = _StubClient(reject_order=True)
    monkeypatch.setattr(oversold_trading_loop, "notify_error", lambda *a, **k: None)
    risk_state = RiskState(trading_date="2026-07-22")
    episode = OversoldEpisodeState()

    episode = process_oversold_entry_once(
        client, risk_state, episode, ma_value=100.0, current_price=90.0, tier_capital_krw=900_000,
        bot_token="", chat_id="",
    )

    assert episode.filled_tier_count == 0
    assert risk_state.open_positions == []


# ---- process_oversold_exit_once ----

def test_exit_fires_on_touch_and_resets_episode():
    client = _StubClient()
    risk_state = RiskState(trading_date="2026-07-22")
    record_position_opened(risk_state, "000660", "2026-07-20T10:00", 900_000, 91.0, total_quantity=9890)
    episode = OversoldEpisodeState(filled_tier_count=1, entry_date="2026-07-20")

    episode = process_oversold_exit_once(
        client, risk_state, episode, ma_value=100.0, current_price=100.0, max_daily_loss_krw=1_000_000,
        bot_token="", chat_id="", today=date(2026, 7, 22),
    )

    assert risk_state.open_positions == []
    assert episode == OversoldEpisodeState()  # 다음 에피소드를 위해 리셋됨
    assert client.orders == [{"code": "000660", "side": "sell", "quantity": 9890}]


def test_exit_fires_on_hard_stop():
    client = _StubClient()
    risk_state = RiskState(trading_date="2026-07-22")
    record_position_opened(risk_state, "000660", "2026-07-20T10:00", 900_000, 100.0, total_quantity=9000)
    episode = OversoldEpisodeState(filled_tier_count=1, entry_date="2026-07-20")

    episode = process_oversold_exit_once(
        client, risk_state, episode, ma_value=130.0, current_price=79.0,  # 평단 대비 -21%, 60선과는 거리 멂
        max_daily_loss_krw=1_000_000, bot_token="", chat_id="", today=date(2026, 7, 22),
    )

    assert risk_state.open_positions == []
    assert client.orders[0]["side"] == "sell"


def test_exit_fires_on_time_exit_past_15_trading_days():
    client = _StubClient()
    risk_state = RiskState(trading_date="2026-08-15")
    record_position_opened(risk_state, "000660", "2026-07-20T10:00", 900_000, 100.0, total_quantity=9000)
    episode = OversoldEpisodeState(filled_tier_count=1, entry_date="2026-07-20")

    # 60선과 거리가 멀고 하드스톱에도 안 걸리는 가격, 진입일로부터 훨씬 지난 날짜
    episode = process_oversold_exit_once(
        client, risk_state, episode, ma_value=130.0, current_price=95.0,
        max_daily_loss_krw=10_000_000, bot_token="", chat_id="", today=date(2026, 8, 15),
    )

    assert risk_state.open_positions == []


def test_exit_handles_order_rejection_without_mutating_state(monkeypatch):
    client = _StubClient(reject_order=True)
    monkeypatch.setattr(oversold_trading_loop, "notify_error", lambda *a, **k: None)
    risk_state = RiskState(trading_date="2026-07-22")
    record_position_opened(risk_state, "000660", "2026-07-20T10:00", 900_000, 91.0, total_quantity=9890)
    episode = OversoldEpisodeState(filled_tier_count=1, entry_date="2026-07-20")

    result = process_oversold_exit_once(
        client, risk_state, episode, ma_value=100.0, current_price=100.0, max_daily_loss_krw=1_000_000,
        bot_token="", chat_id="", today=date(2026, 7, 22),
    )

    assert result == episode  # 거부됐으니 에피소드가 리셋되면 안 됨
    assert len(risk_state.open_positions) == 1  # 포지션도 그대로 유지


def test_exit_no_op_when_no_position_open():
    client = _StubClient()
    risk_state = RiskState(trading_date="2026-07-22")
    episode = OversoldEpisodeState()

    result = process_oversold_exit_once(
        client, risk_state, episode, ma_value=100.0, current_price=100.0, max_daily_loss_krw=1_000_000,
        bot_token="", chat_id="",
    )

    assert result == episode
    assert client.orders == []


def test_exit_no_op_when_no_condition_met():
    client = _StubClient()
    risk_state = RiskState(trading_date="2026-07-22")
    record_position_opened(risk_state, "000660", "2026-07-22T10:00", 900_000, 91.0, total_quantity=9890)
    episode = OversoldEpisodeState(filled_tier_count=1, entry_date="2026-07-22")

    result = process_oversold_exit_once(
        client, risk_state, episode, ma_value=100.0, current_price=91.5, max_daily_loss_krw=1_000_000,
        bot_token="", chat_id="", today=date(2026, 7, 22),
    )

    assert result is episode
    assert len(risk_state.open_positions) == 1
    assert client.orders == []


def test_exit_notifies_kill_switch_when_loss_triggers_it(monkeypatch):
    client = _StubClient()
    notified = []
    monkeypatch.setattr(oversold_trading_loop, "notify_kill_switch", lambda *a, **k: notified.append(a))
    risk_state = RiskState(trading_date="2026-07-22")
    record_position_opened(risk_state, "000660", "2026-07-20T10:00", 900_000, 100.0, total_quantity=9000)
    episode = OversoldEpisodeState(filled_tier_count=1, entry_date="2026-07-20")

    process_oversold_exit_once(
        client, risk_state, episode, ma_value=130.0, current_price=79.0,  # pnl = 900,000 * -0.21 = -189,000
        max_daily_loss_krw=100_000, bot_token="", chat_id="", today=date(2026, 7, 22),
    )

    assert risk_state.kill_switch_active is True
    assert len(notified) == 1


# ---- run_oversold_trading_loop orchestration ----

class _FakeRealtimeFeed:
    instances = []

    def __init__(self, appkey, secretkey, is_mock, stock_codes):
        self.appkey, self.secretkey, self.is_mock, self.stock_codes = appkey, secretkey, is_mock, stock_codes
        self.seeded = []
        self.started = False
        self.stopped = False
        _FakeRealtimeFeed.instances.append(self)

    def seed_from_dataframe(self, code, df):
        self.seeded.append(code)

    def start(self, wait_connected_seconds=10.0):
        self.started = True
        return True

    def stop(self):
        self.stopped = True

    def get_minute_df(self, code):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    def get_latest_price(self, code):
        return 100.0


def _empty_history(*a, **k):
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def test_run_oversold_trading_loop_polls_until_market_closes_and_saves_state(monkeypatch, tmp_path):
    monkeypatch.setattr(oversold_trading_loop, "load_history", _empty_history)
    open_flags = iter([True, True, False])
    monkeypatch.setattr(oversold_trading_loop, "is_extended_market_open", lambda now: next(open_flags))
    monkeypatch.setattr(oversold_trading_loop, "is_kill_switch_requested", lambda path: False)
    monkeypatch.setattr(oversold_trading_loop.time, "sleep", lambda s: None)
    exit_calls, entry_calls = [], []
    monkeypatch.setattr(
        oversold_trading_loop, "process_oversold_exit_once",
        lambda *a, **k: exit_calls.append(1) or a[2],
    )
    monkeypatch.setattr(
        oversold_trading_loop, "process_oversold_entry_once",
        lambda *a, **k: entry_calls.append(1) or a[2],
    )
    # ma_value가 None이면 entry/exit을 아예 건너뛰므로, 항상 값이 나오게 고정
    monkeypatch.setattr(oversold_trading_loop, "compute_current_ma", lambda *a, **k: 100.0)

    _FakeRealtimeFeed.instances = []
    monkeypatch.setattr(oversold_trading_loop, "RealtimeFeed", _FakeRealtimeFeed)

    state_path = str(tmp_path / "strategy_2" / "risk_state.json")
    run_oversold_trading_loop(
        _StubClient(), bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0,
        kill_switch_override_path=str(tmp_path / "kill_switch_override.json"),
    )

    assert len(exit_calls) == 2
    assert len(entry_calls) == 2
    assert __import__("os").path.exists(state_path)
    assert __import__("os").path.exists(str(tmp_path / "strategy_2" / "oversold_episode.json"))


def test_run_oversold_trading_loop_writes_heartbeat_before_first_cycle(monkeypatch, tmp_path):
    from backtesting.heartbeat import read_heartbeat_age_seconds

    monkeypatch.setattr(oversold_trading_loop, "load_history", _empty_history)
    monkeypatch.setattr(oversold_trading_loop, "is_extended_market_open", lambda now: False)  # 루프 진입 전 확인이 목적
    _FakeRealtimeFeed.instances = []
    monkeypatch.setattr(oversold_trading_loop, "RealtimeFeed", _FakeRealtimeFeed)

    state_path = str(tmp_path / "strategy_2" / "risk_state.json")
    run_oversold_trading_loop(
        _StubClient(), bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0,
        kill_switch_override_path=str(tmp_path / "kill_switch_override.json"),
    )

    age = read_heartbeat_age_seconds(str(tmp_path / "strategy_2"))
    assert age is not None and age < 5


def test_run_oversold_trading_loop_stops_when_stop_flag_requested_mid_run(monkeypatch, tmp_path):
    from backtesting.stop_control import request_stop

    monkeypatch.setattr(oversold_trading_loop, "load_history", _empty_history)
    monkeypatch.setattr(oversold_trading_loop, "is_extended_market_open", lambda now: True)  # 장은 계속 열려 있다고 가정
    monkeypatch.setattr(oversold_trading_loop, "is_kill_switch_requested", lambda path: False)
    monkeypatch.setattr(oversold_trading_loop.time, "sleep", lambda s: None)
    monkeypatch.setattr(oversold_trading_loop, "process_oversold_exit_once", lambda *a, **k: a[2])
    monkeypatch.setattr(oversold_trading_loop, "compute_current_ma", lambda *a, **k: 100.0)
    _FakeRealtimeFeed.instances = []
    monkeypatch.setattr(oversold_trading_loop, "RealtimeFeed", _FakeRealtimeFeed)

    state_path = str(tmp_path / "strategy_2" / "risk_state.json")
    stop_flag_path = str(tmp_path / "strategy_2" / "stop_requested.json")
    entry_calls = []

    def fake_entry(*a, **k):
        entry_calls.append(1)
        if len(entry_calls) == 2:
            request_stop(stop_flag_path)  # 두 번째 사이클 도중 중지 요청이 온 상황 재현
        return a[2]

    monkeypatch.setattr(oversold_trading_loop, "process_oversold_entry_once", fake_entry)

    run_oversold_trading_loop(
        _StubClient(), bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0,
        kill_switch_override_path=str(tmp_path / "kill_switch_override.json"),
        stop_flag_path=stop_flag_path,
    )

    assert len(entry_calls) == 2  # 세 번째 사이클로 안 넘어감


def test_run_oversold_trading_loop_skips_entry_when_kill_switch_requested(monkeypatch, tmp_path):
    monkeypatch.setattr(oversold_trading_loop, "load_history", _empty_history)
    open_flags = iter([True, False])
    monkeypatch.setattr(oversold_trading_loop, "is_extended_market_open", lambda now: next(open_flags))
    monkeypatch.setattr(oversold_trading_loop, "is_kill_switch_requested", lambda path: True)
    monkeypatch.setattr(oversold_trading_loop.time, "sleep", lambda s: None)
    monkeypatch.setattr(oversold_trading_loop, "compute_current_ma", lambda *a, **k: 100.0)
    monkeypatch.setattr(oversold_trading_loop, "process_oversold_exit_once", lambda *a, **k: a[2])
    entry_calls = []
    monkeypatch.setattr(
        oversold_trading_loop, "process_oversold_entry_once",
        lambda *a, **k: entry_calls.append(1) or a[2],
    )
    _FakeRealtimeFeed.instances = []
    monkeypatch.setattr(oversold_trading_loop, "RealtimeFeed", _FakeRealtimeFeed)

    state_path = str(tmp_path / "strategy_2" / "risk_state.json")
    run_oversold_trading_loop(
        _StubClient(), bot_token="", chat_id="", max_daily_loss_krw=500_000,
        risk_state_path=state_path, poll_interval_seconds=1.0,
        kill_switch_override_path=str(tmp_path / "kill_switch_override.json"),
    )

    assert entry_calls == []
    with open(state_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["kill_switch_active"] is True


def test_run_oversold_trading_loop_stops_feed_even_if_loop_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(oversold_trading_loop, "load_history", _empty_history)
    monkeypatch.setattr(oversold_trading_loop, "is_extended_market_open", lambda now: (_ for _ in ()).throw(RuntimeError("boom")))
    _FakeRealtimeFeed.instances = []
    monkeypatch.setattr(oversold_trading_loop, "RealtimeFeed", _FakeRealtimeFeed)

    state_path = str(tmp_path / "strategy_2" / "risk_state.json")
    with pytest.raises(RuntimeError):
        run_oversold_trading_loop(
            _StubClient(), bot_token="", chat_id="", max_daily_loss_krw=500_000, risk_state_path=state_path,
        )

    assert _FakeRealtimeFeed.instances[0].stopped is True


def test_run_oversold_trading_loop_seeds_and_starts_feed_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(oversold_trading_loop, "load_history", _empty_history)
    monkeypatch.setattr(oversold_trading_loop, "is_extended_market_open", lambda now: False)
    _FakeRealtimeFeed.instances = []
    monkeypatch.setattr(oversold_trading_loop, "RealtimeFeed", _FakeRealtimeFeed)

    state_path = str(tmp_path / "strategy_2" / "risk_state.json")
    run_oversold_trading_loop(
        _StubClient(), bot_token="", chat_id="", max_daily_loss_krw=500_000, risk_state_path=state_path,
    )

    assert len(_FakeRealtimeFeed.instances) == 1
    feed = _FakeRealtimeFeed.instances[0]
    assert feed.stock_codes == ["000660"]
    assert feed.seeded == ["000660"]
    assert feed.started is True
    assert feed.stopped is True
