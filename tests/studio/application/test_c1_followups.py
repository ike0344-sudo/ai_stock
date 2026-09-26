"""c1 후속(execution·monitoring·data-agent 편지 2026-09-26): Group.formula · 검증 오류 경로 · live_reason · 테마 경고 · 틱 새 조건 명세/서비스."""
import pytest
from pydantic import ValidationError

from studio.application.backtest_service import condition_warnings, structure_hash, family_hash, spec_hash
from studio.domain.conditions.ast import Group
from studio.domain.conditions.catalog import INDICATORS
from studio.domain.conditions.validation import validate_group
from studio.domain.spec import Spec

from .fakes_intraday import IntradayFake
from .test_intraday_service import tick_dict
from .test_optimize_service import lit_dict

from studio.application.backtest_service import run_backtest

F = lambda n="close", **k: {"kind": "field", "name": n, **k}  # noqa: E731


def test_group_formula_is_stored_but_ignored_by_evaluation_and_hashes():
    g = {"logic": "all", "items": [{"left": F(), "op": "gt", "right": {"kind": "const", "value": 1}}], "formula": "C > 1"}
    assert Group.model_validate(g).formula == "C > 1"
    with pytest.raises(ValidationError):
        Group.model_validate({**g, "formula": "x" * 2001})
    assert Group.model_validate({k: v for k, v in g.items() if k != "formula"}).formula is None
    # 해시: 같은 AST 에 원문만 달라도(있고 없고) 같은 전략
    a = lit_dict()
    import copy
    b = copy.deepcopy(lit_dict())
    b["strategy"]["entry"]["formula"] = "CLOSE > HIGHEST(HIGH, 20)"
    sa, sb = Spec.model_validate(a), Spec.model_validate(b)
    assert sb.strategy.entry.formula and spec_hash(sa) == spec_hash(sb) and structure_hash(sa) == structure_hash(sb) and family_hash(sa) == family_hash(sb)


def test_validation_errors_carry_the_json_path_of_the_offending_operand():
    inp = lambda tf: {"kind": "ind", "name": "sma", "params": {"n": 5}, "tf": tf}  # noqa: E731
    cnd = lambda l, r: {"left": l, "op": "gt", "right": r}  # noqa: E731
    g = Group.model_validate({"logic": "all", "items": [
        cnd(F(), {"kind": "const", "value": 1}),
        {"logic": "any", "items": [cnd(F(), {"kind": "expr", "op": "+", "left": {"kind": "const", "value": 1}, "right": inp("daily_prev")})]}]})
    with pytest.raises(ValueError, match=r"^\[strategy\.entry\.items\.1\.items\.0\.right\.right\] .*일봉 모드"):
        validate_group(g, "entry", mode="daily_portfolio")
    exit_pos = Group.model_validate({"logic": "any", "items": [cnd({"kind": "pos", "name": "return_pct"}, {"kind": "const", "value": 5})]})
    with pytest.raises(ValueError, match=r"^\[market_filter\.items\.0\.left\] 포지션 값"):
        validate_group(exit_pos, "market_filter", mode="intraday")
    # Spec 로 올라오면 메시지 안에 같은 경로가 있다(화면이 파싱)
    import copy
    d = copy.deepcopy(lit_dict())  # spec_dict 의 피연산자 dict 는 모듈 전역을 공유한다 — 복사 없이 고치면 다른 테스트가 오염된다
    d["mode"] = "daily_portfolio"
    d["strategy"]["entry"]["items"][0]["left"]["tf"] = "daily_prev"
    with pytest.raises(ValidationError, match=r"\[strategy\.entry\.items\.0\.left\]"):
        Spec.model_validate(d)


def test_live_reason_and_condition_warnings():
    assert INDICATORS["sma"].live_reason_ko == "" and "KRX" not in INDICATORS["sma"].live_reason_ko
    assert "daily_prev" in INDICATORS["atr"].live_reason_ko and "분봉·틱 전용" in INDICATORS["vwap"].live_reason_ko
    ind = INDICATORS["cum_value"]
    assert ind.volume_based and not ind.live
    # 테마·업종 지표를 쓰면 "구성은 현재 기준" 경고가 결과 경고 재료로 나온다
    import copy
    d = copy.deepcopy(lit_dict(mode="daily_portfolio"))
    d["strategy"]["entry"]["items"][0] = {"left": {"kind": "ind", "name": "theme_change", "params": {}}, "op": "gt",
                                          "right": {"kind": "const", "value": 1}}
    w = condition_warnings(Spec.model_validate(d))
    assert len(w) == 1 and "현재 기준" in w[0]
    assert condition_warnings(Spec.model_validate(lit_dict())) == []


