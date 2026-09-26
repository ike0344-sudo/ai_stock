import json
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backtesting import live_monitor
from backtesting.live_monitor import (
    check_candidate,
    fetch_today_regime,
    load_recent_daily,
    log_signal,
    run_monitor_loop,
    scan_watchlist_once,
)
from backtesting.final_strategy import MIN_TRADE_VALUE
from backtesting.ml_entry_filter import TrainedEntryFilterModel

# check_candidate 내부가 date.today()로 "오늘"을 계산하므로, 픽스처도 실제 오늘
# 날짜를 써야 top35_ok 등 날짜 매칭이 실제 코드와 어긋나지 않는다.
TODAY_STR = date.today().isoformat()
PREV_STR = (date.today() - timedelta(days=3)).isoformat()


def _daily(dates: list[str], closes: list[float]) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * len(closes)}, index=index
    )


def _rising_minute(day: str, closes: list[float]) -> pd.DataFrame:
    index = pd.date_range(f"{day} 09:00", periods=len(closes), freq="1min")
    # 분당 거래대금(종가x거래량)이 MIN_TRADE_VALUE를 넘도록 종가에서 역산한다 —
    # 하한 상수가 바뀌어도 픽스처가 조용히 신호를 잃지 않게 리터럴을 쓰지 않는다.
    volume = int(MIN_TRADE_VALUE / min(closes)) + 1
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [volume] * len(closes)},
        index=index,
    )


class _StubProbaModel:
    """predict_proba가 항상 고정된 확률을 반환하는 스텁 (ml_reversal 테스트와 동일한 패턴)."""

    def __init__(self, proba: float):
        self._proba = proba

    def predict_proba(self, X):
        return np.array([[1 - self._proba, self._proba]] * len(X))


def _write_daily_csv(tmp_path, code: str, dates: list[str], closes: list[float]) -> str:
    daily_dir = tmp_path / "stocks" / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    _daily(dates, closes).to_csv(daily_dir / f"{code}.csv")
    return str(tmp_path)


def test_load_recent_daily_returns_empty_when_no_local_file(tmp_path):
    result = load_recent_daily("000001", data_dir=str(tmp_path))

    assert result.empty


def test_check_candidate_returns_none_when_no_entry_signal(tmp_path, monkeypatch):
    flat = _rising_minute(TODAY_STR, [100, 100, 100])  # 어떤 조건도 안 맞음
    monkeypatch.setattr(live_monitor, "load_history", lambda *a, **k: flat)
    data_dir = _write_daily_csv(tmp_path, "000001", [PREV_STR, TODAY_STR], [100, 100])
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.9))

    result = check_candidate(object(), "000001", trained, {"000001"}, True, data_dir=data_dir)

    assert result is None


def test_check_candidate_uses_feed_data_without_calling_rest(tmp_path, monkeypatch):
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    rest_calls = []
    monkeypatch.setattr(live_monitor, "load_history", lambda *a, **k: rest_calls.append(1) or rising)
    data_dir = _write_daily_csv(tmp_path, "000001", [PREV_STR, TODAY_STR], [100, 999])
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.9))
    feed = SimpleNamespace(get_minute_df=lambda code: rising)

    result = check_candidate(object(), "000001", trained, {"000001"}, True, data_dir=data_dir, proba_threshold=0.6, feed=feed)

    assert result is not None
    assert rest_calls == []  # feed에 데이터가 있으니 REST(load_history)는 아예 호출 안 됨


def test_check_candidate_falls_back_to_rest_when_feed_empty(tmp_path, monkeypatch):
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    rest_calls = []
    monkeypatch.setattr(live_monitor, "load_history", lambda *a, **k: rest_calls.append(1) or rising)
    data_dir = _write_daily_csv(tmp_path, "000001", [PREV_STR, TODAY_STR], [100, 999])
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.9))
    feed = SimpleNamespace(get_minute_df=lambda code: pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))

    result = check_candidate(object(), "000001", trained, {"000001"}, True, data_dir=data_dir, proba_threshold=0.6, feed=feed)

    assert result is not None
    assert rest_calls == [1]  # feed가 비어있으니(아직 틱 없음) REST로 폴백


def test_check_candidate_returns_none_when_daily_data_missing(tmp_path, monkeypatch):
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    monkeypatch.setattr(live_monitor, "load_history", lambda *a, **k: rising)
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.9))

    result = check_candidate(object(), "000001", trained, {"000001"}, True, data_dir=str(tmp_path))  # 로컬 daily 없음

    assert result is None


def test_check_candidate_returns_signal_when_all_conditions_and_proba_pass(tmp_path, monkeypatch):
    # idx4(마지막 캔들)에서 당일상승률 11%(밴드[7~22%) 내) + 3분수익률/거래대금/당일신고가/무하락 전부 만족
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    monkeypatch.setattr(live_monitor, "load_history", lambda *a, **k: rising)
    data_dir = _write_daily_csv(tmp_path, "000001", [PREV_STR, TODAY_STR], [100, 999])
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.9))

    result = check_candidate(object(), "000001", trained, {"000001"}, True, data_dir=data_dir, proba_threshold=0.6)

    assert result is not None
    assert result["stock_code"] == "000001"
    assert result["proba"] == pytest.approx(0.9)
    assert result["price"] == 111


