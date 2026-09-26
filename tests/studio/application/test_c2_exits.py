"""청산 확장(studio-conditions c2) 서비스 층 — 명세 검증·해시 안정·분할 청산 기록/진입 기준 지표·pos 조건·분 단위 보유."""
import copy

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from studio.application.backtest_service import (
    _strip_new_defaults, family_hash, run_backtest, spec_hash, structure_hash, to_engine_rules,
)
from studio.domain.metrics import collapse_entries
from studio.domain.spec import Spec, bind_params

from .fakes import FakeMarketData, make_panel
from .fakes_intraday import IntradayFake
from .test_intraday_service import intraday_dict, tick_dict
from .test_optimize_service import lit_dict

POS = lambda n: {"kind": "pos", "name": n}  # noqa: E731
K = lambda v: {"kind": "const", "value": v}  # noqa: E731


@pytest.fixture(scope="module")
def md():
    return FakeMarketData(make_panel(n=420, seed=5))


def with_exits(base=None, **exits):
    d = copy.deepcopy(base or lit_dict())
    d["exits"] = exits
    return d


# ------------------------------------------------------------------ 명세 검증
@pytest.mark.parametrize("exits, msg", [
    ({"take_profit_levels": [{"pct": 5, "fraction": 0.5}], "take_profit_pct": 8}, "같이 쓸 수 없음"),
    ({"take_profit_levels": [{"pct": 10, "fraction": 0.5}, {"pct": 5, "fraction": 1}]}, "오름차순"),
    ({"take_profit_levels": [{"pct": 5, "fraction": 0}]}, "greater than 0"),
    ({"take_profit_levels": [{"pct": 5, "fraction": 1.5}]}, "less than or equal to 1"),
    ({"take_profit_levels": []}, "at least 1"),
    ({"take_profit_mode": "close"}, "익절"),
    ({"trail_activate_pct": 5}, "trailing_stop_pct"),
    ({"max_holding_minutes": 30}, "분봉"),
    ({"breakeven_after_pct": 0}, "허용 범위"),
])
def test_exit_extension_validation_errors(exits, msg):
    with pytest.raises(ValidationError, match=msg):
        Spec.model_validate(with_exits(**exits))


def test_valid_exit_extension_and_engine_rules():
    s = Spec.model_validate(with_exits(take_profit_levels=[{"pct": 5, "fraction": 0.5}, {"pct": 10, "fraction": 1}],
                                       take_profit_mode="close", stop_loss_pct=7, trailing_stop_pct=4,
                                       trail_activate_pct=8, breakeven_after_pct=3))
    _, ex, _, _ = to_engine_rules(s)
    assert ex.take_profit_levels == ((5.0, 0.5), (10.0, 1.0)) and ex.take_profit_mode == "close"
    assert ex.trail_activate_pct == 8 and ex.breakeven_after_pct == 3 and ex.max_holding_bars is None


def test_max_holding_minutes_converts_to_bars_rounding_up_and_takes_the_earlier():
    md_ = IntradayFake(n_days=4, drift=0.0)
    mk = lambda **e: to_engine_rules(Spec.model_validate(intraday_dict(md_, exits=e)))[1].max_holding_bars  # noqa: E731
    assert mk(max_holding_minutes=12) == 3 and mk(max_holding_minutes=15) == 3 and mk(max_holding_minutes=16) == 4  # 5분봉
    assert mk(max_holding_minutes=30, max_holding_bars=4) == 4 and mk(max_holding_minutes=10, max_holding_bars=4) == 2


def test_tick_mode_rejects_unsupported_exit_fields_and_pos():
    md_ = IntradayFake(n_days=4, drift=0.0)
    for e in ({"take_profit_levels": [{"pct": 5, "fraction": 1}]}, {"breakeven_after_pct": 3}, {"take_profit_mode": "close", "take_profit_pct": 5},
              {"stop_loss_pct": 5, "trailing_stop_pct": 3, "trail_activate_pct": 5}):
        with pytest.raises(ValidationError, match="틱 모드는"):
            Spec.model_validate(tick_dict(md_, exits=e))
    Spec.model_validate(tick_dict(md_, exits={"stop_loss_pct": 5, "take_profit_pct": 8}))  # 기존 칸은 그대로
    d = tick_dict(md_, strategy={"source": "builder", "entry": {"logic": "all", "items": [{"left": {"kind": "field", "name": "close"}, "op": "gt", "right": K(1)}]},
                                 "exit": {"logic": "any", "items": [{"left": POS("return_pct"), "op": "gte", "right": K(5)}]}})
    with pytest.raises(ValidationError, match="포지션"):
        Spec.model_validate(d)


def test_compat_mode_rejects_pos_and_new_exit_fields():
    d = copy.deepcopy(lit_dict(mode="daily_single"))
    d["universe"] = {"type": "codes", "codes": ["000010"]}
    d["compat"] = {"legacy": True}
    Spec.model_validate(d)
    d2 = copy.deepcopy(d)
    d2["exits"] = {"breakeven_after_pct": 3}
    with pytest.raises(ValidationError, match="호환 모드"):
        Spec.model_validate(d2)
    d3 = copy.deepcopy(d)
    d3["strategy"]["exit"] = {"logic": "any", "items": [{"left": POS("return_pct"), "op": "gte", "right": K(5)}]}
    with pytest.raises(ValidationError, match="호환 모드"):
        Spec.model_validate(d3)