def test_tick_spec_accepts_new_conditions_and_old_specs_are_unchanged():
    md = IntradayFake(n_days=4, drift=0.0001, seed=3)
    base = tick_dict(md)
    Spec.model_validate(base)  # 옛 모양
    only_new = tick_dict(md, tick={"entry_source": "catalog", "catalog": {"breakout_min": None, "daily_breakout": {"n": 5}},
                                   "cooldown_sec": 300, "time_stop_sec": 600, "eod_time": "15:19:59"})
    s = Spec.model_validate(only_new)
    assert s.tick.catalog.daily_breakout.n == 5 and s.tick.catalog.trade_strength is None
    with pytest.raises(ValidationError, match="틱 조건이 하나도 없음"):
        Spec.model_validate(tick_dict(md, tick={"entry_source": "catalog", "catalog": {"breakout_min": None}}))
    for extra in ({"trade_strength": {"w": 30, "min": 120}}, {"block_trades": {"w": 60, "min_value": 5e7, "min_count": 2}}):
        Spec.model_validate(tick_dict(md, tick={"entry_source": "catalog", "catalog": {"breakout_min": None, **extra}}))


def test_tick_service_computes_daily_breakout_level_from_previous_days_only():
    md = IntradayFake(n_days=6, drift=0.0001, seed=11)
    # 기준선: D−1 까지 n일 최고가 — 그날 일봉 행(D)은 안 본다. n=1 이면 전일 고가.
    rec = run_backtest(Spec.model_validate(tick_dict(md, tick={"entry_source": "catalog", "catalog": {"breakout_min": None, "daily_breakout": {"n": 1}},
                                                                "cooldown_sec": 300, "time_stop_sec": 600, "eod_time": "15:19:59"})), md)
    assert rec.summary["tick"]["signals"] > 0 and len(rec.trades) > 0
    # 신호가 D 일봉 고가에 좌우되면 안 된다: D 일봉 행을 망가뜨려도(같은 날 신호 불변) — 마지막 날 일봉 ×10
    import copy
    from studio.domain.models import Panel
    p = md.panel
    bad = copy.copy(md)
    last = md.days[-1]
    bad.panel = Panel(*(getattr(p, k).where(p.close.index != last, getattr(p, k) * 10) if False else getattr(p, k).copy()
                        for k in ("open", "high", "low", "close", "volume", "value", "prev_close")))
    for k in ("open", "high", "low", "close", "volume", "value", "prev_close"):
        getattr(bad.panel, k).loc[last] = getattr(bad.panel, k).loc[last] * 10
    spec = Spec.model_validate(tick_dict(md, tick={"entry_source": "catalog", "catalog": {"breakout_min": None, "daily_breakout": {"n": 1}},
                                                   "cooldown_sec": 300, "time_stop_sec": 600, "eod_time": "15:19:59"}))
    a = run_backtest(spec, md)
    b = run_backtest(spec, bad)
    day = lambda r: sorted((t.code, t.entry_ts, t.entry_price) for t in r.trades.itertuples() if t.entry_ts.normalize() == pd_ts(last))  # noqa: E731
    assert day(a) == day(b) and day(a)  # 마지막 날 진입은 그날 일봉 행과 무관
    # n 이 이력보다 길면 기준선이 NaN → 신호 없음(조용히 통과가 아니라 0건) — 일봉 이력이 40일뿐인 시장 데이터로
    from tests.studio.application.fakes import make_panel
    md = IntradayFake(n_days=4, drift=0.0001, seed=11, panel=make_panel(n=40, seed=3, codes=list(__import__("tests.studio.application.fakes", fromlist=["CODES"]).CODES)))
    none = run_backtest(Spec.model_validate(tick_dict(md, tick={"entry_source": "catalog", "catalog": {"breakout_min": None, "daily_breakout": {"n": 50}},
                                                                 "cooldown_sec": 300, "time_stop_sec": 600, "eod_time": "15:19:59"})), md)
    assert len(none.trades) == 0


def pd_ts(d):
    import pandas as pd
    return pd.Timestamp(d)
