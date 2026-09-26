"""테마·업종 지표(c4) — 손계산 · 주입 규칙 · 여러 그룹 소속 · 게이트 · 카나리아."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from studio.domain.conditions import indicators as I
from studio.domain.conditions.ast import Group
from studio.domain.conditions.catalog import CROSS_SECTIONAL, INDICATORS
from studio.domain.conditions.evaluator import evaluate_group
from studio.domain.conditions.ind_group import (
    GROUP_INDICATORS, GROUP_WARNING_KO, Reference, set_default_reference, warnings_for,
)
from tests.studio.conditions.helpers import cond, const, group, ind, skew_after, synth_panel

def approx(x):
    return pytest.approx(x, abs=1e-9)


CODES = ["a", "b", "c", "d"]
IDX = pd.bdate_range("2026-08-03", periods=2)


@pytest.fixture(autouse=True)
def _no_default_reference():
    set_default_reference(None)
    yield
    set_default_reference(None)


def _panel(reference=None) -> SimpleNamespace:
    """d1: 등락 a+10 b0 c−10 d+20 / 대금 a50 b30 c20 d100. d2: 전부 보합·대금 동일 1."""
    close = pd.DataFrame([[110, 100, 90, 120], [100, 100, 100, 100]], index=IDX, columns=CODES, dtype=float)
    value = pd.DataFrame([[50, 30, 20, 100], [1, 1, 1, 1]], index=IDX, columns=CODES, dtype=float)
    prev = pd.DataFrame([[100] * 4, [110, 100, 90, 120]], index=IDX, columns=CODES, dtype=float)
    ns = SimpleNamespace(close=close, open=close, high=close, low=close, volume=value, value=value, prev_close=prev)
    if reference is not None:
        ns.reference = reference
    return ns


REF = Reference({"T1": ["a", "b", "c"], "T2": ["d", "c"]}, {"a": "X", "b": "X", "c": "X", "d": "Y"})


def row0(pn, name, **params):
    return I.compute(pn, name, params).iloc[0].to_dict()


def test_theme_change_mean_and_best_of_multiple_groups():
    # T1 평균 (10+0−10)/3=0, T2 평균 (20−10)/2=5 → c 는 두 그룹 소속이라 큰 쪽(5)
    assert row0(_panel(REF), "theme_change", min_members=2) == approx({"a": 0.0, "b": 0.0, "c": 5.0, "d": 5.0})


def test_theme_value_sum_and_rank():
    pn = _panel(REF)
    assert row0(pn, "theme_value", min_members=2) == {"a": 100.0, "b": 100.0, "c": 120.0, "d": 120.0}  # T1=100, T2=120
    assert row0(pn, "theme_rank", by="value", min_members=2) == {"a": 2.0, "b": 2.0, "c": 1.0, "d": 1.0}
    assert row0(pn, "theme_rank", by="change", min_members=2) == {"a": 2.0, "b": 2.0, "c": 1.0, "d": 1.0}  # 0 < 5


def test_theme_top_count_is_the_users_count_criterion():
    pn = _panel(REF)
    # 대금 순위 d1,a2,b3,c4. m=3 → 상위 {d,a,b}, 모두 등락 ≥ 0 → T1 안 a,b = 2개 / T2 안 d = 1개
    assert row0(pn, "theme_top_count", m=3, min_change_pct=0.0, min_members=2) == {"a": 2.0, "b": 2.0, "c": 2.0, "d": 1.0}
    # 등락 ≥ 5% 만 셈(마이너스·약한 종목 제외) → a(+10)·d(+20) 만: T1=1, T2=1
    assert row0(pn, "theme_top_count", m=3, min_change_pct=5.0, min_members=2) == {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}
    # m=1 → 상위 {d} 뿐: T1=0, T2=1
    assert row0(pn, "theme_top_count", m=1, min_change_pct=0.0, min_members=2) == {"a": 0.0, "b": 0.0, "c": 1.0, "d": 1.0}


def test_rank_in_theme():
    pn = _panel(REF)
    assert row0(pn, "rank_in_theme", by="change", min_members=2) == {"a": 1.0, "b": 2.0, "c": 2.0, "d": 1.0}  # c: T1 3위, T2 2위 → 2
    assert row0(pn, "rank_in_theme", by="value", min_members=2) == {"a": 1.0, "b": 2.0, "c": 2.0, "d": 1.0}


def test_sector_change_and_rank():
    ref = Reference({}, {"a": "X", "b": "X", "c": "X", "d": "Y"})
    pn = _panel(ref)
    assert row0(pn, "sector_change", min_members=1) == approx({"a": 0.0, "b": 0.0, "c": 0.0, "d": 20.0})
    assert row0(pn, "sector_rank", by="change", min_members=1) == {"a": 2.0, "b": 2.0, "c": 2.0, "d": 1.0}
    assert row0(pn, "sector_rank", by="value", min_members=1) == {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}  # X=100, Y=100 동률


def test_min_members_gate_and_unlisted_stock_is_nan():
    pn = _panel(Reference({"T1": ["a", "b", "c"], "T2": ["d", "c"]}, {}))
    r = row0(pn, "theme_change", min_members=3)  # T2 는 2종목 → 값 없음, c 는 T1 값
    assert (r["a"], r["b"], r["c"]) == approx((0.0, 0.0, 0.0)) and np.isnan(r["d"])
    pn2 = _panel(Reference({"T1": ["a", "b"]}, {}))  # c·d 는 어느 테마에도 없음
    r2 = row0(pn2, "theme_change", min_members=2)
    assert r2["a"] == approx(5.0) and np.isnan(r2["c"]) and np.isnan(r2["d"])


def test_missing_members_on_a_day_are_ignored_not_zero():
    pn = _panel(Reference({"T": ["a", "b", "c"]}, {}))
    pn.close.iloc[0, 2] = np.nan  # c 그날 빈칸 → 평균은 a,b 만: (10+0)/2
    assert row0(pn, "theme_change", min_members=2)["a"] == approx(5.0)
    assert np.isnan(row0(pn, "theme_change", min_members=3)["a"])  # 값 있는 종목 2 < 3 → 게이트


def test_no_reference_is_an_error_not_silent_empty():
    with pytest.raises(ValueError, match="참조 데이터가 없음"):
        I.compute(_panel(), "theme_change")


def test_default_reference_and_panel_reference_precedence():
    set_default_reference(Reference({"D": ["a", "b", "c"]}, {}))
    assert row0(_panel(), "theme_change", min_members=2)["a"] == approx(0.0)  # 기본 주입
    assert row0(_panel(REF), "theme_change", min_members=2)["c"] == approx(5.0)  # Panel 속성이 우선


def test_intraday_panel_is_rejected_use_daily_prev():
    idx = pd.DatetimeIndex(["2026-08-03 09:05", "2026-08-03 09:10"])
    x = pd.DataFrame(1.0, index=idx, columns=CODES)
    pn = SimpleNamespace(close=x, open=x, high=x, low=x, volume=x, value=x, prev_close=x, reference=REF)
    with pytest.raises(ValueError, match="daily_prev"):
        I.compute(pn, "theme_change")


def test_warning_text_only_for_group_indicators():
    assert warnings_for(["sma", "theme_rank"]) == [GROUP_WARNING_KO] and "현재 기준" in GROUP_WARNING_KO
    assert warnings_for(["sma", "value_rank"]) == []
    assert GROUP_INDICATORS <= CROSS_SECTIONAL
    for n in GROUP_INDICATORS:
        assert INDICATORS[n].category == "group" and "현재 기준" in INDICATORS[n].desc_ko


def test_usable_in_evaluator_condition():
    g = Group.model_validate(group("all", cond(ind("theme_top_count", m=3, min_members=2), "gte", const(2))))
    out = evaluate_group(g, _panel(REF))
    assert out.iloc[0].to_dict() == {"a": True, "b": True, "c": True, "d": False}


def _big():
    pn = synth_panel(n_days=50, n_codes=8, seed=5)
    cols = list(pn.close.columns)
    pn.reference = Reference({"T1": cols[:4], "T2": cols[3:7]}, {c: ("X" if i < 4 else "Y") for i, c in enumerate(cols)})
    return pn


@pytest.mark.parametrize("name,params", [
    ("theme_change", {}), ("theme_value", {}), ("theme_rank", {"by": "value"}), ("theme_rank", {"by": "change"}),
    ("theme_top_count", {"m": 3, "min_change_pct": 0.0}), ("rank_in_theme", {"by": "change"}),
    ("sector_change", {}), ("sector_rank", {"by": "value"}),
])
def test_canary_no_lookahead(name, params):
    pn = _big()
    t = pn.close.index[25]
    bad = skew_after(pn, t)
    bad.reference = pn.reference
    a, b = I.compute(pn, name, params), I.compute(bad, name, params)
    pd.testing.assert_frame_equal(a.loc[:t], b.loc[:t])
    assert not a.loc[t:].iloc[1:].fillna(-1).equals(b.loc[t:].iloc[1:].fillna(-1))  # 변조가 뒤 값엔 닿음(카나리아 생존)
