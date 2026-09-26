"""optimize_service — 그리드·IS 선택·워크포워드·홀드아웃 (합성 일봉)."""
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from studio.application.backtest_service import family_hash, run_backtest, structure_hash
from studio.application.optimize_service import (
    count_grid, run_holdout_check, run_optimize, run_walkforward,
)
from studio.domain.models import Panel
from studio.domain.spec import Spec
from studio.domain.validation import (
    GridTooLargeError, OptimizeConfig, ValidationConfigError, WalkForwardConfig, split_days,
)
from studio.infrastructure.holdout_ledger import FileHoldoutLedger
from studio.infrastructure.legacy_adapter import LegacyAdapter
from studio.infrastructure.run_store import FileRunStore

from .fakes import FakeMarketData, make_panel

_HI = {"kind": "ind", "name": "highest", "params": {"src": "high", "n": {"param": "n"}}}
_LO = {"kind": "ind", "name": "lowest", "params": {"src": "low", "n": {"param": "m"}}}
_C = {"kind": "field", "name": "close"}
PARAMS = {"n": {"default": 20, "min": 10, "max": 30, "step": 5}, "m": {"default": 10, "min": 5, "max": 15, "step": 5}}


def spec_dict(**over):
    d = {
        "version": 1, "name": "최적화 테스트", "mode": "daily_portfolio",
        "period": {"start": "2022-03-01", "end": "2023-06-30"},
        "universe": {"type": "all", "exclude": ["spac", "preferred", "mega_cap"]},
        "strategy": {"source": "builder",
                     "entry": {"logic": "all", "items": [{"left": _C, "op": "gt", "right": _HI}]},
                     "exit": {"logic": "any", "items": [{"left": _C, "op": "lt", "right": _LO}]}},
        "exits": {}, "portfolio": {"max_positions": 3}, "fills": {"volume_cap_pct": None},
        "params": PARAMS, "validation": {"holdout_pct": 20, "objective": "sharpe", "min_trades": 3},
    }
    d.update(over)
    return d


def lit_dict(**over):
    """변수 칸 없이 숫자를 리터럴로 박은 전략(n=20, m=10)."""
    d = spec_dict(params={}, **over)
    d["strategy"]["entry"]["items"][0]["right"]["params"]["n"] = 20
    d["strategy"]["exit"]["items"][0]["right"]["params"]["n"] = 10
    return d


def cfg(**kw):
    return OptimizeConfig(objective=kw.pop("objective", "sharpe"), min_trades=kw.pop("min_trades", 3),
                          train_pct=kw.pop("train_pct", 60), holdout_pct=kw.pop("holdout_pct", 20), **kw)


@pytest.fixture(scope="module")
def md():
    return FakeMarketData(make_panel(n=420, seed=5))


def tamper(md_, after: pd.Timestamp, factor=10.0) -> FakeMarketData:
    p = md_.panel
    m = pd.DataFrame(np.broadcast_to((p.close.index <= after)[:, None], p.close.shape),
                     index=p.close.index, columns=p.close.columns)
    f = lambda df: df.where(m, df * factor)  # noqa: E731
    return FakeMarketData(Panel(*(f(getattr(p, k)) for k in
                                  ("open", "high", "low", "close", "volume", "value", "prev_close"))))


def _days(md_, spec):
    idx = md_.panel.close.index
    return [t.date() for t in idx[(idx >= pd.Timestamp(spec.period.start)) & (idx <= pd.Timestamp(spec.period.end))]]