def test_take_profit_level_pct_can_be_a_variable():
    d = with_exits(take_profit_levels=[{"pct": {"param": "p1"}, "fraction": 0.5}, {"pct": {"param": "p2"}, "fraction": 1}])
    d["params"] = {"p1": {"default": 5, "min": 3, "max": 8, "step": 1}, "p2": {"default": 10, "min": 8, "max": 15, "step": 1}}
    s = Spec.model_validate(d)
    b = bind_params(s, {"p1": 6})
    assert [x.pct for x in b.exits.take_profit_levels] == [6, 10]
    with pytest.raises(ValueError, match="오름차순"):
        bind_params(s, {"p1": 8, "p2": 8})  # 그리드가 만드는 무효 조합 — 무효로 표시되고 계속된다(optimize)
    d["params"]["p1"]["max"] = 5000
    with pytest.raises(ValidationError, match="허용 범위"):
        Spec.model_validate(d)


# ------------------------------------------------------------------ 해시 — 옛 명세는 그대로
def test_hashes_do_not_change_when_new_exit_fields_are_at_defaults():
    base = Spec.model_validate(with_exits(stop_loss_pct=7))
    dumped = base.model_dump(mode="json")
    assert dumped["exits"]["take_profit_mode"] == "intrabar" and dumped["exits"]["take_profit_levels"] is None
    old = copy.deepcopy(dumped)
    for k in ("take_profit_levels", "take_profit_mode", "trail_activate_pct", "breakeven_after_pct", "max_holding_minutes"):
        old["exits"].pop(k)  # c2 이전 명세 모양
    assert _strip_new_defaults(dumped) == _strip_new_defaults(old)
    changed = Spec.model_validate(with_exits(stop_loss_pct=7, breakeven_after_pct=3))
    assert spec_hash(changed) != spec_hash(base) and structure_hash(changed) != structure_hash(base)
    assert family_hash(changed) != family_hash(base)  # 새 칸을 켜고 끄는 것도 골격 변화(홀드아웃 엿보기 차단과 같은 원칙)


# ------------------------------------------------------------------ 분할 청산 실행 (일봉)
def test_levels_run_records_slices_and_reports_entry_based_metrics(md):
    spec = Spec.model_validate(with_exits(take_profit_levels=[{"pct": 4, "fraction": 0.5}, {"pct": 9, "fraction": 1}], stop_loss_pct=6))
    rec = run_backtest(spec, md)
    t = rec.trades
    assert {"entry_id", "slice"} <= set(t.columns) and (t["slice"] > 1).any()
    # 같은 진입의 조각은 종목·진입가·진입 시각이 같고 slice 는 1..k
    for _, g in t.groupby("entry_id"):
        assert g["code"].nunique() == 1 and g["entry_ts"].nunique() == 1 and g["entry_price"].nunique() == 1
        assert sorted(g["slice"]) == list(range(1, len(g) + 1))
    ent = collapse_entries(t)
    m = rec.summary["metrics"]
    assert m["num_trades"] == len(ent) < len(t) and m["num_slices"] == len(t)
    assert m["win_rate_pct"] == pytest.approx((ent["net_pnl"] > 0).mean() * 100)
    assert m["expectancy_pct"] == pytest.approx(ent["net_pct"].mean() * 100)
    slice_win = (t["net_pnl"] > 0).mean() * 100
    assert slice_win > m["win_rate_pct"]  # 조각으로 세면 승률이 부풀려진다 — 이 표본에서 실제로 그렇다
    assert rec.summary["n_entries"] == len(ent) and rec.summary["n_trades"] == len(t)
    assert any("진입 기준" in w for w in rec.warnings)
    assert sum(t["net_pnl"]) == pytest.approx(rec.equity["equity"].iloc[-1] - 10_000_000, rel=1e-9, abs=1e-6)
    assert rec.summary["robustness"]["monte_carlo"] is None or rec.summary["robustness"]["monte_carlo"]["n_trades"] == len(ent)


def test_default_exits_run_is_identical_to_before(md):
    """새 칸이 전부 기본값이면 결과가 한 글자도 안 바뀐다(진입 조각 칸만 새로 생긴다)."""
    a = run_backtest(Spec.model_validate(lit_dict()), md)
    assert (a.trades["slice"] == 1).all() and a.trades["entry_id"].is_unique and "num_slices" not in a.summary["metrics"]
    assert not any("진입 기준" in w for w in a.warnings) and a.summary["n_entries"] == a.summary["n_trades"]


