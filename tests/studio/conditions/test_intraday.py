"""분봉 지표(day_change_pct·time·cum_value·vwap·gap_pct) + 일봉 D−1 사전 필터 + C3 카나리아."""
import numpy as np
import pandas as pd
import pytest

from studio.domain.conditions.ast import Group
from studio.domain.conditions.evaluator import evaluate_group
from studio.domain.conditions.indicators import compute
from studio.domain.conditions.intraday import is_intraday
from studio.domain.conditions.prefilter import (
    daily_prefilter, previous_day_flags, previous_day_values, top_value_prefilter,
)
from tests.studio.conditions.helpers import (
    cond, const, field, group, ind, intraday_panel, panel_from, synth_candles, tamper_after,
)

BARS = 12


@pytest.fixture(scope="module")
def p():
    return intraday_panel(n_days=6, bars=BARS, n_codes=4, seed=1)


def test_is_intraday_detects_repeated_dates(p):
    assert is_intraday(p)
    assert not is_intraday(panel_from(synth_candles(n_days=30, n_codes=2)))


def test_time_is_bar_end_hhmm_and_offset(p):
    t = compute(p, "time")
    assert t.iloc[0].tolist() == [905.0] * 4 and t.iloc[BARS - 1].tolist() == [1000.0] * 4
    assert t.iloc[BARS, 0] == 905.0  # 다음 날 첫 봉
    p2 = intraday_panel(n_days=2, bars=BARS, n_codes=1, seed=1)
    p2.bar_end_offset_minutes = 5    # 로더 라벨이 봉 시작이면 5분 더해 봉 끝으로
    assert compute(p2, "time").iloc[0, 0] == 910.0


def test_cum_value_resets_each_day(p):
    cv = compute(p, "cum_value")
    v = p.value
    assert cv.iloc[0].equals(v.iloc[0])
    assert np.allclose(cv.iloc[BARS - 1], v.iloc[:BARS].sum())          # 첫날 끝 = 그날 합계
    assert cv.iloc[BARS].equals(v.iloc[BARS])                            # 둘째 날 첫 봉 = 그 봉 값(0부터)
    assert np.allclose(cv.iloc[BARS + 3], v.iloc[BARS:BARS + 4].sum())


def test_vwap_is_cumulative_value_over_cumulative_volume_per_day(p):
    w = compute(p, "vwap")
    assert np.allclose(w.iloc[0], p.close.iloc[0])                       # 첫 봉 = 그 봉 종가(value/volume)
    k = BARS + 5
    d = slice(BARS, k + 1)
    assert np.allclose(w.iloc[k], p.value.iloc[d].sum() / p.volume.iloc[d].sum())
    assert np.allclose(w.iloc[BARS], p.close.iloc[BARS])                 # 날이 바뀌면 다시 시작


def test_day_change_pct_uses_previous_day_close(p):
    d = compute(p, "day_change_pct")
    assert d.iloc[:BARS].isna().all().all()                              # 첫날은 전일 종가 없음
    assert np.allclose(d.iloc[BARS + 2], (p.close.iloc[BARS + 2] / p.close.iloc[BARS - 1] - 1) * 100)


def test_gap_pct_intraday_is_day_open_over_prev_close_and_constant_within_day():
    pm = intraday_panel(n_days=3, bars=BARS, n_codes=2, seed=2, missing=[(BARS, 1)])  # 둘째 날 첫 봉이 종목1 만 비어 있음
    g = compute(pm, "gap_pct")
    prev = pm.close.iloc[BARS - 1]
    assert np.allclose(g.iloc[BARS + 4, 0], (pm.open.iloc[BARS, 0] / prev.iloc[0] - 1) * 100)
    # 종목1: 첫 봉이 없으니 그 날 첫 non-null 시가(둘째 봉)가 당일 시가
    assert np.isclose(g.iloc[BARS + 4, 1], (pm.open.iloc[BARS + 1, 1] / prev.iloc[1] - 1) * 100)
    assert g.iloc[BARS + 1, 0] == g.iloc[BARS + 9, 0]                    # 하루 안에서 상수
    assert g.iloc[:BARS].isna().all().all()


