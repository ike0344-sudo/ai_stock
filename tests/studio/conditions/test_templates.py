"""조건 템플릿(문장 빈칸 채우기, 설계 §5.5) — 모든 템플릿 × 지원 모드: build → 명세 검증 통과, build → match 되돌리기 동일, 골든, 쉬운 말 오류, 풀이 문장과의 정합."""
import pytest
from pydantic import ValidationError

from studio.domain.conditions import templates as T
from studio.domain.conditions.ast import Group
from studio.domain.conditions.catalog import MINUTE_TIMEFRAMES
from studio.domain.conditions.validation import validate_group
from studio.domain.narration import narrate_group
from studio.domain.spec import Spec
from tests.studio.application.fakes import spec_dict

MODES = ("daily_single", "daily_portfolio", "intraday")


def _cases():
    for t in T.TEMPLATES:
        for m in MODES:
            if T.availability(t, m)[0]:
                yield pytest.param(t, m, id=f"{t.id}-{m}")


CASES = list(_cases())


def _group(c):
    return Group.model_validate({"logic": "all", "items": [c]})


def _spec(t, mode, cond, source="al"):
    d = spec_dict(mode=mode)
    role = "exit" if t.role == "exit" else "entry"
    d["strategy"][role] = {"logic": "all", "items": [cond]}
    if t.role == "exit":
        d["strategy"]["entry"] = {"logic": "all", "items": [{"left": {"kind": "field", "name": "close"}, "op": "gt", "right": {"kind": "const", "value": 1}}]}
    if mode == "intraday":
        d["intraday"] = {"bar_minutes": 5, "source": source}
        d["period"] = {"start": "2026-08-03", "end": "2026-08-20"}
    return d


def test_there_are_about_fifty_templates_in_all_eight_categories():
    assert 40 <= len(T.TEMPLATES) <= 70
    assert {t.category for t in T.TEMPLATES} == set(T.CATEGORIES)
    assert len({t.id for t in T.TEMPLATES}) == len(T.TEMPLATES)


@pytest.mark.parametrize("t,mode", CASES)
def test_default_build_passes_group_validation_and_the_whole_spec(t, mode):
    c = T.build(t.id, mode=mode)
    role = "exit" if t.role == "exit" else "entry"
    validate_group(_group(c), role, mode=mode, bar_minutes=5, source="al")     # 모드·시간 단위·pos 규칙
    if mode != "daily_single":
        Spec.model_validate(_spec(t, mode, c))                                   # 전체 명세(진입/청산 자리 포함)


@pytest.mark.parametrize("t,mode", CASES)
def test_build_then_match_returns_the_same_template_and_values(t, mode):
    dv = T.defaults(t, mode)
    got = T.match(T.build(t.id, mode=mode), mode)
    assert got is not None and got[0] == t.id, (t.id, got)
    want = {s.name: dv[s.name] for s in T.visible_slots(t, mode) if s.name in got[1]}
    assert {k: (float(v) if not isinstance(v, str) else v) for k, v in got[1].items() if k in want} == \
           {k: (float(v) if not isinstance(v, str) else v) for k, v in want.items()}
    # mode 를 모르면 일봉용·분봉용이 같은 AST 가 되는 쌍(high_break ↔ high_break_bars)에서 먼저 나오는 쪽이 답이다 — 어느 쪽이든 다시 만들면 같은 조건
    blind = T.match(T.build(t.id, mode=mode))
    assert blind is not None and any(T.build(blind[0], blind[1], mode=m) == T.build(t.id, mode=mode) for m in MODES if T.availability(T.BY_ID[blind[0]], m)[0])


