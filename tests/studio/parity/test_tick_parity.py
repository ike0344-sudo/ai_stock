"""P5 — 틱 돌파 조건 vs `backtesting.precursor_master.detect_breakouts`: 실제 체결 파일 20개에서 동일.

추가 대조(같은 20개): 격자(px·vol·cnt) = `_precursor_fastpath.to_grid`, 체결대금 속도·매수 비중 =
`precursor_master_features.compute_features` (이 쪽은 창이 1초 늦다 — 여기 s 의 값 = 그쪽 t0 = s+1 의 값).
실데이터(data/stocks/tick_al)가 없으면 skip — `@pytest.mark.parity`.
"""
import datetime as dt
import pathlib

import numpy as np
import pytest

from _precursor_fastpath import N as GRID_N, to_grid
from backtesting.precursor_master import detect_breakouts
from backtesting.precursor_master_features import compute_features
from studio.domain.conditions.tick import (
    N, TickDay, apply_cooldown, breakout_hits, build_grid, buy_ratio_series, detect_signals, value_speed_series,
)

TICK_DIR = pathlib.Path("data") / "stocks" / "tick_al"
WINDOWS = (1, 3, 5, 10, 20)


def _pick_files(n=20):
    """코드별 하나씩(가운데 날짜) 앞에서 n 개 — 종목이 겹치지 않게."""
    if not TICK_DIR.exists():
        return []
    out = []
    for d in sorted(p for p in TICK_DIR.iterdir() if p.is_dir()):
        files = sorted(d.glob("*.parquet"))
        if files:
            out.append(files[len(files) // 2])
        if len(out) == n:
            break
    return out


@pytest.fixture(scope="module")
def real_days():
    files = _pick_files()
    if not files:
        pytest.skip("data/stocks/tick_al 체결 파일 없음")
    days = []
    for f in files:
        g = to_grid(str(f))
        if g is None:
            continue
        day = TickDay(f.parent.name, dt.date.fromisoformat(f.stem), g["tick_sec"], g["tick_prc"], g["tick_qty"])
        days.append((day, g))
    assert days, "정규장 체결이 있는 파일이 하나도 없음"
    return days


def test_grid_size_matches_research():
    assert N == GRID_N


@pytest.mark.parity
def test_grid_equals_to_grid(real_days):
    for day, g in real_days:
        mine = build_grid(day)
        assert np.array_equal(mine.px, g["px"], equal_nan=True), day.code
        assert np.allclose(mine.vol, g["vol"]) and np.allclose(mine.cnt, g["cnt"]), day.code


@pytest.mark.parity
@pytest.mark.parametrize("w_min", WINDOWS)
def test_p5_breakout_equals_detect_breakouts(real_days, w_min):
    total = 0
    for day, g in real_days:
        expected = detect_breakouts(g["px"], w_min, 300)
        got = apply_cooldown(np.flatnonzero(breakout_hits(build_grid(day), w_min)), 300)
        assert np.array_equal(got, expected), f"{day.code} {day.date} w={w_min}: {got[:5]} vs {expected[:5]}"
        # 공개 함수(전 조건 AND·시간 범위·쿨다운·진입 체결)도 같은 신호를 내야 한다 — 뒤에 체결이 없는 신호만 빠짐
        ev = detect_signals(day, breakout_min=w_min, time_from="09:00:00", time_to="15:30:00", cooldown_sec=300)
        has_later = np.searchsorted(day.sec, expected, side="right") < len(day.sec)
        assert np.array_equal(ev.signal_sec, expected[has_later])
        assert (ev.entry_sec > ev.signal_sec).all()
        total += len(expected)
    assert total > 0, "20개 파일에서 돌파가 한 건도 없으면 대조가 의미 없다"


@pytest.mark.parity
@pytest.mark.parametrize("w_min,key", [(1, "v1m"), (3, "v3m"), (5, "v5m"), (10, "v10m")])
def test_value_speed_and_buy_ratio_match_research_features_shifted_by_one_second(real_days, w_min, key):
    s = np.arange(700, N - 2, 137)
    for day, g in real_days:
        feats = compute_features(g, s + 1)  # 연구 창은 [t0−1−w, t0−1) = 여기 s=t0−1 의 [s−w, s)
        grid = build_grid(day)
        np.testing.assert_allclose(value_speed_series(grid, w_min)[s], feats[f"{key}_value_surge"],
                                   rtol=1e-9, equal_nan=True, err_msg=f"{day.code} value_speed")
        np.testing.assert_allclose(buy_ratio_series(grid, w_min)[s], feats[f"{key}_buy_ratio"],
                                   rtol=1e-9, equal_nan=True, err_msg=f"{day.code} buy_ratio")