# ------------------------------------------------------------------ 최적화
def test_optimize_selects_on_is_only_and_reports_oos(md):
    spec = Spec.model_validate(spec_dict())
    rec = run_optimize(spec, md, cfg())
    g = rec.grid
    assert len(g) == 15 and g["selected"].sum() == 1
    sel = g[g["selected"]].iloc[0]
    assert sel["rank_is"] == 1 and sel["is_sharpe"] == g["is_sharpe"].max()  # IS 최고가 뽑혔다
    # OOS 가 더 좋은 조합이 있어도 안 뽑혔다는 걸 보이려면 있어야 하는 게 아니라, 뽑힌 기준이 IS 인지만 확인
    o = rec.summary["optimize"]
    assert o["selected"]["params"] == {"n": int(sel["n"]), "m": int(sel["m"])}
    assert o["selected"]["selected_by"] == "IS 목표값만 사용" and o["n_combos"] == 15
    days = _days(md, spec)
    segs = split_days(days, 20, 60)
    assert o["segments"]["is"][:2] == [str(segs.is_days[0]), str(segs.is_days[-1])]
    assert o["segments"]["oos"][2] == len(segs.oos_days) and o["segments"]["holdout"][2] == len(segs.holdout_days)
    assert rec.meta["kind"] == "optimize" and rec.meta["holdout_used"] is False
    assert any("홀드아웃" in w and "쓰지 않았다" in w for w in rec.warnings)
    # 기록: 선택 조합의 실행이 최적화 구간(홀드아웃 제외)까지만 돌았다
    assert rec.equity["ts"].max() <= pd.Timestamp(segs.opt_days[-1])
    assert not rec.trades.empty and pd.Timestamp(segs.holdout_days[0]) > rec.trades["exit_ts"].max()


def test_canary_oos_and_holdout_tampering_cannot_change_selection(md):
    spec = Spec.model_validate(spec_dict())
    base = run_optimize(spec, md, cfg())
    segs = split_days(_days(md, spec), 20, 60)
    bad = run_optimize(spec, tamper(md, pd.Timestamp(segs.is_days[-1])), cfg())  # IS 이후(OOS+홀드아웃) 전부 ×10
    isc = [c for c in base.grid.columns if c.startswith("is_")] + ["n", "m", "status", "rank_is", "selected"]
    pd.testing.assert_frame_equal(base.grid[isc], bad.grid[isc])  # IS 점수·순위·선택 불변
    assert base.summary["optimize"]["selected"]["params"] == bad.summary["optimize"]["selected"]["params"]
    oosc = [c for c in base.grid.columns if c.startswith("oos_")]
    assert not base.grid[oosc].equals(bad.grid[oosc])  # 변조가 OOS 는 실제로 바꿨다(카나리아가 둔감하지 않다)


def test_canary_holdout_data_is_never_loaded_by_optimize(md):
    spec = Spec.model_validate(spec_dict())
    base = run_optimize(spec, md, cfg())
    segs = split_days(_days(md, spec), 20, 60)
    bad = run_optimize(spec, tamper(md, pd.Timestamp(segs.oos_days[-1])), cfg())  # 홀드아웃만 ×10
    pd.testing.assert_frame_equal(base.grid, bad.grid)  # IS·OOS 열 전부 동일
    pd.testing.assert_frame_equal(base.equity, bad.equity)


def test_grid_too_large_and_count(md):
    big = spec_dict(params={"n": {"default": 20, "min": 1, "max": 100, "step": 1},
                            "m": {"default": 10, "min": 1, "max": 60, "step": 1}})
    spec = Spec.model_validate(big)
    assert count_grid(spec) == 6000 and count_grid(Spec.model_validate(spec_dict())) == 15
    assert count_grid(Spec.model_validate(spec_dict()), vary=["n"]) == 5
    with pytest.raises(GridTooLargeError):
        run_optimize(spec, md, cfg())


def test_optimize_config_errors(md):
    no_params = Spec.model_validate(lit_dict())
    with pytest.raises(ValidationConfigError, match="변수"):
        run_optimize(no_params, md, cfg())
    fixed = Spec.model_validate(spec_dict(params={"n": {"default": 20}, "m": {"default": 10}}))  # 범위 없음 = 고정
    with pytest.raises(ValidationConfigError, match="조합이 1개"):
        run_optimize(fixed, md, cfg())
    with pytest.raises(ValidationConfigError, match="최소 거래"):
        run_optimize(Spec.model_validate(spec_dict()), md, cfg(min_trades=10_000))


