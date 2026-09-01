import pandas as pd
import pytest

from backtesting.chgtop_leader_persistence import (
    MinuteCloseLookup,
    build_swap_dataset,
    extract_episodes,
    forward_returns,
)

NAME_TO_CODE = {"A": "000001", "B": "000002"}


def _frame(t, chgtop):
    return {"t": t, "chgtop": chgtop}


def test_extract_episodes_merges_consecutive_same_leader():
    frames = [
        _frame("09:01", ["A", 1.0, 0.5]),
        _frame("09:02", ["A", 1.2, 0.5]),
        _frame("09:03", ["B", 2.0, 0.3]),
    ]
    episodes = extract_episodes(frames, "2026-07-01", NAME_TO_CODE)

    assert len(episodes) == 2
    assert episodes[0]["code"] == "000001" and episodes[0]["end_i"] - episodes[0]["start_i"] + 1 == 2
    assert episodes[1]["code"] == "000002" and episodes[1]["start_t"] == "09:03"


def test_extract_episodes_none_gap_splits_same_code_into_two_episodes():
    frames = [
        _frame("09:01", ["A", 1.0, None]),
        _frame("09:02", None),
        _frame("09:03", ["A", 1.0, None]),
    ]
    episodes = extract_episodes(frames, "2026-07-01", NAME_TO_CODE)

    # None 이 사이에 끼면 앞뒤가 같은 코드라도 하나로 안 합친다(연속성 끊김) - 에피소드가
    # None 은 아예 기록 안 하고(코드 있는 것만), A 가 두 번(09:01 / 09:03) 따로 나와야 한다.
    assert [(e["code"], e["start_t"]) for e in episodes] == [("000001", "09:01"), ("000001", "09:03")]


def test_extract_episodes_unmapped_name_produces_no_episode():
    frames = [_frame("09:01", ["unknown-name", 1.0, None])]
    episodes = extract_episodes(frames, "2026-07-01", NAME_TO_CODE)

    assert episodes == []


def test_minute_close_lookup_returns_next_price_within_tolerance(tmp_path):
    d = tmp_path
    p = d / "000001.csv"
    p.write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-01 09:01:00,100,100,100,100,1\n"
        "2026-07-01 09:05:00,110,110,110,110,1\n",
        encoding="utf-8",
    )
    lookup = MinuteCloseLookup(str(d))

    # 09:01:30 에 조회하면 다음 체결(09:05)까지 4분짜리 공백 - MAX_STALE_SEC(300초) 안이라 유효.
    px = lookup.price_at_or_after("000001", pd.Timestamp("2026-07-01 09:01:30"))
    assert px == 110.0


def test_minute_close_lookup_rejects_stale_gap(tmp_path):
    d = tmp_path
    p = d / "000001.csv"
    p.write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-01 09:01:00,100,100,100,100,1\n"
        "2026-07-01 09:20:00,110,110,110,110,1\n",
        encoding="utf-8",
    )
    lookup = MinuteCloseLookup(str(d))

    px = lookup.price_at_or_after("000001", pd.Timestamp("2026-07-01 09:01:30"))
    assert px is None  # 다음 체결까지 300초 넘게 비어 무효 처리돼야 한다


def test_minute_close_lookup_uses_open_not_close_for_the_bar_timestamp(tmp_path):
    """실제 발견(2026-09-01): 이 저장소의 1분봉 행은 구간 *시작* 라벨이라 그 시각의
    가격은 close(구간 끝, ~1분 뒤)가 아니라 open(구간 첫 체결)이어야 한다."""
    p = tmp_path / "000001.csv"
    p.write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-01 09:01:00,175600,178500,173500,173500,30009\n",
        encoding="utf-8",
    )
    lookup = MinuteCloseLookup(str(tmp_path))

    px = lookup.price_at_or_after("000001", pd.Timestamp("2026-07-01 09:01:00"))

    assert px == 175600.0  # open, close(173500)이 아니다


def test_minute_close_lookup_missing_code_returns_none(tmp_path):
    lookup = MinuteCloseLookup(str(tmp_path))
    assert lookup.price_at_or_after("999999", pd.Timestamp("2026-07-01 09:01:00")) is None


def test_build_swap_dataset_lag_shifts_the_reference_timestamp(tmp_path, monkeypatch):
    """실행지연 시뮬레이션(swap_signal_validation.py 재사용) - lag_minutes 만큼
    진입 기준시각이 밀려서 다른(1분 뒤) 봉 가격을 잡아야 한다."""
    frames = [
        {"t": "09:01", "chgtop": ["A", 1.0, None]},
        {"t": "09:02", "chgtop": ["B", 2.0, None]},
    ]
    monkeypatch.setattr("backtesting.chgtop_leader_persistence.load_full_frames", lambda d: frames)

    (tmp_path / "000002.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-01 09:02:00,100,100,100,100,1\n"
        "2026-07-01 09:03:00,200,200,200,200,1\n",
        encoding="utf-8",
    )
    (tmp_path / "000001.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-01 09:02:00,50,50,50,50,1\n"
        "2026-07-01 09:03:00,60,60,60,60,1\n",
        encoding="utf-8",
    )
    lookup = MinuteCloseLookup(str(tmp_path))

    no_lag = build_swap_dataset(["2026-07-01"], {"A": "000001", "B": "000002"}, lookup)
    lagged = build_swap_dataset(["2026-07-01"], {"A": "000001", "B": "000002"}, lookup, lag_minutes=1)

    # lag=0: 진입시각 09:02(B의 09:02봉 open=100) -> lag=1: 09:03(B의 09:03봉 open=200)
    assert no_lag.loc[0, "new_ret_1m"] != lagged.loc[0, "new_ret_1m"]


def test_forward_returns_computes_ratio_against_entry(tmp_path):
    p = tmp_path / "000001.csv"
    p.write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-01 09:01:00,100,100,100,100,1\n"
        "2026-07-01 09:02:00,105,105,105,105,1\n",
        encoding="utf-8",
    )
    lookup = MinuteCloseLookup(str(tmp_path))

    fwd, entry = forward_returns(lookup, "000001", pd.Timestamp("2026-07-01 09:01:00"))

    assert entry == 100.0
    assert fwd["ret_1m"] == pytest.approx(0.05)
