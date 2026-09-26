"""studio-conditions c9 — 거래대금(억) 조건: `value_eok`·`value_sum_eok(n)`(일봉·분봉, 시간 단위 전부) + 틱 `value_window(w_min, min_eok)`.

손계산: 5분봉→15분 묶음 대금·합·창 경계. 카나리아: t 이후 변조 → t 이하 값 불변(mN·daily_live 포함).
"""
import copy

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from studio.domain.conditions.ast import FieldOperand, Group, IndOperand
from studio.domain.conditions.catalog import INDICATORS, LIVE_REGISTRY
from studio.domain.conditions.evaluator import _operand
from studio.domain.conditions.tick import TickDay, build_grid, detect_signals, value_window_series
from studio.domain.conditions.timeframe import TimeContext, check_live_equals_recompute
from studio.domain.conditions.validation import validate_group
from studio.domain.models import Panel
from studio.domain.spec import Spec

from .test_timeframe import BAR, make_data, tamper_after

EOK = 1e8


def val(daily, minute, name, params, tf="bar", panel=None):
    op = IndOperand.model_validate({"kind": "ind", "name": name, "params": params, "tf": tf})
    p = panel if panel is not None else minute
    return _operand(op, p, None, [], None, TimeContext(p, daily, BAR))


def test_catalog_entries_are_live_volume_based_and_in_the_volume_group():
    for n in ("value_eok", "value_sum_eok"):
        d = INDICATORS[n]
        assert d.category == "volume" and d.volume_based and d.live and n in LIVE_REGISTRY and d.definition and d.example
        assert set(d.modes) == {"daily_single", "daily_portfolio", "intraday"}
    assert INDICATORS["value_sum_eok"].param("n").default == 3


def test_daily_value_eok_and_sum_hand_computed():
    daily, minute = make_data(n_hist=40, n_min_days=2)
    v1 = val(None, daily, "value_eok", {}, panel=daily)  # 일봉 실행: 값 = 일봉 대금 ÷ 1억
    pd.testing.assert_frame_equal(v1, daily.value / EOK)
    v3 = val(None, daily, "value_sum_eok", {"n": 3}, panel=daily)  # 최근 3봉(오늘 포함) 합
    exp = pd.DataFrame({c: [np.nan, np.nan] + [daily.value[c].iloc[i - 2: i + 1].sum() / EOK for i in range(2, len(daily.value))]
                        for c in daily.value.columns}, index=daily.value.index)
    pd.testing.assert_frame_equal(v3, exp)
    pd.testing.assert_frame_equal(val(None, daily, "value_sum_eok", {"n": 1}, panel=daily), v1)


def test_intraday_bar_and_m15_bucket_sums_hand_computed():
    daily, minute = make_data(n_hist=40, n_min_days=3)  # 5분봉 · 끝 라벨 09:05..15:20
    pd.testing.assert_frame_equal(val(daily, minute, "value_eok", {}, "bar"), minute.value / EOK)
    idx = minute.value.index
    hour9 = pd.Timedelta(hours=9)
    step = pd.Timedelta(minutes=15)

    def bucket(c, day, end):  # 09:00 격자 15분 묶음(끝 end) 안 5분봉 대금 합
        m = (idx.normalize() == day) & (idx > end - step) & (idx <= end)
        return minute.value[c][m].sum() / EOK

    m15 = val(daily, minute, "value_eok", {}, "m15")
    s2 = val(daily, minute, "value_sum_eok", {"n": 2}, "m15")
    checked = 0
    for t in idx[::5]:
        day = t.normalize()
        k = (t - day - hour9) // step  # t 까지 마감된 15분 묶음 개수(끝 시각 ≤ t)
        if k < 2:
            continue  # 오늘 첫 묶음들은 전날 값이 이어진다(c1 규칙) — 손계산 표본에서 뺀다
        last = day + hour9 + step * k
        for c in minute.value.columns:
            assert m15.loc[t, c] == pytest.approx(bucket(c, day, last)), (c, t)
            assert s2.loc[t, c] == pytest.approx(bucket(c, day, last) + bucket(c, day, last - step)), (c, t)
            checked += 1
    assert checked > 100


@pytest.mark.parametrize("name,params", [("value_eok", {}), ("value_sum_eok", {"n": 1}), ("value_sum_eok", {"n": 3}), ("value_sum_eok", {"n": 5})])
@pytest.mark.parametrize("halt", [None, "B"])
def test_daily_live_equals_recompute_with_virtual_bar(name, params, halt):
    daily, minute = make_data(halt_col=halt)
    assert check_live_equals_recompute(name, params, daily, minute, sample=25) < 1e-9