def test_invalid_combos_are_kept_in_table_and_excluded():
    md_ = FakeMarketData(make_panel(n=420, seed=5))
    d = spec_dict(strategy={"source": "legacy", "name": "ma_crossover",
                            "params": {"short_window": {"param": "s"}, "long_window": {"param": "l"}}},
                  params={"s": {"default": 5, "min": 3, "max": 9, "step": 3}, "l": {"default": 6, "min": 6, "max": 12, "step": 3}})
    rec = run_optimize(Spec.model_validate(d), md_, cfg(min_trades=1), legacy=LegacyAdapter())
    bad = rec.grid[rec.grid["status"].str.startswith("invalid")]
    assert len(rec.grid) == 9 and len(bad) == 3  # s>=l: (6,6) (9,6) (9,9)
    assert all(b["s"] >= b["l"] for _, b in bad.iterrows())
    assert rec.summary["optimize"]["n_invalid"] == len(bad)
    assert rec.grid[rec.grid["selected"]].iloc[0]["status"] == "ok"
    assert any("무효 조합" in w for w in rec.warnings)


def test_criteria_judged_on_oos_and_saved_in_spec(md):
    d = spec_dict(validation={"holdout_pct": 20, "objective": "sharpe", "min_trades": 3,
                              "criteria": {"sharpe": 99.0, "max_drawdown_pct": 100.0}})
    spec = Spec.model_validate(d)
    rec = run_optimize(spec, md)  # config 는 Spec.validation 에서
    crit = {c["metric"]: c for c in rec.summary["optimize"]["criteria_on_oos"]}
    assert not crit["sharpe"]["passed"] and crit["max_drawdown_pct"]["passed"]
    assert rec.spec.validation.criteria == {"sharpe": 99.0, "max_drawdown_pct": 100.0}  # 기준은 실행 전 명세에 있다


def test_run_store_roundtrip_with_grid_and_folds(md, tmp_path):
    spec = Spec.model_validate(spec_dict())
    rec = run_optimize(spec, md, cfg())
    store = FileRunStore(tmp_path)
    rid = store.save(rec)
    back = store.load(rid)
    pd.testing.assert_frame_equal(back.grid, rec.grid)
    assert back.folds is None and (tmp_path / rid / "grid.parquet").exists() and not (tmp_path / rid / "folds.json").exists()
    wf = run_walkforward(spec, md, WalkForwardConfig(120, 40, base=cfg(min_trades=1)))
    rid2 = store.save(wf)
    back2 = store.load(rid2)
    assert back2.folds == wf.folds and (tmp_path / rid2 / "folds.json").exists()
    pd.testing.assert_frame_equal(back2.grid, wf.grid)


def test_progress_cancel_propagates(md):
    def prog(stage, frac):
        if stage == "grid" and frac > 0.3:
            raise RuntimeError("취소 요청으로 중단")
    with pytest.raises(RuntimeError, match="취소"):
        run_optimize(Spec.model_validate(spec_dict()), md, cfg(), prog)


def test_holiday_calendar_counts_trading_days(md):
    hol = {dt.date(2022, 5, 5), dt.date(2022, 6, 6), dt.date(2022, 9, 12)}
    idx = md.panel.close.index
    keep = ~pd.Series(idx).dt.date.isin(hol).to_numpy()
    p = md.panel
    md2 = FakeMarketData(Panel(*(getattr(p, k).loc[keep] for k in ("open", "high", "low", "close", "volume", "value", "prev_close"))))

    class Cal:
        def trading_days(self, start, end):
            return [t.date() for t in md2.panel.close.index if start <= t.date() <= end]

    spec = Spec.model_validate(spec_dict())
    rec = run_optimize(spec, md2, cfg(), calendar=Cal())
    days = Cal().trading_days(spec.period.start, spec.period.end)
    assert not set(days) & hol
    segs = split_days(days, 20, 60)
    seg = rec.summary["optimize"]["segments"]
    assert (seg["is"][2], seg["oos"][2], seg["holdout"][2]) == (len(segs.is_days), len(segs.oos_days), len(segs.holdout_days))


