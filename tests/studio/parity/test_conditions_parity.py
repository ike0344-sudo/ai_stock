"""P6 — 조립기(조건식 평가기)로 만든 전략 vs 기존 전략 `evaluate`: 실제 20종목에서 Signal 이 한 칸도 안 틀려야 한다.

실데이터(data/cache/daily_all.parquet, 고정 구간 2023-01-02~2026-08-31, 코드 정렬 앞 20종목)는
@pytest.mark.parity — 없으면 skip. 합성 데이터 버전은 항상 돈다.
불일치가 나면 종목별로 (불일치 수, 그 종목이 넓은 표에서 NaN 인 날 수) 를 메시지에 남긴다 —
거래정지로 종목 자신의 거래일이 넓은 표(날짜 합집합)와 다르면 rolling 이 NaN 을 물어 어긋날 수 있다.
"""
import os

import pandas as pd
import pytest

from backtesting.strategies.envelope import EnvelopeStrategy
from backtesting.strategies.ma_crossover import MovingAverageCrossover
from backtesting.strategies.new_high_swing import NewHighSwing
from backtesting.strategies.rsi_strategy import RsiStrategy
from studio.domain.conditions.ast import Group
from studio.domain.conditions.evaluator import evaluate, to_signals
from studio.infrastructure.legacy_strategies import REGISTRY, evaluate_legacy, legacy_signals
from tests.studio.conditions.helpers import cond, const, field, group, ind, panel_from, synth_candles

PARQUET = os.path.join("data", "cache", "daily_all.parquet")


def _g(logic, *items):
    return Group.model_validate(group(logic, *items))


def _sma(n, src="close", **kw):
    return ind("sma", src=src, n=n, **kw)


# ---- 조립기 명세 (기존 전략과 같은 규칙을 조립기 문법으로) -----------------------------
def ma_cross(short=5, long=20):
    return (_g("all", cond(_sma(short), "cross_above", _sma(long))),
            _g("any", cond(_sma(short), "cross_below", _sma(long))))


def rsi_levels(period=14, lo=30, hi=70):
    return (_g("all", cond(ind("rsi", n=period), "lt", const(lo))),
            _g("any", cond(ind("rsi", n=period), "gt", const(hi))))


def new_high(n=20, exit_low=7):
    # 기존: volume >= shift(1).rolling(20).mean() * 1.5  →  sma(volume,20) 를 1봉 미뤄 ×1.5 (vol_ratio 는 경계가 다를 수 있어 안 씀)
    return (_g("all", cond(field("close"), "gt", ind("highest", src="high", n=n)),
               cond(field("volume"), "gte", _sma(20, "volume", offset=1, mul=1.5))),
            _g("any", cond(field("close"), "lt", ind("lowest", src="low", n=exit_low))))


def envelope(window=60, pct=0.02, exit_mode="ma_touch"):
    entry = _g("all", cond(field("close"), "lte", _sma(window, mul=1 - pct)))
    exit_ = (cond(field("close"), "gte", _sma(window)) if exit_mode == "ma_touch"
             else cond(field("close"), "gte", _sma(window, mul=1 + pct)))
    return entry, _g("any", exit_)


CASES = {
    "ma_crossover_5_20": (lambda: ma_cross(5, 20), MovingAverageCrossover(), {"short_window": 5, "long_window": 20}),
    "ma_crossover_10_60": (lambda: ma_cross(10, 60), MovingAverageCrossover(), {"short_window": 10, "long_window": 60}),
    "rsi_14_30_70": (lambda: rsi_levels(), RsiStrategy(), {"period": 14, "buy_below": 30, "sell_above": 70}),
    "new_high_swing_20": (lambda: new_high(20, 7), NewHighSwing(), {"n_day_high": 20}),
    "new_high_swing_60": (lambda: new_high(60, 20), NewHighSwing(), {"n_day_high": 60}),
    "envelope_ma_touch": (lambda: envelope(60, 0.02, "ma_touch"), EnvelopeStrategy(),
                          {"ma_window": 60, "envelope_pct": 0.02, "exit_mode": "ma_touch"}),
    "envelope_opposite": (lambda: envelope(60, 0.03, "opposite_band"), EnvelopeStrategy(),
                          {"ma_window": 60, "envelope_pct": 0.03, "exit_mode": "opposite_band"}),
}


