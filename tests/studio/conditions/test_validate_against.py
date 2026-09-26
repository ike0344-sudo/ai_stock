"""validate_against — 기간이 데이터 범위 밖이면 조용히 0건이 되지 않고 문제로 돌려준다."""
import copy
import datetime as dt
import json
import pathlib

from studio.domain.spec import Problem, Spec, validate_against

ROOT = pathlib.Path(__file__).resolve().parents[3]
D = dt.date


def _load(name: str) -> dict:
    return json.loads((ROOT / "presets" / "studio" / f"{name}.json").read_text(encoding="utf-8"))


def _spec(name="new_high_20", **over) -> Spec:
    d = _load(name)
    d.update(over)
    return Spec.model_validate(d)


FULL = {"daily": (D(2019, 4, 23), D(2026, 8, 31))}


def test_inside_range_has_no_problems():
    assert validate_against(_spec(), FULL) == []


def test_partial_overlap_is_warning_with_dates():
    s = _spec(period={"start": "2019-01-02", "end": "2026-09-30"})
    probs = validate_against(s, FULL)
    assert [p.severity for p in probs] == ["warning", "warning"]
    assert "2019-04-23" in probs[0].message and "2026-08-31" in probs[1].message


def test_no_overlap_is_error():
    (p,) = validate_against(_spec(period={"start": "2010-01-04", "end": "2012-12-28"}), FULL)
    assert p.severity == "error" and p.dataset == "daily" and "겹치지 않음" in p.message


def test_missing_dataset_range_is_error_not_silent():
    (p,) = validate_against(_spec(), {})
    assert p.severity == "error" and "범위 정보가 없음" in p.message


def test_market_filter_index_range_checked():
    d = _load("new_high_20")
    d["market_filter"] = {"logic": "all", "items": [{
        "left": {"kind": "market", "index": "kospi", "name": "close"}, "op": "gt",
        "right": {"kind": "market", "index": "kospi", "name": "sma", "params": {"n": 20}}}]}
    s = Spec.model_validate(d)  # 기간 2021-01-04~ — 지수 csv 는 2021-07-26 부터
    ranges = {**FULL, "kospi": (D(2021, 7, 26), D(2026, 8, 31))}
    (p,) = validate_against(s, ranges)
    assert p.severity == "warning" and p.dataset == "kospi" and "2021-07-26" in p.message
    (q,) = validate_against(s, FULL)  # 지수 범위를 안 넘기면 조용히 통과하지 않고 error
    assert q.severity == "error" and q.dataset == "kospi"


def test_market_operand_in_entry_condition_also_counts_and_kosdaq_is_separate():
    d = _load("new_high_20")
    d["strategy"]["entry"]["items"].append({
        "left": {"kind": "market", "index": "kosdaq", "name": "change_pct"}, "op": "gt",
        "right": {"kind": "const", "value": -1}})
    s = Spec.model_validate(d)
    probs = validate_against(s, {**FULL, "kospi": (D(2021, 7, 26), D(2026, 8, 31))})
    assert [(p.severity, p.dataset) for p in probs] == [("error", "kosdaq")]


def test_mode_picks_dataset_and_intraday_also_needs_daily():
    s = Spec.model_validate(_load("gap_up_value_top"))  # 분봉 모드
    probs = validate_against(s, {"minute_al": (D(2026, 6, 15), D(2026, 8, 31))})
    kinds = {(p.severity, p.dataset) for p in probs}
    assert kinds == {("warning", "minute_al"), ("error", "daily")}  # 6/1~ 이 6/15 보다 앞 + 일봉 범위 없음
    t = Spec.model_validate(_load("tick_breakout_5m"))
    assert validate_against(t, {"tick_al": (D(2026, 8, 1), D(2026, 8, 31)), "daily": FULL["daily"]}) == []


def test_problem_is_plain_data():
    p = Problem("error", "daily", "x")
    assert (p.severity, p.dataset, p.message) == ("error", "daily", "x")
    assert copy.copy(p) == p


def _intraday(source=None) -> Spec:
    d = _load("gap_up_value_top")
    if source is not None:
        d["intraday"]["source"] = source
    return Spec.model_validate(d)


def test_intraday_source_selects_dataset_key_and_message():
    daily = {"daily": FULL["daily"]}
    al_only = {**daily, "minute_al": (D(2026, 5, 1), D(2026, 8, 31))}
    krx_only = {**daily, "minute_krx": (D(2025, 7, 1), D(2026, 8, 31))}
    assert validate_against(_intraday(), al_only) == []                       # 기본 al → minute_al 을 본다
    assert validate_against(_intraday("krx"), krx_only) == []                 # krx → minute_krx 를 본다
    (p,) = validate_against(_intraday(), krx_only)                            # 출처를 섞지 않는다: al 인데 krx 범위만 있으면 오류
    assert (p.severity, p.dataset) == ("error", "minute_al") and "통합 분봉" in p.message
    (q,) = validate_against(_intraday("krx"), al_only)
    assert (q.severity, q.dataset) == ("error", "minute_krx") and "KRX 분봉" in q.message and "범위 정보가 없음" in q.message


def test_krx_source_range_partial_overlap_warns_with_krx_label():
    ranges = {"daily": FULL["daily"], "minute_krx": (D(2026, 6, 15), D(2026, 8, 31))}   # 기간 2026-06-01~ 이 6/15 보다 앞
    (p,) = validate_against(_intraday("krx"), ranges)
    assert p.severity == "warning" and p.dataset == "minute_krx" and "KRX 분봉" in p.message and "2026-06-15" in p.message