# ------------------------------------------------------------------ 워크포워드
def test_walkforward_folds_stitching_and_independent_recompute(md):
    spec = Spec.model_validate(spec_dict())
    wcfg = WalkForwardConfig(120, 40, base=cfg(min_trades=1))
    rec = run_walkforward(spec, md, wcfg)
    f = rec.folds["folds"]
    days = _days(md, spec)
    segs = split_days(days, 20, 70)
    assert len(f) >= 2 and rec.summary["walkforward"]["n_folds"] == len(f)
    for a, b in zip(f, f[1:]):  # 검증 구간끼리 안 겹치고 학습은 검증 앞
        assert a["test"][1] < b["test"][0]
    assert all(x["train"][1] < x["test"][0] for x in f)
    assert pd.Timestamp(f[-1]["test"][1]) <= pd.Timestamp(segs.opt_days[-1])  # 홀드아웃 안 침범
    # 이은 곡선 길이 = 검증 거래일 합
    n_test = sum(len(pd.bdate_range(x["test"][0], x["test"][1])) for x in f if "oos" in x)
    assert len(rec.equity) == n_test
    # 독립 재계산: 첫 폴드에서 고른 변수로 최적화 구간 전체를 직접 돌려 검증 구간 수익률을 비교
    x = f[0]
    opt_spec = spec.model_copy(update={"period": spec.period.model_copy(update={"end": segs.opt_days[-1]})})
    direct = run_backtest(opt_spec, md, None, overrides=x["params"])
    e = direct.equity.set_index("ts")["equity"]
    t0, t1 = pd.Timestamp(x["test"][0]), pd.Timestamp(x["test"][1])
    base = e[e.index < t0].iloc[-1]
    expect = (e[(e.index >= t0) & (e.index <= t1)].iloc[-1] / base - 1) * 100
    assert x["oos"]["total_return_pct"] == pytest.approx(expect, rel=1e-9)
    st = rec.equity[(rec.equity["ts"] >= t0) & (rec.equity["ts"] <= t1)]["equity"]
    assert (st.iloc[-1] / spec.portfolio.initial_capital - 1) * 100 == pytest.approx(expect, rel=1e-9)  # 첫 폴드는 원금에서 시작
    # WFE = 이은 곡선 연환산 ÷ 폴드 IS 연환산 평균
    done = [q for q in f if "oos" in q]
    is_mean = np.mean([q["is"]["cagr_pct"] for q in done])
    w = rec.summary["walkforward"]
    if is_mean > 0:
        assert w["wfe"] == pytest.approx(w["oos_metrics"]["cagr_pct"] / is_mean)
    assert set(w["params_drift"]) == {"n", "m"} and rec.meta["kind"] == "walkforward"


def test_walkforward_anchored_train_starts_fixed(md):
    spec = Spec.model_validate(spec_dict())
    rec = run_walkforward(spec, md, WalkForwardConfig(100, 40, mode="anchored", base=cfg(min_trades=1)))
    starts = {x["train"][0] for x in rec.folds["folds"]}
    assert len(starts) == 1 and len(rec.folds["folds"]) >= 2


def test_walkforward_too_short_period_errors(md):
    with pytest.raises(ValidationConfigError, match="폴드가 하나도"):
        run_walkforward(Spec.model_validate(spec_dict()), md, WalkForwardConfig(400, 40, base=cfg()))


