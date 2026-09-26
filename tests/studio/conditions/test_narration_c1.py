"""풀이 문장 — studio-conditions c1 새 칸(tf·hold·within·negate·expr·pos·새 연산자)을 문장으로."""
import copy
import json
import pathlib

from studio.domain.conditions.ast import Group
from studio.domain.narration import narrate, narrate_group
from studio.domain.spec import Spec, bind_params

ROOT = pathlib.Path(__file__).resolve().parents[3]


def F(name="close", **kw):
    return {"kind": "field", "name": name, **kw}


def I(name, params=None, **kw):
    return {"kind": "ind", "name": name, "params": params or {}, **kw}


def C(v):
    return {"kind": "const", "value": v}


def cond(left, op, right=None, **kw):
    d = {"left": left, "op": op, **kw}
    if right is not None:
        d["right"] = right
    return d


def grp(*items, logic="all", **kw):
    return {"logic": logic, "items": list(items), **kw}


def say(*items, unit="봉", **kw) -> str:
    return narrate_group(Group.model_validate(grp(*items, **kw)), unit)


def test_gt_at_the_end_reads_neumyeon():
    assert say(cond(F(), "gt", C(100))) == "종가가 100을 넘으면"          # '넘면' 이 아니라 '넘으면'
    assert say(cond(F(), "gt", C(100)), cond(F("volume"), "gte", C(5))) == "종가가 100을 넘고 거래량이 5 이상이면"


def test_time_frame_prefix_and_own_unit():
    m15 = I("sma", {"src": "close", "n": 20}, tf="m15")
    assert say(cond(F(), "gt", m15)) == "종가가 15분봉 종가 20봉 이동평균을 넘으면"
    dprev = I("highest", {"src": "high", "n": 20}, tf="daily_prev")
    assert say(cond(F(), "gt", dprev)) == "종가가 일봉(전일 확정) 20일 최고가를 넘으면"
    live = I("sma", {"src": "close", "n": 20}, tf="daily_live", offset=1)
    assert say(cond(F(), "gt", live)) == "종가가 일봉(장중 실시간) 1일 전 종가 20일 이동평균을 넘으면"   # offset 은 그 시간 단위(일)로
    assert say(cond(F("close", tf="daily_prev"), "gt", C(0))) == "일봉(전일 확정) 종가가 0을 넘으면".replace("0을", "0을")


def test_hold_within_and_unary_operators():
    assert say(cond(F(), "gt", C(100), hold=3)) == "3봉 연속으로 종가가 100을 넘으면"
    sma5, sma20 = I("sma", {"src": "close", "n": 5}), I("sma", {"src": "close", "n": 20})
    assert say(cond(sma5, "cross_above_within", sma20, within=3)) == \
        "최근 3봉 안에 종가 5봉 이동평균이 종가 20봉 이동평균을 상향 돌파했으면"
    assert say(cond(sma5, "cross_below_within", sma20, within=2), cond(F(), "gt", C(1))) == \
        "최근 2봉 안에 종가 5봉 이동평균이 종가 20봉 이동평균을 하향 이탈했고 종가가 1을 넘으면"
    assert say(cond(I("hammer"), "is_true")).endswith("성립하면")
    assert say(cond(I("hammer"), "is_false")).endswith("성립하지 않으면")
    assert "망치형" in say(cond(I("hammer"), "is_true"))


def test_negate_top_level_and_nested_group():
    assert say(cond(F(), "gt", C(100)), negate=True) == "(종가가 100을 넘는다) 조건이 성립하지 않으면"
    inner = grp(cond(F(), "gt", C(200)), cond(F("open"), "lt", C(50)), logic="any", negate=True)
    assert say(cond(F(), "gt", C(100)), inner) == \
        "종가가 100을 넘고 (종가가 200을 넘는다 또는 시가가 50 미만이다) 조건이 성립하지 않으면"