def test_intraday_only_indicator_on_daily_panel_raises():
    with pytest.raises(ValueError, match="분봉 전용"):
        compute(panel_from(synth_candles(n_days=30, n_codes=2)), "vwap")


def test_evaluator_uses_intraday_indicators_and_masks_missing_bars():
    pm = intraday_panel(n_days=4, bars=BARS, n_codes=3, seed=3, missing=[(20, 1)])
    g = Group.model_validate(group(
        "all",
        cond(ind("time"), "gte", const(910)),
        cond(ind("time"), "lte", const(950)),
        cond(field("close"), "gt", ind("vwap")),
    ))
    r = evaluate_group(g, pm)
    t, vw = compute(pm, "time"), compute(pm, "vwap")
    want = (t >= 910) & (t <= 950) & (pm.close > vw)
    assert r.equals(want & pm.close.notna())
    assert not r.iloc[20, 1]                                             # 비어 있는 봉은 신호 없음
    assert r.to_numpy().any()


# ---------------------------------------------------------------- 일봉 D−1
def test_previous_day_flags_use_strictly_earlier_daily_row():
    d = pd.to_datetime(["2026-08-03", "2026-08-04", "2026-08-05"])
    flags = pd.DataFrame({"A": [True, False, True]}, index=d)
    bars = pd.DatetimeIndex(["2026-08-03 09:05", "2026-08-04 09:05", "2026-08-05 15:30", "2026-08-06 09:05"])
    out = previous_day_flags(flags, bars, ["A", "Z"])
    assert out["A"].tolist() == [False, True, False, True]   # 08-03=없음, 08-04=08-03 값, 08-05=08-04 값, 08-06(일봉 미갱신)=08-05 값
    assert not out["Z"].any()                                 # 일봉에 없는 종목은 False
    vals = previous_day_values(pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=d), bars, ["A"])
    assert vals["A"].tolist()[1:] == [1.0, 2.0, 3.0] and np.isnan(vals["A"].iloc[0])


def _daily_and_bars(seed=5):
    daily = panel_from(synth_candles(n_days=60, n_codes=4, seed=seed, start="2026-07-01"))
    return daily, intraday_panel(n_days=6, bars=BARS, n_codes=4, seed=seed)


def test_top_value_prefilter_is_previous_day_rank():
    daily, pm = _daily_and_bars()
    f = top_value_prefilter(daily, 2, pm.close.index, list(pm.close.columns))
    rank = compute(daily, "value_rank", {"lookback": 1})
    day = pm.close.index.normalize()[BARS + 3]
    prev = daily.close.index[daily.close.index < day][-1]
    assert f.iloc[BARS + 3].tolist() == (rank.loc[prev] <= 2).tolist()


def _minute_signal(pm, daily):
    g = Group.model_validate(group("all", cond(ind("time"), "gte", const(910)), cond(field("close"), "gt", ind("vwap"))))
    dg = Group.model_validate(group("all", cond(field("close"), "gt", ind("sma", src="close", n=5))))
    codes, idx = list(pm.close.columns), pm.close.index
    pre = daily_prefilter(dg, daily, idx, codes) & top_value_prefilter(daily, 3, idx, codes)
    return evaluate_group(g, pm) & pre, pre


@pytest.mark.parametrize("k", [BARS * 3 + 4, BARS * 4 + 8])  # 3·4번째 날 — 앞선 날이 충분해야 카나리아가 빈손이 아님
def test_c3_future_minute_bars_and_same_day_daily_do_not_change_past_signals(k):
    daily, pm = _daily_and_bars()
    t = pm.close.index[k]
    base, pre = _minute_signal(pm, daily)
    day = t.normalize()
    pm2 = tamper_after(pm, t)                                   # 분봉 k 이후 변조
    daily2 = tamper_after(daily, day - pd.Timedelta(days=1))    # 당일(D) 이후 일봉 행 전부 변조
    fut, _ = _minute_signal(pm2, daily2)
    pd.testing.assert_frame_equal(base.iloc[: k + 1], fut.iloc[: k + 1])
    assert pre.iloc[: k + 1].to_numpy().any() and base.iloc[: k + 1].to_numpy().any()  # 카나리아가 빈손이 아니게