# ------------------------------------------------------------------ 홀드아웃
def test_holdout_check_ledger_and_second_open_warns(md, tmp_path):
    ledger = FileHoldoutLedger(tmp_path / "holdout_ledger.json")
    spec = Spec.model_validate(spec_dict(exits={"stop_loss_pct": 7}))  # 손절 7% 리터럴
    opt = run_optimize(spec, md, cfg())
    assert ledger.all_entries() == {}  # 최적화는 홀드아웃을 열지 않는다(장부 기록 없음)
    params = opt.summary["optimize"]["selected"]["params"]
    r1 = run_holdout_check(spec, params, md, ledger, cfg(), source_run_id="20260925-000000-abcdef")
    segs = split_days(_days(md, spec), 20, 60)
    h = r1.summary["holdout"]
    assert h["nth_open"] == 1 and h["period"][:2] == [str(segs.holdout_days[0]), str(segs.holdout_days[-1])]
    assert not any("번째 열었다" in w for w in r1.warnings) and r1.meta["kind"] == "holdout_check"
    assert r1.equity["ts"].min() >= pd.Timestamp(segs.holdout_days[0]) and r1.equity["ts"].max() <= pd.Timestamp(segs.holdout_days[-1])
    sh = structure_hash(spec)
    assert len(ledger.history(sh)) == 1 and ledger.history(sh)[0]["params"] == params
    r2 = run_holdout_check(spec, {"n": 10, "m": 5}, md, ledger, cfg())  # 변수 값이 달라도 같은 구조 → 두 번째 열람
    assert r2.summary["holdout"]["nth_open"] == 2 and r2.summary["holdout"]["nth_open_structure"] == 2
    assert any("2번째 열었다" in w and "엿보기" in w for w in r2.warnings)  # 경고만, 막지는 않는다
    assert len(ledger.history(sh)) == 2 and len(r2.summary["holdout"]["previous_opens"]) == 1
    # 결과를 보고 손절을 7% → 8% 로 고쳐 다시 열면: 구조 해시는 달라도 **열람 횟수는 골격 기준**이라 3번째(lead 판정)
    lit = Spec.model_validate(spec_dict(exits={"stop_loss_pct": 8}))
    assert structure_hash(lit) != sh and family_hash(lit) == family_hash(spec)
    r3 = run_holdout_check(lit, {"n": 10, "m": 5}, md, ledger, cfg())
    h3 = r3.summary["holdout"]
    assert h3["nth_open"] == 3 and h3["nth_open_structure"] == 1 and len(h3["previous_opens"]) == 2
    assert any("3번째 열었다" in w and "구조 해시 기준으로는 1번째" in w for w in r3.warnings)
    # 손절을 아예 떼거나 붙이는 것(None <-> 숫자)도 같은 골격 — 4번째
    off = Spec.model_validate(spec_dict())
    r4 = run_holdout_check(off, {"n": 10, "m": 5}, md, ledger, cfg())
    assert r4.summary["holdout"]["nth_open"] == 4
    # 연산자가 다른 전략은 다른 골격 — 1번째
    other = spec_dict()
    other["strategy"]["entry"]["items"][0]["op"] = "lt"
    r5 = run_holdout_check(Spec.model_validate(other), {"n": 10, "m": 5}, md, ledger, cfg())
    assert r5.summary["holdout"]["nth_open"] == 1 and not any("번째 열었다" in w for w in r5.warnings)


def test_holdout_requires_a_holdout_and_daily_mode(md, tmp_path):
    ledger = FileHoldoutLedger(tmp_path / "l.json")
    spec = Spec.model_validate(spec_dict())
    with pytest.raises(ValidationConfigError, match="홀드아웃 구간이 없다"):
        run_holdout_check(spec, {"n": 20, "m": 10}, md, ledger, cfg(holdout_pct=0))
    assert ledger.all_entries() == {}  # 실패한 열기는 기록하지 않는다


