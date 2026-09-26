"""studio-conditions c1 — AST 새 칸(tf·expr·pos·hold·within·negate·새 연산자) · 평가기 · 모드/시간 단위 검증 · 시간 단위 카나리아(C5·C6·C3 확장).

SC-C1: 분봉에서 "현재가 > 전일까지 20일 최고가" 신호 = 손계산.  SC-C2: "5분 20선 위 그리고 일봉 20선(장중 실시간) 위" 이 돈다.
"""
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from studio.domain.conditions.ast import Group, iter_operands
from studio.domain.conditions.evaluator import evaluate, evaluate_group
from studio.domain.conditions.validation import validate_group
from studio.domain.models import Panel

from .test_timeframe import BAR, make_data, tamper_after


def F(name="close", **kw):
    return {"kind": "field", "name": name, **kw}


def I(name, params=None, **kw):  # noqa: E743
    return {"kind": "ind", "name": name, "params": params or {}, **kw}


def C(v):
    return {"kind": "const", "value": v}


def cond(left, op, right=None, **kw):
    d = {"left": left, "op": op, **kw}
    if right is not None:
        d["right"] = right
    return d


def G(*items, logic="all", **kw):
    return {"logic": logic, "items": list(items), **kw}


def grp(*items, **kw):
    return Group.model_validate(G(*items, **kw))


# ------------------------------------------------------------------ AST
def test_old_shaped_spec_dicts_still_validate_and_defaults_are_old_behaviour():
    g = Group.model_validate({"logic": "all", "items": [
        {"left": {"kind": "field", "name": "close"}, "op": "gt", "right": {"kind": "ind", "name": "sma", "params": {"src": "close", "n": 20}}}]})
    c = g.items[0]
    assert c.left.tf == "bar" and c.right.tf == "bar" and c.hold == 1 and c.within is None and g.negate is False


@pytest.mark.parametrize("bad,msg", [
    (cond(F(), "cross_above_within", I("sma", {"n": 5})), "within"),  # within 필요
    (cond(F(), "gt", I("sma", {"n": 5}), within=3), "within"),  # within 은 *_within 전용
    (cond(F(), "is_true", I("sma", {"n": 5})), "오른쪽 값이 없다"),
    (cond(F(), "gt"), "오른쪽 값이 필요"),
    (cond(F(tf="weekly"), "gt", C(1)), None),  # 모르는 시간 단위
    (cond(F(), "gt", C(1), hold=0), None),
    (cond(I("atr", {"n": 14}, tf="daily_live"), "gt", C(1)), "daily_live"),  # live 미지원 지표
    (cond(I("time", tf="daily_prev"), "gt", C(900)), "분봉 전용"),
    (cond(I("value_rank", tf="m5"), "lt", C(10)), "일봉 전용"),
])
def test_ast_rejects_bad_new_fields(bad, msg):
    with pytest.raises(ValidationError) as e:
        Group.model_validate(G(bad))
    if msg:
        assert msg in str(e.value)


def test_expr_operand_depth_and_leaf_iteration():
    e = {"kind": "expr", "op": "+", "left": F(), "right": {"kind": "expr", "op": "*", "left": I("sma", {"n": 5}), "right": C(2)}}
    g = grp(cond(e, "gt", C(0)))
    assert [type(o).__name__ for o in iter_operands(g)] == ["FieldOperand", "IndOperand", "ConstOperand", "ConstOperand"]
    deep = F()
    for _ in range(8):
        deep = {"kind": "expr", "op": "+", "left": deep, "right": C(1)}
    Group.model_validate(G(cond(deep, "gt", C(0))))  # 깊이 8 까지
    with pytest.raises(ValidationError, match="산술 식은"):
        Group.model_validate(G(cond({"kind": "expr", "op": "+", "left": deep, "right": C(1)}, "gt", C(0))))
    with pytest.raises(ValidationError):
        Group.model_validate(G(cond({"kind": "pos", "name": "nope"}, "gt", C(0))))


