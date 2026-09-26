"""Spec — 프리셋 6종 검증 통과, 모드별 의미 검사, 변수 범위·치환, 문장 풀이."""
import copy
import json
import pathlib

import pytest
from pydantic import ValidationError

from studio.domain.conditions.ast import iter_operands, ParamRef
from studio.domain.narration import josa, narrate
from studio.domain.spec import LEGACY_NAMES, Spec, bind_params

ROOT = pathlib.Path(__file__).resolve().parents[3]
PRESETS = sorted((ROOT / "presets" / "studio").glob("*.json"))
EXPECTED = {"new_high_20", "golden_cross_5_20", "rsi_rebound", "pullback_ma20", "gap_up_value_top", "tick_breakout_5m"}


def _load(name: str) -> dict:
    return json.loads((ROOT / "presets" / "studio" / f"{name}.json").read_text(encoding="utf-8"))


def _bad(data: dict, fragment: str):
    with pytest.raises(ValidationError) as e:
        Spec.model_validate(data)
    assert fragment in str(e.value), str(e.value)


def test_exactly_the_six_presets_exist_and_validate():
    assert {p.stem for p in PRESETS} == EXPECTED
    for p in PRESETS:
        Spec.model_validate(json.loads(p.read_text(encoding="utf-8")))


def test_presets_roundtrip_json():
    for p in PRESETS:
        s = Spec.model_validate(json.loads(p.read_text(encoding="utf-8")))
        assert Spec.model_validate(s.model_dump(mode="json")) == s


def test_daily_presets_bind_with_defaults_and_narrate():
    for name in ("new_high_20", "golden_cross_5_20", "rsi_rebound", "pullback_ma20"):
        s = bind_params(Spec.model_validate(_load(name)))
        assert not any(isinstance(v, ParamRef) for g in s._groups() for o in iter_operands(g)
                       for v in getattr(o, "params", {}).values())
        assert narrate(s).strip()


def test_narration_examples():
    s = bind_params(Spec.model_validate(_load("new_high_20")))
    first = narrate(s).splitlines()[0]
    assert first == ("종가가 20일 최고가를 넘고 거래량이 1일 전 거래량 20일 이동평균의 1.5배 이상이면 "
                     "다음 날 시가에 산다.")
    g = narrate(bind_params(Spec.model_validate(_load("golden_cross_5_20")))).splitlines()
    assert g[0] == "종가 5일 이동평균이 종가 20일 이동평균을 상향 돌파하면 다음 날 시가에 산다."
    assert g[1] == "종가 5일 이동평균이 종가 20일 이동평균을 하향 이탈하면 다음 날 시가에 판다."
    assert "손절 -7%" in narrate(bind_params(Spec.model_validate(_load("new_high_20"))))
    # 변수가 안 채워진 명세는 [변수이름] 으로 보인다
    assert "[n]일 최고가" in narrate(Spec.model_validate(_load("new_high_20")))


def test_josa():
    assert josa("종가", "이/가") == "가" and josa("거래량", "이/가") == "이"
    assert josa("20일", "은/는") == "은" and josa("5", "을/를") == "를" and josa("30", "을/를") == "을"


def test_bind_params_overrides_and_range():
    s = bind_params(Spec.model_validate(_load("new_high_20")), {"n": 60, "vol_mult": 2.0})
    assert s.strategy.entry.items[0].right.params["n"] == 60
    assert s.strategy.entry.items[1].right.mul == 2.0
    with pytest.raises(ValueError, match="params 에 없는"):
        bind_params(Spec.model_validate(_load("new_high_20")), {"zzz": 1})
    with pytest.raises(ValidationError):
        bind_params(Spec.model_validate(_load("new_high_20")), {"n": 1000})  # n 최대 500


def test_variable_must_be_defined_and_within_slot_range():
    d = _load("new_high_20")
    d1 = copy.deepcopy(d)
    del d1["params"]["n"]
    _bad(d1, "params 에 정의되지 않음")
    d2 = copy.deepcopy(d)
    d2["params"]["n"]["max"] = 900  # highest.n 은 500 까지
    _bad(d2, "허용 범위")
    d3 = copy.deepcopy(d)
    d3["params"]["n"]["step"] = 2.5
    _bad(d3, "정수")


def test_mode_specific_checks():
    d = _load("new_high_20")
    a = copy.deepcopy(d); a["mode"] = "daily_single"
    _bad(a, "종목 1개")
    b = copy.deepcopy(d); b["mode"] = "intraday"
    _bad(b, "intraday 설정이 없음")
    c = copy.deepcopy(d); c["mode"] = "tick"
    _bad(c, "tick 설정이 없음")
    e = copy.deepcopy(d); e["strategy"] = None
    _bad(e, "strategy 가 필요")
    f = copy.deepcopy(d); f["strategy"]["entry"]["items"] = []
    _bad(f, "조건이 하나도 없음")


def test_compat_only_daily_single_and_locks_exits():
    d = _load("new_high_20")
    d["compat"] = {"legacy": True}
    _bad(d, "daily_single 에서만")
    d["mode"] = "daily_single"
    d["universe"] = {"type": "codes", "codes": ["005930"]}
    _bad(d, "호환 모드에서는")            # exits 에 손절·트레일링이 남아 있음
    d["exits"] = {}
    Spec.model_validate(d)