@pytest.mark.parametrize("t,mode", CASES)
def test_round_trip_at_range_edges_every_choice_and_every_enabled_time_unit(t, mode):
    for s in T.visible_slots(t, mode):
        opts = ([s.lo, s.hi] if s.kind == "number" else [v for v, _ in s.choices] if s.kind == "choice"
                else [c["value"] for c in T._tf_choices(t, s, mode, 5, "al") if c["enabled"]])
        for x in opts:
            vals = {s.name: x}
            if s.name in ("a", "n1", "n2") and s.kind == "number":                # 짧은 선 < 긴 선 조건을 깨지 않게
                vals = {s.name: min(x, 10)}
            try:
                c = T.build(t.id, vals, mode=mode)
            except T.TemplateError:
                continue                                                          # 관계 검사(짧은 선 < 긴 선 등)에 걸린 경계는 건너뜀
            got = T.match(c, mode)
            assert got is not None and got[0] == t.id, (t.id, vals, got)
            assert float(got[1][s.name]) == float(list(vals.values())[0]) if s.kind == "number" else got[1][s.name] == x


def test_golden_conditions():
    # 1분봉으로 실행할 때의 5분봉 거래대금(실행 봉과 같은 5분은 "지금 보는 봉"으로 고른다)
    assert T.build("value_eok", {"tf": "m5", "x": 20}, mode="intraday", bar_minutes=1) == \
        {"left": {"kind": "ind", "name": "value_eok", "tf": "m5"}, "op": "gte", "right": {"kind": "const", "value": 20.0}}   # 설계서 §5.5 대표 골든
    assert T.build("value_eok", {"x": 20}, mode="daily_portfolio") == \
        {"left": {"kind": "ind", "name": "value_eok"}, "op": "gte", "right": {"kind": "const", "value": 20.0}}                 # 일봉은 시간 단위 칸 자체가 없다
    assert T.build("high_break", {"n": 20}, mode="intraday") == \
        {"left": {"kind": "field", "name": "close"}, "op": "gt",
         "right": {"kind": "ind", "name": "highest", "params": {"src": "high", "n": 20}, "tf": "daily_prev"}}                    # 분봉에선 D.HIGHEST(H,20)
    assert T.build("high_break", {"n": 20}, mode="daily_portfolio")["right"] == {"kind": "ind", "name": "highest", "params": {"src": "high", "n": 20}}
    assert T.build("pos_loss", {"x": 3}, mode="intraday") == {"left": {"kind": "pos", "name": "return_pct"}, "op": "lte", "right": {"kind": "const", "value": -3.0}}
    assert T.build("ma_disparity_low", {"n": 20, "x": 5}, mode="daily_portfolio")["right"]["value"] == 95.0                      # 낮다 = 100 − x
    assert T.build("ma_disparity_high", {"n": 20, "x": 5}, mode="daily_portfolio")["right"]["value"] == 105.0
    assert T.build("cum_value", {"x": 100}, mode="intraday")["right"]["value"] == 1e10                                            # 억 → 원
    assert T.build("ma_cross_up", {"a": 5, "b": 20, "tf": "m15"}, mode="intraday")["op"] == "cross_above"
    assert T.build("prev_high_break", mode="daily_portfolio") == {"left": {"kind": "ind", "name": "prev_high_break"}, "op": "is_true"}
    assert T.build("rsi_level", {"x": 70, "cmp": "gte"}, mode="daily_portfolio")["op"] == "gte"
    assert T.build("value_eok", {"x": 0.3}, mode="daily_portfolio")["right"]["value"] == 0.3
    assert T.build("first_n_value", {"x": 0.3}, mode="intraday")["right"]["value"] == 30000000.0                                      # 0.3×1e8 부동소수 잡음 없음


