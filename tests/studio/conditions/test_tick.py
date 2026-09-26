"""틱 조건 — 정의 정확도(손계산·순진한 구현 대조), 쿨다운, 진입은 신호 초보다 엄격히 뒤, C4 카나리아."""
import datetime as dt
import json
import pathlib

import numpy as np
import pytest

from studio.domain.conditions.tick import (
    N, TickDay, apply_cooldown, breakout_hits, build_grid, buy_ratio_hits, buy_ratio_series, detect_from_spec,
    detect_signals, is_gap_open_day, time_mask, value_speed_hits, value_speed_series,
)
from studio.domain.spec import Spec

ROOT = pathlib.Path(__file__).resolve().parents[3]
DATE = dt.date(2026, 8, 4)


def make_day(seed=0, n=6000, base=10_000.0, prev_close=None) -> TickDay:
    rng = np.random.default_rng(seed)
    sec = np.sort(rng.integers(0, N, n)).astype(np.int64)      # 같은 초 다중 체결 포함
    prc = base + np.cumsum(rng.choice([-10, 0, 10], size=n, p=[0.4, 0.2, 0.4]))
    qty = rng.integers(1, 200, n).astype(float)
    return TickDay("000001", DATE, sec, prc.astype(float), qty, prev_close)


def steady_day(prc=None, qty=None) -> TickDay:
    """매초 1건 체결(0..N-1초)."""
    sec = np.arange(N, dtype=np.int64)
    return TickDay("000001", DATE, sec, np.full(N, 100.0) if prc is None else prc,
                   np.ones(N) if qty is None else qty)


def naive_breakouts(px, w, cooldown):
    hits = [s for s in range(w, len(px)) if px[s] > px[s - w:s].max()]
    keep, last = [], -10**9
    for s in hits:
        if s - last >= cooldown:
            keep.append(s)
            last = s
    return np.array(keep, dtype=np.int64)


# ---------------------------------------------------------------- 격자·정의
def test_grid_last_trade_in_second_wins_and_ffills():
    d = TickDay("X", DATE, np.array([5, 5, 7]), np.array([100.0, 101.0, 102.0]), np.array([1.0, 2.0, 3.0]))
    g = build_grid(d)
    assert g.px[5] == 101.0 and g.px[6] == 101.0 and g.px[7] == 102.0   # 같은 초는 마지막 체결가
    assert g.vol[5] == 3.0 and g.cnt[5] == 2.0 and g.val[5] == 100 * 1 + 101 * 2


@pytest.mark.parametrize("w_min", [1, 3])
def test_breakout_equals_naive_window_definition(w_min):
    day = make_day(seed=1)
    px = build_grid(day).px
    got = apply_cooldown(np.flatnonzero(breakout_hits(build_grid(day), w_min)), 300)
    assert len(got) > 0
    assert np.array_equal(got, naive_breakouts(px, w_min * 60, 300))


def test_breakout_excludes_current_second_and_needs_strictly_greater():
    px_flat = steady_day()                                 # 가격 100 고정 → 같은 값은 돌파가 아니다
    assert not breakout_hits(build_grid(px_flat), 1).any()
    prc = np.full(N, 100.0)
    prc[500] = 101.0                                       # 500 초에 처음으로 앞 60 초 최고가(100)를 넘음
    hits = np.flatnonzero(breakout_hits(build_grid(steady_day(prc=prc)), 1))
    assert hits.tolist() == [500]


def test_cooldown_measures_from_last_kept_signal():
    assert apply_cooldown(np.array([0, 100, 299, 300, 600]), 300).tolist() == [0, 300, 600]
    assert apply_cooldown(np.array([0, 1, 2]), 0).tolist() == [0, 1, 2]


def test_value_speed_hand_computed():
    g = build_grid(steady_day())                           # 매초 체결대금 100
    sp = value_speed_series(g, 1)
    assert np.isnan(sp[:120]).all() and np.allclose(sp[120:], 1.0)   # 창(60)+지난 구간 1개 이상 있어야 값이 생김
    qty = np.ones(N)
    qty[300:360] = 10                                       # 300~359 초 체결대금 10 배
    sp = value_speed_series(build_grid(steady_day(qty=qty)), 1)
    assert np.isclose(sp[360], 10.0)                        # [300,360) = 60000, 평균 = 30000/(300/60) = 6000
    assert not value_speed_hits(build_grid(steady_day()), 1, 1.01).any()
    assert value_speed_hits(build_grid(steady_day(qty=qty)), 1, 9.9)[360]


def test_buy_ratio_uses_tick_rule():
    prc = 100.0 + (np.arange(N) % 2)                        # 100,101,100,101… → 홀수 초가 상승체결(매수)
    g = build_grid(steady_day(prc=prc))
    r = buy_ratio_series(g, 1)
    assert np.isnan(r[:60]).all() and np.allclose(r[60:], 0.5)
    assert buy_ratio_hits(g, 1, 0.5)[60:].all() and not buy_ratio_hits(g, 1, 0.51).any()


def test_tick_rule_flat_ticks_inherit_previous_direction():
    d = TickDay("X", DATE, np.arange(4), np.array([100.0, 101.0, 101.0, 100.0]), np.ones(4))
    g = build_grid(d)
    assert g.buy[:4].tolist() == [0.0, 1.0, 1.0, 0.0]       # 보합(101→101)은 직전 방향(상승) 계승, 마지막은 하락