# ------------------------------------------------------------------ 평가기: 연산자·hold·negate·expr
def small_panel():
    idx = pd.bdate_range("2024-01-02", periods=12)
    close = pd.DataFrame({"A": [10, 11, 12, 11, 10, 9, 10, 11, 12, 13, 12, 11.0], "B": [5.0] * 12}, index=idx)
    z = close * 0
    return Panel(close, close + 1, close - 1, close, z + 1000, close * 1000, close.shift(1))


def test_hold_within_is_true_and_expr_division():
    p = small_panel()
    c = p.close["A"]
    up = c > 10.5
    got = evaluate_group(grp(cond(F(), "gt", C(10.5), hold=3)), p)["A"]
    assert list(got) == list(up & up.shift(1, fill_value=False) & up.shift(2, fill_value=False))  # 연속 3봉
    x = evaluate_group(grp(cond(F(), "cross_above_within", C(10.5), within=3)), p)["A"]
    cross = (c > 10.5) & (c.shift(1) <= 10.5)
    assert list(x) == list(cross.rolling(3, min_periods=1).max().gt(0))  # 최근 3봉 안에 크로스
    ind = evaluate_group(grp(cond(F("volume"), "is_true")), p)["A"]
    assert ind.all()  # 거래량 1000 ≠ 0
    assert not evaluate_group(grp(cond(F("volume"), "is_false")), p)["A"].any()
    # expr: (종가 * 2) - 종가 == 종가, 0 으로 나누기는 NaN → 거짓
    e = {"kind": "expr", "op": "-", "left": {"kind": "expr", "op": "*", "left": F(), "right": C(2)}, "right": F()}
    assert evaluate_group(grp(cond(e, "gte", F())), p)["A"].all()
    div0 = {"kind": "expr", "op": "/", "left": F(), "right": {"kind": "expr", "op": "-", "left": F(), "right": F()}}
    assert not evaluate_group(grp(cond(div0, "gt", C(0))), p).any().any()


def test_negate_is_not_true_where_values_are_missing():
    p = small_panel()
    g = grp(cond(F(), "gt", I("sma", {"src": "close", "n": 5})))  # 처음 4봉은 sma 값이 없다
    plain = evaluate_group(g, p)["A"]
    neg = evaluate_group(grp(cond(F(), "gt", I("sma", {"src": "close", "n": 5})), negate=True), p)["A"]
    assert not neg.iloc[:4].any() and not plain.iloc[:4].any()  # 워밍업 구간에서 NOT 이 참이 되지 않는다
    assert list(neg.iloc[4:]) == list(~plain.iloc[4:])  # 값이 있는 곳에선 정확히 반대


def test_pos_operand_is_not_evaluable_by_the_evaluator_alone():
    p = small_panel()
    g = grp(cond({"kind": "pos", "name": "return_pct"}, "gte", C(5)))
    with pytest.raises(ValueError, match="엔진이 평가"):
        evaluate_group(g, p)


def test_non_bar_timeframe_without_intraday_context_is_an_error():
    p = small_panel()
    with pytest.raises(ValueError, match="분봉 실행에서만"):
        evaluate_group(grp(cond(I("sma", {"n": 3}, tf="daily_prev"), "gt", C(1))), p)


