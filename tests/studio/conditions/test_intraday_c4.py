"""분봉 전용 지표 추가분(c4) — 손계산 + 미래참조 카나리아(같은 날 뒤 봉·다음 날 변조)."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from studio.domain.conditions import indicators as I
from studio.domain.conditions.ast import Group
from studio.domain.conditions.catalog import INDICATORS
from studio.domain.conditions.evaluator import evaluate_group
from studio.domain.conditions.intraday import INTRADAY_ONLY
from tests.studio.conditions.helpers import cond, const, group, ind, intraday_panel, skew_after, tamper_after

NEW = ("open_change_pct", "day_high_break", "day_low_break", "minutes_since_open", "first_n_value", "vwap_disparity", "cum_value_rank")


def _panel(o, h, l, c, v, codes=("a",), start_label=False):
    """2일 × 4봉(5분). 인자는 (8행 × 종목수) 배열 목록. value = 종가×거래량."""
    days = pd.bdate_range("2026-08-03", periods=2)
    mins = [0, 5, 10, 15] if start_label else [5, 10, 15, 20]
    idx = pd.DatetimeIndex([d + pd.Timedelta(hours=9, minutes=m) for d in days for m in mins])
    f = {n: pd.DataFrame(np.array(a, dtype=float).reshape(8, -1), index=idx, columns=list(codes))
         for n, a in dict(open=o, high=h, low=l, close=c, volume=v).items()}
    ns = SimpleNamespace(**f, value=f["close"] * f["volume"], prev_close=f["close"] * 0 + 100.0)
    if start_label:
        ns.bar_end_offset_minutes = 5
    return ns


def col(df, k=0):
    return df.iloc[:, k].tolist()


def test_new_names_are_registered_intraday_only():
    assert set(NEW) <= set(INTRADAY_ONLY)
    for n in NEW:
        assert INDICATORS[n].category == "intraday" and INDICATORS[n].modes == ("intraday",)


def test_open_change_pct_hand_calc_and_first_bar_missing():
    o = [100, 101, 102, 99, 200, 205, 210, 190]
    c = [101, 102, 99, 100, 200, 210, 189, 200]
    pn = _panel(o, o, o, c, [1] * 8)
    assert col(I.compute(pn, "open_change_pct")) == pytest.approx([1, 2, -1, 0, 0, 5, -5.5, 0])  # 그 날 첫 봉 시가 기준
    # 첫 봉이 비면(체결 없음) 그 날 시가는 첫 체결 봉의 시가 — 그 이전 행엔 값 없음(미래 시가 안 샘)
    pn2 = _panel(o, o, o, c, [1] * 8)
    for f in ("open", "high", "low", "close", "volume", "value"):
        getattr(pn2, f).iloc[0, 0] = np.nan
    r = col(I.compute(pn2, "open_change_pct"))
    assert np.isnan(r[0]) and r[1] == pytest.approx((102 / 101 - 1) * 100)


def test_day_high_break_and_low_break_hand_calc():
    h = [10, 12, 11, 15, 10, 9, 20, 8]
    l = [8, 9, 7, 10, 5, 4, 6, 3]
    c = [9, 13, 6, 16, 4, 3, 21, 2]
    pn = _panel(c, h, l, c, [1] * 8)
    hi = col(I.compute(pn, "day_high_break", {"src": "close"}))
    assert np.isnan(hi[0]) and hi[1:4] == [1.0, 0.0, 1.0]        # 13>10 · 6>12? · 16>12
    assert np.isnan(hi[4]) and hi[5:] == [0.0, 1.0, 0.0]        # 둘째 날은 다시 시작: 3>10? · 21>10 · 2>20?
    lo = col(I.compute(pn, "day_low_break", {"src": "close"}))
    assert np.isnan(lo[0]) and lo[1:4] == [0.0, 1.0, 0.0]        # 13<8? · 6<8 · 16<7?
    hi_h = col(I.compute(pn, "day_high_break", {"src": "high"}))
    assert hi_h[1:4] == [1.0, 0.0, 1.0]                          # 고가 12>10 · 11>12? · 15>12
    lo_l = col(I.compute(pn, "day_low_break", {"src": "low"}))
    assert lo_l[1:4] == [0.0, 1.0, 0.0]                          # 저가 9<8? · 7<8 · 10<7?


def test_day_break_skips_missing_bar_but_keeps_earlier_extreme():
    h = [10, 50, 11, 15, 1, 1, 1, 1]
    c = [9, 40, 30, 16, 1, 1, 1, 1]
    pn = _panel(c, h, c, c, [1] * 8)
    for f in ("open", "high", "low", "close", "volume", "value"):
        getattr(pn, f).iloc[2, 0] = np.nan  # 3번째 봉 체결 없음
    hi = col(I.compute(pn, "day_high_break", {"src": "close"}))
    assert np.isnan(hi[2]) and hi[3] == 0.0  # 16 > 50(빠진 봉 앞 최고) 아님


def test_minutes_since_open_end_label_and_start_label_offset():
    pn = _panel([1] * 8, [1] * 8, [1] * 8, [1] * 8, [1] * 8)
    assert col(I.compute(pn, "minutes_since_open"))[:4] == [5, 10, 15, 20]
    ps = _panel([1] * 8, [1] * 8, [1] * 8, [1] * 8, [1] * 8, start_label=True)  # 09:00 시작 라벨 + 5분 봉 → 끝 = 09:05
    assert col(I.compute(ps, "minutes_since_open"))[:4] == [5, 10, 15, 20]


def test_first_n_value_hand_calc_fixed_after_n_and_bar_alignment():
    v = [1, 2, 4, 8, 1, 2, 4, 8]  # 종가 1 → 대금 = 거래량
    pn = _panel([1] * 8, [1] * 8, [1] * 8, [1] * 8, v)
    r = col(I.compute(pn, "first_n_value", {"n": 10}))
    assert np.isnan(r[0]) and r[1:4] == [3.0, 3.0, 3.0]          # 09:10 에 (1+2) 확정, 이후 그 날 내내 같은 값
    assert np.isnan(r[4]) and r[5:] == [3.0, 3.0, 3.0]           # 둘째 날은 다시 시작
    assert col(I.compute(pn, "first_n_value", {"n": 20}))[3] == 15.0
    with pytest.raises(ValueError, match="배수"):
        I.compute(pn, "first_n_value", {"n": 7})  # 5분 봉에 7분 창 — 봉 경계에 안 맞음


def test_vwap_disparity_hand_calc():
    c = [100, 110, 100, 100, 50, 50, 50, 50]
    pn = _panel(c, c, c, c, [1] * 8)
    r = col(I.compute(pn, "vwap_disparity"))
    assert r[0] == pytest.approx(0) and r[1] == pytest.approx((110 / 105 - 1) * 100)  # VWAP=(100+110)/2
    assert r[4] == pytest.approx(0)  # 둘째 날 VWAP 다시 시작


def test_cum_value_rank_hand_calc_resets_daily():
    # 두 종목. a 대금 [1,1,1,1 | 9,1,1,1], b [2,0,0,3 | 1,1,1,1] (종가 1, value=거래량)
    v = np.array([[1, 2], [1, 0], [1, 0], [1, 3], [9, 1], [1, 1], [1, 1], [1, 1]], dtype=float)
    pn = _panel(np.ones((8, 2)), np.ones((8, 2)), np.ones((8, 2)), np.ones((8, 2)), v, codes=("a", "b"))
    r = I.compute(pn, "cum_value_rank")
    # 누적: a 1,2,3,4 / b 2,2,2,5 → 순위 a: 2,1(2=2 동률→1),1(3>2),2(4<5)
    assert col(r, 0)[:4] == [2.0, 1.0, 1.0, 2.0] and col(r, 1)[:4] == [1.0, 1.0, 2.0, 1.0]
    assert col(r, 0)[4] == 1.0  # 둘째 날 첫 봉 a 9 > b 1


def test_dispatch_rejects_daily_table():
    from tests.studio.conditions.helpers import synth_panel
    with pytest.raises(ValueError, match="분봉 전용"):
        I.compute(synth_panel(n_days=20, n_codes=2), "open_change_pct")


def test_usable_in_evaluator_on_minute_panel():
    c = [9, 13, 6, 16, 4, 3, 21, 2]
    h = [10, 12, 11, 15, 10, 9, 20, 8]
    pn = _panel(c, h, c, c, [1] * 8)
    g = Group.model_validate(group("all", cond(ind("day_high_break", src="close"), "gt", const(0.5))))
    assert col(evaluate_group(g, pn)) == [False, True, False, True, False, False, True, False]


@pytest.mark.parametrize("name,params", [
    ("open_change_pct", {}), ("day_high_break", {"src": "close"}), ("day_high_break", {"src": "high"}),
    ("day_low_break", {"src": "close"}), ("day_low_break", {"src": "low"}), ("minutes_since_open", {}),
    ("first_n_value", {"n": 10}), ("first_n_value", {"n": 30}), ("vwap_disparity", {}), ("cum_value_rank", {}),
])
@pytest.mark.parametrize("tamper", [tamper_after, skew_after])
def test_canary_no_lookahead_same_day_and_next_days(name, params, tamper):
    """t(둘째 날 한가운데) 이후 봉 — 같은 날 뒤 봉·다음 날 전부 — 을 변조해도 t 이하 값은 그대로."""
    pn = intraday_panel(n_days=5, bars=12, n_codes=4, seed=11)
    t = pn.close.index[12 + 5]
    a = I.compute(pn, name, params)
    b = I.compute(tamper(pn, t), name, params)
    pd.testing.assert_frame_equal(a.loc[:t], b.loc[:t])
    assert not a.loc[t:].iloc[1:].fillna(-9).equals(b.loc[t:].iloc[1:].fillna(-9)) or name == "minutes_since_open"  # 카나리아 생존


def test_canary_with_missing_bars():
    pn = intraday_panel(n_days=4, bars=12, n_codes=3, seed=2, missing=[(1, 0), (13, 1), (14, 1), (20, 2)])
    t = pn.close.index[25]
    for name, params in [("open_change_pct", {}), ("day_high_break", {}), ("first_n_value", {"n": 10}), ("cum_value_rank", {})]:
        a, b = I.compute(pn, name, params), I.compute(tamper_after(pn, t), name, params)
        pd.testing.assert_frame_equal(a.loc[:t], b.loc[:t])