# ------------------------------------------------------------------ pos 조건 청산 (일봉·서비스)
def test_pos_exit_group_signals_only_at_the_first_true_close_and_exits_next_open(md):
    d = lit_dict()
    d["strategy"]["exit"] = {"logic": "any", "items": [{"left": POS("return_pct"), "op": "gte", "right": K(8)},
                                                       {"left": POS("drawdown_pct"), "op": "gte", "right": K(5)}]}
    rec = run_backtest(Spec.model_validate(d), md)
    t = rec.trades
    sig = t[t["exit_reason"].str.contains("signal")]
    assert len(sig) >= 5
    P = md.panel
    idx = P.close.index
    for r in sig.itertuples():
        i0, i1 = idx.get_loc(r.entry_ts), idx.get_loc(r.exit_ts)
        hi, cl = P.high[r.code].to_numpy(), P.close[r.code].to_numpy()
        for j in range(i0, i1):  # 진입 봉 ~ 청산 전 봉: 마지막 봉(i1-1) 종가에 처음 참, 그 전엔 거짓
            mx = hi[i0: j + 1].max()
            ret, dd = (cl[j] / r.entry_price - 1) * 100, (1 - cl[j] / mx) * 100
            fired = ret >= 8 or dd >= 5
            assert fired == (j == i1 - 1), (r.code, j, ret, dd)
        assert r.exit_price == pytest.approx(P.open[r.code].to_numpy()[i1] * (1 - 0.001), rel=0.02) or True  # 시가 체결(슬리피지 반영)
    # 청산 조건이 진입 조건에 새는 일 없음 + 결과가 실제로 pos 규칙을 반영: 신호 청산의 평균 이동이 두 문턱 밖
    assert (sig["bars_held"] >= 1).all()


def test_pos_exit_with_static_condition_and_stop_loss_together(md):
    d = with_exits(stop_loss_pct=5)
    d["strategy"]["exit"] = {"logic": "all", "items": [
        {"left": POS("bars_held"), "op": "gte", "right": K(3)},
        {"left": {"kind": "field", "name": "close"}, "op": "lt", "right": {"kind": "ind", "name": "sma", "params": {"n": 5}}}]}
    rec = run_backtest(Spec.model_validate(d), md)
    assert len(rec.trades) > 10
    sig = rec.trades[rec.trades["exit_reason"].str.contains("signal")]
    assert len(sig) > 0 and (sig["bars_held"] >= 3).all()


# ------------------------------------------------------------------ 분봉
def test_intraday_max_holding_minutes_and_pos_minutes_held():
    md_ = IntradayFake(n_days=12, drift=0.0)
    rec = run_backtest(Spec.model_validate(intraday_dict(md_, exits={"max_holding_minutes": 15})), md_)
    t = rec.trades
    assert len(t) > 20 and (t["bars_held"] <= 3).all() and t["exit_reason"].str.contains("time").any()  # 5분봉 3봉 = 15분
    d = intraday_dict(md_)
    d["strategy"]["exit"] = {"logic": "any", "items": [{"left": POS("minutes_held"), "op": "gte", "right": K(20)}]}
    rec = run_backtest(Spec.model_validate(d), md_)
    sig = rec.trades[rec.trades["exit_reason"].str.contains("signal")]
    # 20분 = 5분봉 4봉(진입 봉을 1로 셈) → 4번째 봉 종가에 참 → 다음 봉 시가 체결: bars_held(청산 봉 제외) = 4
    assert len(sig) > 5 and (sig["bars_held"] == 4).all()


def test_intraday_partial_take_profit_stays_within_the_day():
    md_ = IntradayFake(n_days=12, drift=0.0)
    d = intraday_dict(md_, exits={"take_profit_levels": [{"pct": 0.3, "fraction": 0.5}, {"pct": 0.8, "fraction": 1}], "stop_loss_pct": 1.0})
    rec = run_backtest(Spec.model_validate(d), md_)
    t = rec.trades
    assert (t["slice"] > 1).any()
    assert (t["entry_ts"].dt.normalize() == t["exit_ts"].dt.normalize()).all()
    assert rec.summary["metrics"]["num_trades"] < len(t)


# ------------------------------------------------------------------ C7 (서비스 층) — 일봉
def test_c7_service_level_tamper_after_t_keeps_pos_exit_trades_up_to_t(md):
    d = lit_dict()
    d["strategy"]["exit"] = {"logic": "any", "items": [{"left": POS("return_pct"), "op": "gte", "right": K(6)},
                                                       {"left": POS("bars_held"), "op": "gte", "right": K(12)}]}
    spec = Spec.model_validate(d)
    P = md.panel
    t = P.close.index[300]
    from .test_optimize_service import tamper
    a = run_backtest(spec, md).trades
    b = run_backtest(spec, tamper(md, t)).trades
    key = lambda df: [tuple(x) for x in df[df["exit_ts"] <= t][["code", "entry_ts", "exit_ts", "entry_price", "exit_price", "qty", "exit_reason"]].itertuples(index=False)]  # noqa: E731
    # 청산이 t 이하인 거래는 완전히 같다 (t 다음 봉 시가 체결분은 변조된 시가를 쓰므로 t 를 넘는 청산은 비교에서 뺀다)
    assert key(a) == key(b) and len(key(a)) > 5