# ------------------------------------------------------------------ 모드·역할 검증
def test_validate_group_rules():
    inp = lambda tf: grp(cond(I("sma", {"n": 20}, tf=tf), "gt", C(1)))  # noqa: E731
    # 일봉 모드: 시간 단위는 bar 뿐
    validate_group(inp("bar"), "entry", mode="daily_portfolio")
    with pytest.raises(ValueError, match="일봉 모드에서는 시간 단위"):
        validate_group(inp("daily_prev"), "entry", mode="daily_portfolio")
    # 분봉(5분 실행): m5 는 실행 봉과 같아 불가, m3 는 배수 아님, m15 는 가능, m60 가능
    for tf in ("m5", "m3", "m1"):
        with pytest.raises(ValueError, match="배수이면서 더 긴"):
            validate_group(inp(tf), "entry", mode="intraday", bar_minutes=5)
    for tf in ("m15", "m60", "daily_prev", "daily_live"):
        validate_group(inp(tf), "entry", mode="intraday", bar_minutes=5)
    validate_group(inp("m5"), "entry", mode="intraday", bar_minutes=1)  # 1분 실행이면 5분 가능
    # 거래량 계열 daily_live: 통합(al)에서 오류, krx 에서 허용
    vol_live = grp(cond(I("sma", {"src": "volume", "n": 5}, tf="daily_live"), "gt", C(1)))
    vol_field = grp(cond(F("value", tf="daily_live"), "gt", C(1)))
    for g in (vol_live, vol_field):
        # sma(volume) 자체는 volume_based 가 아니라 지표 단위로는 통과 — 필드(volume/value) 는 통과 못 한다
        pass
    with pytest.raises(ValueError, match="KRX 분봉에서만"):
        validate_group(vol_field, "entry", mode="intraday", source="al")
    validate_group(vol_field, "entry", mode="intraday", source="krx")
    ratio_live = grp(cond(I("vol_ratio", {"n": 20}, tf="daily_prev"), "gt", C(3)))
    validate_group(ratio_live, "entry", mode="intraday", source="al")  # daily_prev 는 확정값이라 출처와 무관
    # pos 는 청산에서만
    posc = grp(cond({"kind": "pos", "name": "return_pct"}, "gte", C(5)))
    validate_group(posc, "exit", mode="daily_portfolio")
    for role in ("entry", "market_filter", "prefilter"):
        with pytest.raises(ValueError, match="청산 조건에서만"):
            validate_group(posc, role, mode="intraday")
    # 사전 필터는 시간 단위 없음 + 일봉 지표
    with pytest.raises(ValueError, match="사전 필터는 일봉"):
        validate_group(inp("daily_prev"), "prefilter", mode="intraday")
    validate_group(inp("bar"), "prefilter", mode="intraday")
    # 분봉 전용 지표(time)는 일봉 모드에서 못 씀(기존 규칙 유지)
    with pytest.raises(ValueError, match="쓸 수 없음"):
        validate_group(grp(cond(I("time"), "gt", C(900))), "entry", mode="daily_portfolio")


def test_spec_level_validation_uses_the_same_rules():
    from studio.domain.spec import Spec
    base = {"version": 1, "name": "t", "mode": "intraday", "period": {"start": "2026-08-24", "end": "2026-09-23"},
            "strategy": {"source": "builder", "entry": G(cond(F(), "gt", I("highest", {"src": "high", "n": 20, "include_current": False}, tf="daily_live"))),
                         "exit": G()},
            "intraday": {"bar_minutes": 5, "prefilter_top_value": 30, "eod_time": "15:20"}}
    Spec.model_validate(base)  # SC-C1 프리셋 모양이 명세로 통과
    bad = {**base, "strategy": {"source": "builder", "entry": G(cond({"kind": "pos", "name": "return_pct"}, "gte", C(5))), "exit": G()}}
    with pytest.raises(ValidationError, match="청산 조건에서만"):
        Spec.model_validate(bad)
    with pytest.raises(ValidationError, match="배수이면서"):
        Spec.model_validate({**base, "strategy": {"source": "builder", "exit": G(),
                                                  "entry": G(cond(F(), "gt", I("sma", {"n": 5}, tf="m3")))}})


# ------------------------------------------------------------------ SC-C1 / SC-C2 (분봉 + 일봉 지표)
def _hist_max(daily, code, pos, n, field="high"):
    return daily.__dict__[field][code].iloc[pos - n + 1: pos + 1].max()