def test_match_of_hand_made_conditions_and_of_things_no_sentence_can_say():
    hand = {"left": {"kind": "ind", "name": "value_eok", "tf": "m5"}, "op": "gte", "right": {"kind": "const", "value": 20}}   # 손으로 만든 기본값 생략형
    assert T.match(hand, "intraday") == ("value_eok", {"tf": "m5", "x": 20, "cmp": "gte"})
    full = Group.model_validate({"logic": "all", "items": [hand]}).model_dump(mode="json")["items"][0]                             # 기본값이 다 채워진 형태도
    assert T.match(full, "intraday") == ("value_eok", {"tf": "m5", "x": 20, "cmp": "gte"})
    assert T.match({"left": {"kind": "ind", "name": "value_eok"}, "op": "gte", "right": {"kind": "const", "value": 20}, "hold": 3}) is None  # hold 3 은 문장에 없다
    assert T.match({"left": {"kind": "field", "name": "close", "offset": 2}, "op": "gt", "right": {"kind": "const", "value": 5}}) is None
    assert T.match({"left": {"kind": "ind", "name": "sma", "params": {"src": "close", "n": 7}}, "op": "gt",
                    "right": {"kind": "ind", "name": "sma", "params": {"src": "open", "n": 7}}}) is None
    assert T.match({"left": {"kind": "ind", "name": "rsi", "params": {"n": 14}}, "op": "gt", "right": {"kind": "const", "value": 30}}) is None   # gt 는 이상/이하 문장에 없다
    assert T.match({"left": {"kind": "ind", "name": "rsi", "params": {"n": 14}}, "op": "lte", "right": {"kind": "const", "value": 130}}) is None  # 범위 밖 값


# ---------------------------------------------------------------- 오류는 쉬운 말로, 어느 칸인지 알려서
@pytest.mark.parametrize("tid,vals,mode,slot,words", [
    ("value_eok", {"x": -1}, "daily_portfolio", "x", "사이로 적어"),
    ("value_eok", {"x": True}, "daily_portfolio", "x", "숫자"),
    ("value_eok", {"x": "20"}, "daily_portfolio", "x", "숫자"),
    ("above_ma", {"n": 20.5}, "daily_portfolio", "n", "소수점 없는"),
    ("above_ma", {"n": 1}, "daily_portfolio", "n", "사이로 적어"),
    ("above_ma", {"cmp": "eq"}, "daily_portfolio", "cmp", "중에서 골라"),
    ("above_ma", {"nope": 1}, "daily_portfolio", "nope", "없는 빈칸"),
    ("ma_cross_up", {"a": 30, "b": 20}, "daily_portfolio", "b", "짧은 선"),
    ("ma_aligned", {"n1": 20, "n2": 10, "n3": 60}, "daily_portfolio", "n1", "짧은 것부터"),
    ("value_eok", {"tf": "m3"}, "intraday", "tf", "배수"),
    ("value_eok", {"tf": "m5"}, "intraday", "tf", "배수"),                       # 실행 봉과 같은 5분은 '지금 보는 봉' 으로 고른다
    ("value_eok", {"tf": "daily_live"}, "intraday", "tf", "KRX"),                # 거래대금 + 통합(AL) 분봉 + 오늘 지금까지
    ("rsi_level", {"tf": "nope"}, "intraday", "tf", "고를 수 있는 값이"),
    ("cum_value", {}, "daily_portfolio", "", "분봉 실행에서만"),
    ("pos_minutes", {}, "daily_portfolio", "", "분봉 실행에서만"),
    ("value_eok", {}, "tick", "", "쓸 수 없어요"),
])
def test_bad_values_raise_template_error_in_plain_korean(tid, vals, mode, slot, words):
    with pytest.raises(T.TemplateError) as e:
        T.build(tid, vals, mode=mode, bar_minutes=5, source="al")
    assert words in e.value.message and e.value.slot == slot


def test_unknown_template_id_is_a_key_error():
    with pytest.raises(KeyError):
        T.build("nope")


def test_volume_based_daily_live_needs_krx_source_and_then_passes_the_spec():
    tmpl = T.BY_ID["value_eok"]
    c = T.build("value_eok", {"tf": "daily_live", "x": 100}, mode="intraday", source="krx")
    Spec.model_validate(_spec(tmpl, "intraday", c, source="krx"))
    with pytest.raises(ValidationError, match="KRX"):
        Spec.model_validate(_spec(tmpl, "intraday", c, source="al"))


