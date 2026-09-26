"""틱 조건 추가분(c4) — trade_strength · block_trades · daily_breakout: 손계산 · 순진한 구현 대조 · 카나리아."""
import datetime as dt
from types import SimpleNamespace

import numpy as np
import pytest

from studio.domain.conditions.catalog import TICK_CATALOG
from studio.domain.conditions.tick import (
    N, TickDay, block_count_series, block_trades_hits, build_grid, daily_breakout_hits, detect_from_spec,
    detect_signals, prior_n_high, trade_strength_hits, trade_strength_series,
)
from tests.studio.conditions.test_tick import make_day

DATE = dt.date(2026, 8, 4)


def day(ticks) -> TickDay:
    """(초, 가격, 수량) 목록 → TickDay."""
    a = np.array(ticks, dtype=float)
    return TickDay("000001", DATE, a[:, 0].astype(np.int64), a[:, 1], a[:, 2])


def test_registered_in_tick_catalog():
    assert {"trade_strength", "block_trades", "daily_breakout"} <= set(TICK_CATALOG)


def test_trade_strength_hand_calc_tick_rule():
    # 0:100(첫 틱 방향 없음) 1:101(상승=매수 3) 2:100(하락=매도 2) 3:100(보합→직전 매도 계승, 4)
    g = build_grid(day([(0, 100, 1), (1, 101, 3), (2, 100, 2), (3, 100, 4)]))
    r = trade_strength_series(g, 3)
    assert r[3] == pytest.approx(3 / 2 * 100)   # 창 [0,3): 매수 3 / 매도 2
    assert r[4] == pytest.approx(3 / 6 * 100)   # 창 [1,4): 매수 3 / 매도 2+4
    assert np.isnan(r[2])                       # s=2 < w=3 — 창이 세션 시작 앞에 걸치면 값 없음
    assert trade_strength_hits(g, 3, 100)[3] and not trade_strength_hits(g, 3, 100)[4]


def test_trade_strength_all_buys_is_inf_and_empty_window_is_nan():
    g = build_grid(day([(0, 100, 1), (1, 101, 5), (2, 102, 5)]))
    r = trade_strength_series(g, 2)
    assert np.isposinf(r[3])                    # [1,3): 매수 10, 매도 0
    assert trade_strength_hits(g, 2, 1e9)[3]    # inf 는 어떤 문턱도 넘는다
    assert np.isnan(r[100])                     # 체결 없는 창


def naive_strength(d: TickDay, w, s):
    """느리지만 명백한 구현: 초 s 직전 w 초 체결을 하나씩 훑는다."""
    buy = sell = 0.0
    dirn = 0
    prev = None
    for sec, p, q in zip(d.sec, d.prc, d.qty):
        if prev is not None:
            dirn = 1 if p > prev else -1 if p < prev else dirn
        prev = p
        if s - w <= sec < s:
            buy += q if dirn > 0 else 0
            sell += q if dirn < 0 else 0
    return buy, sell


def test_trade_strength_matches_naive_on_random_day():
    d = make_day(seed=4, n=3000)
    g = build_grid(d)
    r = trade_strength_series(g, 90)
    for s in (100, 5000, 12000, 23000):
        b, sl = naive_strength(d, 90, s)
        want = b / sl * 100 if sl > 0 else (np.inf if b > 0 else np.nan)
        assert (np.isnan(r[s]) and np.isnan(want)) or r[s] == pytest.approx(want)


def test_block_trades_hand_calc():
    d = day([(1, 100, 10), (2, 100, 500), (3, 100, 600), (20, 100, 700)])  # 대금 1천 · 5만 · 6만 · 7만
    c = block_count_series(d, 10, 50_000)
    assert c[10] == 2                              # [0,10): 5만(2초)·6만(3초) → 2건, 1천은 작아서 제외
    assert c[13] == 1                              # [3,13): 6만 1건
    assert c[21] == 1                              # [11,21): 7만(20초) 1건
    assert block_trades_hits(d, 10, 50_000, 2)[10] and not block_trades_hits(d, 10, 50_000, 3)[10]
    assert not block_trades_hits(d, 10, 50_000, 1)[5]  # s<w 값 없음


def test_prior_n_high_excludes_today_and_needs_n_days():
    dates = [dt.date(2026, 8, k) for k in (3, 4, 5, 6, 7)]
    hi = [1, 5, 3, 4, 2]
    assert prior_n_high(dates, hi, dt.date(2026, 8, 10), 3) == 4.0        # 8/5~8/7 → max(3,4,2)
    assert prior_n_high(dates, hi, dt.date(2026, 8, 7), 3) == 5.0         # 8/7 자신 제외: 8/4~8/6 → max(5,3,4)
    assert prior_n_high(dates, [1, 5, 3, 4, 99], dt.date(2026, 8, 7), 3) == 5.0  # 당일 고가는 안 봄
    assert np.isnan(prior_n_high(dates, hi, dt.date(2026, 8, 5), 3))     # 앞선 날이 2일뿐


