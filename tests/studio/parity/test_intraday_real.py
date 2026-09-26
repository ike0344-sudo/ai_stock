"""실데이터 분봉·틱 스모크 (통합 AL 분봉 보관소·체결) - @pytest.mark.parity, 데이터가 없으면 skip.

성과 검증이 아니라 실제 데이터로 끝까지 도는지, 세션 규칙(EOD 15:20·15:30 봉 비거래)·진입은 신호 뒤·커버리지 보고가 지켜지는지.
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from perf_intraday import spec  # noqa: E402

from studio.application.backtest_service import run_backtest  # noqa: E402
from studio.domain.conditions.tick import detect_from_spec  # noqa: E402
from studio.infrastructure.market_data import LocalMarketData  # noqa: E402

pytestmark = pytest.mark.parity
PARQUET = os.path.join("data", "cache", "daily_all.parquet")


@pytest.fixture(scope="module")
def md():
    if not os.path.exists(PARQUET) or not os.path.isdir(os.path.join("data", "stocks", "tick_al")):
        pytest.skip("실데이터 없음")
    return LocalMarketData()


def test_real_intraday_session_rules_and_coverage(md):
    rec = run_backtest(spec(start="2026-08-24", end="2026-09-23"), md)
    t = rec.trades
    assert len(t) > 10
    assert (t["entry_ts"].dt.normalize() == t["exit_ts"].dt.normalize()).all()
    assert (t["exit_ts"].dt.time <= pd.Timestamp("15:20").time()).all()  # 15:30 종가 단일가 봉(라벨 15:35)은 거래 안 함
    assert (t["entry_ts"].dt.time > pd.Timestamp("09:05").time()).all()
    cov = rec.summary["intraday"]
    assert 0 < cov["used_pairs"] <= cov["expected_pairs"] and cov["warmup_days"] >= 1
    # 경고는 데이터 사정에 따라 나온다(부분 커버리지일 때만 / 60일 미만일 때만) — 실데이터 갱신으로 커버리지가 100% 가 되면 없는 게 정상
    assert any("분봉 커버리지" in w for w in rec.warnings) == (cov["used_pairs"] < cov["expected_pairs"])
    assert any("분봉 짧은 표본" in w for w in rec.warnings) == (cov["days_with_bars"] < 60)
    assert any("종가×거래량 근사" in w for w in rec.warnings)


def test_real_mode_a_ticks_refine_and_mode_b_entries_follow_signals(md):
    a = run_backtest(spec("tick", start="2026-09-14", end="2026-09-23",
                          tick={"entry_source": "minute_refine", "catalog": {"breakout_min": 5}}), md)
    tr = a.summary["tick_refine"]
    assert tr["n_trades"] == len(a.trades) and tr["n_refined"] > 0
    assert (a.trades.loc[a.trades["tick_refined"], "entry_ref_tick"] > 0).all()
    b = run_backtest(spec("tick", start="2026-09-22", end="2026-09-23", strategy=None,
                          tick={"entry_source": "catalog", "catalog": {"breakout_min": 5, "time_from": "09:05", "time_to": "15:00"},
                                "cooldown_sec": 300, "exclude_gap_open_pct": 5, "time_stop_sec": 600, "eod_time": "15:19:59"},
                          universe={"type": "top_value", "n": 30}), md)
    assert len(b.trades) > 0
    for r in b.trades.head(5).itertuples():  # 진입은 신호 초보다 엄격히 뒤
        td = md.tick_day(r.code, r.entry_ts.date())
        ev = detect_from_spec(td, b.spec.tick)
        es = int((r.entry_ts - r.entry_ts.normalize()).total_seconds()) - 9 * 3600
        j = list(ev.entry_sec).index(es)
        assert es > ev.signal_sec[j]
    assert any("틱 표본" in w for w in b.warnings)
