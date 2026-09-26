"""새 분류 지표(가격·이평·신고가 / 보조지표 / 캔들) 공통 검사 — 등록 메타·기본 계산·**미래참조 카나리아**·거래정지 열·분봉 표.

지표마다: t 이후 봉을 잘라 내도(prefix)·바꿔도(tamper) t 이하 값이 안 변해야 한다(미래참조 없음이 최우선).
"""
import numpy as np
import pandas as pd
import pytest

from studio.domain.conditions import ind_candle, ind_oscillator, ind_trend
from studio.domain.conditions.ast import Group
from studio.domain.conditions.catalog import CATEGORIES, INDICATORS, ParamDef
from studio.domain.conditions.indicators import compute
from studio.domain.narration import narrate_group
from tests.studio.conditions.helpers import cond, const, field, group, ind, intraday_panel, panel_from, synth_candles, tamper_after
from tests.studio.conditions.ind_helpers import head

DESIGN = {
    "trend": "wma vwma ma_disparity ma_slope ma_aligned ma_reversed new_high new_low high52_pct low52_pct bars_since_high "
             "box_pct up_streak down_streak limit_up_pct limit_up_hit prev_high_break".split(),
    "oscillator": "rsi_signal macd macd_signal macd_hist stoch_k stoch_d cci adx plus_di minus_di obv obv_signal mfi "
                  "williams_r momentum roc ichimoku_conv ichimoku_base ichimoku_span_a ichimoku_span_b ichimoku_cloud_top "
                  "ichimoku_cloud_bottom envelope_upper envelope_lower bb_pctb bb_width psar keltner_upper keltner_lower "
                  "psy vr atr_pct volatility".split(),
    "candle": "body_pct upper_wick_ratio lower_wick_ratio range_pct long_bull long_bear doji hammer inverted_hammer "
              "bull_engulfing bear_engulfing inside_bar outside_bar gap_held gap_filled".split(),
}
NEW = [n for names in DESIGN.values() for n in names]
MY_CATEGORIES = ("trend", "oscillator", "candle")
ALL_MINE = sorted(n for n, d in INDICATORS.items() if d.category in MY_CATEGORIES)


def test_design_table_names_are_all_registered_in_the_right_category():
    for cat, names in DESIGN.items():
        for n in names:
            assert n in INDICATORS and INDICATORS[n].category == cat, n


def test_metadata_is_complete_and_defaults_are_valid():
    for n in NEW:
        d = INDICATORS[n]
        assert d.category in CATEGORIES and d.definition and d.example and d.label_ko, n
        assert {"daily_single", "daily_portfolio", "intraday"} <= set(d.modes), n
        for p in d.params:
            assert isinstance(p, ParamDef)
            if p.numeric:
                assert p.lo <= p.default <= p.hi, (n, p.name)
            if p.kind == "enum":
                assert p.default in p.choices, (n, p.name)


def test_live_flags_match_design_table_and_registry():  # 재계산 대조·카나리아는 test_ind_live.py
    for mod in (ind_trend, ind_oscillator, ind_candle):
        assert mod.LIVE_CANDIDATES <= set(mod.COMPUTE)
    assert "psar" not in ind_oscillator.LIVE_CANDIDATES and "cci" not in ind_oscillator.LIVE_CANDIDATES  # 설계표 live "—"
    assert ind_candle.LIVE_CANDIDATES == set(ind_candle.COMPUTE)                                       # 캔들은 전부 ✔


@pytest.fixture(scope="module")
def panel():
    return panel_from(synth_candles(n_days=320, n_codes=6, seed=13))


@pytest.mark.parametrize("name", ALL_MINE)
def test_computes_with_default_params_and_shape(panel, name):
    out = compute(panel, name)
    assert out.shape == panel.close.shape
    assert out.iloc[-1].notna().any(), f"{name}: 마지막 봉에도 값이 하나도 없음"


@pytest.mark.parametrize("name", ALL_MINE)
def test_canary_prefix_values_do_not_depend_on_later_bars(panel, name):
    k = 270                                                    # 250봉 창 지표도 값이 생기는 지점 이후
    full = compute(panel, name).iloc[:k]
    part = compute(head(panel, k), name)
    np.testing.assert_allclose(full.to_numpy(), part.to_numpy(), rtol=1e-9, atol=1e-9, equal_nan=True)


@pytest.mark.parametrize("name", ALL_MINE)
def test_canary_tampering_future_bars_does_not_change_past_values(panel, name):
    t = panel.close.index[270]
    base = compute(panel, name).loc[:t]
    fut = compute(tamper_after(panel, t), name).loc[:t]
    np.testing.assert_allclose(base.to_numpy(), fut.to_numpy(), rtol=1e-9, atol=1e-9, equal_nan=True)


@pytest.mark.parametrize("name", ALL_MINE)
def test_halted_stock_uses_its_own_trading_days(name):
    candles = synth_candles(n_days=120, n_codes=3, seed=5)
    code = "000001"
    candles[code] = candles[code].drop(candles[code].index[[60, 61, 90]])
    pn = panel_from(candles)
    got = compute(pn, name)[code]
    alone = compute(panel_from({code: candles[code]}), name)[code]
    pd.testing.assert_series_equal(got.loc[candles[code].index], alone, check_names=False, check_freq=False)
    assert got.loc[pn.close.index.difference(candles[code].index)].isna().all()


@pytest.mark.parametrize("name", ALL_MINE)
def test_computes_on_intraday_panel(name):
    pm = intraday_panel(n_days=5, bars=12, n_codes=3, seed=2)
    assert compute(pm, name).shape == pm.close.shape


def test_every_new_indicator_can_be_used_in_a_condition_and_narrated():
    for n in NEW:
        g = Group.model_validate(group("all", cond(ind(n), "gt", const(0))))
        assert INDICATORS[n].label_ko in narrate_group(g), n          # 풀이 문장에 지표 이름이 나온다
    g = Group.model_validate(group("all", cond(ind("macd", fast=8, slow=21), "gt", const(0))))
    assert "fast=8" in narrate_group(g) and "slow=21" in narrate_group(g)   # 기본값과 다른 파라미터는 문장에 보인다