def test_expr_and_position_operands():
    price_band = {"kind": "expr", "op": "*", "left": I("sma", {"src": "close", "n": 20}), "right": C(1.05)}
    assert say(cond(F(), "gt", price_band)) == "종가가 (종가 20봉 이동평균 × 1.05)를 넘으면"
    diff = {"kind": "expr", "op": "-", "left": F("high"), "right": F("low")}
    assert say(cond(diff, "gt", C(3))) == "(고가 − 저가)가 3을 넘으면"
    pos = {"kind": "pos", "name": "return_pct"}
    assert say(cond(pos, "gte", C(5))) == "보유 수익률이 5% 이상이면"                      # 상수와 비교하면 % 를 붙인다
    dd = {"kind": "pos", "name": "drawdown_pct"}
    assert say(cond(dd, "gte", C(3))) == "보유 중 최고가 대비 하락률이 3% 이상이면"         # 양수 % = 최고가보다 N% 아래
    assert say(cond({"kind": "pos", "name": "bars_held"}, "gte", C(20))) == "보유 봉 수가 20 이상이면"   # % 아닌 값엔 안 붙음
    assert "매수가" in say(cond(F(), "lt", {"kind": "pos", "name": "entry_price"}))


def _spec(entry_extra: dict) -> Spec:
    d = json.loads((ROOT / "presets" / "studio" / "gap_up_value_top.json").read_text(encoding="utf-8"))
    d = copy.deepcopy(d)
    d["strategy"]["entry"]["items"].append(entry_extra)
    return bind_params(Spec.model_validate(d))


def _exit_line(preset: str, exits: dict) -> str:
    d = json.loads((ROOT / "presets" / "studio" / f"{preset}.json").read_text(encoding="utf-8"))
    d["exits"] = exits
    text = narrate(bind_params(Spec.model_validate(d)))
    return next(x for x in text.splitlines() if x.startswith("청산 규칙:"))


def test_exit_rules_c2_fields_are_narrated():
    line = _exit_line("new_high_20", {
        "stop_loss_pct": 7, "take_profit_levels": [{"pct": 5, "fraction": 0.5}, {"pct": 10, "fraction": 1}],
        "take_profit_mode": "close", "trailing_stop_pct": 10, "trail_activate_pct": 8, "breakeven_after_pct": 4,
        "max_holding_bars": 20})
    assert line == ("청산 규칙: 손절 -7%, 최고 수익률 4% 를 넘으면 손절선을 매수가로, "
                    "분할 익절 +5% 에 남은 수량의 50%, +10% 에 나머지 전부 (종가가 선을 넘으면 다음 봉 시가에), "
                    "고점 대비 -10% 트레일링(최고 수익률 8% 를 넘은 뒤부터), 최대 20봉 보유.")
    assert _exit_line("new_high_20", {"take_profit_pct": 6, "take_profit_mode": "close"}) == \
        "청산 규칙: 익절 +6% (종가가 선을 넘으면 다음 봉 시가에)."
    assert _exit_line("gap_up_value_top", {"stop_loss_pct": 3, "max_holding_minutes": 30}) == \
        "청산 규칙: 손절 -3%, 30분 보유 후 종가 청산."
    assert _exit_line("new_high_20", {"stop_loss_pct": 7, "trailing_stop_pct": 10}) == \
        "청산 규칙: 손절 -7%, 고점 대비 -10% 트레일링."          # 옛 명세 문장은 그대로


def test_notes_rolling_previous_day_bars_only_for_minute_time_frames():
    rolling = "전날 봉을 포함"
    minute_sma = cond(F(), "gt", I("sma", {"src": "close", "n": 20}, tf="m15"))
    assert rolling in narrate(_spec(minute_sma))
    daily_sma = cond(F(), "gt", I("sma", {"src": "close", "n": 20}, tf="daily_prev"))
    assert rolling not in narrate(_spec(daily_sma))                    # 일봉 지표는 날 단위 창이라 해당 없음
    for extra in ({}, {"include_current": True}):                       # daily_prev 는 "장 시작 전에 알 수 있는 값"(설계 v0.3) — 하루 묵음 주의문 없음
        hi = cond(F(), "gt", I("highest", {"src": "high", "n": 20, **extra}, tf="daily_prev"))
        assert "하루 묵은" not in narrate(_spec(hi))
    assert rolling in narrate(_spec(cond(F(), "gt", I("wma", {"src": "close", "n": 10}))))   # 새 롤링 지표도 잡는다
    assert rolling not in narrate(_spec(cond(F(), "gt", I("hammer"))))                        # 창이 없는 캔들은 해당 없음