def _diff_report(candles, panel, sig_df, strat, params):
    bad = {}
    for code, c in candles.items():
        old = [s.value for s in strat.evaluate(c, params)]
        new = sig_df.loc[c.index, code].tolist()
        n_bad = sum(o != n for o, n in zip(old, new))
        if n_bad:
            span = panel.close.index[(panel.close.index >= c.index[0]) & (panel.close.index <= c.index[-1])]
            gap_days = len(span.difference(c.index))  # 상장 중인데 이 종목만 빠진 날(거래정지 등)
            bad[code] = (n_bad, gap_days)
    return bad


def _check(candles, case, dates=None):
    build, strat, params = case
    panel = panel_from(candles, dates)
    entry, exit_ = build()
    sig = to_signals(evaluate(entry, exit_, panel))
    bad = _diff_report(candles, panel, sig, strat, params)
    assert not bad, f"신호 불일치 {{종목: (불일치 수, 종목 자신의 결측일 수)}} = {bad}"
    for code, c in candles.items():  # 종목이 없는 날은 hold 여야 한다
        outside = sig[code].drop(c.index)
        assert (outside == "hold").all()


@pytest.mark.parametrize("case_name", sorted(CASES))
def test_builder_equals_legacy_on_synthetic(case_name):
    _check(synth_candles(n_days=400, n_codes=12, seed=11), CASES[case_name])


@pytest.mark.parametrize("case_name", sorted(CASES))
def test_builder_equals_legacy_with_trading_halt_gaps(case_name):
    """거래정지로 행이 빠진 종목도 기존 전략(종목 자기 거래일)과 신호가 같아야 한다."""
    candles = synth_candles(n_days=400, n_codes=12, seed=11)
    candles["000001"] = candles["000001"].drop(candles["000001"].index[120:126])
    candles["000003"] = candles["000003"].drop(candles["000003"].index[[200, 201, 250, 330]])
    _check(candles, CASES[case_name])


# ------------------------------------------------------------------ 실데이터 (P6)
@pytest.fixture(scope="module")
def real20():
    if not os.path.exists(PARQUET):
        pytest.skip("daily_all.parquet 없음")
    d = pd.read_parquet(PARQUET)
    d = d[(d["date"] >= "2023-01-02") & (d["date"] <= "2026-08-31")]
    out = {}
    for code, g in d.groupby("code"):
        if len(g) < 500:
            continue
        out[code] = g.assign(date=pd.to_datetime(g["date"])).set_index("date")[
            ["open", "high", "low", "close", "volume"]].astype(float)
        if len(out) == 20:
            break
    assert len(out) == 20
    return out


@pytest.mark.parity
@pytest.mark.parametrize("case_name", sorted(CASES))
def test_p6_builder_equals_legacy_on_real_20(real20, case_name):
    _check(real20, CASES[case_name])


@pytest.fixture(scope="module")
def real_gap():
    """실데이터에서 활동 구간 안에 행이 빠진 날이 있는 종목 최대 3개 + 빈칸 없는 5개, 전체 거래일 달력 위에서."""
    if not os.path.exists(PARQUET):
        pytest.skip("daily_all.parquet 없음")
    d = pd.read_parquet(PARQUET)
    d = d[(d["date"] >= "2023-01-02") & (d["date"] <= "2026-08-31")].assign(date=lambda x: pd.to_datetime(x["date"]))
    dates = pd.DatetimeIndex(sorted(d["date"].unique()))
    gap, full = {}, {}
    for code, g in d.groupby("code"):
        if len(g) < 500:
            continue
        c = g.set_index("date")[["open", "high", "low", "close", "volume"]].astype(float)
        span = dates[(dates >= c.index[0]) & (dates <= c.index[-1])]
        target = gap if len(span.difference(c.index)) else full
        if len(target) < (3 if target is gap else 5):
            target[code] = c
        if len(gap) == 3 and len(full) == 5:
            break
    if not gap:
        pytest.skip("실데이터에 빈칸 종목 없음")
    return {**gap, **full}, dates


