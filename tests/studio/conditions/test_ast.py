"""조건식 AST — 오류 경로·범위·깊이·변수 치환."""
import pytest
from pydantic import ValidationError

from studio.domain.conditions.ast import Group, ParamRef, bind_group, has_params, iter_param_slots
from tests.studio.conditions.helpers import cond, const, field, group, ind


def _g(*items, logic="all"):
    return group(logic, *items)


def _errors(data) -> list[dict]:
    with pytest.raises(ValidationError) as e:
        Group.model_validate(data)
    return e.value.errors()


def test_valid_group_parses():
    g = Group.model_validate(_g(cond(field("close"), "gt", ind("highest", src="high", n=20))))
    assert g.depth == 1 and not has_params(g)


def test_unknown_indicator_error_has_path():
    errs = _errors(_g(cond(field("close"), "gt", ind("no_such", n=20))))
    e = next(x for x in errs if "없는 지표" in x["msg"])
    assert "items" in e["loc"] and "right" in e["loc"]


@pytest.mark.parametrize("n", [0, 501, -3])
def test_n_out_of_range(n):
    errs = _errors(_g(cond(field("close"), "gt", ind("sma", src="close", n=n))))
    assert any("범위" in x["msg"] for x in errs)


def test_non_integer_n_and_bad_enum_and_unknown_param():
    assert any("정수" in x["msg"] for x in _errors(_g(cond(field("close"), "gt", ind("sma", n=2.5)))))
    assert any("허용값" in x["msg"] for x in _errors(_g(cond(field("close"), "gt", ind("sma", src="foo", n=5)))))
    assert any("없는 파라미터" in x["msg"] for x in _errors(_g(cond(field("close"), "gt", ind("sma", zzz=1)))))


def test_depth_limit_is_two():
    ok = _g(_g(cond(field("close"), "gt", const(1))))
    Group.model_validate(ok)  # 그룹 안 그룹 = 2단계
    too_deep = _g(_g(_g(cond(field("close"), "gt", const(1)))))
    assert any("단계" in x["msg"] for x in _errors(too_deep))


def test_const_vs_const_rejected_and_negative_offset_rejected():
    assert any("상수끼리" in x["msg"] for x in _errors(_g(cond(const(1), "gt", const(2)))))
    with pytest.raises(ValidationError):
        Group.model_validate(_g(cond(field("close", offset=-1), "gt", const(1))))  # 음수 = 미래 참조


def test_unknown_field_and_extra_keys_rejected():
    with pytest.raises(ValidationError):
        Group.model_validate(_g(cond(field("adj_close"), "gt", const(1))))
    bad = _g(cond(field("close"), "gt", const(1)))
    bad["items"][0]["typo"] = 1
    with pytest.raises(ValidationError):
        Group.model_validate(bad)


def test_param_refs_and_bind():
    g = Group.model_validate(_g(
        cond(field("close"), "gt", ind("highest", src="high", n={"param": "n"})),
        cond(field("volume"), "gte", ind("sma", offset=1, mul={"param": "m"}, src="volume", n=20)),
        cond(ind("rsi", n=14), "lt", const({"param": "lvl"})),
    ))
    assert has_params(g)
    assert {s[0] for s in iter_param_slots(g)} == {"n", "m", "lvl"}
    bound = bind_group(g, {"n": 60, "m": 1.5, "lvl": 30})
    assert not has_params(bound)
    assert bound.items[0].right.params["n"] == 60
    assert bound.items[1].right.mul == 1.5
    with pytest.raises(ValueError, match="값이 없음"):
        bind_group(g, {"n": 60})
    with pytest.raises(ValidationError):  # 바인딩 뒤 재검증 — 범위 밖 값은 오류
        bind_group(g, {"n": 9999, "m": 1.5, "lvl": 30})


def test_paramref_type():
    assert ParamRef(param="x").param == "x"
    with pytest.raises(ValidationError):
        ParamRef(param="1bad")


def test_market_operand():
    ok = _g(cond({"kind": "market", "index": "kospi", "name": "close"}, "gt",
                 {"kind": "market", "index": "kospi", "name": "sma", "params": {"n": 20}}))
    Group.model_validate(ok)
    with pytest.raises(ValidationError):
        Group.model_validate(_g(cond({"kind": "market", "index": "nasdaq", "name": "close"}, "gt", const(1))))
    with pytest.raises(ValidationError):
        Group.model_validate(_g(cond({"kind": "market", "index": "kospi", "name": "close", "params": {"n": 5}}, "gt", const(1))))
