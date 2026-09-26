"""분류 "가격·이평·신고가" 지표 — 손계산 기대값. (공통 카나리아·등록 검사는 test_ind_common.py)"""
import numpy as np
import pytest

from studio.domain.conditions.ind_trend import limit_up_price
from tests.studio.conditions.helpers import intraday_panel
from tests.studio.conditions.ind_helpers import mk, nan_eq, val

nan = np.nan


def test_wma_weights_recent_bars_most():
    # n=3, 가중 1·2·3: t2 = (1·1+2·2+3·3)/6 = 14/6, t3 = (2+4·... ) 아래 손계산
    got = val(mk([1, 2, 3, 4, 5]), "wma", n=3)
    nan_eq(got, [nan, nan, 14 / 6, (1 * 2 + 2 * 3 + 3 * 4) / 6, (1 * 3 + 2 * 4 + 3 * 5) / 6])


def test_vwma_is_volume_weighted_and_nan_when_window_has_no_volume():
    got = val(mk([10, 20, 30], v=[1, 1, 2]), "vwma", n=2)
    nan_eq(got, [nan, (10 * 1 + 20 * 1) / 2, (20 * 1 + 30 * 2) / 3])
    nan_eq(val(mk([10, 20, 30], v=[0, 0, 5]), "vwma", n=2), [nan, nan, 30.0])   # [0,0] 창은 NaN


def test_ma_disparity_sma_and_ema():
    nan_eq(val(mk([10, 10, 10, 20]), "ma_disparity", n=3, ma="sma"), [nan, nan, 100.0, 20 / (40 / 3) * 100])
    # EMA(2): α=2/3, y1 = (1/3)·10 + (2/3)·20 = 50/3 → 20 ÷ (50/3) × 100 = 120
    nan_eq(val(mk([10, 20]), "ma_disparity", n=2, ma="ema"), [nan, 120.0])


def test_ma_slope():
    got = val(mk([1, 2, 3, 4, 5, 6]), "ma_slope", n=3, k=2)     # SMA3 = nan,nan,2,3,4,5
    nan_eq(got, [nan, nan, nan, nan, (4 / 2 - 1) * 100, (5 / 3 - 1) * 100])


def test_ma_aligned_and_reversed():
    up, down = mk(np.arange(1, 11)), mk(np.arange(10, 0, -1))
    nan_eq(val(up, "ma_aligned", n1=2, n2=3, n3=4)[:5], [nan, nan, nan, 1, 1])      # SMA4 가 생기는 t=3 부터
    nan_eq(val(up, "ma_reversed", n1=2, n2=3, n3=4)[3:5], [0, 0])
    nan_eq(val(down, "ma_aligned", n1=2, n2=3, n3=4)[3:5], [0, 0])
    nan_eq(val(down, "ma_reversed", n1=2, n2=3, n3=4)[3:5], [1, 1])
    # 같으면 정배열 아님(엄격): 5,5,5,5 → SMA 전부 같음 / 마지막 9 로 오르면 SMA2=7 > SMA3=6.33 > SMA4=6
    m = mk([5, 5, 5, 5, 9])
    nan_eq(val(m, "ma_aligned", n1=2, n2=3, n3=4)[3:], [0, 1])


def test_ma_aligned_four_lines_and_order_check():
    up = mk(np.arange(1, 11))
    nan_eq(val(up, "ma_aligned", n1=1, n2=2, n3=3, n4=4)[3:6], [1, 1, 1])
    with pytest.raises(ValueError, match="n1 < n2"):
        val(up, "ma_aligned", n1=20, n2=5, n3=60)


def test_new_high_excludes_today_and_src_choice():
    h, c = [10, 11, 12, 11, 13], [10, 11, 11.5, 10, 13.5]
    nan_eq(val(mk(c, h=h), "new_high", n=2, src="high"), [nan, nan, 1, 0, 1])   # 기준선 = 직전 2봉 고가 최대
    nan_eq(val(mk(c, h=h), "new_high", n=2, src="close"), [nan, nan, 1, 0, 1])  # 11.5>11, 10>12 아님, 13.5>12
    nan_eq(val(mk([10, 11, 11.5, 12.5, 13], h=h), "new_high", n=2, src="close"), [nan, nan, 1, 1, 1])