@pytest.mark.parity
@pytest.mark.parametrize("case_name", sorted(CASES))
def test_p6_real_stocks_with_halt_gaps(real_gap, case_name):
    candles, dates = real_gap
    _check(candles, CASES[case_name], dates)


@pytest.mark.parity
def test_p6_sma5_20_cross_is_signal_identical_to_ma_crossover(real20):
    """SC-4 의 핵심: 조립기 SMA5/20 교차 → 기존 MovingAverageCrossover 와 Signal 동일."""
    _check(real20, CASES["ma_crossover_5_20"])


# ------------------------------------------------------------------ 기존 전략 어댑터
@pytest.mark.parametrize("name,params", [
    ("ma_crossover", {}), ("rsi", {}), ("envelope", {}), ("new_high_swing", {}),
    ("vcp_breakout", {}), ("new_high_leg_exit", {}), ("new_high_volume_divergence_exit", {}),
    ("pullback_reentry", {}),
])
def test_legacy_adapter_matches_direct_evaluate(name, params):
    from studio.infrastructure.legacy_strategies import validate_params, _strategy
    candles = synth_candles(n_days=350, n_codes=6, seed=21)
    panel = panel_from(candles)
    sig = legacy_signals(name, params, panel)
    strat, p = _strategy(REGISTRY[name]), validate_params(name, params)
    for code, c in candles.items():
        assert sig[code].tolist() == [s.value for s in strat.evaluate(c, p)]
    ev = evaluate_legacy(name, params, panel)
    assert (ev.entry == sig.eq("buy")).all().all() and (ev.exit == sig.eq("sell")).all().all()


def test_legacy_adapter_uses_each_stocks_own_trading_days():
    """거래정지로 빠진 날(NaN)이 있어도 종목 자신의 캔들로 평가 — 기존 연구와 같은 결과."""
    candles = synth_candles(n_days=300, n_codes=3, seed=31)
    candles["000001"] = candles["000001"].drop(candles["000001"].index[100:105])  # 5일 결측
    panel = panel_from(candles)
    sig = legacy_signals("new_high_swing", {"n_day_high": 20}, panel)
    strat = NewHighSwing()
    for code, c in candles.items():
        assert sig.loc[c.index, code].tolist() == [s.value for s in strat.evaluate(c, {"n_day_high": 20})]
    assert (sig.loc[panel.close.index.difference(candles["000001"].index), "000001"] == "hold").all()


def test_legacy_param_validation():
    from studio.infrastructure.legacy_strategies import validate_params
    assert validate_params("new_high_swing", {}) == {"n_day_high": 20}          # exit_low_days None → 뺌
    assert validate_params("ma_crossover", {"short_window": 5.0})["short_window"] == 5
    for name, bad in [("ma_crossover", {"short_window": 30, "long_window": 20}), ("rsi", {"buy_below": 120}),
                      ("envelope", {"exit_mode": "x"}), ("new_high_swing", {"n_day_high": 1}),
                      ("new_high_swing", {"typo": 1}), ("nope", {})]:
        with pytest.raises(ValueError):
            validate_params(name, bad)


def test_registry_covers_eight_strategies_without_ml():
    assert set(REGISTRY) == {"ma_crossover", "rsi", "envelope", "new_high_swing", "pullback_reentry",
                             "vcp_breakout", "new_high_leg_exit", "new_high_volume_divergence_exit"}
    assert REGISTRY["pullback_reentry"].deprecated