def test_ledger_concurrent_safe(tmp_path):
    """12스레드 동시 기록 × 여러 판. Windows 에선 열려 있는(삭제 대기 중인) 파일에 대한 open(O_EXCL)·replace·read 가
    PermissionError 로 실패해 기록이 빠졌다(2026-09-25 실측: 판당 수건) — 재시도로 막고, 실패하면 예외가 밖으로 나와야 한다."""
    import threading
    errors: list[BaseException] = []
    for rnd in range(15):
        ledger = FileHoldoutLedger(tmp_path / f"l{rnd}.json")

        def work(i, ledger=ledger):
            try:
                ledger.record_open("h", {"i": i, "opened_at": "x", "family_hash": "f"})
                ledger.history("h")  # 잠금 밖 읽기가 교체와 겹치는 경우도
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        ts = [threading.Thread(target=work, args=(i,)) for i in range(12)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert sorted(e["i"] for e in ledger.history("h")) == list(range(12)), (rnd, errors[:2])
        assert len(ledger.family_history("f")) == 12 and not (tmp_path / f"l{rnd}.lock").exists()
    assert errors == []


def test_ledger_lock_timeout_raises_not_silent(tmp_path, monkeypatch):
    """잠금을 못 얻으면 조용히 넘기지 않고 예외 — 열람 기록이 빠지면 '몇 번째 열람' 경고가 틀려진다."""
    from studio.infrastructure import holdout_ledger as hl
    monkeypatch.setattr(hl, "_WAIT_SEC", 0.3)
    ledger = FileHoldoutLedger(tmp_path / "l.json")
    (tmp_path / "l.lock").write_text("")  # 살아 있는(방금 만든) 다른 소유자의 잠금
    with pytest.raises(TimeoutError):
        ledger.record_open("h", {"opened_at": "x"})
    assert ledger.history("h") == []


# ------------------------------------------------------------------ 일반 백테스트에 붙은 견고성·판정
def test_backtest_summary_has_robustness_and_criteria(md):
    d = lit_dict(validation={"holdout_pct": 20, "objective": "sharpe", "min_trades": 3, "criteria": {"num_trades": 1}})
    rec = run_backtest(Spec.model_validate(d), md)
    r = rec.summary["robustness"]
    assert len(r["cost_sensitivity"]) == 6 and r["monte_carlo"]["seed"] == 42 and r["concentration"]["by_code"]
    k1 = {x["mult"]: x for x in r["cost_sensitivity"]}[1.0]["net_pnl"]
    assert k1 == pytest.approx(rec.trades["net_pnl"].sum(), rel=1e-9)
    assert rec.summary["criteria"][0]["metric"] == "num_trades" and rec.summary["criteria"][0]["passed"]


def test_structure_hash_judgement():
    """structure_hash 는 파라미터 '값'만 뺀다 — 리터럴 상수를 바꾸면 달라진다(그래서 family_hash 를 같이 쓴다)."""
    base = Spec.model_validate(spec_dict())
    other_default = Spec.model_validate(spec_dict(params={**PARAMS, "n": {"default": 25, "min": 10, "max": 30, "step": 5}}))
    assert structure_hash(base) == structure_hash(other_default) == structure_hash(
        base.model_copy(update={"name": "다른 이름"}))
    literal = spec_dict()
    literal["strategy"] = {"source": "builder", "exit": {"logic": "any", "items": []}, "entry": {"logic": "all", "items": [
        {"left": _C, "op": "gt", "right": {"kind": "ind", "name": "highest", "params": {"src": "high", "n": 20}}}]}}
    literal["params"] = {}
    lit2 = {**literal, "strategy": {**literal["strategy"], "entry": {"logic": "all", "items": [
        {"left": _C, "op": "gt", "right": {"kind": "ind", "name": "highest", "params": {"src": "high", "n": 40}}}]}}}
    a, b = Spec.model_validate(literal), Spec.model_validate(lit2)
    assert structure_hash(a) != structure_hash(b) and family_hash(a) == family_hash(b)
    # 청산 규칙 켜고 끄기(None <-> 숫자)와 값 변경은 같은 골격, 조건식 연산 변경은 다른 골격
    e0 = Spec.model_validate({**literal, "exits": {}})
    e1 = Spec.model_validate({**literal, "exits": {"stop_loss_pct": 7}})
    e2 = Spec.model_validate({**literal, "exits": {"stop_loss_pct": 8, "trailing_stop_pct": 10}})
    assert structure_hash(e0) != structure_hash(e1) and family_hash(e0) == family_hash(e1) == family_hash(e2)
    op_changed = Spec.model_validate({**literal, "strategy": {**literal["strategy"], "entry": {"logic": "all", "items": [
        {"left": _C, "op": "lt", "right": {"kind": "ind", "name": "highest", "params": {"src": "high", "n": 20}}}]}}})
    assert family_hash(op_changed) != family_hash(a)  # 연산이 바뀌면 다른 전략 골격


# ------------------------------------------------------------------ 작업 처리기 · 맥락
def test_restrict_context_drops_rows_after_end(md):
    from studio.application.backtest_service import prepare_context, restrict_context
    spec = Spec.model_validate(spec_dict())
    full = prepare_context(spec, md)
    short = spec.model_copy(update={"period": spec.period.model_copy(update={"end": dt.date(2022, 12, 30)})})
    r = restrict_context(full, short)
    assert r.panel.close.index.max() <= pd.Timestamp("2022-12-30") < full.panel.close.index.max()
    assert r.in_period.sum() < full.in_period.sum() and r.key != full.key


class _Ctx:
    def __init__(self, payload, cancel=False):
        self.payload, self._cancel, self.stages, self.run_id = payload, cancel, [], None

    def is_cancelled(self):
        return self._cancel

    def progress(self, pct, stage="", message="", **kw):
        self.stages.append((stage, pct))

    def set_run_id(self, rid):
        self.run_id = rid


def test_job_handlers_end_to_end(md, tmp_path, monkeypatch):
    from studio.application import jobs
    ledger = FileHoldoutLedger(tmp_path / "l.json")
    store = FileRunStore(tmp_path / "runs")
    monkeypatch.setattr(jobs, "deps_factory", lambda: jobs.Deps(market_data=md, run_store=store, holdout_ledger=ledger))
    spec = spec_dict()
    rid = "20260925-120000-aaaaaa"
    c = _Ctx({"spec": spec, "run_id": rid, "config": {"train_pct": 60, "split_date": None}})
    assert jobs.run_optimize_job(c) == {"run_id": rid} and c.run_id == rid and c.stages[-1] == ("done", 100)
    rec = store.load(rid)
    assert rec.grid is not None and rec.summary["optimize"]["objective"] == "sharpe"
    rid2 = "20260925-120001-bbbbbb"
    c2 = _Ctx({"spec": spec, "run_id": rid2, "walkforward": {"train_days": 120, "test_days": 40},
               "config": {"min_trades": 1}})
    jobs.run_walkforward_job(c2)
    assert store.load(rid2).folds["config"]["mode"] == "rolling"
    rid3 = "20260925-120002-cccccc"
    c3 = _Ctx({"spec": spec, "run_id": rid3, "overrides": rec.summary["optimize"]["selected"]["params"],
               "source_run_id": rid, "config": {"train_pct": 60}})
    jobs.run_holdout_check_job(c3)
    assert store.load(rid3).summary["holdout"]["nth_open"] == 1 and len(ledger.all_entries()) == 1
    # 취소: 진행 콜백이 예외를 던져 작업이 멈춘다
    with pytest.raises(RuntimeError, match="취소"):
        jobs.run_optimize_job(_Ctx({"spec": spec, "run_id": "20260925-120003-dddddd"}, cancel=True))
    # 장부가 없으면 홀드아웃 작업은 거절
    monkeypatch.setattr(jobs, "deps_factory", lambda: jobs.Deps(market_data=md, run_store=store))
    with pytest.raises(RuntimeError, match="장부"):
        jobs.run_holdout_check_job(_Ctx({"spec": spec, "run_id": "20260925-120004-eeeeee", "overrides": {}}))


# ------------------------------------------------------------------ 병렬 메모리 상한
def test_plan_workers_pure_function_and_estimate():
    from studio.application.optimize_service import estimate_worker_bytes
    from studio.infrastructure import wiring
    G = 1024 ** 3
    assert wiring.plan_workers(20 * G, 2 * G, 6 * G) == 7  # (20-6)/2
    assert wiring.plan_workers(7 * G, 2 * G, 6 * G) == 1  # 예비를 못 채우면 최소 1(직렬)
    assert wiring.plan_workers(4 * G, 2 * G, 6 * G) == 1  # 가용 < 예비여도 최소 1
    assert wiring.plan_workers(100 * G, 1, 6 * G) >= 1
    # 실측 보정값: 패널 3.77M 셀 + 훑는 값 20개(변수 2개 × 10) → 약 2.5GB(피크 1.25GB + memo 24표 + 고정)
    est = estimate_worker_bytes(3_769_497, {"short": list(range(10)), "long": list(range(10))})
    assert 2.0 * G < est < 3.2 * G
    # 값이 하나뿐인(고정) 변수는 표를 안 늘린다, memo 상한 64 표에서 멈춘다
    assert estimate_worker_bytes(1_000_000, {"a": [1]}) < estimate_worker_bytes(1_000_000, {"a": list(range(10))}) < \
        estimate_worker_bytes(1_000_000, {"a": list(range(500))}) == estimate_worker_bytes(1_000_000, {"a": list(range(900))})
    assert wiring.available_bytes() > 0


def test_memory_limit_forces_serial_with_warning_and_never_starts_a_pool(md):
    spec = Spec.model_validate(spec_dict())
    calls = []

    def limit(per_worker):  # 가짜 메모리: 워커 1개도 못 돌릴 만큼 부족 → 직렬
        calls.append(per_worker)
        return 1

    # bootstrap 이 잘못된 이름이라 풀이 시작되면 실패한다 — 직렬로 돌았다는 증거
    rec = run_optimize(spec, md, cfg(), workers=4, bootstrap="no.such.module:fn", memory_limit=limit)
    assert calls and calls[0] > 0 and rec.meta["workers"] == 1
    assert any("메모리 부족으로 직렬" in w for w in rec.warnings)
    # 일부만 허락: 4 → 2 (경고 문구), 요청 1개면 메모리 함수를 부르지도 않는다
    from studio.application.optimize_service import _cap_workers
    w = []
    assert _cap_workers(4, lambda b: 2, 5 * 1024 ** 3, w) == 2 and "4개 → 2개" in w[0]
    assert _cap_workers(1, lambda b: 1 / 0, 1, w) == 1 and _cap_workers(4, None, 1, w) == 4
    assert _cap_workers(3, lambda b: 8, 1, w) == 3 and len(w) == 1  # 여유 충분 → 그대로, 경고 없음


# ------------------------------------------------------------------ 실데이터에서만 드러난 것들(monitoring 편지 2026-09-26)
def test_jsonable_handles_numpy_bool_and_summary_dumps_with_numpy_metrics():
    import json

    from studio.application.backtest_service import _jsonable
    from studio.domain.validation import evaluate_criteria
    assert json.dumps(_jsonable({"a": np.bool_(True), "b": np.float64("nan"), "c": [np.int64(3)]})) == '{"a": true, "b": null, "c": [3]}'
    crit = evaluate_criteria({"sharpe": 1.0}, {"sharpe": np.float64(1.5)})
    assert json.dumps(_jsonable(crit))  # passed 가 np.bool_ 이어도(합성 데이터는 파이썬 float 라 못 잡았다) 저장 가능


def test_holdout_ledger_entry_keeps_run_id_and_walkforward_trades_have_mfe_mae(md, tmp_path):
    ledger = FileHoldoutLedger(tmp_path / "l.json")
    spec = Spec.model_validate(spec_dict())
    rid = "20260926-090000-abcdef"
    run_holdout_check(spec, {"n": 20, "m": 10}, md, ledger, cfg(), run_id=rid)
    assert [e["run_id"] for es in ledger.all_entries().values() for e in es] == [rid]
    wf = run_walkforward(spec, md, WalkForwardConfig(120, 40, base=cfg(min_trades=1)))
    assert {"mfe_pct", "mae_pct"} <= set(wf.trades.columns) and wf.trades["mfe_pct"].notna().any()


def test_hashes_ignore_new_condition_defaults_but_see_real_changes():
    """c1 이 조건 AST 에 넣은 칸(tf·hold·within·right·negate)의 **기본값**은 해시에 안 들어간다 — 옛 명세의 해시가 그대로.
    기본값이 아닌 값(hold=2, tf=daily_prev)은 다른 전략이라 해시가 달라진다."""
    from studio.application.backtest_service import _strip_new_defaults
    spec = Spec.model_validate(lit_dict())
    dump = spec.model_dump(mode="json")
    text = json.dumps(_strip_new_defaults(dump))
    for k in ('"tf"', '"hold"', '"within"', '"negate"'):
        assert k not in text  # 기본값이라 사라졌다
    assert '"right"' in text  # 오른쪽 값이 있는 조건의 right 는 남는다
    d2 = lit_dict()
    d2["strategy"]["entry"]["items"][0]["hold"] = 2
    assert structure_hash(Spec.model_validate(d2)) != structure_hash(spec)
    d3 = lit_dict()
    d3["strategy"]["entry"]["items"][0]["left"]["tf"] = "bar"  # 명시해도 기본값 = 같은 해시
    assert structure_hash(Spec.model_validate(d3)) == structure_hash(spec)