def test_daily_breakout_signal_and_no_signal_before_first_trade():
    d = day([(5, 104, 1), (8, 106, 1), (9, 106, 1), (30, 104, 1)])
    g = build_grid(d)
    h = daily_breakout_hits(g, 105.0)
    assert not h[:8].any() and h[8] and h[9] and h[29] and not h[30]     # px: 8초에 처음 106 → 30초에 104
    # 첫 체결이 이미 레벨 위여도 첫 체결 **전** 초에는 신호 없음(앞채움 가격 = 미래 값)
    d2 = day([(5, 106, 1), (9, 106, 1)])
    h2 = daily_breakout_hits(build_grid(d2), 105.0)
    assert not h2[:5].any() and h2[5]
    assert not daily_breakout_hits(g, float("nan")).any()               # 기준선 없음(일봉 부족) → 신호 없음


def test_detect_signals_daily_breakout_entry_strictly_after_signal():
    d = day([(5, 104, 1), (8, 106, 1), (9, 107, 1), (30, 104, 1)])
    ev = detect_signals(d, daily_breakout=(20, 105.0), cooldown_sec=10_000)
    assert ev.signal_sec.tolist() == [8]
    assert ev.entry_sec.tolist() == [9] and ev.entry_price.tolist() == [107.0] and (ev.entry_sec > ev.signal_sec).all()


def test_detect_signals_combines_and_and_requires_something():
    d = day([(k, 100 + (k % 3), 10) for k in range(0, 200)])
    both = detect_signals(d, trade_strength=(10, 0), block_trades=(10, 1_000, 1), cooldown_sec=1)
    only = detect_signals(d, trade_strength=(10, 0), cooldown_sec=1)
    assert set(both.signal_sec) <= set(only.signal_sec) and len(only.signal_sec) > 0
    with pytest.raises(ValueError, match="틱 조건이 하나도 없음"):
        detect_signals(d)


def test_detect_from_spec_reads_new_fields_and_old_specs_still_work():
    d = day([(5, 104, 1), (8, 106, 1), (9, 107, 1)])
    old = SimpleNamespace(catalog=SimpleNamespace(breakout_min=None, value_speed=None, buy_ratio=SimpleNamespace(w=1, min=0.0),
                                                  time_from="09:00:00", time_to="15:30:00"), cooldown_sec=300)
    detect_from_spec(d, old)  # 새 칸 없는 옛 명세도 동작
    new = SimpleNamespace(catalog=SimpleNamespace(breakout_min=None, value_speed=None, buy_ratio=None,
                                                  daily_breakout=SimpleNamespace(n=20), time_from="09:00:00", time_to="15:30:00"),
                          cooldown_sec=300)
    with pytest.raises(ValueError, match="daily_high_level"):
        detect_from_spec(d, new)
    assert detect_from_spec(d, new, daily_high_level=105.0).signal_sec.tolist() == [8]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_canary_no_lookahead_ticks_after_s_do_not_change_values_up_to_s(seed):
    """S 초 **뒤** 체결(가격·수량)을 크게 바꿔도 0..S 초의 값은 그대로 — 창 [s−w, s) 와 px[s] 만 쓴다는 증거."""
    d = make_day(seed=seed, n=4000)
    S = 12_000
    later = d.sec > S
    prc, qty = d.prc.copy(), d.qty.copy()
    prc[later] *= 1.5
    qty[later] *= 7
    bad = TickDay(d.code, d.date, d.sec, prc, qty, d.prev_close)
    g, gb = build_grid(d), build_grid(bad)
    a, b = trade_strength_series(g, 60)[: S + 1], trade_strength_series(gb, 60)[: S + 1]
    np.testing.assert_array_equal(a, b)
    np.testing.assert_array_equal(block_count_series(d, 60, 50_000)[: S + 1], block_count_series(bad, 60, 50_000)[: S + 1])
    lvl = float(np.median(d.prc))
    np.testing.assert_array_equal(daily_breakout_hits(g, lvl)[: S + 1], daily_breakout_hits(gb, lvl)[: S + 1])
    assert not np.array_equal(daily_breakout_hits(g, lvl), daily_breakout_hits(gb, lvl))  # 변조가 뒤쪽엔 닿음