def _kospi(n=10, tamper_from=None):
    """지수 일봉(×100 저장): 2026-08-03 부터 영업일, 실제 포인트 = 3000 + 10·i."""
    idx = pd.bdate_range("2026-08-03", periods=n)
    raw = 300000.0 + 1000.0 * np.arange(n)
    if tamper_from is not None:
        raw[idx >= tamper_from] *= 10
    return {"kospi": pd.DataFrame({"close": raw}, index=idx)}


def _mk(name, **params):
    return {"kind": "market", "index": "kospi", "name": name, **({"params": params} if params else {})}


def test_market_operand_on_intraday_panel_uses_previous_day_index():
    pm = intraday_panel(n_days=6, bars=BARS, n_codes=2, seed=7)
    day_no = np.repeat(np.arange(6), BARS)                       # 각 봉이 속한 날 0..5
    g = Group.model_validate(group("all", cond(_mk("close"), "gt", const(3025))))
    r = evaluate_group(g, pm, market=_kospi())
    # 날 j 의 봉에는 j−1 번째 날 지수(3000+10(j−1))가 붙는다 → 3025 초과는 j−1 ≥ 3, 즉 j ≥ 4
    assert (r.iloc[:, 0].to_numpy() == (day_no >= 4)).all() and (r.iloc[:, 1].to_numpy() == (day_no >= 4)).all()
    # 첫날은 이전 지수가 없어 조건 거짓(조용히 0건이 아니라 값이 붙는 날은 정확히 그 이후)
    assert not r.iloc[:BARS].to_numpy().any()
    sma = evaluate_group(Group.model_validate(group("all", cond(_mk("close"), "gt", _mk("sma", n=3)))), pm, market=_kospi())
    assert (sma.iloc[:, 0].to_numpy() == (day_no >= 3)).all()    # 지수 3일 평균은 자기 거래일 3개가 차야 값이 있음(행 i ≥ 2) → D−1 = 행 j−1 ≥ 2 ⇔ j ≥ 3
    chg = evaluate_group(Group.model_validate(group("all", cond(_mk("change_pct"), "gt", const(0)))), pm, market=_kospi())
    assert (chg.iloc[:, 0].to_numpy() == (day_no >= 2)).all()    # D−1 의 전일 대비 등락률은 D−2 가 있어야 값이 생김(j−1 ≥ 1)


@pytest.mark.parametrize("k", [BARS * 3 + 4, BARS * 4 + 8])
def test_c3_future_index_rows_from_day_d_do_not_change_signals_up_to_k(k):
    pm = intraday_panel(n_days=6, bars=BARS, n_codes=3, seed=8)
    day = pm.close.index[k].normalize()
    g = Group.model_validate(group("all", cond(ind("time"), "gte", const(910)),
                                   cond(_mk("close"), "gt", _mk("sma", n=2)),
                                   cond(_mk("close"), "lt", const(5000))))   # 변조(×10)되면 거짓이 되는 조건
    base = evaluate_group(g, pm, market=_kospi())
    fut = evaluate_group(g, pm, market=_kospi(tamper_from=day))   # 당일(D) 이후 지수 행을 ×10 — D 행이 새면 신호가 바뀐다
    pd.testing.assert_frame_equal(base.iloc[: k + 1], fut.iloc[: k + 1])
    assert base.iloc[: k + 1].to_numpy().any()
    assert not base.equals(fut)                                    # 변조는 D 다음 날 봉부터 실제로 영향(카나리아 자체 점검)


def test_c3_daily_operands_are_d_minus_1_not_same_day():
    daily, pm = _daily_and_bars(seed=6)
    day = pm.close.index.normalize()[BARS * 2]
    dg = Group.model_validate(group("all", cond(field("close"), "gt", const(0))))
    a = daily_prefilter(dg, daily, pm.close.index, list(pm.close.columns))
    d2 = tamper_after(daily, day - pd.Timedelta(days=1), factor=0.0)   # D 일봉 종가를 0 으로 (D 행이 보이면 False 가 됨)
    b = daily_prefilter(dg, d2, pm.close.index, list(pm.close.columns))
    on_day = pm.close.index.normalize() == day
    assert a[on_day].equals(b[on_day])