@pytest.mark.parametrize("tf", ["bar", "m15", "daily_prev", "daily_live"])
@pytest.mark.parametrize("name,params", [("value_eok", {}), ("value_sum_eok", {"n": 3})])
def test_c9_canary_data_after_t_does_not_change_values_up_to_t(tf, name, params):
    daily, minute = make_data(n_hist=60, n_min_days=4)
    base = val(daily, minute, name, params, tf)
    for k in (40, 150):
        t = minute.close.index[k]
        bad = tamper_after(minute, t)
        dbad = daily
        if tf in ("daily_prev", "daily_live"):  # 오늘(D) 이후의 일봉 행을 통째로 변조 — 그날 값은 불변이어야 한다
            fr = {f: getattr(daily, f).copy() for f in ("open", "high", "low", "close", "volume", "value", "prev_close")}
            for f in fr:
                fr[f].loc[fr[f].index >= t.normalize()] = fr[f].loc[fr[f].index >= t.normalize()] * 10
            dbad = Panel(**fr)
        got = val(dbad, bad, name, params, tf)
        pd.testing.assert_frame_equal(base.loc[:t], got.loc[:t])
        assert not base.loc[t:].iloc[1:].equals(got.loc[t:].iloc[1:])  # 카나리아가 살아 있다


def test_daily_live_volume_based_is_krx_only_and_valid_in_bar_m15_daily_prev():
    def g(tf):
        return Group.model_validate({"logic": "all", "items": [{"left": {"kind": "ind", "name": "value_sum_eok", "params": {"n": 3}, "tf": tf},
                                                                 "op": "gte", "right": {"kind": "const", "value": 20}}]})
    validate_group(g("bar"), "entry", mode="intraday", source="al")
    validate_group(g("m15"), "entry", mode="intraday", bar_minutes=5, source="al")
    validate_group(g("daily_prev"), "entry", mode="intraday", source="al")
    with pytest.raises(ValueError, match="KRX"):
        validate_group(g("daily_live"), "entry", mode="intraday", source="al")
    validate_group(g("daily_live"), "entry", mode="intraday", source="krx")


# ------------------------------------------------------------------ 틱 value_window
def _day(secs, prcs, qtys):
    return TickDay("A", pd.Timestamp("2026-01-05").date(), np.array(secs), np.array(prcs, float), np.array(qtys, float), 100.0)


def test_tick_value_window_hand_calc_window_is_s_minus_w_exclusive_s_inclusive():
    # 체결대금(원): 초 10 → 20억, 초 100 → 6억, 초 130 → 5억. w=1분(60초), 문턱 10억
    day = _day([10, 100, 130, 300], [1000, 1000, 1000, 1000], [2_000_000, 600_000, 500_000, 1])
    s = value_window_series(build_grid(day), 1)
    assert np.isnan(s[:59]).all()  # 창이 세션 시작 앞에 걸치면(s < w−1) 값 없음
    assert s[59] == pytest.approx(20e8) and s[69] == pytest.approx(20e8) and s[70] == pytest.approx(0)  # (s−60, s] — 초 10 은 s=69 까지 창 안
    assert s[100] == pytest.approx(6e8) and s[129] == pytest.approx(6e8)
    assert s[130] == pytest.approx(11e8)  # 초 130 체결이 창에 들어온다(s 자신 포함)
    assert s[159] == pytest.approx(11e8) and s[160] == pytest.approx(5e8)  # (100, 160] — 초 100 이 s=160 에서 빠진다
    ev = detect_signals(day, value_window=(1, 10.0), cooldown_sec=0, time_from="09:00:00", time_to="15:30:00")
    assert ev.signal_sec.tolist() == list(range(59, 70)) + list(range(130, 160))
    assert (ev.entry_sec > ev.signal_sec).all()  # 진입은 s 뒤 첫 체결
    assert ev.entry_sec[0] == 100 and ev.entry_sec[-1] == 300
    assert detect_signals(day, value_window=(1, 10.0), cooldown_sec=300).signal_sec.tolist() == [59]  # 쿨다운 300: 130 은 걸러진다


def test_tick_value_window_canary_ticks_after_s_do_not_change_signals_up_to_s():
    rng = np.random.default_rng(3)
    sec = np.sort(rng.integers(0, 20000, 2000))
    prc = np.round(20000 * np.exp(np.cumsum(rng.normal(0, 0.001, 2000))) / 10) * 10
    qty = rng.integers(1, 3000, 2000)
    S = 9000
    a = detect_signals(_day(sec, prc, qty), value_window=(1, 1.0), cooldown_sec=0)
    b = detect_signals(_day(sec, np.where(sec > S, prc * 10, prc), np.where(sec > S, qty * 10, qty)), value_window=(1, 1.0), cooldown_sec=0)
    assert a.signal_sec[a.signal_sec <= S].tolist() == b.signal_sec[b.signal_sec <= S].tolist() and (a.signal_sec <= S).sum() > 20
    assert len(b.signal_sec) != len(a.signal_sec)  # 카나리아가 살아 있다


