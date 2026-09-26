"""사용자 수식 해석기 — 설계 §3.5·§7·§8: 조립기 명세와 신호 동일(대표 20식) · 새 칸 모양 · 오류 위치 · 악성 입력 거부."""
import random

import pandas as pd

import pytest

from studio.domain.conditions import ast as ast_mod
from studio.domain.conditions import formula as F
from studio.domain.conditions.ast import Group
from studio.domain.conditions.evaluator import evaluate_group
from studio.domain.conditions.formula import FormulaError, compile_formula
from tests.studio.conditions.helpers import cond, const, field, group, ind, synth_panel

C, H, L, V = field("close"), field("high"), field("low"), field("volume")

# (수식, 같은 조건을 조립기로 만든 명세) — 현재 AST 가 받는 칸만 쓴다(tf·expr·pos·hold·negate 는 아래 모양 테스트)
PARITY = [
    ("C > MA(C,20)", group("all", cond(C, "gt", ind("sma", src="close", n=20)))),
    ("C > MA(C,20)*1.05", group("all", cond(C, "gt", ind("sma", mul=1.05, src="close", n=20)))),
    ("c >= ema(c,10)", group("all", cond(C, "gte", ind("ema", src="close", n=10)))),
    ("RSI(14) >= 70", group("all", cond(ind("rsi", n=14), "gte", const(70)))),
    ("RSI_WILDER(14) < 30", group("all", cond(ind("rsi_wilder", n=14), "lt", const(30)))),
    ("C > HIGHEST(H,20)", group("all", cond(C, "gt", ind("highest", src="high", n=20)))),
    ("C < LOWEST(L,20)", group("all", cond(C, "lt", ind("lowest", src="low", n=20)))),
    ("HIGHEST(H,20,TRUE) < C", group("all", cond(ind("highest", src="high", n=20, include_current=True), "lt", C))),
    ("VOL_RATIO(20) >= 2", group("all", cond(ind("vol_ratio", n=20), "gte", const(2)))),
    ("CROSSUP(MA(C,5), MA(C,20))", group("all", cond(ind("sma", src="close", n=5), "cross_above", ind("sma", src="close", n=20)))),
    ("CROSSDOWN(MA(C,5), MA(C,20))", group("all", cond(ind("sma", src="close", n=5), "cross_below", ind("sma", src="close", n=20)))),
    ("C(1) < C", group("all", cond(field("close", offset=1), "lt", C))),
    ("MA(C,5)(2) < MA(C,5)", group("all", cond(ind("sma", offset=2, src="close", n=5), "lt", ind("sma", src="close", n=5)))),
    ("C > 5000 AND C < 20000", group("all", cond(C, "gt", const(5000)), cond(C, "lt", const(20000)))),
    ("RSI(14) < 30 OR RSI(14) > 70", group("any", cond(ind("rsi", n=14), "lt", const(30)), cond(ind("rsi", n=14), "gt", const(70)))),
    ("C > MA(C,20) AND (RSI(14) > 50 OR V > MA(V,20))",
     group("all", cond(C, "gt", ind("sma", src="close", n=20)),
           group("any", cond(ind("rsi", n=14), "gt", const(50)), cond(V, "gt", ind("sma", src="volume", n=20))))),
    ("NOT (C > MA(C,20))", group("all", cond(C, "lte", ind("sma", src="close", n=20)))),
    ("NOT (C > MA(C,20) AND RSI(14) > 50)",
     group("any", cond(C, "lte", ind("sma", src="close", n=20)), cond(ind("rsi", n=14), "lte", const(50)))),
    ("C > BB_UPPER(20, 2)", group("all", cond(C, "gt", ind("bb_upper", n=20, k=2.0)))),
    ("-C < -MA(C,20) AND 2*V > MA(V,10)",
     group("all", cond(field("close", mul=-1.0), "lt", ind("sma", mul=-1.0, src="close", n=20)),
           cond(field("volume", mul=2.0), "gt", ind("sma", src="volume", n=10)))),
]


@pytest.fixture(scope="module")
def panel():
    return synth_panel(n_days=260, n_codes=6, seed=3)


@pytest.mark.parametrize("text,spec", PARITY, ids=[t for t, _ in PARITY])
def test_formula_equals_assembled_spec(text, spec, panel):
    got = Group.model_validate(compile_formula(text))
    want = Group.model_validate(spec)
    assert got.model_dump() == want.model_dump()                       # 같은 AST
    a, b = evaluate_group(got, panel), evaluate_group(want, panel)
    assert a.equals(b)                                                 # 같은 신호
    assert a.to_numpy().any() or text.startswith(("CROSSDOWN", "HIGHEST")), "신호가 하나도 없으면 비교가 공허하다"


