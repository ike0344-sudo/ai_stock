"""평가기 — cross 정의, offset·mul, 변수 치환, market, 신호 조립, look-ahead 카나리아(C1형·C2)."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from studio.domain.conditions.ast import Group
from studio.domain.conditions.evaluator import (
    BUY, HOLD, SELL, Evaluation, evaluate, evaluate_group, to_signals,
)
from studio.domain.conditions.indicators import value_rank
from tests.studio.conditions.helpers import cond, const, field, group, ind, synth_panel, tamper_after


def _tiny(a, b):
    idx = pd.date_range("2024-01-01", periods=len(a))
    close = pd.DataFrame({"X": a, "Y": b}, index=idx, dtype=float)
    ones = close * 0 + 1
    return SimpleNamespace(open=close, high=close, low=close, close=close, volume=ones, value=close,
                           prev_close=close.shift(1))


def _run(panel, c) -> pd.DataFrame:
    return evaluate_group(Group.model_validate(group("all", c)), panel)


def test_cross_above_definition_and_nan():
    p = _tiny([1, 2, 3, 1, 3, np.nan, 3], [1, 2, 3, 1, 3, np.nan, 3])
    p.close["Y"] = 2.0  # Y = 상수 2, X = 위 수열
    p.open["Y"] = p.high["Y"] = p.low["Y"] = 2.0
    r = _run(p, cond(field("close"), "cross_above", const(2)))
    #        X:   1      2      3     1      3      nan    3
    assert r["X"].tolist() == [False, False, True, False, True, False, False]  # 2>2 아님, NaN 다음 날은 False
    assert r["Y"].tolist() == [False] * 7                                       # 계속 2 == 2 → 돌파 없음


def test_cross_below_is_symmetric():
    p = _tiny([3, 2, 1, 3, 1], [0, 0, 0, 0, 0])
    r = _run(p, cond(field("close"), "cross_below", const(2)))
    assert r["X"].tolist() == [False, False, True, False, True]  # a<2 이면서 직전 a>=2


def test_gt_gte_lt_lte_with_nan_false():
    p = _tiny([1, np.nan, 3], [3, 3, 3])
    assert _run(p, cond(field("close"), "gt", const(2)))["X"].tolist() == [False, False, True]
    assert _run(p, cond(field("close"), "gte", const(3)))["X"].tolist() == [False, False, True]
    assert _run(p, cond(field("close"), "lt", const(2)))["X"].tolist() == [True, False, False]
    assert _run(p, cond(field("close"), "lte", const(1)))["X"].tolist() == [True, False, False]


def test_offset_and_mul():
    p = _tiny([10, 20, 30, 40], [1, 1, 1, 1])
    r = _run(p, cond(field("close"), "gt", field("close", offset=1, mul=1.5)))  # 오늘 > 어제×1.5
    assert r["X"].tolist() == [False, True, False, False]  # 20>15 True, 30>30 False, 40>45 False


def test_and_or_nesting_and_empty_group():
    p = _tiny([1, 5, 9], [9, 5, 1])
    a, b = cond(field("close"), "gt", const(4)), cond(field("close"), "lt", const(6))
    assert evaluate_group(Group.model_validate(group("all", a, b)), p)["X"].tolist() == [False, True, False]
    assert evaluate_group(Group.model_validate(group("any", a, b)), p)["X"].tolist() == [True, True, True]
    nested = group("all", a, group("any", b, cond(field("close"), "gt", const(8))))
    assert evaluate_group(Group.model_validate(nested), p)["X"].tolist() == [False, True, True]
    assert not evaluate_group(Group.model_validate(group("all")), p).to_numpy().any()


def test_values_substitution_and_missing_value():
    p = _tiny([1, 5, 9], [9, 5, 1])
    g = Group.model_validate(group("all", cond(field("close"), "gt", const({"param": "lvl"}))))
    assert evaluate_group(g, p, values={"lvl": 4})["X"].tolist() == [False, True, True]
    with pytest.raises(ValueError):
        evaluate_group(g, p)  # 채워지지 않은 변수


def test_market_operand_scale_and_sma_and_missing():
    idx = pd.date_range("2024-01-01", periods=6)
    p = _tiny([1] * 6, [1] * 6)
    kospi = pd.DataFrame({"close": [300000, 310000, 320000, 330000, 340000, 350000]}, index=idx)  # ×100 저장
    m = {"kospi": kospi}
    above = cond({"kind": "market", "index": "kospi", "name": "close"}, "gt", const(3300))
    r = evaluate_group(Group.model_validate(group("all", above)), p, market=m)
    assert r["X"].tolist() == [False, False, False, False, True, True]        # 3400 > 3300 부터 (×100 보정)
    sma = cond({"kind": "market", "index": "kospi", "name": "close"}, "gt",
               {"kind": "market", "index": "kospi", "name": "sma", "params": {"n": 3}})
    assert evaluate_group(Group.model_validate(group("all", sma)), p, market=m)["X"].tolist() == \
        [False, False, True, True, True, True]
    chg = cond({"kind": "market", "index": "kospi", "name": "change_pct"}, "gt", const(3.3))
    assert evaluate_group(Group.model_validate(group("all", chg)), p, market=m)["X"].tolist() == \
        [False, True, False, False, False, False]  # 3100/3000-1 = 3.33% 만 3.3% 초과(나머지 3.23·3.13·3.03·2.94%)
    with pytest.raises(ValueError, match="지수"):
        evaluate_group(Group.model_validate(group("all", above)), p)


def test_market_dates_missing_in_index_are_false():
    p = _tiny([1] * 4, [1] * 4)
    kospi = pd.DataFrame({"close": [400000, 400000]}, index=p.close.index[:2])
    r = evaluate_group(Group.model_validate(group("all", cond(
        {"kind": "market", "index": "kospi", "name": "close"}, "gt", const(1)))), p, market={"kospi": kospi})
    assert r["X"].tolist() == [True, True, False, False]  # 지수 데이터 없는 날 = NaN → False


def test_market_filter_gates_entry_only():
    p = _tiny([1, 5, 9], [9, 5, 1])
    ent = Group.model_validate(group("all", cond(field("close"), "gt", const(0))))
    ex = Group.model_validate(group("any", cond(field("close"), "gt", const(8))))
    flt = Group.model_validate(group("all", cond(field("close"), "lt", const(6))))
    ev = evaluate(ent, ex, p, market_filter=flt)
    assert ev.entry["X"].tolist() == [True, True, False]   # 필터가 진입을 막음
    assert ev.exit["X"].tolist() == [False, False, True]   # 청산은 안 막음


def test_to_signals_default_hold_exit_wins():
    idx = pd.date_range("2024-01-01", periods=3)
    e = pd.DataFrame({"X": [True, True, False]}, index=idx)
    x = pd.DataFrame({"X": [False, True, False]}, index=idx)
    assert to_signals(Evaluation(e, x))["X"].tolist() == [BUY, SELL, HOLD]  # 둘 다면 sell


# ---------------------------------------------------------------- look-ahead 카나리아
def _rich_entry() -> Group:
    return Group.model_validate(group(
        "all",
        cond(field("close"), "gt", ind("highest", src="high", n=20)),
        cond(field("volume"), "gte", ind("sma", offset=1, mul=1.5, src="volume", n=20)),
        cond(ind("rsi", n=14), "gt", const(40)),
    ))


def _rich_exit() -> Group:
    return Group.model_validate(group(
        "any",
        cond(field("close"), "lt", ind("lowest", src="low", n=7)),
        cond(ind("sma", src="close", n=5), "cross_below", ind("sma", src="close", n=20)),
        cond(ind("bb_upper", n=20, k=2.0), "lt", field("close")),
        cond(ind("atr", n=14), "gt", ind("atr", n=14, offset=3)),
        cond(ind("vol_ratio", n=20), "gte", const(2)),
        cond(ind("change_pct", n=3), "lt", const(-5)),
    ))


@pytest.mark.parametrize("t_idx", [80, 150, 250])
def test_canary_future_tamper_does_not_change_past_signals(t_idx):
    p = synth_panel(n_days=300, n_codes=8, seed=3)
    t = p.close.index[t_idx]
    base = evaluate(_rich_entry(), _rich_exit(), p)
    fut = evaluate(_rich_entry(), _rich_exit(), tamper_after(p, t))
    pd.testing.assert_frame_equal(base.entry.loc[:t], fut.entry.loc[:t])
    pd.testing.assert_frame_equal(base.exit.loc[:t], fut.exit.loc[:t])
    assert base.entry.to_numpy().any() and base.exit.to_numpy().any()  # 카나리아가 아무것도 안 보는 게 아니게


def test_c2_value_rank_unchanged_by_future_volume():
    p = synth_panel(n_days=200, n_codes=10, seed=5)
    t = p.close.index[100]
    fut_value = p.value.copy()  # 한 종목만 t 이후 거래대금 ×1000 (전 종목 균일 변조는 순위를 안 바꿈)
    fut_value.loc[fut_value.index > t, fut_value.columns[-1]] *= 1000
    for lookback in (1, 5):
        a, b = value_rank(p.value, lookback), value_rank(fut_value, lookback)
        pd.testing.assert_frame_equal(a.loc[:t], b.loc[:t])
    assert not value_rank(p.value).loc[t:].equals(value_rank(fut_value).loc[t:])  # 변조가 미래엔 실제로 영향


def test_value_rank_condition_through_evaluator_is_causal():
    p = synth_panel(n_days=200, n_codes=10, seed=6)
    g = Group.model_validate(group("all", cond(ind("value_rank", lookback=3), "lte", const(3))))
    t = p.close.index[120]
    a = evaluate_group(g, p)
    b = evaluate_group(g, tamper_after(p, t, fields=("volume",)))
    pd.testing.assert_frame_equal(a.loc[:t], b.loc[:t])
