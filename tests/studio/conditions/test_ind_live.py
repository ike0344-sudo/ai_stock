"""daily_live — 값 = "오늘 가상 봉을 일봉 끝에 붙여 일반 함수로 다시 계산한 값"(C6) + 미래참조 카나리아.

대상: 내가 등록한 live 지표 전부(가격·이평·신고가 16 / 보조지표 15 / 캔들 15). 재계산 대조는 backtest-agent 의
`timeframe.check_live_equals_recompute`(표본 봉·종목의 최대 절대 오차)를 그대로 쓴다.
"""
import numpy as np
import pandas as pd
import pytest

from studio.domain.conditions import ind_candle, ind_oscillator, ind_trend
from studio.domain.conditions.catalog import INDICATORS, LIVE_REGISTRY, resolve_params
from studio.domain.conditions.timeframe import check_live_equals_recompute, make_live_bars
from tests.studio.conditions.helpers import intraday_panel, panel_from, synth_candles, tamper_after

CASES = [
    # ---- 가격·이평·신고가
    ("wma", {"n": 5}), ("wma", {"n": 1}), ("wma", {"n": 4, "src": "volume"}), ("vwma", {"n": 5}), ("vwma", {"n": 1}),
    ("ma_disparity", {"n": 10, "ma": "sma"}), ("ma_disparity", {"n": 10, "ma": "ema"}), ("ma_slope", {"n": 5, "k": 3}),
    ("ma_slope", {"n": 5, "k": 1}), ("ma_aligned", {"n1": 3, "n2": 5, "n3": 10}),
    ("ma_aligned", {"n1": 2, "n2": 3, "n3": 5, "n4": 8}), ("ma_reversed", {"n1": 3, "n2": 5, "n3": 10}),
    ("new_high", {"n": 10, "src": "high"}), ("new_high", {"n": 10, "src": "close"}), ("new_low", {"n": 10}),
    ("high52_pct", {"n": 30}), ("high52_pct", {"n": 1}), ("low52_pct", {"n": 30}), ("bars_since_high", {"n": 15}),
    ("bars_since_high", {"n": 1}), ("bars_since_high", {"n": 2}), ("box_pct", {"n": 15}), ("up_streak", {}),
    ("down_streak", {}), ("limit_up_pct", {}), ("limit_up_hit", {}),
    # ---- 보조지표
    ("rsi_signal", {"n": 5, "m": 3}), ("rsi_signal", {"n": 5, "m": 1}), ("macd", {"fast": 5, "slow": 10, "sig": 4}),
    ("macd_signal", {"fast": 5, "slow": 10, "sig": 4}), ("macd_signal", {"fast": 5, "slow": 10, "sig": 1}),
    ("macd_hist", {"fast": 5, "slow": 10, "sig": 4}), ("stoch_k", {"n": 10, "k": 3, "d": 3}),
    ("stoch_d", {"n": 10, "k": 3, "d": 3}), ("stoch_k", {"n": 10, "k": 1, "d": 1}), ("stoch_d", {"n": 10, "k": 1, "d": 1}),
    ("williams_r", {"n": 10}), ("momentum", {"n": 4}), ("momentum", {"n": 1}), ("roc", {"n": 4}),
    ("envelope_upper", {"n": 10, "pct": 5.0}), ("envelope_lower", {"n": 10, "pct": 5.0}),
    ("bb_pctb", {"n": 10, "k": 2.0}), ("bb_width", {"n": 10, "k": 2.0}), ("psy", {"n": 8}), ("psy", {"n": 1}),
    ("atr_pct", {"n": 8}), ("atr_pct", {"n": 1}),
    # ---- 캔들
    ("body_pct", {}), ("upper_wick_ratio", {}), ("lower_wick_ratio", {}), ("range_pct", {}),
    ("long_bull", {"min_body_pct": 0.3}), ("long_bear", {"min_body_pct": 0.3}), ("doji", {"max_body_ratio": 0.3}),
    ("hammer", {"wick_mult": 1.0, "max_other_wick": 0.3}), ("inverted_hammer", {"wick_mult": 1.0, "max_other_wick": 0.3}),
    ("bull_engulfing", {}), ("bear_engulfing", {}), ("inside_bar", {}), ("outside_bar", {}),
    ("gap_held", {"min_gap_pct": 0.0}), ("gap_filled", {"min_gap_pct": 0.0}),
]
LOOSE = {"bb_pctb", "bb_width"}   # 볼린저 live 는 제곱합 식(내장)이라 부동소수 오차가 조금 더 크다


@pytest.fixture(scope="module")
def daily():
    return panel_from(synth_candles(n_days=90, n_codes=3, seed=21, start="2026-05-01"))


@pytest.fixture(scope="module")
def minute():
    return intraday_panel(n_days=6, bars=12, n_codes=3, seed=22)   # 2026-08-03 ~ (일봉 표 안 날짜)


def test_every_live_candidate_is_registered_and_flagged_live():
    for mod in (ind_trend, ind_oscillator, ind_candle):
        for name in mod.LIVE_CANDIDATES:
            assert INDICATORS[name].live and name in LIVE_REGISTRY, name
    assert {n for n, _ in CASES} == set(ind_trend.LIVE_CANDIDATES) | set(ind_oscillator.LIVE_CANDIDATES) | set(ind_candle.LIVE_CANDIDATES)
    assert INDICATORS["vwma"].volume_based and INDICATORS["vwma"].live          # 거래량 계열 — 통합 분봉이면 daily_live 는 c1 이 막는다
    assert not INDICATORS["cci"].live and not INDICATORS["psar"].live           # 설계표 live "—"


@pytest.mark.parametrize("name,params", CASES, ids=[f"{n}-{'-'.join(f'{k}{v}' for k, v in p.items())}" for n, p in CASES])
def test_live_equals_recompute_with_virtual_bar(daily, minute, name, params):
    err = check_live_equals_recompute(name, params, daily, minute, sample=20)
    assert err < (1e-5 if name in LOOSE else 1e-6), f"{name}{params}: 최대 오차 {err}"
    live = make_live_bars(minute, daily)
    val = LIVE_REGISTRY[name](live, resolve_params(name, params))
    assert val.shape == minute.close.shape and val.notna().to_numpy().any(), f"{name}: 값이 하나도 없으면 대조가 비어 있다"


@pytest.mark.parametrize("name,params", CASES, ids=[f"{n}-{'-'.join(f'{k}{v}' for k, v in p.items())}" for n, p in CASES])
def test_canary_future_minute_bars_and_same_day_daily_do_not_change_live_values(daily, minute, name, params):
    k = 12 * 3 + 5                                              # 4번째 날 6번째 봉
    t = minute.close.index[k]
    day = t.normalize()
    p = resolve_params(name, params)
    base = LIVE_REGISTRY[name](make_live_bars(minute, daily), p)
    fut = LIVE_REGISTRY[name](make_live_bars(tamper_after(minute, t), tamper_after(daily, day - pd.Timedelta(days=1))), p)
    np.testing.assert_allclose(base.iloc[: k + 1].to_numpy(), fut.iloc[: k + 1].to_numpy(), rtol=1e-9, atol=1e-9, equal_nan=True)