def test_parity_covers_twenty_formulas():
    assert len(PARITY) >= 20


# ---- 새 칸(AST 확장 대기)의 모양 — 설계 §3.1 ----
def test_every_shape_the_grammar_can_emit_is_accepted_by_the_spec():
    for text in ["M5.C > M5.MA(C,20) AND DL.C > DL.MA(C,20)", "C > D.HIGHEST(H,20)", "(C + 1) / 2 > MA(C,5) * 1.5",
                 "POS.RETURN_PCT >= 5 AND RSI(14) >= 70", "HOLD(C > MA(C,20), 3)", "NOT CROSSUP(MA(C,5), MA(C,20))",
                 "CROSSUP(C, MA(C,20), 3)", "VWAP AND M15.RSI(14) < 30", "NOT (C > 1 AND V > 1)", "C > D.HIGHEST(H,20,TRUE)"]:
        Group.model_validate(compile_formula(text))


def test_time_unit_becomes_tf_on_the_operand():
    g = compile_formula("M5.C > M5.MA(C,20) AND DL.C > DL.MA(C,20) AND C > D.HIGHEST(H,20)")
    c1, c2, c3 = g["items"]
    assert c1["left"]["tf"] == c1["right"]["tf"] == "m5"
    assert c2["left"]["tf"] == c2["right"]["tf"] == "daily_live"
    assert "tf" not in c3["left"] and c3["right"]["tf"] == "daily_prev"     # 단위 없으면 칸 자체가 없다 = bar
    assert c3["right"]["params"] == {"src": "high", "n": 20}


def test_unit_only_before_field_or_indicator():
    for bad in ["D > 1", "D.5 > 1", "D.D.C > 1", "M7.C > 1", "D. > 1"]:
        with pytest.raises(FormulaError):
            compile_formula(bad)


def test_arithmetic_becomes_expr_and_folds_constants():
    g = compile_formula("(C + 1) / 2 > MA(C,5) * (1 + 0.5)")
    c = g["items"][0]
    assert c["left"]["kind"] == "expr" and c["left"]["op"] == "/"
    assert c["right"] == {"kind": "ind", "name": "sma", "params": {"src": "close", "n": 5}, "offset": 0, "mul": 1.5}
    assert compile_formula("C > 2 * 5")["items"][0]["right"] == const(10.0)


def test_pos_operands():
    g = compile_formula("POS.RETURN_PCT >= 5 AND pos.minutes_held > 30")
    assert g["items"][0]["left"] == {"kind": "pos", "name": "return_pct"}
    assert g["items"][1]["left"] == {"kind": "pos", "name": "minutes_held"}
    for bad in ["POS.FOO > 1", "POS > 1", "POS.RETURN_PCT(1) > 1", "D.POS.RETURN_PCT > 1"]:
        with pytest.raises(FormulaError):
            compile_formula(bad)


def test_hold_sets_condition_hold():
    c = compile_formula("HOLD(C > MA(C,20), 3)")["items"][0]
    assert c["hold"] == 3 and c["op"] == "gt"
    for bad in ["HOLD(C > 1 AND V > 1, 3)", "HOLD(C > 1, 0)", "HOLD(C > 1, 2.5)", "HOLD(C > 1, MA(C,3))", "HOLD(C > 1)", "HOLD(C > 1, 51)", "HOLD(HOLD(C > 1, 2), 3)"]:
        with pytest.raises(FormulaError):
            compile_formula(bad)


def test_not_flips_operator_so_nan_stays_false():
    # NOT (a>b) 를 그룹 negate 로 두면 워밍업 NaN(비교 False)이 NOT 을 지나 True 가 된다 → 연산자를 뒤집어 NaN 은 계속 False
    p = synth_panel(n_days=40, n_codes=2, seed=1)
    r = evaluate_group(Group.model_validate(compile_formula("NOT (C > MA(C,20))")), p)
    assert not r.iloc[:19].to_numpy().any()          # MA(20) 워밍업 19행은 값이 없다 → 신호도 없다
    assert compile_formula("NOT (C > 1)")["items"][0]["op"] == "lte"
    assert compile_formula("NOT NOT (C > 1)")["items"][0]["op"] == "gt"


