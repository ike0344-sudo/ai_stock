"""분봉 세션 규칙(bar_sessions + run_portfolio(session=)) · 틱 엔진(simulate_tick_days) · 정밀화 함수 — 손계산 시나리오."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from studio.domain.costs import CostModel
from studio.domain.engine.fills import ExitRules, FillRules
from studio.domain.engine.intraday import bar_sessions
from studio.domain.engine.portfolio import PortfolioRules, run_portfolio
from studio.domain.engine.tick import (
    Candidate, TickRules, hms_to_sec, refine_entry, refine_exit, repriced_net, simulate_tick_days,
)
from studio.domain.models import ExitReason, Panel

NOCOST = CostModel(0.0, 0.0, "rate", 0.0, 0.0)
D1, D2 = pd.Timestamp("2024-03-04"), pd.Timestamp("2024-03-05")


def labels(day, ends):  # ends: ["09:05", ...] 봉 끝 라벨
    return [day + pd.Timedelta(hours=int(e[:2]), minutes=int(e[3:])) for e in ends]


# ------------------------------------------------------------------ 세션 규칙
def test_bar_sessions_eod_bar_and_after_eod_labels():
    idx = pd.DatetimeIndex(labels(D1, ["15:10", "15:15", "15:20", "15:35"]) + labels(D2, ["09:05", "15:20", "15:35"]))
    s = bar_sessions(idx, "15:20")
    assert list(s.eod_bar) == [False, False, True, False, False, True, False]  # 날마다 끝 시각 <= 15:20 인 마지막 봉
    assert list(s.after_eod) == [False, False, False, True, False, False, True]  # 15:30 종가 단일가 봉(라벨 15:35)은 EOD 이후
    assert list(s.day_id) == [0, 0, 0, 0, 1, 1, 1]
    # 초 단위 eod(15:19:59)는 15:20 으로 올림, 15:15 이면 15:15 봉이 EOD
    assert list(bar_sessions(idx, "15:19:59").eod_bar) == list(s.eod_bar)
    assert list(bar_sessions(idx, "15:15").eod_bar)[:4] == [False, True, False, False]


def _panel(idx, closes, opens=None):
    c = pd.DataFrame({"A": closes}, index=idx, dtype=float)
    o = c if opens is None else pd.DataFrame({"A": opens}, index=idx, dtype=float)
    v = pd.DataFrame({"A": 1e6}, index=idx)
    pc = pd.DataFrame({"A": 100.0}, index=idx)  # 그 날 전일 종가(상수)
    return Panel(o, np.maximum(o, c), np.minimum(o, c), c, v, c * v, pc)


def test_eod_close_and_no_trade_after_eod_and_no_cross_day_fill():
    ends = ["15:00", "15:05", "15:10", "15:15", "15:20", "15:35"]
    idx = pd.DatetimeIndex(labels(D1, ends) + labels(D2, ["09:05", "09:10"]))
    p = _panel(idx, [100, 100, 100, 100, 101, 999, 100, 100], opens=[100, 100, 100, 100, 100, 999, 100, 100])
    ent = pd.DataFrame(False, index=idx, columns=["A"])
    ent.iloc[1, 0] = True  # 15:05 종가 신호 -> 15:10 봉 시가 체결
    ent.iloc[4, 0] = True  # 15:20(EOD 봉) 종가 신호 -> 다음 봉은 15:35(EOD 이후) - 체결 금지
    ent.iloc[5, 0] = True  # 15:35 봉 신호 -> 다음 봉은 다음 날 09:05 - 날 경계라 체결 금지
    ses = bar_sessions(idx, "15:20")
    r = run_portfolio(p, ent, None, NOCOST, ExitRules(), FillRules(), PortfolioRules(initial_capital=1e6, max_positions=1), session=ses)
    (t,) = r.trades
    assert t.entry_ts == idx[2] and t.exit_ts == idx[4] and t.exit_reason == ExitReason.EOD  # EOD 봉 종가(101)에 청산
    assert t.exit_price == 101
    assert not [f for f in r.fills if f.ts in (idx[5], idx[6], idx[7])]  # 15:35, 다음 날 체결 없음
    assert r.equity["n_positions"].iloc[-1] == 0


def test_eod_locked_close_carries_to_next_day_first_bar():
    ends = ["15:15", "15:20", "15:35"]
    idx = pd.DatetimeIndex(labels(D1, ends) + labels(D2, ["09:05"]))
    # 전일 종가 100, EOD 봉 종가가 하한가(70) 근처라 청산 불가 -> 다음 날 첫 봉으로 이월
    p = _panel(idx, [100, 70, 70, 80], opens=[100, 100, 70, 80])
    ent = pd.DataFrame(False, index=idx, columns=["A"])
    ent.iloc[0, 0] = True
    ses = bar_sessions(idx, "15:20")
    r = run_portfolio(p, ent, None, NOCOST, ExitRules(), FillRules(), PortfolioRules(initial_capital=1e6, max_positions=1), session=ses)
    (t,) = r.trades
    assert t.exit_ts == idx[3] and t.exit_reason == ExitReason.EOD and t.exit_price == 80  # 이월된 청산은 다음 날 시가


# ------------------------------------------------------------------ 틱 엔진 (모드 B)
def cand(code, sec, prc, entry_idx, prev_close=None, day=dt.date(2024, 3, 4)):
    return Candidate(code, day, np.asarray(sec, "int64"), np.asarray(prc, float), prev_close, int(sec[entry_idx]) - 1, entry_idx)


def sim(cands, *, exit_rules=ExitRules(), tr=TickRules(600, "15:19:59"), port=None, cost=NOCOST):
    port = port or PortfolioRules(initial_capital=1_000_000, max_positions=2)
    days = {}
    for c in cands:
        days.setdefault(c.day, []).append(c)
    return simulate_tick_days(days, sorted(days) or [dt.date(2024, 3, 4)], cost, exit_rules, port, tr)


def test_hms_to_sec():
    assert hms_to_sec("09:00:00") == 0 and hms_to_sec("15:19:59") == 6 * 3600 + 19 * 60 + 59 and hms_to_sec("09:05") == 300


def test_tick_stop_uses_first_crossing_tick_price_not_the_line():
    # 진입 100(틱1) -> 98 -> 94(선 95 를 뚫음, 선이 아니라 이 틱 가격 94 에 청산) -> 200
    r = sim([cand("A", [10, 20, 30, 40, 50], [99, 100, 98, 94, 200], 1)], exit_rules=ExitRules(stop_loss_pct=5))
    (t,) = r.trades
    assert t.exit_reason == ExitReason.STOP and t.exit_price == 94 and t.entry_price == 100
    assert t.exit_ts == D1 + pd.Timedelta(hours=9, seconds=40) and t.bars_held == 20
    assert t.mfe_pct == pytest.approx(0) and t.mae_pct == pytest.approx(-6)


def test_tick_target_trailing_time_and_eod():
    tgt = sim([cand("A", [10, 20, 30, 40], [100, 100, 106, 90], 1)], exit_rules=ExitRules(take_profit_pct=5))
    assert tgt.trades[0].exit_reason == ExitReason.TARGET and tgt.trades[0].exit_price == 106
    # 트레일링: 고점(직전 틱까지) 110 -> 선 99, 98 에서 청산. 고점 갱신 틱(110) 자신은 판정 뒤 갱신
    tr = sim([cand("A", [10, 20, 30, 40, 50], [100, 100, 110, 105, 98], 1)], exit_rules=ExitRules(trailing_stop_pct=10))
    assert tr.trades[0].exit_reason == ExitReason.TRAILING and tr.trades[0].exit_price == 98
    # 시간 손절: 진입 초 20 + 600 초 이후 첫 체결(sec 700)
    ts = sim([cand("A", [10, 20, 100, 700, 900], [100, 100, 101, 102, 103], 1)])
    assert ts.trades[0].exit_reason == ExitReason.TIME and ts.trades[0].exit_price == 102
    # EOD: 15:19:59 이하 마지막 체결(시간 손절 없음)
    eod_sec = hms_to_sec("15:19:59")
    e = sim([cand("A", [10, 20, eod_sec - 5, eod_sec, eod_sec + 1], [100, 100, 101, 102, 150], 1)], tr=TickRules(None, "15:19:59"))
    assert e.trades[0].exit_reason == ExitReason.EOD and e.trades[0].exit_price == 102
    # 진입이 EOD 이후면 안 산다
    late = sim([cand("A", [10, eod_sec + 1], [100, 100], 1)], tr=TickRules(None, "15:19:59"))
    assert late.trades == [] and late.diagnostics["no_entry_after_eod"] == 1


def test_tick_slots_priority_limit_and_costs():
    a = cand("A", [10, 20, 100], [100, 100, 100], 1)  # 진입 20 초
    b = cand("B", [15, 25, 100], [50, 50, 50], 1)  # 진입 25 초 - 슬롯 1개면 A 가 잡고 있어 건너뜀
    r = sim([b, a], port=PortfolioRules(initial_capital=1e6, max_positions=1))
    assert [t.code for t in r.trades] == ["A"] and r.skipped["slots_full"] == 1  # 진입 시각 순
    r2 = sim([b, a], port=PortfolioRules(initial_capital=1e6, max_positions=2))
    assert sorted(t.code for t in r2.trades) == ["A", "B"]
    # 상한가로 잠긴 진입가(전일 종가 100 -> 130) 는 안 산다
    lk = sim([cand("A", [10, 20], [130, 130], 1, prev_close=100.0)])
    assert lk.trades == [] and lk.skipped["upper_limit"] == 1
    # 비용: 수수료·세금·슬리피지가 봉 엔진과 같은 식
    cm = CostModel(0.001, 0.002, "rate", 0.01)
    c = sim([cand("A", [10, 20, 30], [100, 100, 110], 1)], exit_rules=ExitRules(take_profit_pct=5), cost=cm,
            port=PortfolioRules(initial_capital=1_000_000, max_positions=1)).trades[0]
    net, pct = repriced_net(cm, c.qty, 100, 110)
    assert c.entry_price == pytest.approx(101) and c.exit_price == pytest.approx(108.9)
    assert c.net_pnl == pytest.approx(net) and c.net_pct == pytest.approx(pct)


def test_tick_compound_sizing_and_daily_equity():
    d1, d2 = dt.date(2024, 3, 4), dt.date(2024, 3, 5)
    w = cand("A", [10, 20, 30], [100, 100, 150], 1, day=d1)  # +50% 익절
    n = cand("A", [10, 20, 30], [100, 100, 100], 1, day=d2)
    port = PortfolioRules(initial_capital=1_000_000, max_positions=1, sizing="equal_slot_compound")
    r = simulate_tick_days({d1: [w], d2: [n]}, [d1, d2, dt.date(2024, 3, 6)], NOCOST, ExitRules(take_profit_pct=10), port,
                           TickRules(None, "15:19:59"))
    assert r.trades[0].qty == 10_000 and r.trades[1].qty == 15_000  # 둘째 날은 첫날 이익이 붙은 평가금(150만)으로
    assert list(r.equity["equity"]) == [1_500_000, 1_500_000, 1_500_000] and len(r.equity) == 3  # 거래 없는 날도 한 줄


# ------------------------------------------------------------------ 정밀화 함수 (모드 A)
def test_refine_entry_and_exits():
    sec = np.array([100, 250, 300, 310, 500, 599, 600, 610])
    prc = np.array([10.0, 11, 12, 13, 9, 8, 7, 6])
    assert refine_entry(sec, prc, 300, 12.0).tick_ref == 12  # 봉이 끝난 시각(300초) 이후 첫 체결
    assert refine_entry(sec, prc, 300, 12.5).diff_pct == pytest.approx((12 / 12.5 - 1) * 100)
    assert refine_entry(sec, prc, 9999, 1.0).tick_ref is None  # 이후 체결 없음
    # 손절선 10 을 [300, 600) 안에서 처음 넘은(<=10) 체결 = 9 (봉 엔진은 선 10 에 체결한다고 가정)
    x = refine_exit(sec, prc, ExitReason.STOP, 300, 600, 10.0, 10.0)
    assert x.tick_ref == 9 and x.diff_pct == pytest.approx(-10)
    # 익절선 13 -> 13 체결, 봉 구간 밖(600 이후) 체결은 안 봄
    assert refine_exit(sec, prc, ExitReason.TARGET, 300, 600, 13.0, 13.0).tick_ref == 13
    assert refine_exit(sec, prc, ExitReason.TARGET, 300, 600, 20.0, 20.0).tick_ref is None  # 선을 안 넘음
    # 종가 청산 = 봉 안 마지막 체결(599초 = 8), 시그널 청산 = 봉 시작 이후 첫 체결
    assert refine_exit(sec, prc, ExitReason.EOD, 300, 600, 8.0, None).tick_ref == 8
    assert refine_exit(sec, prc, ExitReason.SIGNAL, 300, 600, 12.0, 12.0).tick_ref == 12