def test_time_unit_choices_follow_bar_length_and_explain_why_disabled():
    s = next(s for s in T.BY_ID["value_eok"].slots if s.kind == "tf")
    ch = {c["value"]: c for c in T._tf_choices(T.BY_ID["value_eok"], s, "intraday", 5, "al")}
    assert [k for k, c in ch.items() if c["enabled"] and k in MINUTE_TIMEFRAMES] == ["m10", "m15", "m30", "m60"]
    assert ch["m3"]["reason"] and ch["daily_live"]["reason"] and ch["daily_prev"]["enabled"] and ch["bar"]["enabled"]
    ch = {c["value"]: c for c in T._tf_choices(T.BY_ID["value_eok"], s, "intraday", 1, "krx")}
    assert ch["m3"]["enabled"] and ch["daily_live"]["enabled"]
    rsi = T.BY_ID["rsi_level"]                                                   # 오늘 지금까지(live) 를 지원하는 지표는 통합 출처에서도 켜진다
    ch = {c["value"]: c for c in T._tf_choices(rsi, next(s for s in rsi.slots if s.kind == "tf"), "intraday", 5, "al")}
    assert ch["daily_live"]["enabled"]


# ---------------------------------------------------------------- 문장
def test_sentences_have_no_leftover_braces_and_read_as_plain_sentences():
    for t, mode in ((t, m) for t in T.TEMPLATES for m in MODES if T.availability(t, m)[0]):
        s = T.sentence(t, T.defaults(t, mode), mode)
        assert "{" not in s and "}" not in s, (t.id, s)
        assert s.rstrip(")").endswith(("다", "요", "있다", "이다")) or s.endswith(")"), (t.id, s)
        assert t.hint and t.category in T.CATEGORIES


def test_golden_sentences():
    tv = lambda i, v, m="intraday": T.sentence(T.BY_ID[i], v, m)
    assert tv("value_eok", {"tf": "m5", "x": 20}) == "5분봉 거래대금이 20억 이상이다"
    assert tv("value_eok", {"tf": "bar", "x": 20}) == "5분봉 거래대금이 20억 이상이다"
    assert tv("value_eok", {"x": 20}, "daily_portfolio") == "거래대금이 20억 이상이다"
    assert tv("value_eok", {"tf": "daily_prev", "x": 20, "cmp": "lte"}) == "어제까지 확정된 일봉 거래대금이 20억 이하다"
    assert tv("high_break", {"n": 20}, "daily_portfolio") == "가격이 20일 최고가를 넘었다"
    assert tv("above_ma", {"n": 20}, "daily_portfolio") == "가격이 20일 이동평균선 위에 있다"
    assert tv("above_ma", {"n": 20, "tf": "m15", "cmp": "lt"}) == "15분봉 가격이 20봉 이동평균선 아래에 있다"
    assert tv("above_daily_ma", {"n": 20, "dtf": "daily_live"}) == "지금 가격이 오늘 지금까지 반영한 20일 이동평균선 위에 있다"
    assert tv("ma_cross_up", {"a": 5, "b": 20}, "daily_portfolio") == "5일선이 20일선을 아래에서 위로 뚫고 올라갔다(골든크로스)"
    assert tv("pos_loss", {"x": 3}) == "산 가격보다 3% 이상 내렸다(손실)"
    assert tv("pos_bars", {"n": 5}, "daily_portfolio") == "산 지 5일이 지났다"
    assert tv("rsi_level", {"n": 14, "x": 30}, "daily_portfolio") == "RSI(14)가 30 이하다"


# 풀이 문장(narration.py, strategy-agent 담당)과의 정합 — 방향(이상/이하/넘/미만/돌파/이탈)과 기준 숫자가 같은 조건을 두 곳이 다르게 말하면 안 된다.
# 알려진 어긋남(보고서에 적음): 큰 수를 1e+10 으로 찍는다 / 전용 문구가 없는 지표(정배열·기울기·이격도·거래대금 배수·장대봉·볼린저 폭)는 기간 같은 인자를 안 보여준다.
NARRATION_PRINTS_SCIENTIFIC = {"cum_value", "first_n_value"}
DIRECTION = {"gte": "이상", "lte": "이하", "gt": "넘", "lt": "미만", "cross_above": "상향 돌파", "cross_below": "하향 이탈", "is_true": "성립"}