def test_not_of_cross_or_hold_needs_negate_group():
    g = compile_formula("NOT CROSSUP(MA(C,5), MA(C,20))")   # 맨 위 그룹이 곧 negate 그룹
    assert g["negate"] is True and g["items"][0]["op"] == "cross_above"
    g = compile_formula("NOT HOLD(C > 1, 3)")
    assert g["negate"] is True and g["items"][0]["hold"] == 3
    g = compile_formula("C > 1 AND NOT CROSSUP(MA(C,5), MA(C,20))")
    assert g["items"][1]["negate"] is True and "negate" not in g
    assert "negate" not in compile_formula("NOT NOT CROSSUP(MA(C,5), MA(C,20))")  # 이중 부정은 걷힌다


def test_same_logic_nesting_is_flattened_to_save_depth():
    g = compile_formula("(C > 1 AND C > 2) AND (C > 3 AND C > 4)")
    assert g["logic"] == "all" and len(g["items"]) == 4 and all("logic" not in i for i in g["items"])


def test_bare_boolean_indicator_is_true_and_not_is_false():
    c = compile_formula("EMA(C,5)(1) > 0 AND VWAP")["items"][1]
    assert c == {"left": {"kind": "ind", "name": "vwap", "params": {}, "offset": 0, "mul": 1.0}, "op": "is_true"}   # right 없음
    assert compile_formula("NOT VWAP")["items"][0]["op"] == "is_false"
    assert compile_formula("NOT NOT VWAP")["items"][0]["op"] == "is_true"
    Group.model_validate(compile_formula("VWAP AND NOT VWAP"))                    # 명세 형식에도 맞는다
    for bad in ["5", "C > 1 AND 5"]:
        with pytest.raises(FormulaError):
            compile_formula(bad)


def test_cross_within_and_its_negation():
    c = compile_formula("CROSSUP(MA(C,5), MA(C,20), 3)")["items"][0]
    assert c["op"] == "cross_above_within" and c["within"] == 3
    assert compile_formula("CROSSDOWN(C, MA(C,20), 10)")["items"][0]["op"] == "cross_below_within"
    assert "within" not in compile_formula("CROSSUP(C, MA(C,20))")["items"][0]
    g = compile_formula("NOT CROSSUP(C, MA(C,20), 3)")
    assert g["negate"] is True and g["items"][0]["within"] == 3
    for bad in ["CROSSUP(C, MA(C,20), 0)", "CROSSUP(C, MA(C,20), 51)", "CROSSUP(C, MA(C,20), 2.5)", "CROSSUP(C, MA(C,20), C)",
                "CROSSUP(C, MA(C,20), 3, 4)"]:
        with pytest.raises(FormulaError):
            compile_formula(bad)


def test_new_shapes_evaluate_to_hand_computed_signals(panel):
    """AST 모양만이 아니라 신호까지 — 수식이 만든 새 칸(expr·hold·within·negate)을 pandas 로 직접 계산한 값과 대조."""
    c = panel.close
    ma = c.rolling(20).mean()
    cross = (c > ma) & (c.shift(1) <= ma.shift(1))
    ev = lambda t: evaluate_group(Group.model_validate(compile_formula(t)), panel)
    up = c > ma
    assert ev("(C - MA(C,20)) / MA(C,20) * 100 > 3").equals((c - ma) / ma * 100 > 3)
    assert ev("C - C(1) > 0").equals(c.diff() > 0)
    assert ev("HOLD(C > MA(C,20), 3)").equals(up & up.shift(1, fill_value=False) & up.shift(2, fill_value=False))
    assert ev("CROSSUP(C, MA(C,20), 1)").equals(cross)
    within3 = cross | cross.shift(1, fill_value=False) | cross.shift(2, fill_value=False)      # 오늘 포함 최근 3봉
    assert ev("CROSSUP(C, MA(C,20), 3)").equals(within3)
    assert not ev("NOT CROSSUP(C, MA(C,20), 3)").iloc[:19].to_numpy().any()                     # negate 도 워밍업 NaN 을 참으로 만들지 않는다
    assert not ev("NOT (C > MA(C,20) AND RSI(14) > 50)").iloc[:14].to_numpy().any()             # 두 값 다 없는 구간(RSI 가 먼저 생기면 그 뒤는 참일 수 있다)


def test_daily_prev_highest_compiles_literally():
    # 컴파일러는 문자 그대로 — "전일까지 20일" 의 뜻은 시간 단위 규칙(daily_prev = 오늘 장 시작 전에 아는 값)이 정한다
    r = compile_formula("C > D.HIGHEST(H,20)")["items"][0]["right"]
    assert r["tf"] == "daily_prev" and r["params"] == {"src": "high", "n": 20}                 # include_current 를 몰래 넣지 않는다
    r = compile_formula("C > D.HIGHEST(H,20,TRUE)")["items"][0]["right"]
    assert r["tf"] == "daily_prev" and r["params"] == {"src": "high", "n": 20, "include_current": True}


