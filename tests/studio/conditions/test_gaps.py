"""거래정지 빈칸 — 롤링·시프트는 종목 자기 거래일(행이 있는 날)만 이어서 계산 (lead 판정 2026-09-25)."""
import numpy as np
import pandas as pd
import pytest

from studio.domain.conditions.ast import Group
from studio.domain.conditions.evaluator import evaluate_group
from studio.domain.conditions.indicators import compute, gap_columns, own_shift
from tests.studio.conditions.helpers import cond, const, field, group, ind, panel_from, synth_candles
from tests.studio.conditions.test_evaluator import _tiny

GAP_CODE = "000001"
CASES = [("sma", {"n": 20}), ("ema", {"n": 10}), ("rsi", {"n": 14}), ("rsi_wilder", {"n": 14}),
         ("highest", {"n": 20}), ("lowest", {"n": 7}), ("change_pct", {"n": 3}), ("gap_pct", {}),
         ("atr", {"n": 14}), ("bb_upper", {"n": 20}), ("bb_lower", {"n": 20}), ("vol_ratio", {"n": 20})]


@pytest.fixture(scope="module")
def gapped():
    candles = synth_candles(n_days=300, n_codes=4, seed=2)
    candles[GAP_CODE] = candles[GAP_CODE].drop(candles[GAP_CODE].index[[100, 101, 102, 103, 104, 180]])
    return candles, panel_from(candles)


def test_gap_columns_detects_only_inside_gaps():
    idx = pd.date_range("2024-01-01", periods=6)
    close = pd.DataFrame({"full": [1.0] * 6, "gap": [1, 1, np.nan, 1, 1, 1], "late": [np.nan, np.nan, 1, 1, 1, 1],
                          "delisted": [1, 1, 1, np.nan, np.nan, np.nan]}, index=idx)
    assert gap_columns(close) == ["gap"]  # 상장 전·상폐 후 빈칸은 활동 구간 밖 → 해당 없음


@pytest.mark.parametrize("name,params", CASES)
def test_indicator_on_gapped_stock_equals_standalone(gapped, name, params):
    candles, panel = gapped
    got = compute(panel, name, params)
    alone = compute(panel_from({GAP_CODE: candles[GAP_CODE]}), name, params)[GAP_CODE]
    own = candles[GAP_CODE].index
    pd.testing.assert_series_equal(got.loc[own, GAP_CODE], alone, check_names=False, check_freq=False)  # 그 종목만 떼어 계산한 값
    assert got.loc[panel.close.index.difference(own), GAP_CODE].isna().all()                            # 빈칸 날 자체는 NaN
    for other in panel.close.columns.drop(GAP_CODE):                                                    # 빈칸 없는 열은 그대로
        pd.testing.assert_series_equal(got[other], compute(panel_from({other: candles[other]}), name, params)[other],
                                       check_names=False, check_freq=False)


def test_value_rank_uses_own_days_for_average(gapped):
    candles, panel = gapped
    got = compute(panel, "value_rank", {"lookback": 3})
    own = candles[GAP_CODE].index
    avg = (candles[GAP_CODE]["close"] * candles[GAP_CODE]["volume"]).rolling(3).mean()  # 자기 거래일 3일 평균
    others = panel.value.drop(columns=GAP_CODE).rolling(3).mean()
    t = own[100]  # 첫 빈칸 블록(원래 100~104번째 날) 직후 첫 거래일 — 자기 거래일 3일 평균이 넓은 표 rolling 과 갈리는 자리
    row = pd.concat([others.loc[t], pd.Series({GAP_CODE: avg.loc[t]})])
    assert got.loc[t].equals(row.rank(ascending=False, method="min").reindex(got.columns))
    assert np.isnan(got.loc[panel.close.index.difference(own)[0], GAP_CODE])


def test_own_shift_skips_gap_rows():
    p = _tiny([10, 20, np.nan, 40, 50], [1, 2, 3, 4, 5])
    s = own_shift(p, p.close, 1)
    assert s["X"].tolist()[3:] == [20.0, 40.0]  # 빈칸 다음 날의 "어제" = 자기 직전 거래일(20)
    assert s["Y"].iloc[1:].tolist() == [1, 2, 3, 4]  # 빈칸 없는 열은 그냥 shift


def test_cross_across_gap_day_is_detected_like_legacy():
    p = _tiny([1, 1, np.nan, 3, 3], [0, 0, 0, 0, 0])
    r = evaluate_group(Group.model_validate(group("all", cond(field("close"), "cross_above", const(2)))), p)
    assert r["X"].tolist() == [False, False, False, True, False]  # 자기 거래일 기준 1→3 상향돌파(순진한 벡터는 놓침)


def test_offset_across_gap_day():
    p = _tiny([10, 20, np.nan, 40, 50], [1, 1, 1, 1, 1])
    r = evaluate_group(Group.model_validate(group("all", cond(field("close"), "gt", field("close", offset=1)))), p)
    assert r["X"].tolist() == [False, True, False, True, True]


def test_gap_day_never_signals_even_for_market_only_condition():
    idx = pd.date_range("2024-01-01", periods=4)
    p = _tiny([1, np.nan, 1, 1], [1, 1, 1, 1])
    m = {"kospi": pd.DataFrame({"close": [400000] * 4}, index=idx)}
    g = Group.model_validate(group("all", cond({"kind": "market", "index": "kospi", "name": "close"}, "gt", const(1))))
    assert evaluate_group(g, p, market=m)["X"].tolist() == [True, False, True, True]  # 봉 없는 날은 신호 없음


def test_zero_volume_day_is_a_normal_bar():
    p = _tiny([1, 2, 3, 4], [1, 1, 1, 1])
    p.volume["X"] = [5, 0, 5, 5]  # 행은 있음 — 빈칸 아님
    assert gap_columns(p.close) == []
    r = evaluate_group(Group.model_validate(group("all", cond(field("volume"), "lte", const(0)))), p)
    assert r["X"].tolist() == [False, True, False, False]