def test_intraday_only_indicator_rejected_in_daily_and_daily_only_in_intraday():
    d = _load("new_high_20")
    d["strategy"]["entry"]["items"][0]["right"] = {"kind": "ind", "name": "vwap"}
    _bad(d, "vwap")
    g = _load("gap_up_value_top")
    g["strategy"]["entry"]["items"].append({"left": {"kind": "ind", "name": "value_rank"}, "op": "lte",
                                            "right": {"kind": "const", "value": 30}})
    _bad(g, "value_rank")


def test_intraday_prefilter_may_use_daily_indicator():
    g = _load("gap_up_value_top")
    g["intraday"]["prefilter"] = {"logic": "all", "items": [
        {"left": {"kind": "ind", "name": "value_rank"}, "op": "lte", "right": {"kind": "const", "value": 30}}]}
    Spec.model_validate(g)


def test_sizing_consistency_and_period_and_tick_conditions():
    d = _load("new_high_20")
    a = copy.deepcopy(d); a["portfolio"]["sizing"] = "fixed_amount"
    _bad(a, "fixed_amount")
    b = copy.deepcopy(d); b["portfolio"]["sizing"] = "risk_pct"; b["portfolio"]["risk_pct"] = 1; b["exits"]["stop_loss_pct"] = None
    _bad(b, "risk_pct")
    c = copy.deepcopy(d); c["period"] = {"start": "2026-01-01", "end": "2025-01-01"}
    _bad(c, "늦음")
    t = _load("tick_breakout_5m")
    t["tick"]["catalog"]["breakout_min"] = None
    _bad(t, "틱 조건이 하나도 없음")
    u = _load("tick_breakout_5m")
    u["tick"]["catalog"]["time_from"] = "16:00"
    _bad(u, "time_from")


def test_exit_literal_ranges_and_unknown_keys():
    d = _load("new_high_20")
    a = copy.deepcopy(d); a["exits"]["stop_loss_pct"] = 0
    _bad(a, "stop_loss_pct")
    b = copy.deepcopy(d); b["exits"]["max_holding_bars"] = 2.5
    _bad(b, "max_holding_bars")
    c = copy.deepcopy(d); c["surprise"] = 1
    _bad(c, "surprise")


def test_legacy_source_spec_and_names_match_registry():
    from studio.infrastructure.legacy_strategies import REGISTRY
    assert set(LEGACY_NAMES) == set(REGISTRY)
    d = _load("new_high_20")
    d["strategy"] = {"source": "legacy", "name": "new_high_swing", "params": {"n_day_high": {"param": "n"}}}
    d["params"] = {"n": {"default": 20, "min": 20, "max": 120, "step": 20}}
    s = bind_params(Spec.model_validate(d), {"n": 60})
    assert s.strategy.params["n_day_high"] == 60
    assert "N일 신고가 스윙" in narrate(s)
    d["strategy"]["name"] = "nope"
    _bad(d, "nope")


def test_intraday_source_default_is_al_and_old_specs_load_as_al():
    d = _load("gap_up_value_top")
    assert "source" not in d["intraday"]                          # 옛 명세(칸 없음)
    assert Spec.model_validate(d).intraday.source == "al"
    d["intraday"]["source"] = "krx"
    assert Spec.model_validate(d).intraday.source == "krx"
    d["intraday"]["source"] = "nxt"
    _bad(d, "source")
    assert Spec.model_validate(_load("gap_up_value_top")).model_dump(mode="json")["intraday"]["source"] == "al"


def test_intraday_krx_narration_has_source_note_and_al_does_not():
    d = _load("gap_up_value_top")
    assert "KRX 분봉 기준" not in narrate(bind_params(Spec.model_validate(d)))
    d["intraday"]["source"] = "krx"
    text = narrate(bind_params(Spec.model_validate(d)))
    assert "KRX 분봉 기준" in text and "20~40% 작다" in text


def test_market_condition_narration_says_previous_day_in_intraday_only():
    mk = {"logic": "all", "items": [{"left": {"kind": "market", "index": "kospi", "name": "close"}, "op": "gt",
                                     "right": {"kind": "market", "index": "kospi", "name": "sma", "params": {"n": 20}}}]}
    g = _load("gap_up_value_top")
    g["market_filter"] = mk
    assert "전일 코스피 종가가 전일 코스피 20일 이동평균을" in narrate(bind_params(Spec.model_validate(g)))
    d = _load("new_high_20")
    d["market_filter"] = mk
    line = next(x for x in narrate(bind_params(Spec.model_validate(d))).splitlines() if x.startswith("단,"))
    assert "코스피 종가가 코스피 20일 이동평균을" in line and "전일" not in line   # 일봉 모드는 그대로


def test_intraday_narration_warns_that_rolling_indicators_include_previous_day_bars():
    note = "전날 봉을 포함"
    g = _load("gap_up_value_top")                       # gap_pct·time·vwap 만 — 롤링 지표 없음
    assert note not in narrate(bind_params(Spec.model_validate(g)))
    g["strategy"]["entry"]["items"].append({
        "left": {"kind": "field", "name": "close"}, "op": "gt",
        "right": {"kind": "ind", "name": "sma", "params": {"src": "close", "n": 20}}})
    assert note in narrate(bind_params(Spec.model_validate(g)))
    assert note not in narrate(bind_params(Spec.model_validate(_load("new_high_20"))))  # 일봉엔 안 붙음