def _with_breakout(minute, code="A", factor=1.2):
    """마지막 날 한 종목의 분봉을 ×factor — 전일까지 20일 최고가를 넘는 봉이 생기게(손계산 표본이 의미 있도록)."""
    last = minute.close.index[-1].normalize()
    m = pd.Series(minute.close.index.normalize() == last, index=minute.close.index)
    fr = {}
    for k in ("open", "high", "low", "close", "volume", "value", "prev_close"):
        df = getattr(minute, k).copy()
        if k in ("open", "high", "low", "close"):
            df.loc[m, code] = df.loc[m, code] * factor
        fr[k] = df
    fr["value"] = fr["close"] * fr["volume"]
    return Panel(**fr)


def test_sc_c1_close_above_previous_20_day_high_matches_hand_calculation():
    daily, minute = make_data(n_hist=60, n_min_days=4)
    minute = _with_breakout(_with_breakout(minute, "A", 1.2), "B", 1.3)
    d_last = minute.close.index[-1].normalize()
    d_prev = daily.close.index[daily.close.index.get_loc(d_last) - 1]
    daily.high.loc[d_prev, "A"] = daily.high["A"].iloc[:-4].max() * 3  # D−1 고가 스파이크 — D−20..D−1 창엔 들어가고 D−21..D−2 창엔 안 들어간다
    g = grp(cond(F(), "gt", I("highest", {"src": "high", "n": 20, "include_current": False}, tf="daily_live")))
    got = evaluate_group(g, minute, daily=daily, bar_minutes=BAR)
    exp = pd.DataFrame(False, index=minute.close.index, columns=minute.close.columns)
    for code in minute.close.columns:
        for t in minute.close.index:
            pos = daily.close.index.get_loc(t.normalize()) - 1  # D−1 의 행
            exp.loc[t, code] = minute.close.loc[t, code] > _hist_max(daily, code, pos, 20)  # 전일까지 20일 최고가(D−20..D−1)
    pd.testing.assert_frame_equal(got, exp)
    assert got[["B", "C"]].any().any() and not got.all().all()  # 신호가 실제로 나오고 항상 참도 아니다(손계산이 의미 있는 표본)
    assert not got.loc[got.index.normalize() == d_last, "A"].any()  # A 는 D−1 스파이크가 창에 들어가 마지막 날 신호가 없다
    # 같은 뜻을 daily_prev + include_current=True 로 써도 같다(D−1 행의 20일 최고가 = D−20..D−1)
    g2 = grp(cond(F(), "gt", I("highest", {"src": "high", "n": 20, "include_current": True}, tf="daily_prev")))
    pd.testing.assert_frame_equal(evaluate_group(g2, minute, daily=daily, bar_minutes=BAR), exp)
    # lead 판정(2026-09-26): daily_prev 는 "오늘 장 시작 전에 아는 값" — 현재 봉을 빼는 highest(기본)는 행 D = D−20..D−1 이라 세 식이 같다
    g3 = grp(cond(F(), "gt", I("highest", {"src": "high", "n": 20}, tf="daily_prev")))
    pd.testing.assert_frame_equal(evaluate_group(g3, minute, daily=daily, bar_minutes=BAR), exp)


def test_sc_c2_five_minute_ma20_and_daily_live_ma20():
    daily, minute = make_data(n_hist=60, n_min_days=4)
    g = grp(cond(F(), "gt", I("sma", {"src": "close", "n": 20})),  # 분봉(실행 봉) 20선 — 롤링은 날을 넘어 이어진다
            cond(F(), "gt", I("sma", {"src": "close", "n": 20}, tf="daily_live")))
    got = evaluate_group(g, minute, daily=daily, bar_minutes=BAR)
    m20 = minute.close.rolling(20).mean()
    exp = pd.DataFrame(False, index=minute.close.index, columns=minute.close.columns)
    for code in minute.close.columns:
        for t in minute.close.index:
            pos = daily.close.index.get_loc(t.normalize()) - 1
            live20 = (daily.close[code].iloc[pos - 18: pos + 1].sum() + minute.close.loc[t, code]) / 20  # D−19..D−1 19개 + 오늘 가상 종가
            exp.loc[t, code] = (minute.close.loc[t, code] > m20.loc[t, code]) and (minute.close.loc[t, code] > live20)
    pd.testing.assert_frame_equal(got, exp)
    assert got.any().any()