def test_check_candidate_returns_none_when_proba_below_threshold(tmp_path, monkeypatch):
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    monkeypatch.setattr(live_monitor, "load_history", lambda *a, **k: rising)
    data_dir = _write_daily_csv(tmp_path, "000001", [PREV_STR, TODAY_STR], [100, 999])
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.4))  # 임계값(0.6) 미달

    result = check_candidate(object(), "000001", trained, {"000001"}, True, data_dir=data_dir, proba_threshold=0.6)

    assert result is None


def test_check_candidate_returns_none_when_regime_is_down(tmp_path, monkeypatch):
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    monkeypatch.setattr(live_monitor, "load_history", lambda *a, **k: rising)
    data_dir = _write_daily_csv(tmp_path, "000001", [PREV_STR, TODAY_STR], [100, 999])
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.9))

    result = check_candidate(object(), "000001", trained, {"000001"}, False, data_dir=data_dir)  # 레짐 하락

    assert result is None


def test_check_candidate_returns_none_when_not_in_todays_top35(tmp_path, monkeypatch):
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    monkeypatch.setattr(live_monitor, "load_history", lambda *a, **k: rising)
    data_dir = _write_daily_csv(tmp_path, "000001", [PREV_STR, TODAY_STR], [100, 999])
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.9))

    result = check_candidate(object(), "000001", trained, {"다른종목"}, True, data_dir=data_dir)

    assert result is None


def test_scan_watchlist_once_dedupes_repeated_signal_via_seen_signals(tmp_path, monkeypatch):
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    monkeypatch.setattr(live_monitor, "load_history", lambda *a, **k: rising)
    data_dir = _write_daily_csv(tmp_path, "000001", [PREV_STR, TODAY_STR], [100, 999])
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.9))
    seen: set = set()

    first = scan_watchlist_once(object(), trained, {"000001"}, True, data_dir=data_dir, seen_signals=seen)
    second = scan_watchlist_once(object(), trained, {"000001"}, True, data_dir=data_dir, seen_signals=seen)

    assert len(first) == 1
    assert len(second) == 0


def test_scan_watchlist_once_passes_feed_through_to_check_candidate(tmp_path, monkeypatch):
    rising = _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])
    rest_calls = []
    monkeypatch.setattr(live_monitor, "load_history", lambda *a, **k: rest_calls.append(1) or rising)
    data_dir = _write_daily_csv(tmp_path, "000001", [PREV_STR, TODAY_STR], [100, 999])
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.9))
    feed = SimpleNamespace(get_minute_df=lambda code: rising)

    signals = scan_watchlist_once(object(), trained, {"000001"}, True, data_dir=data_dir, feed=feed)

    assert len(signals) == 1
    assert rest_calls == []  # feed로 처리돼서 REST 폴백이 안 일어남


def test_scan_watchlist_once_continues_after_per_stock_error(tmp_path, monkeypatch):
    def flaky_load_history(client, code, start, end, interval, use_cache, exchange=None):
        if code == "000001":
            raise RuntimeError("API error")
        return _rising_minute(TODAY_STR, [100.5, 102, 105, 108, 111])

    monkeypatch.setattr(live_monitor, "load_history", flaky_load_history)
    data_dir = _write_daily_csv(tmp_path, "000660", [PREV_STR, TODAY_STR], [100, 999])
    _daily([PREV_STR, TODAY_STR], [100, 999]).to_csv(f"{data_dir}/stocks/daily/000001.csv")
    trained = TrainedEntryFilterModel(model=_StubProbaModel(0.9))

    signals = scan_watchlist_once(object(), trained, {"000001", "000660"}, True, data_dir=data_dir)

    assert len(signals) == 1
    assert signals[0]["stock_code"] == "000660"


def test_log_signal_appends_jsonl_and_creates_parent_dir(tmp_path):
    path = str(tmp_path / "nested" / "signals.jsonl")

    log_signal({"stock_code": "000001", "proba": 0.9}, path)
    log_signal({"stock_code": "000660", "proba": 0.8}, path)

    with open(path, encoding="utf-8") as f:
        lines = f.read().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["stock_code"] == "000001"
    assert json.loads(lines[1])["stock_code"] == "000660"


def test_run_monitor_loop_polls_until_market_closes(monkeypatch):
    watchlist = pd.DataFrame([{"stock_code": "000001", "name": "A"}])
    monkeypatch.setattr(live_monitor, "top_by_trading_value", lambda client, top_n: watchlist)
    monkeypatch.setattr(live_monitor, "fetch_today_regime", lambda client, data_dir: True)
    open_flags = iter([True, True, False])
    monkeypatch.setattr(live_monitor, "is_extended_market_open", lambda now: next(open_flags))
    sleeps = []
    monkeypatch.setattr(live_monitor.time, "sleep", lambda s: sleeps.append(s))
    scan_calls = []
    monkeypatch.setattr(
        live_monitor, "scan_watchlist_once",
        lambda client, trained, watchlist_set, regime_ok, data_dir, proba_threshold, seen: scan_calls.append(watchlist_set) or [],
    )

    run_monitor_loop(object(), TrainedEntryFilterModel(model=None), output_path="unused.jsonl", poll_interval_seconds=1.0)

    assert len(scan_calls) == 2
    assert scan_calls[0] == {"000001"}


