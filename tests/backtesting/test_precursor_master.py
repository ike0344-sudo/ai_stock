"""상승전조 마스터 — T0 탐지·라벨 검증.

사전등록: docs/PRECURSOR_MASTER_PREREGISTRATION.md
막을 것: (1) 창에 t 자신이 섞이는 것 (2) 진입가를 T0 체결가로 쓰는 낙관 편향
(3) 장 마감 넘어간 라벨 (4) 쿨다운 미작동으로 같은 신호가 수십 번 세어지는 것
"""
import numpy as np
import pandas as pd
import pytest

from backtesting.precursor_master import (
    COOLDOWN_SEC, detect_breakouts, is_gap_open, mfe_mae, passes_daily_filter)
from _precursor_fastpath import N


def test_breakout_window_excludes_current_second():
    """창이 `[t-w, t)`여야 한다 — t를 포함하면 자기 가격을 못 넘어 신호가 0이 된다."""
    px = np.full(N, 100.0)
    px[400:] = 101.0                       # t=400에서 상승

    hits = detect_breakouts(px, window_min=1)

    assert 400 in hits, "직전 60초 고점(100)을 넘었으므로 신호여야 한다"


def test_breakout_needs_strict_high():
    """같은 값으로는 돌파가 아니다."""
    px = np.full(N, 100.0)

    assert len(detect_breakouts(px, window_min=1)) == 0


def test_cooldown_collapses_burst_into_one_signal():
    """계속 오르면 매 초가 신고가다 — 쿨다운이 없으면 한 흐름이 수백 신호로 센다."""
    px = np.full(N, 100.0)
    px[400:500] = np.linspace(101, 120, 100)   # 100초 연속 상승
    px[500:] = 120.0

    hits = detect_breakouts(px, window_min=1, cooldown=COOLDOWN_SEC)

    assert len(hits) == 1, f"연속 상승 한 흐름은 신호 1건이어야 하는데 {len(hits)}건"


def test_cooldown_allows_new_signal_after_gap():
    px = np.full(N, 100.0)
    px[400] = 110.0
    px[400 + COOLDOWN_SEC + 10] = 120.0        # 쿨다운 지난 뒤 새 돌파

    hits = detect_breakouts(px, window_min=1, cooldown=COOLDOWN_SEC)

    assert len(hits) == 2


def test_entry_price_is_after_t0_not_at_t0():
    """**진입가는 T0 다음 체결가.** T0 체결가로 사면 살 수 없는 가격에 산 셈이 된다."""
    sec = np.array([100, 101, 102, 400])
    prc = np.array([1000.0, 1010.0, 1020.0, 1100.0])

    r = mfe_mae(sec, prc, t0=100, horizons_min=(1,))

    assert r["entry_price"] == 1010.0, "T0(100초)의 체결가 1000으로 진입하면 안 된다"
    assert r["entry_sec"] == 101


def test_mfe_and_mae_measured_on_ticks():
    sec = np.array([100, 110, 120, 130])
    prc = np.array([1000.0, 1000.0, 1100.0, 900.0])     # +10% 찍고 -10%

    r = mfe_mae(sec, prc, t0=100, horizons_min=(1,))

    assert r["entry_price"] == 1000.0
    assert r["mfe_1m"] == pytest.approx(0.10)
    assert r["mae_1m"] == pytest.approx(-0.10)


def test_no_label_when_horizon_runs_past_session_end():
    """장 마감까지 못 채우는 horizon은 NaN — 강제청산 값을 섞으면 정의가 달라진다."""
    sec = np.array([N - 100, N - 50])
    prc = np.array([1000.0, 1010.0])

    r = mfe_mae(sec, prc, t0=N - 100, horizons_min=(1, 60))

    assert np.isfinite(r["mfe_1m"])
    assert np.isnan(r["mfe_60m"]) and np.isnan(r["mae_60m"])