def test_new_low_excludes_today():
    nan_eq(val(mk([10, 9, 8, 9, 7], l=[10, 9, 8, 9, 7]), "new_low", n=2), [nan, nan, 1, 0, 1])


def test_high52_and_low52_include_today():
    nan_eq(val(mk([10, 11, 10, 9], h=[10, 12, 11, 10]), "high52_pct", n=3),
           [nan, nan, (10 / 12 - 1) * 100, (9 / 12 - 1) * 100])
    nan_eq(val(mk([10, 11, 12], h=[10, 11, 12]), "high52_pct", n=3)[2:], [0.0])     # 신고가 종가 = 0
    nan_eq(val(mk([10, 9, 12], l=[10, 8, 9]), "low52_pct", n=3)[2:], [(12 / 8 - 1) * 100])


def test_bars_since_high():
    nan_eq(val(mk([1, 5, 3, 4, 2], h=[1, 5, 3, 4, 2]), "bars_since_high", n=3), [nan, nan, 1, 2, 1])
    nan_eq(val(mk([5, 5, 5], h=[5, 5, 5]), "bars_since_high", n=3)[2:], [0])        # 같은 값이면 가장 최근


def test_box_pct():
    nan_eq(val(mk([10, 10, 10], h=[10, 12, 11], l=[9, 8, 10]), "box_pct", n=3)[2:], [(12 - 8) / 8 * 100])


def test_streaks_reset_on_flat():
    c = [1, 2, 3, 3, 2, 1, 2]
    nan_eq(val(mk(c), "up_streak"), [nan, 1, 2, 0, 0, 0, 1])
    nan_eq(val(mk(c), "down_streak"), [nan, 0, 0, 0, 1, 2, 0])


def test_limit_up_price_truncates_to_tick_not_rounds():
    import pandas as pd
    prev = pd.DataFrame({"A": [10000, 13750, 1000, 5000, 50000, 15350, 16000, 15400, 1540, nan]})
    got = limit_up_price(prev)["A"].to_numpy()
    nan_eq(got, [13000, 17870, 1300, 6500, 65000, 19950, 20800, 20000, 2000, nan])
    # 13,750×1.3 = 17,875 → 호가 10원 → 반올림이면 17,880(130% 초과) 이지만 절사라 17,870


def test_limit_up_pct_and_hit():
    p = mk([12000, 12000], h=[12000, 13000], prev=[10000, 10000])
    nan_eq(val(p, "limit_up_pct"), [(13000 - 12000) / 12000 * 100] * 2)
    nan_eq(val(p, "limit_up_hit"), [0, 1])
    nan_eq(val(mk([12000], h=[12999], prev=[10000]), "limit_up_hit"), [0])
    nan_eq(val(mk([12000], h=[12000], prev=[nan]), "limit_up_hit"), [nan])          # 전일 종가 없으면 판정 불가


def test_prev_high_break_daily():
    nan_eq(val(mk([9, 13, 11.5], h=[10, 12, 11]), "prev_high_break"), [nan, 1, 0])   # 13>10, 11.5>12 아님


def test_prev_high_break_intraday_uses_previous_days_highest_bar():
    pm = intraday_panel(n_days=4, bars=6, n_codes=2, seed=4)
    from studio.domain.conditions.indicators import compute
    got = compute(pm, "prev_high_break")
    days = pm.close.index.normalize()
    dh = pm.high.groupby(days).max()
    for j in (1, 2, 3):
        rows = np.flatnonzero(days == dh.index[j])
        want = (pm.close.iloc[rows] > dh.iloc[j - 1]).astype(float)
        np.testing.assert_array_equal(got.iloc[rows].to_numpy(), want.to_numpy())
    assert got.iloc[:6].isna().all().all()                                            # 첫날은 직전 날짜 없음