def test_time_window_is_inclusive_on_signal_second():
    m = time_mask("10:00", "11:00")
    assert not m[3599] and m[3600] and m[7200] and not m[7201]
    day = make_day(seed=2)
    ev = detect_signals(day, breakout_min=1, time_from="10:00", time_to="11:00", cooldown_sec=1)
    assert len(ev.signal_sec) > 0 and ev.signal_sec.min() >= 3600 and ev.signal_sec.max() <= 7200


def test_no_condition_raises_and_empty_day_is_fine():
    with pytest.raises(ValueError, match="틱 조건이 하나도 없음"):
        detect_signals(make_day(), cooldown_sec=300)
    empty = TickDay("X", DATE, np.array([], dtype=np.int64), np.array([]), np.array([]))
    ev = detect_signals(empty, breakout_min=1, value_speed=(1, 1.0), buy_ratio=(1, 0.5))
    assert len(ev.signal_sec) == 0 and ev.n_no_entry == 0


def test_tickday_validation():
    with pytest.raises(ValueError):
        TickDay("X", DATE, np.array([5, 3]), np.array([1.0, 1.0]), np.array([1.0, 1.0]))   # 시간순 아님
    with pytest.raises(ValueError):
        TickDay("X", DATE, np.array([1, 2]), np.array([1.0]), np.array([1.0, 1.0]))        # 길이 다름


def test_gap_open_day():
    d = TickDay("X", DATE, np.array([0]), np.array([106.0]), np.array([1.0]), prev_close=100.0)
    assert is_gap_open_day(d) and not is_gap_open_day(d, 10.0)
    assert not is_gap_open_day(TickDay("X", DATE, np.array([0]), np.array([106.0]), np.array([1.0])))  # 전일 종가 모름


# ---------------------------------------------------------------- 진입 = 신호 초보다 엄격히 뒤
def test_entry_is_first_tick_strictly_after_signal_second():
    day = make_day(seed=3)
    ev = detect_signals(day, breakout_min=1, cooldown_sec=60)
    assert len(ev.signal_sec) > 5
    assert (ev.entry_sec > ev.signal_sec).all()
    for s, j in zip(ev.signal_sec, ev.entry_idx):
        assert j == np.flatnonzero(day.sec > s)[0]          # s 보다 뒤인 첫 체결
        assert ev.entry_price[list(ev.entry_idx).index(j)] == day.prc[j]
        assert j == 0 or day.sec[j - 1] <= s


def test_signal_with_no_later_tick_is_dropped_and_counted():
    prc = np.full(N, 100.0)
    prc[N - 1] = 101.0                                      # 마지막 초에 돌파 — 그 뒤 체결 없음
    ev = detect_signals(steady_day(prc=prc), breakout_min=1, cooldown_sec=300)
    assert len(ev.signal_sec) == 0 and ev.n_no_entry == 1


# ---------------------------------------------------------------- C4
CONFIGS = [
    dict(breakout_min=1),
    dict(value_speed=(1, 1.2)),
    dict(buy_ratio=(1, 0.5)),
    dict(breakout_min=1, value_speed=(1, 1.0), buy_ratio=(1, 0.5)),
]


def _tampered(day: TickDay, s: int) -> TickDay:
    m = day.sec > s
    prc, qty = day.prc.copy(), day.qty.copy()
    prc[m] *= 10
    qty[m] *= 10
    return TickDay(day.code, day.date, day.sec, prc, qty, day.prev_close)


@pytest.mark.parametrize("cfg_i", range(len(CONFIGS)))
@pytest.mark.parametrize("s", [8_000, 15_600])
def test_c4_future_ticks_do_not_change_signals_at_or_before_s(cfg_i, s):
    day = make_day(seed=4)
    cfg = CONFIGS[cfg_i]
    base = detect_signals(day, cooldown_sec=60, **cfg)
    fut = detect_signals(_tampered(day, s), cooldown_sec=60, **cfg)
    a, b = base.signal_sec[base.signal_sec <= s], fut.signal_sec[fut.signal_sec <= s]
    assert np.array_equal(a, b)
    if cfg_i < 3:
        assert len(a) > 0                                    # 카나리아가 빈손이 아니게
    assert (fut.entry_sec > fut.signal_sec).all()


def test_c4_tampering_future_really_changes_future_signals():
    day = make_day(seed=4)
    base = detect_signals(day, breakout_min=1, cooldown_sec=60)
    fut = detect_signals(_tampered(day, 8_000), breakout_min=1, cooldown_sec=60)
    assert not np.array_equal(base.signal_sec[base.signal_sec > 8_000], fut.signal_sec[fut.signal_sec > 8_000])


# ---------------------------------------------------------------- 명세 연결
def test_detect_from_spec_matches_direct_call():
    spec = Spec.model_validate(json.loads((ROOT / "presets" / "studio" / "tick_breakout_5m.json").read_text(encoding="utf-8")))
    day = make_day(seed=5)
    a = detect_from_spec(day, spec.tick)
    b = detect_signals(day, breakout_min=5, time_from="09:05", time_to="15:00", cooldown_sec=300)
    assert np.array_equal(a.signal_sec, b.signal_sec) and len(a.signal_sec) > 0
    assert a.signal_sec.min() >= 300  # 09:05 이전 신호 없음
