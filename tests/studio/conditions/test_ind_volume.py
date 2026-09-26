"""거래량·순위 지표(c4) — 손계산 + 미래참조 카나리아 + 빈칸 종목 순위 회귀."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from studio.domain.conditions import indicators as I
from studio.domain.conditions.catalog import CROSS_SECTIONAL, INDICATORS
from studio.domain.conditions.ind_volume import top_value_count, value_ratio, vol_change_pct
from tests.studio.conditions.helpers import skew_after, synth_panel

IDX = pd.bdate_range("2026-08-03", periods=4)


def _p(**cols) -> SimpleNamespace:
    """열 이름 → 4일 값. close·volume 을 주면 value 도 그것으로(없으면 value 를 직접)."""
    return SimpleNamespace(**{k: pd.DataFrame(v, index=IDX) if isinstance(v, dict) else v for k, v in cols.items()})


def test_vol_change_pct_hand_calc_and_zero_prev():
    v = pd.DataFrame({"a": [100.0, 200.0, 0.0, 50.0]}, index=IDX)
    r = vol_change_pct(v)["a"].tolist()
    assert np.isnan(r[0]) and r[1] == 200.0 and r[2] == 0.0 and np.isnan(r[3])  # 직전 0 → 값 없음


def test_value_ratio_hand_calc_excludes_today():
    v = pd.DataFrame({"a": [10.0, 20.0, 30.0, 60.0]}, index=IDX)
    r = value_ratio(v, 2)["a"].tolist()
    assert np.isnan(r[0]) and np.isnan(r[1]) and r[2] == 30 / 15 and r[3] == 60 / 25  # 평균은 오늘 제외


def test_top_value_count_hand_calc():
    # 4일 × 3종목 대금. 순위(1=최대): d0 a>b>c, d1 b>a>c, d2 b>c>a, d3 c>b>a
    v = pd.DataFrame({"a": [9, 8, 1, 1], "b": [5, 9, 9, 5], "c": [1, 1, 5, 9]}, index=IDX, dtype=float)
    r = top_value_count(v, n=3, m=2)  # 상위 2 안 = d0 a,b · d1 a,b · d2 b,c · d3 b,c
    assert r["a"].isna().tolist() == [True, True, False, False]  # 창(3일)이 차야 값
    assert r["a"].tolist()[2:] == [2.0, 1.0]   # d0..d2 = 1,1,0 → 2 ; d1..d3 = 1,0,0 → 1
    assert r["b"].tolist()[2:] == [3.0, 3.0]
    assert r["c"].tolist()[2:] == [1.0, 2.0]


def test_top_value_count_ties_share_rank_and_nan_not_counted():
    v = pd.DataFrame({"a": [5.0, 5.0], "b": [5.0, np.nan], "c": [1.0, 1.0]}, index=IDX[:2])
    r = top_value_count(v, n=1, m=1)  # 동률은 같은 1위 → 둘 다 진입, NaN 은 안 셈
    assert r.iloc[0].to_dict() == {"a": 1.0, "b": 1.0, "c": 0.0} and r.iloc[1].to_dict() == {"a": 1.0, "b": 0.0, "c": 0.0}


def test_registered_and_cross_sectional():
    assert {"volume_rank", "top_value_count"} <= CROSS_SECTIONAL
    assert {"vol_change_pct", "value_ratio"}.isdisjoint(CROSS_SECTIONAL)
    for n in ("vol_change_pct", "value_ratio", "volume_rank", "top_value_count"):
        assert INDICATORS[n].category == "volume" and INDICATORS[n].volume_based


def _gappy():
    pn = synth_panel(n_days=40, n_codes=5, seed=3)
    for f in ("open", "high", "low", "close", "volume", "value", "prev_close"):
        getattr(pn, f).iloc[10:13, 2] = np.nan  # 종목 2 는 거래정지 3일 — 활동 구간 안 빈칸
    return pn


def test_volume_rank_gap_column_ranks_among_all_not_alone():
    pn = _gappy()
    got = I.compute(pn, "volume_rank", {"lookback": 1})
    want = pn.volume.rank(axis=1, ascending=False, method="min")
    pd.testing.assert_frame_equal(got, want)  # own_days 로 1열 Panel 에서 재계산되면 빈칸 종목이 전부 1위가 돼 여기서 깨진다
    assert got.iloc[:, 2].dropna().max() > 1


def test_top_value_count_via_compute_matches_direct_with_gap():
    pn = _gappy()
    got = I.compute(pn, "top_value_count", {"n": 5, "m": 2})
    pd.testing.assert_frame_equal(got, top_value_count(pn.value, 5, 2))


@pytest.mark.parametrize("name,params", [
    ("vol_change_pct", {}), ("value_ratio", {"n": 5}), ("volume_rank", {"lookback": 3}), ("top_value_count", {"n": 5, "m": 3}),
])
def test_canary_no_lookahead(name, params):
    """t 이후 값을 10배로 바꿔도 t 이하 지표 값은 그대로(미래참조 없음)."""
    pn = synth_panel(n_days=60, n_codes=6, seed=7)
    t = pn.close.index[30]
    a = I.compute(pn, name, params)
    b = I.compute(skew_after(pn, t), name, params)
    pd.testing.assert_frame_equal(a.loc[:t], b.loc[:t])
    assert not a.loc[t:].iloc[1:].equals(b.loc[t:].iloc[1:])  # 변조가 실제로 뒤 값에는 닿았는지(카나리아 자체가 살아 있는지)


# ------------------------------------------------------------------ daily_live (C6) — 거래량 계열은 KRX 분봉에서만(validation 이 막음)
from studio.domain.conditions import catalog, timeframe as T  # noqa: E402
from tests.studio.conditions.test_timeframe import make_data, tamper_after as tamper_minute  # noqa: E402

LIVE_VOL = [("vol_change_pct", {}), ("value_ratio", {"n": 5}), ("value_ratio", {"n": 20})]


@pytest.mark.parametrize("halt", [None, "B"])
@pytest.mark.parametrize("name,params", LIVE_VOL)
def test_daily_live_equals_recompute_with_virtual_bar(name, params, halt):
    daily, minute = make_data(halt_col=halt)
    assert T.check_live_equals_recompute(name, params, daily, minute, sample=25) < 1e-6


@pytest.mark.parametrize("name,params", LIVE_VOL)
def test_daily_live_canary_bars_after_t_do_not_change_values_up_to_t(name, params):
    daily, minute = make_data()
    pp = catalog.resolve_params(name, params)
    t = minute.close.index[len(minute.close) // 2]
    base = catalog.LIVE_REGISTRY[name](T.make_live_bars(minute, daily), pp)
    bad = catalog.LIVE_REGISTRY[name](T.make_live_bars(tamper_minute(minute, t), daily), pp)
    pd.testing.assert_frame_equal(base.loc[:t], bad.loc[:t])
    assert not base.loc[t:].iloc[1:].equals(bad.loc[t:].iloc[1:])


def test_live_volume_indicators_are_volume_based_and_others_have_no_live():
    for n in ("vol_change_pct", "value_ratio"):
        assert INDICATORS[n].live and INDICATORS[n].volume_based
    for n in ("volume_rank", "top_value_count"):
        assert not INDICATORS[n].live