def test_d_highest_formula_is_previous_20_days_high_same_as_dl_and_include_current():
    """설계서 §3.2 v0.3(lead 09-26): D.HIGHEST(H,20) = D−20..D−1 = DL.HIGHEST(H,20) = D.HIGHEST(H,20,TRUE) — 수식 → 평가기 → 손계산."""
    from tests.studio.conditions.test_c1_operators_and_timeframes import _with_breakout
    from tests.studio.conditions.test_timeframe import BAR, make_data
    daily, minute = make_data(n_hist=60, n_min_days=4)
    minute = _with_breakout(_with_breakout(minute, "A", 1.2), "B", 1.3)          # 신호가 실제로 나오게 돌파를 심는다
    d_last = minute.close.index[-1].normalize()
    d_prev = daily.close.index[daily.close.index.get_loc(d_last) - 1]
    daily.high.loc[d_prev, "A"] = daily.high["A"].iloc[:-4].max() * 3               # D−1 고가 스파이크: D−20..D−1 창엔 들어가고 D−21..D−2 창엔 안 들어간다
    ev = lambda t: evaluate_group(Group.model_validate(compile_formula(t)), minute, daily=daily, bar_minutes=BAR)
    row = lambda t: daily.close.index.get_loc(t.normalize())                      # 그 봉 날짜 D 의 일봉 행 위치
    exp = pd.DataFrame({c: [minute.close.loc[t, c] > daily.high[c].iloc[row(t) - 20:row(t)].max() for t in minute.close.index]
                        for c in minute.close.columns}, index=minute.close.index)  # 창 = D−20..D−1
    got = ev("C > D.HIGHEST(H,20)")
    pd.testing.assert_frame_equal(got, exp)
    assert got.to_numpy().any() and not got.to_numpy().all()                      # 손계산이 의미 있는 표본
    pd.testing.assert_frame_equal(ev("C > DL.HIGHEST(H,20)"), exp)
    pd.testing.assert_frame_equal(ev("C > D.HIGHEST(H,20,TRUE)"), exp)
    exp_lo = pd.DataFrame({c: [minute.close.loc[t, c] < daily.low[c].iloc[row(t) - 10:row(t)].min() for t in minute.close.index]
                           for c in minute.close.columns}, index=minute.close.index)
    pd.testing.assert_frame_equal(ev("C < D.LOWEST(L,10)"), exp_lo)               # lowest 도 같은 규칙


def test_group_depth_limit_is_the_specs():
    assert F.MAX_GROUP_DEPTH == ast_mod.MAX_GROUP_DEPTH == 2
    with pytest.raises(FormulaError, match="겹"):
        compile_formula("C > 1 AND (C < 9 OR (V > 1 AND V < 2))")


# ---- 오류: (줄, 칸, 기대한 것) ----
@pytest.mark.parametrize("text,line,col", [
    ("C >", 1, 4),
    ("C > 1 AND\n   FOO(3) > 1", 2, 4),
    ("C > MA(C,", 1, 10),
    ("C > 1 )", 1, 7),
    ("RSI(0) > 1", 1, 5),
    ("RSI(14.5) > 1", 1, 5),
    ("C(-1) > 1", 1, 3),
    ("C = 1", 1, 3),
    ("C > 1 $", 1, 7),
    ("1 > 2", 1, 1),
])
def test_error_position(text, line, col):
    with pytest.raises(FormulaError) as e:
        compile_formula(text)
    assert (e.value.line, e.value.col) == (line, col), str(e.value)
    assert e.value.to_dict()["line"] == line


def test_unknown_function_lists_what_is_allowed():
    with pytest.raises(FormulaError) as e:
        compile_formula("FOO(3) > 1")
    assert "SMA" in e.value.expected and "RSI" in e.value.expected


def test_future_reference_is_unspeakable():
    for bad in ["C(-1) > 1", "C(1.5) > 1", "MA(C,20)(-2) > 1", "C(1)(1) > 1"]:
        with pytest.raises(FormulaError):
            compile_formula(bad)