@pytest.mark.parametrize("t,mode", [c for c in CASES if c.values[1] != "daily_single"])
def test_narration_agrees_with_the_condition_on_direction_and_threshold(t, mode):
    c = T.build(t.id, mode=mode)
    text = narrate_group(_group(c), "일" if mode != "intraday" else "봉")
    assert text
    if t.id not in ("above_ma", "above_daily_ma", "vwap_side"):                   # 위/아래 선택형은 아래에서 따로(gt/lt 둘 다 나올 수 있다)
        assert DIRECTION[c["op"]] in text, (t.id, mode, c["op"], text)
    if c.get("right", {}).get("kind") == "const" and t.id not in NARRATION_PRINTS_SCIENTIFIC:
        assert f"{c['right']['value']:g}" in text, (t.id, mode, text)             # 기준 숫자(변환된 값 그대로)


def test_choice_direction_words_follow_the_chosen_side():
    for tid, mode, up in (("above_ma", "daily_portfolio", "넘"), ("vwap_side", "intraday", "넘")):
        hi, lo = T.build(tid, {"cmp": "gt"}, mode=mode), T.build(tid, {"cmp": "lt"}, mode=mode)
        assert up in narrate_group(_group(hi), "일") and "미만" in narrate_group(_group(lo), "일")


# ---------------------------------------------------------------- 화면용 목록
def test_describe_lists_every_template_with_slots_choices_and_reasons():
    d = T.describe("intraday", bar_minutes=5, source="al")
    assert len(d) == len(T.TEMPLATES) and all(x["available"] for x in d)
    v = next(x for x in d if x["id"] == "value_eok")
    assert v["example"] == "5분봉 거래대금이 20억 이상이다" and v["role"] == "both" and v["category_label"] == "거래량·거래대금"
    tf = next(s for s in v["slots"] if s["name"] == "tf")
    assert tf["kind"] == "tf" and tf["default"] == "bar" and any(not c["enabled"] and c["reason"] for c in tf["choices"])
    x = next(s for s in v["slots"] if s["name"] == "x")
    assert (x["unit"], x["default"], x["lo"], x["hi"]) == ("억", 20, 0.1, 100000)
    daily = T.describe("daily_portfolio")
    off = next(x for x in daily if x["id"] == "cum_value")
    assert not off["available"] and "분봉" in off["reason"] and off["slots"] == []
    assert not any(s["kind"] == "tf" for x in daily if x["available"] for s in x["slots"])   # 일봉 모드는 시간 단위 칸이 없다
    assert next(s for s in next(x for x in daily if x["id"] == "pos_bars")["slots"])["unit"] == "일"
    assert all(not x["available"] for x in T.describe("tick"))
    assert next(x for x in d if x["id"] == "theme_rank")["warn"]                              # 테마 구성 '현재 기준' 경고
    assert next(x for x in T.describe("daily_portfolio") if x["id"] == "pos_loss")["role"] == "exit"


def test_low_break_bars_matches_the_default_intraday_exit_and_round_trips():
    """분봉 새 백테스트의 기본 청산(종가 < 10봉 최저값) 이 문장 카드로 나온다 — 일봉은 종전대로 low_break."""
    default_exit = {"left": {"kind": "field", "name": "close"}, "op": "lt", "right": {"kind": "ind", "name": "lowest", "params": {"src": "low", "n": 10}}}
    assert T.match(default_exit, "intraday") == ("low_break_bars", {"tf": "bar", "n": 10})
    assert T.match(default_exit, "daily_portfolio")[0] == "low_break"
    card = T.build_card("low_break_bars", {"tf": "bar", "n": 10}, mode="intraday")
    assert T.match(card["condition"], "intraday") == ("low_break_bars", {"tf": "bar", "n": 10})
    assert "10봉 최저가 아래로 내려갔다" in card["sentence"]
    m5 = T.build_card("low_break_bars", {"tf": "m5", "n": 10}, mode="intraday", bar_minutes=1)  # 5분봉 기준 손절도 카드로 되읽힌다
    assert T.match(m5["condition"], "intraday") == ("low_break_bars", {"tf": "m5", "n": 10})