def test_mN_condition_through_evaluator_and_C5_canary():
    daily, minute = make_data(n_hist=40, n_min_days=4)
    g = grp(cond(I("sma", {"src": "close", "n": 3}, tf="m15"), "cross_above", I("sma", {"src": "close", "n": 8}, tf="m15")))
    base = evaluate_group(g, minute, daily=daily, bar_minutes=BAR)
    assert base.any().any()
    for k in (60, 150, 230):
        t = minute.close.index[k]
        bad = tamper_after(minute, t)
        out = evaluate_group(g, bad, daily=daily, bar_minutes=BAR)
        pd.testing.assert_frame_equal(base.loc[:t], out.loc[:t])  # t 이하 신호 불변(미마감 15분봉·이후 봉을 안 본다)
    assert not base.equals(evaluate_group(g, tamper_after(minute, minute.close.index[60]), daily=daily, bar_minutes=BAR))


def test_c6_and_c3_canaries_through_evaluator_with_daily_prev_and_daily_live():
    daily, minute = make_data(n_hist=60, n_min_days=4)
    live_g = grp(cond(I("rsi", {"n": 14}, tf="daily_live"), "gt", C(50)),
                 cond(F(), "gt", I("bb_lower", {"n": 20, "k": 1.0}, tf="daily_live")))
    prev_g = grp(cond(F(), "gt", I("sma", {"src": "close", "n": 10}, tf="daily_prev")))
    for g in (live_g, prev_g):
        b0 = evaluate_group(g, minute, daily=daily, bar_minutes=BAR)
        assert b0.any().any() and not b0.all().all()  # 조건이 항상 참/거짓이 아니어야 카나리아가 뜻 있다
        base = evaluate_group(g, minute, daily=daily, bar_minutes=BAR)
        t = minute.close.index[len(minute.close) // 2]
        bad = tamper_after(minute, t)
        d = t.normalize()
        # 그 날 일봉 행(D)도 같이 망가뜨린다 — D 행은 daily_prev·daily_live 어디서도 안 쓴다(C3 확장)
        dd = Panel(*(getattr(daily, k).copy() for k in ("open", "high", "low", "close", "volume", "value", "prev_close")))
        for k in ("open", "high", "low", "close", "volume", "value", "prev_close"):
            getattr(dd, k).loc[d] = getattr(dd, k).loc[d] * 10
        out = evaluate_group(g, bad, daily=dd, bar_minutes=BAR)
        pd.testing.assert_frame_equal(base.loc[:t], out.loc[:t])
    # 둔감하지 않다: 봉 자체를 t 이전부터 망가뜨리면 결과가 바뀐다
    base = evaluate_group(live_g, minute, daily=daily, bar_minutes=BAR)
    assert not base.equals(evaluate_group(live_g, tamper_after(minute, minute.close.index[3]), daily=daily, bar_minutes=BAR))


def test_evaluate_shares_time_context_between_entry_and_exit():
    daily, minute = make_data(n_hist=40, n_min_days=3)
    e = grp(cond(F(), "gt", I("sma", {"n": 5}, tf="daily_prev")))
    x = grp(cond(F(), "lt", I("sma", {"n": 5}, tf="daily_prev")))
    ev = evaluate(e, x, minute, daily=daily, bar_minutes=BAR)
    assert not (ev.entry & ev.exit).any().any()  # 같은 값으로 > 와 < 는 동시에 참이 될 수 없다
    assert (ev.entry | ev.exit).any().any()