def test_tick_catalog_accepts_value_window_and_old_hash_is_unchanged():
    from studio.application.backtest_service import _strip_new_defaults, spec_hash
    from tests.studio.application.fakes_intraday import IntradayFake
    from tests.studio.application.test_intraday_service import tick_dict
    md = IntradayFake(n_days=3)
    base = Spec.model_validate(tick_dict(md))
    dumped = base.model_dump(mode="json")
    assert dumped["tick"]["catalog"]["value_window"] is None
    old = copy.deepcopy(dumped)
    old["tick"]["catalog"].pop("value_window")
    assert _strip_new_defaults(dumped) == _strip_new_defaults(old)

    def mk(vw):
        return Spec.model_validate(tick_dict(md, tick={**tick_dict(md)["tick"], "catalog": {"breakout_min": None, "value_window": vw}}))
    on = mk({"w": 1, "min_eok": 10})
    assert on.tick.catalog.value_window.min_eok == 10 and spec_hash(on) != spec_hash(base)
    for bad in ({"w": 0, "min_eok": 10}, {"w": 61, "min_eok": 10}, {"w": 1, "min_eok": 0}):
        with pytest.raises(ValidationError):
            mk(bad)


def test_service_tick_run_entries_match_brute_force_window_and_value_eok_warning():
    from studio.application.backtest_service import condition_warnings, run_backtest
    from tests.studio.application.fakes_intraday import IntradayFake
    from tests.studio.application.test_intraday_service import intraday_dict, tick_dict
    md = IntradayFake(n_days=8, drift=0.0001, seed=11)
    tk = {**tick_dict(md)["tick"], "catalog": {"breakout_min": None, "value_window": {"w": 1, "min_eok": 0.1}, "time_from": "09:05", "time_to": "15:00"},
          "cooldown_sec": 60}
    d = tick_dict(md, tick=tk)
    d["portfolio"] = {"max_positions": 50}
    rec = run_backtest(Spec.model_validate(d), md)
    assert len(rec.trades) > 10
    allowed = set()
    for (code, day), (sec, prc, qty) in md.ticks.items():
        amt = prc * qty
        last, hits = -10**9, []
        for s in range(59, 23401):  # 손으로: (s−60, s] 체결대금 합 ≥ 0.1억, 09:05~15:00, 쿨다운 60
            if not (300 <= s <= 21600):
                continue
            w = amt[(sec > s - 60) & (sec <= s)].sum()
            if w >= 0.1 * 1e8 and s - last >= 60:
                hits.append(s)
                last = s
        for s in hits:
            j = np.searchsorted(sec, s, side="right")
            if j < len(sec):
                allowed.add((code, pd.Timestamp(day) + pd.Timedelta(seconds=9 * 3600 + int(sec[j]))))
    got = {(t.code, t.entry_ts) for t in rec.trades.itertuples()}
    assert got and got <= allowed
    # 경고: 분·일봉 value_eok 는 종가×거래량 근사 문구가 결과 경고 재료에 실린다(틱 value_window 는 정확값이라 없음)
    spec = Spec.model_validate(intraday_dict(md))
    d2 = copy.deepcopy(intraday_dict(md))
    d2["strategy"]["entry"]["items"][0] = {"left": {"kind": "ind", "name": "value_eok", "params": {}}, "op": "gte", "right": {"kind": "const", "value": 20}}
    assert any("종가×거래량 근사" in w for w in condition_warnings(Spec.model_validate(d2)))
    assert not any("종가×거래량 근사" in w for w in condition_warnings(spec))
    assert not any("종가×거래량 근사" in w for w in rec.warnings if "거래대금(억)" in w)


@pytest.mark.parametrize("tf", ["bar", "m15"])
def test_legacy_value_field_vs_won_equals_value_eok_vs_eok(tf):
    """옛 명세 `field:value >= N원` 을 화면이 `value_eok >= N÷1억` 으로 바꿔 보여도 진입 판정이 같다(17:58 lead 요청)."""
    daily, minute = make_data(n_hist=40, n_min_days=3)
    fld = _operand(FieldOperand.model_validate({"kind": "field", "name": "value", "tf": tf}),
                   minute, None, [], None, TimeContext(minute, daily, BAR))
    eok = val(daily, minute, "value_eok", {}, tf)
    for won in (1e9, 2.5e9, float(np.nanmedian(fld.values))):
        a, b = fld >= won, eok >= won / EOK
        pd.testing.assert_frame_equal(a, b)
