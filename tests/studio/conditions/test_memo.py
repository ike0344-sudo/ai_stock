"""지표 memo(그리드용 재사용) — 결과 숫자는 memo 없을 때와 같고, 같은 (지표, 파라미터) 는 한 번만 계산한다."""
import pandas as pd
import pytest

from studio.domain.conditions import indicators as I
from studio.domain.conditions.ast import Group
from studio.domain.conditions.evaluator import evaluate, evaluate_group
from tests.studio.conditions.helpers import cond, group, ind, panel_from, synth_candles, synth_panel
from tests.studio.conditions.test_evaluator import _rich_entry, _rich_exit


def _panel(gap: bool, seed: int = 9):
    c = synth_candles(n_days=300, n_codes=6, seed=seed)
    if gap:
        c["000001"] = c["000001"].drop(c["000001"].index[[100, 101, 150]])  # 거래정지 빈칸 열도 memo 를 타야 한다
    return panel_from(c)


@pytest.mark.parametrize("gap", [False, True])
def test_memo_gives_identical_results_and_second_call_is_a_hit(gap):
    p, memo = _panel(gap), {}
    base = evaluate(_rich_entry(), _rich_exit(), p)
    first = evaluate(_rich_entry(), _rich_exit(), p, memo=memo)
    second = evaluate(_rich_entry(), _rich_exit(), p, memo=memo)   # 전부 캐시 적중
    for got in (first, second):
        pd.testing.assert_frame_equal(base.entry, got.entry)
        pd.testing.assert_frame_equal(base.exit, got.exit)
    assert base.entry.to_numpy().any()


def _grid_group() -> Group:
    return Group.model_validate(group("all", cond(
        ind("sma", src="close", n={"param": "s"}), "cross_above", ind("sma", src="close", n={"param": "l"}))))


def test_grid_computes_each_distinct_indicator_once(monkeypatch):
    p, g = synth_panel(n_days=300, n_codes=6, seed=1), _grid_group()
    calls = []
    orig = I._wide
    monkeypatch.setattr(I, "_wide", lambda pn, name, prm: (calls.append(prm.get("n")), orig(pn, name, prm))[1])
    combos = [(s, l) for s in (3, 4, 5) for l in (10, 20)]
    memo = {}
    with_memo = [evaluate_group(g, p, values={"s": s, "l": l}, memo=memo) for s, l in combos]
    assert sorted(calls) == [3, 4, 5, 10, 20]                      # 조합 6개 × 지표 2개 = 12번이 아니라 서로 다른 5개만
    calls.clear()
    without = [evaluate_group(g, p, values={"s": s, "l": l}) for s, l in combos]
    assert len(calls) == 12                                          # memo 없으면 종전대로
    for a, b in zip(with_memo, without):
        pd.testing.assert_frame_equal(a, b)


def test_different_params_are_not_confused():
    p, memo = synth_panel(n_days=100, n_codes=3, seed=2), {}
    a = I.compute(p, "sma", {"n": 5}, memo=memo)
    b = I.compute(p, "sma", {"n": 6}, memo=memo)
    c = I.compute(p, "sma", {"n": 5.0}, memo=memo)                   # 5.0 → int 5 로 정규화돼 같은 키
    assert not a.equals(b) and c is a
    assert not I.compute(p, "sma", {"n": 5, "src": "high"}, memo=memo).equals(a)


def test_memo_is_single_panel_and_resets_when_panel_changes():
    p1, p2 = synth_panel(n_days=100, n_codes=3, seed=3), synth_panel(n_days=100, n_codes=3, seed=4)
    memo = {}
    I.compute(p1, "sma", {"n": 5}, memo=memo)
    got = I.compute(p2, "sma", {"n": 5}, memo=memo)                  # 다른 Panel — 옛 결과가 새어 나오면 안 됨
    pd.testing.assert_frame_equal(got, I.compute(p2, "sma", {"n": 5}))
    assert memo["__panel__"] is p2


def test_memo_size_is_capped(monkeypatch):
    monkeypatch.setattr(I, "MEMO_MAX", 4)
    p, memo = synth_panel(n_days=100, n_codes=3, seed=5), {}
    for n in range(2, 20):
        pd.testing.assert_frame_equal(I.compute(p, "sma", {"n": n}, memo=memo), I.compute(p, "sma", {"n": n}))
        assert len(memo) <= 4


def test_cached_frames_are_not_mutated_by_evaluation():
    p, memo = _panel(True), {}
    x = I.compute(p, "sma", {"n": 20}, memo=memo)
    snap = x.copy()
    evaluate(_rich_entry(), _rich_exit(), p, memo=memo)
    pd.testing.assert_frame_equal(x, snap)
    assert I.compute(p, "sma", {"n": 20}, memo=memo) is x