def test_fetch_today_regime_combines_local_gap_and_live_data(tmp_path, monkeypatch):
    # 실제 60기간 이평선 계산(compute_index_regime_by_day)은 entry_filters 쪽에서
    # 이미 검증됐으므로, 여기서는 "로컬+갭+실시간 데이터를 올바르게 합치는지"만
    # 확인하기 위해 그 함수를 스텁으로 대체한다. PREV_STR(오늘-3일)이 로컬의
    # 마지막 날짜라 오늘 사이에 이틀치 갭이 생기고, load_index_history가 그 갭을
    # 메우는 별도 호출로 오는지를 start 인자로 구분해서 검증한다.
    index_dir = tmp_path / "index" / "minute"
    index_dir.mkdir(parents=True)
    local_index = pd.date_range(f"{PREV_STR} 09:00", periods=3, freq="1min")
    pd.DataFrame(
        {"open": [100] * 3, "high": [100] * 3, "low": [100] * 3, "close": [100] * 3, "volume": [1000] * 3},
        index=local_index,
    ).to_csv(index_dir / "001.csv")

    gap_index = pd.date_range(f"{TODAY_STR} 08:00", periods=1, freq="1min")  # 갭 구간(전일 이전) 대용 타임스탬프
    gap_df = pd.DataFrame(
        {"open": [150], "high": [150], "low": [150], "close": [150], "volume": [1000]}, index=gap_index
    )
    live_index = pd.date_range(f"{TODAY_STR} 09:00", periods=2, freq="1min")
    live_df = pd.DataFrame(
        {"open": [200] * 2, "high": [200] * 2, "low": [200] * 2, "close": [200] * 2, "volume": [1000] * 2},
        index=live_index,
    )

    calls = []

    def fake_load_index_history(client, code, start, end, interval, use_cache):
        calls.append((start, end))
        return live_df if start == date.today() else gap_df

    monkeypatch.setattr(live_monitor, "load_index_history", fake_load_index_history)

    captured = {}

    def fake_compute_regime(combined_df, ma_period, resample_minutes):
        captured["n_rows"] = len(combined_df)
        captured["n_dates"] = combined_df.index.normalize().nunique()
        return {pd.Timestamp(date.today()): True}

    monkeypatch.setattr(live_monitor, "compute_index_regime_by_day", fake_compute_regime)

    result = fetch_today_regime(object(), data_dir=str(tmp_path))

    assert result is True
    assert len(calls) == 2  # 갭 구간 조회 1회 + 당일 조회 1회
    assert captured["n_rows"] == 6  # 로컬 3 + 갭 1 + 실시간 2 결합
    assert captured["n_dates"] == 2  # 전일(로컬)/당일(갭+실시간) 두 날짜 다 포함

    persisted = pd.read_csv(index_dir / "001.csv", index_col=0, parse_dates=True)
    assert len(persisted) == 4  # 로컬 3 + 갭 1 이 파일에도 병합 저장됨(다음 실행부터 갭 재발 방지)


def test_fetch_today_regime_skips_gap_fetch_when_local_already_current(tmp_path, monkeypatch):
    index_dir = tmp_path / "index" / "minute"
    index_dir.mkdir(parents=True)
    local_index = pd.date_range(f"{TODAY_STR} 09:00", periods=1, freq="1min")  # 로컬이 이미 오늘자
    pd.DataFrame(
        {"open": [100], "high": [100], "low": [100], "close": [100], "volume": [1000]}, index=local_index
    ).to_csv(index_dir / "001.csv")

    calls = []
    live_df = pd.DataFrame(
        {"open": [200], "high": [200], "low": [200], "close": [200], "volume": [1000]},
        index=pd.date_range(f"{TODAY_STR} 09:01", periods=1, freq="1min"),
    )
    monkeypatch.setattr(
        live_monitor, "load_index_history",
        lambda client, code, start, end, interval, use_cache: calls.append((start, end)) or live_df,
    )
    monkeypatch.setattr(live_monitor, "compute_index_regime_by_day", lambda *a, **k: {pd.Timestamp(date.today()): True})

    result = fetch_today_regime(object(), data_dir=str(tmp_path))

    assert result is True
    assert len(calls) == 1  # 갭이 없으니 당일 조회 1회만


def test_fetch_today_regime_false_when_no_data_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(live_monitor, "load_index_history", lambda *a, **k: pd.DataFrame())

    result = fetch_today_regime(object(), data_dir=str(tmp_path))

    assert result is False