def test_gap_open_excluded():
    """[회귀] 갭시작을 안 빼면 누적대금 0이라 저대금 필터를 자동 통과해 결과가 부풀려진다."""
    assert is_gap_open(np.array([1060.0]), prev_close=1000.0) is True
    assert is_gap_open(np.array([1040.0]), prev_close=1000.0) is False


def test_daily_filter_uses_previous_day_only():
    """MA는 shift(1) — 당일 종가가 섞이면 미래참조다."""
    idx = pd.to_datetime(["2026-01-01", "2026-01-02"])
    ma = pd.DataFrame({"ma5": [np.nan, 3.0], "ma10": [np.nan, 2.0], "ma20": [np.nan, 1.0]}, index=idx)

    assert passes_daily_filter(ma, idx[0]) is None        # 전일 정보가 없으면 판정 불가
    assert passes_daily_filter(ma, idx[1]) is True


# ---------------------------------------------------------------- 피처 미래참조 차단

def _grid(prices, qty=10):
    """가격 배열(초 단위) → to_grid 와 같은 형태의 dict."""
    from _precursor_fastpath import N as _N
    px = np.full(_N, float(prices[-1]))
    px[:len(prices)] = prices
    sec = np.arange(len(prices))
    prc = np.asarray(prices, dtype=float)
    q = np.full(len(prices), float(qty))
    return dict(px=px, vol=np.bincount(sec, weights=q, minlength=_N),
                cnt=np.bincount(sec, minlength=_N).astype(float),
                tick_sec=sec, tick_prc=prc, tick_qty=q)


def test_features_do_not_change_when_future_is_mutated():
    """**핵심.** T0 이후를 통째로 바꿔도 T0 피처가 하나도 안 변해야 한다."""
    from backtesting.precursor_master_features import compute_features

    base = [1000 + (i % 7) for i in range(2000)]
    mut = list(base)
    for i in range(1000, 2000):
        mut[i] = 99999

    t0 = np.array([900])
    a = compute_features(_grid(base), t0)
    b = compute_features(_grid(mut), t0)

    changed = [k for k in a
               if isinstance(a[k][0], (int, float, np.floating, np.integer))
               and not (np.isnan(float(a[k][0])) and np.isnan(float(b[k][0])))
               and float(a[k][0]) != pytest.approx(float(b[k][0]), nan_ok=True)]
    assert not changed, f"미래 변조에 영향받은 피처: {changed}"


def test_features_do_not_see_the_t0_tick_itself():
    """T0는 '돌파한 틱'이라 그 체결이 피처에 섞이면 특히 위험하다."""
    from backtesting.precursor_master_features import compute_features

    a = [1000] * 1000
    b = list(a)
    b[900] = 5000                                  # T0 그 순간의 체결만 바꾼다

    t0 = np.array([900])
    fa = compute_features(_grid(a), t0)
    fb = compute_features(_grid(b), t0)

    for k in fa:
        x, y = fa[k][0], fb[k][0]
        if not isinstance(x, (int, float, np.floating, np.integer)):
            continue
        if np.isnan(float(x)) and np.isnan(float(y)):
            continue
        assert float(x) == pytest.approx(float(y), nan_ok=True), f"{k}가 T0 체결을 봤다"


def test_mutation_does_change_features_at_later_t0():
    """음성 대조 — 전부 안 변하면 테스트가 아무것도 검증하지 못한 것이다."""
    from backtesting.precursor_master_features import compute_features

    a = [1000] * 2000
    b = list(a)
    for i in range(1000, 2000):
        b[i] = 5000

    t0 = np.array([1500])                          # 변조 구간 **안쪽** T0
    fa = compute_features(_grid(a), t0)
    fb = compute_features(_grid(b), t0)

    diff = [k for k in fa
            if isinstance(fa[k][0], (int, float, np.floating, np.integer))
            and not (np.isnan(float(fa[k][0])) and np.isnan(float(fb[k][0])))
            and float(fa[k][0]) != pytest.approx(float(fb[k][0]), nan_ok=True)]
    assert diff, "변조가 이후 T0 피처에도 안 잡혔다 — 테스트가 무의미하다"