# ---- 악성 입력(§7): eval·exec 없이 오류만 낸다 ----
HOSTILE = [
    "__import__('os').system('calc')", "().__class__.__bases__", "C.__class__", "open('x')", "exec('1')", "lambda: 1",
    "1; 2", "C > 1 # 주석", "C > 1 //", "\x00", "C > ${x}", "C > `1`", "C > [1]", "C > {1}", "C ** 2 > 1", "C > 1e400",
    "C > " + "9" * 1500, "가나다 > 1", "C >​1", "C > 1 && V > 1", "!C", "C ? 1 : 2", "MA(C,20)(", ")(", "AND", "NOT", "C AND",
    "C > 1 OR", "CROSSUP(C)", "CROSSUP(C, MA(C,5), 3, 4)", "MA(C,20,30)", "MA(1,20)", "MA(C,C)", "MA(C, 'x')",
    "SMA(C, 10*)", "((((", "C > 1 AND AND V > 1", "D.", ".C", "1.", "1..2", "C > .5", "-", "C > -", "HIGHEST(H,20,2) < C",
]


@pytest.mark.parametrize("text", HOSTILE)
def test_hostile_input_is_rejected_cleanly(text):
    with pytest.raises(FormulaError):
        compile_formula(text)


def test_limits():
    with pytest.raises(FormulaError, match="너무 깁니다"):
        compile_formula("C > 1 " * 400)                      # 2,400자
    compile_formula("C > 1 AND " * 100 + "C > 1")              # 2,000자 이하·호출 0 — 통과
    with pytest.raises(FormulaError, match="중첩"):
        compile_formula("(" * 25 + "C" + ")" * 25 + " > 1")
    with pytest.raises(FormulaError, match="중첩"):
        compile_formula("NOT " * 30 + "C > 1")
    with pytest.raises(FormulaError, match="중첩"):
        compile_formula("-" * 30 + "C > 1")
    with pytest.raises(FormulaError, match="호출"):
        compile_formula(" AND ".join(["RSI(14) > 1"] * 51))  # 호출 51 개
    compile_formula(" AND ".join(["RSI(14) > 1"] * 50))
    with pytest.raises(FormulaError, match="산술"):
        compile_formula("C" + "+C" * 9 + " > 1")            # 왼쪽 결합 깊이 9 > 8


def test_non_string_and_empty():
    for bad in ["", "   \n ", None, 5, ["C > 1"]]:
        with pytest.raises(FormulaError):
            compile_formula(bad)


def test_fuzz_only_formula_errors_or_valid_ast():
    rng = random.Random(0)
    atoms = ["C", "V", "MA", "(", ")", ",", "20", "1.5", ">", "<=", "AND", "OR", "NOT", "+", "-", "*", "/", "D.", "M5.", "POS.", "RSI",
             "CROSSUP", "HOLD", " ", "\n", "TRUE", "(1)", "H", "HIGHEST"]
    ok = 0
    for _ in range(3000):
        text = "".join(rng.choice(atoms) for _ in range(rng.randint(1, 30)))
        try:
            out = compile_formula(text)
        except FormulaError:
            continue
        ok += 1
        assert out["logic"] in ("all", "any") and out["items"]     # RecursionError·KeyError 같은 다른 예외는 여기서 터진다
    assert ok >= 0


# ---- 수식 → 전체 명세(Spec) 검증: 모드·시간 단위·pos 규칙은 명세 검증(validate_group)이 한다 ----
def _spec_with(mode, entry, exit_=None):
    from tests.studio.application.fakes import spec_dict
    d = spec_dict(mode=mode)
    d["strategy"]["entry"] = compile_formula(entry)
    if exit_:
        d["strategy"]["exit"] = compile_formula(exit_)
    if mode == "intraday":
        d["intraday"] = {"bar_minutes": 5}
        d["period"] = {"start": "2026-08-03", "end": "2026-08-20"}
    return d


@pytest.mark.parametrize("mode,entry,exit_,ok,why", [
    ("intraday", "M15.C > M15.MA(C,20)", None, True, ""),
    ("intraday", "C > MA(C,20)", "POS.RETURN_PCT >= 5 OR C < MA(C,5)", True, ""),
    ("daily_portfolio", "M5.C > 1", None, False, "일봉 모드"),
    ("intraday", "POS.RETURN_PCT > 5", None, False, "청산 조건에서만"),
    ("intraday", "M3.C > 1", None, False, "배수"),
    ("intraday", "DL.VOL_RATIO(20) > 2", None, False, "daily_live"),
])
def test_formula_inside_a_full_spec(mode, entry, exit_, ok, why):
    from pydantic import ValidationError
    from studio.domain.spec import Spec
    d = _spec_with(mode, entry, exit_)
    if ok:
        Spec.model_validate(d)
    else:
        with pytest.raises(ValidationError, match=why):
            Spec.model_validate(d)
