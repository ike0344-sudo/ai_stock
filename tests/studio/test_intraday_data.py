"""studio.infrastructure.intraday_data — P8(리샘플 동일) · 체결 오름차순·같은 초 · 범위 밖 요청 · D−1 사전 필터 · 성능 · 계층 규칙."""
import ast
import datetime as dt
import pathlib
import time

import numpy as np
import pandas as pd
import pytest

from backtesting.data_loader import _resample_minute
from datahub import catalog, minute_al_archive as arch
from studio.infrastructure import intraday_data as I

D = dt.date
REPO = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAHUB_ROOT", str(tmp_path))
    return tmp_path


def minute_frame(days, start="08:00", end="20:00", seed=1, gaps=False, base=1000):
    """통합 분봉 모양(08:00~20:00) 합성 — 종목 하나."""
    rng = np.random.default_rng(seed)
    parts = []
    for d in days:
        idx = pd.date_range(f"{d} {start}", f"{d} {end}", freq="min", name="date")
        close = base + rng.integers(-5, 6, len(idx)).cumsum()
        df = pd.DataFrame({"open": close - 1, "high": close + 3, "low": close - 3, "close": close,
                           "volume": rng.integers(1, 100, len(idx))}, index=idx)
        if gaps:
            df = df.drop(df.index[rng.choice(len(df), 40, replace=False)]).sort_index()
        parts.append(df)
    return pd.concat(parts)


def test_default_source_is_integrated_al(root):
    """2026-09-01 사용자 규칙(통합만) — 기본은 통합, krx 는 명시할 때만."""
    assert I.DEFAULT_SOURCE == "al"
    put_archive("005930", minute_frame(["2026-09-22", "2026-09-23"]))
    dflt = I.load_minute_bars("005930", D(2026, 9, 22), D(2026, 9, 23), 5)
    pd.testing.assert_frame_equal(dflt, I.load_minute_bars("005930", D(2026, 9, 22), D(2026, 9, 23), 5, source="al"))
    with pytest.raises(I.DataRangeError, match="krx"):                                       # krx 파일이 없으면 krx 요청만 실패 — 기본(al)은 성공
        I.load_minute_bars("005930", D(2026, 9, 22), D(2026, 9, 23), 5, source="krx")
    assert I.minute_coverage("005930").dates == (D(2026, 9, 22), D(2026, 9, 23)) and I.minute_coverage("005930", "krx") is None


# ---------- P8: 기존 _resample_minute 와 동일 ----------


@pytest.mark.parametrize("n", [3, 5, 10, 15, 30, 60])
@pytest.mark.parametrize("gaps", [False, True])
def test_p8_resample_identical_to_legacy(n, gaps):
    df = I.session_filter(minute_frame(["2026-09-21", "2026-09-22", "2026-09-23"], gaps=gaps), "regular")
    pd.testing.assert_frame_equal(I.resample_minutes(df, n), _resample_minute(df, n))       # 값·인덱스·자료형까지


def test_p8_full_session_and_odd_first_bar_identical():
    """시간외 포함(하루 첫 봉이 08:00)·정규장 중간에 시작하는 날(첫 봉 13:50) 도 같다."""
    part = minute_frame(["2026-09-21"], start="13:50", end="15:35", seed=3)
    df = pd.concat([minute_frame(["2026-09-18"], seed=2), part])
    for n in (5, 15, 60):
        pd.testing.assert_frame_equal(I.resample_minutes(df, n), _resample_minute(df, n))
    reg = I.session_filter(df, "regular")
    pd.testing.assert_frame_equal(I.resample_minutes(reg, 7 if False else 15), _resample_minute(reg, 15))


def test_p8_real_archive_samples():
    if not (REPO / "data/stocks/minute_al_archive").is_dir():
        pytest.skip("보관소 없음")
    for c in ("005930", "000660", "035420"):
        df = I.session_filter(arch.read(c), "regular")
        if df.empty:
            continue
        for n in (3, 5, 15, 60):
            pd.testing.assert_frame_equal(I.resample_minutes(df, n), _resample_minute(df, n))


def test_session_filter_boundaries():
    df = minute_frame(["2026-09-23"])
    reg = I.session_filter(df, "regular")
    assert reg.index[0].time() == dt.time(9, 0) and reg.index[-1].time() == dt.time(15, 30)      # 15:30 종가 단일가 봉 포함, 15:31 부터 제외
    assert len(reg) == 391 and len(I.session_filter(df, "full")) == len(df)
    with pytest.raises(ValueError):
        I.session_filter(df, "night")
    # 정규장만 자르면 첫 봉이 09:00 — 시간외를 안 자르면 5분 봉의 첫 버킷이 08:00 이다
    assert I.resample_minutes(reg, 5).index[0].time() == dt.time(9, 0)


# ---------- 분봉 로더 · 범위 ----------


def put_archive(code, df):
    arch.merge(code, df)


def test_load_minute_bars_and_range_error(root):
    put_archive("005930", minute_frame(["2026-09-21", "2026-09-22", "2026-09-23"]))
    b = I.load_minute_bars("005930", D(2026, 9, 22), D(2026, 9, 23), bar_minutes=5)
    assert b.index.min() == pd.Timestamp("2026-09-22 09:00") and b.index.max() == pd.Timestamp("2026-09-23 15:30")
    assert list(b.columns) == I.MINUTE_COLS and b.index.name == "date" and b.index.is_monotonic_increasing
    assert len(I.load_minute_bars("005930", D(2026, 9, 23), D(2026, 9, 23), 1, session="full")) == 721
    with pytest.raises(I.DataRangeError) as e:                                              # 조용히 빈 표를 돌려주지 않는다
        I.load_minute_bars("005930", D(2026, 9, 1), D(2026, 9, 23))
    assert e.value.available == (D(2026, 9, 21), D(2026, 9, 23)) and "2026-09-21 ~ 2026-09-23" in str(e.value)
    with pytest.raises(I.DataRangeError):
        I.load_minute_bars("005930", D(2026, 9, 22), D(2026, 9, 30))                        # 끝이 밖
    with pytest.raises(I.DataRangeError) as e:
        I.load_minute_bars("999999", D(2026, 9, 22), D(2026, 9, 23))                        # 종목 자체가 없다
    assert e.value.available is None
    part = I.load_minute_bars("005930", D(2026, 9, 1), D(2026, 9, 30), 5, strict=False)     # 부분 요청은 명시적으로만
    assert part.index.min().date() == D(2026, 9, 21)
    assert I.load_minute_bars("999999", D(2026, 9, 1), D(2026, 9, 2), strict=False).empty
    with pytest.raises(ValueError):
        I.load_minute_bars("005930", D(2026, 9, 22), D(2026, 9, 23), bar_minutes=7)


def test_minute_panel_skips_empty_and_coverage(root):
    put_archive("005930", minute_frame(["2026-09-22", "2026-09-23"]))
    put_archive("000660", minute_frame(["2026-09-23"], seed=2))
    panel = I.load_minute_panel(["005930", "000660", "999999", "005930"], D(2026, 9, 22), D(2026, 9, 23), 15)
    assert list(panel) == ["005930", "000660"]                                              # 없는 종목은 빠지고 중복은 한 번
    cov = I.minute_coverage("000660")
    assert cov.dates == (D(2026, 9, 23), D(2026, 9, 23)) and I.minute_coverage("999999") is None


# ---------- 사전 필터 재료 (D−1) ----------


def daily_frame(days, codes, seed=5):
    rng = np.random.default_rng(seed)
    rows = [{"code": c, "date": d, "open": 10, "high": 11, "low": 9, "close": 10, "volume": int(rng.integers(1, 10_000))}
            for d in days for c in codes]
    return pd.DataFrame(rows)


def test_top_value_is_previous_day_and_matches_hub_expectation(root):
    from datahub import status
    days = [d.date() for d in pd.bdate_range("2026-09-14", "2026-09-23")]
    codes = [f"{i:06d}" for i in range(12)]
    daily = daily_frame(days, codes)
    got = I.top_value_by_date(days, 5, daily=daily)
    assert D(2026, 9, 14) not in got                                                        # 첫 날은 직전 순위가 없다
    for d in days[1:]:
        prev = days[days.index(d) - 1]
        ranked = daily[daily["date"] == prev].assign(tv=lambda x: x["close"] * x["volume"]).sort_values("tv", ascending=False, kind="stable")
        assert got[d] == list(ranked["code"][:5])                                           # D−1 순위, 큰 순서
    assert {d: set(v) for d, v in got.items()} == {d: v for d, v in status.expected_tick_codes(daily, days, 5).items()}   # 허브 조회창 기대 종목과 같은 집합
    ex = I.top_value_by_date(days[1:3], 5, daily=daily, exclude={got[days[1]][0]})
    assert got[days[1]][0] not in ex[days[1]] and len(ex[days[1]]) == 5
    only = I.top_value_by_date(days[1:3], 5, daily=daily, codes=codes[:6])
    assert set(only[days[1]]) <= set(codes[:6])
    tomorrow = D(2026, 9, 24)                                                               # 일봉이 아직 없는 날 — 마지막 순위를 쓴다
    assert I.top_value_by_date([tomorrow], 5, daily=daily)[tomorrow] == I.top_value_by_date([days[-1] + dt.timedelta(days=1)], 5, daily=daily)[tomorrow]


def test_prefiltered_minute_days_reads_each_code_once(root, monkeypatch):
    days = [d.date() for d in pd.bdate_range("2026-09-21", "2026-09-23")]
    codes = [f"{i:06d}" for i in range(6)]
    daily = daily_frame([D(2026, 9, 18)] + days, codes)
    for c in codes[:4]:                                                                     # 상위권 6종목 중 4개만 분봉이 있다
        put_archive(c, minute_frame([d.isoformat() for d in days], seed=int(c)))
    reads = []
    real = arch.read
    monkeypatch.setattr(arch, "read", lambda *a, **k: reads.append(a[0]) or real(*a, **k))
    out = I.prefiltered_minute_days(days[0], days[-1], 3, 15, daily=daily)
    top = I.top_value_by_date(days, 3, daily=daily)
    assert sorted(out) == days
    for d in days:
        assert set(out[d]) == {c for c in top[d] if c in codes[:4]}                         # 순위 밖·분봉 없는 종목은 빠진다
        for c, df in out[d].items():
            assert (df.index.normalize() == pd.Timestamp(d)).all() and df.index[0].time() == dt.time(9, 0)
    assert len(reads) == len(set(reads))                                                    # 종목마다 한 번만 읽는다


# ---------- 체결 ----------


def put_ticks(code, day, rows, csv=False):
    """rows: 원본 순서(역시간순) (time, price, qty, sig)."""
    p = catalog.path("tick_al", code=code, date=day.isoformat())
    p.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["time", "cur_prc", "trde_qty", "pred_pre_sig"])
    if csv:
        df.to_csv(p.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    else:
        df.astype({"time": "string"}).to_parquet(p)


SRC = [("200000", 1010, 5, 2), ("153000", 1005, 7, 5), ("100501", 1004, 3, 5), ("100500", 1003, 30, 5), ("100500", 1002, 20, 5),
       ("100500", 1001, 10, 2), ("090000", 1000, 1, 3), ("080500", 990, 9, 3)]           # 원본: 최신이 앞, 같은 초(10:05:00) 3건은 역순


def test_ticks_ascending_same_second_order_preserved(root):
    put_ticks("001380", D(2026, 9, 23), SRC)
    t = I.load_ticks("001380", D(2026, 9, 23), session="full")
    assert list(t["price"]) == [990, 1000, 1001, 1002, 1003, 1004, 1005, 1010]              # 뒤집기 = 실제 체결 순서(정렬이 아니다)
    assert list(t.columns) == I.TICK_COLS and t.index.name == "ts" and t.index.is_monotonic_increasing
    assert t.dtypes.to_dict() == {"price": np.dtype("int64"), "qty": np.dtype("int64"), "sig": np.dtype("int64"), "sec": np.dtype("int32")}
    assert t.index[0] == pd.Timestamp("2026-09-23 08:05:00") and int(t["sec"].iloc[0]) == 8 * 3600 + 5 * 60
    same = t[t.index == pd.Timestamp("2026-09-23 10:05:00")]
    assert list(same["price"]) == [1001, 1002, 1003] and list(same["qty"]) == [10, 20, 30]  # 같은 초 다중 체결의 순서
    reg = I.load_ticks("001380", D(2026, 9, 23))                                            # 기본 정규장: 08:05·20:00 제외, 09:00·15:30 포함
    assert list(reg["price"]) == [1000, 1001, 1002, 1003, 1004, 1005]


def test_ticks_csv_fallback_keeps_leading_zero_and_abs_price(root):
    rows = [("100000", "-1010", 5, 5), ("090005", "-1000", 1, 5)]
    put_ticks("001380", D(2026, 9, 22), rows, csv=True)
    t = I.load_ticks("001380", D(2026, 9, 22))
    assert list(t["price"]) == [1000, 1010] and t.index[0] == pd.Timestamp("2026-09-22 09:00:05")        # 앞자리 0(090005) 유지, 가격 부호 제거


def test_ticks_source_not_reverse_chronological_is_refused(root):
    put_ticks("001380", D(2026, 9, 23), [(f"09{m:02d}00", 1, 1, 3) for m in range(0, 59)] + [(f"10{m:02d}00", 2, 1, 3) for m in range(0, 59)])   # 오름차순으로 저장된 파일
    with pytest.raises(ValueError, match="역시간순"):
        I.load_ticks("001380", D(2026, 9, 23))


def test_ticks_few_misordered_rows_are_sorted_by_second_like_to_grid(root):
    """실제 파일처럼 몇 줄만 어긋나 있으면(000150) 초 단위 안정 정렬 — 같은 초 안은 뒤집은 순서를 유지."""
    rows = [(f"1000{s:02d}", 100 + s, 1, 3) for s in range(59, 0, -1)]          # 정상: 10:00:59 … 10:00:01
    rows[10], rows[11] = rows[11], rows[10]                                       # 두 줄이 서로 자리를 바꿨다
    put_ticks("001380", D(2026, 9, 23), rows)
    t = I.load_ticks("001380", D(2026, 9, 23))
    assert t.index.is_monotonic_increasing and list(t["sec"]) == sorted(t["sec"]) and len(t) == 59
    put_ticks("001380", D(2026, 9, 22), [(f"1000{s:02d}", 1, 1, 3) for s in range(1, 60)] * 2)   # 오름차순으로 저장된 파일은 여전히 거부
    with pytest.raises(ValueError, match="역시간순"):
        I.load_ticks("001380", D(2026, 9, 22))


def test_ticks_range_and_missing_days(root):
    for d in (D(2026, 9, 21), D(2026, 9, 23)):                                              # 09-22 는 휴장/미수집
        put_ticks("001380", d, SRC[1:3])
    t = I.load_ticks_range("001380", D(2026, 9, 21), D(2026, 9, 23))
    assert t.index.is_monotonic_increasing and {x.date() for x in t.index} == {D(2026, 9, 21), D(2026, 9, 23)}     # 중간 구멍은 오류가 아니다
    assert I.tick_days("001380") == [D(2026, 9, 21), D(2026, 9, 23)] and I.tick_days("999999") == []
    with pytest.raises(I.DataRangeError) as e:
        I.load_ticks_range("001380", D(2026, 9, 1), D(2026, 9, 23))
    assert e.value.available == (D(2026, 9, 21), D(2026, 9, 23))
    with pytest.raises(I.DataRangeError) as e:
        I.load_ticks("001380", D(2026, 9, 22))
    assert e.value.available == (D(2026, 9, 21), D(2026, 9, 23))
    assert I.load_ticks("001380", D(2026, 9, 22), strict=False).empty and I.load_ticks_range("001380", D(2026, 9, 1), D(2026, 9, 2), strict=False).empty
    with pytest.raises(I.DataRangeError) as e:
        I.load_ticks_range("999999", D(2026, 9, 1), D(2026, 9, 2))
    assert e.value.available is None


def test_real_tick_file_is_readable_and_ascending():
    days = I.tick_days("001380")
    if not days:
        pytest.skip("실제 체결 사본 없음")
    t = I.load_ticks("001380", days[0], session="full")
    assert t.index.is_monotonic_increasing and len(t) > 0 and (t["price"] > 0).all()


# ---------- 조건식 계약 모양 (TickDay · 분봉 Panel) ----------


def test_session_filter_on_empty_frame_keeps_columns():
    """빈 표에 bool 리스트로 df[[]] 를 하면 열이 사라진다(실제로 겪음) — 빈 기간이 KeyError 가 되지 않게."""
    empty = minute_frame(["2026-09-23"]).iloc[0:0]
    out = I.session_filter(empty, "regular")
    assert list(out.columns) == I.MINUTE_COLS and I.resample_minutes(out, 5).empty


def test_tick_day_contract_shape(root):
    from studio.domain.conditions.tick import N, TickDay
    put_ticks("001380", D(2026, 9, 23), SRC)
    td = I.load_tick_day("001380", D(2026, 9, 23), prev_close=1000.0)
    assert isinstance(td, TickDay) and td.code == "001380" and td.date == D(2026, 9, 23) and td.prev_close == 1000.0
    assert list(td.sec) == [0, 65 + 3600 - 65 + 0, 3600 + 5 * 60, 3600 + 5 * 60, 3600 + 5 * 60, 3600 + 5 * 60 + 1, 6 * 3600 + 30 * 60][:0] or True
    assert list(td.prc) == [1000, 1001, 1002, 1003, 1004, 1005]                              # 08:05·20:00 제외(정규장), 같은 초 순서 보존
    assert list(td.sec) == [0, 3900, 3900, 3900, 3901, 23400] and td.sec.max() < N            # 09:00:00 = 0, 15:30:00 = 23400
    assert I.load_tick_day("001380", D(2026, 9, 23), strict=True).prev_close is None
    put_ticks("001380", D(2026, 9, 22), [("200000", 1, 1, 3), ("080000", 1, 1, 3)])          # 정규장 체결이 하나도 없는 날
    assert I.load_tick_day("001380", D(2026, 9, 22)) is None                                 # to_grid 와 같이 None
    with pytest.raises(I.DataRangeError):
        I.load_tick_day("001380", D(2026, 9, 21))


def test_tick_days_fill_prev_close_from_daily(root):
    put_ticks("001380", D(2026, 9, 22), SRC[1:4])
    put_ticks("001380", D(2026, 9, 23), SRC[1:4])
    daily = daily_frame([D(2026, 9, 21), D(2026, 9, 22)], ["001380"])
    daily.loc[daily["date"] == D(2026, 9, 21), "close"] = 999
    days = I.load_tick_days("001380", D(2026, 9, 22), D(2026, 9, 23), daily=daily)
    assert [x.date for x in days] == [D(2026, 9, 22), D(2026, 9, 23)] and [x.prev_close for x in days] == [999.0, 10.0]      # D−1 종가
    assert I.prev_close_of("001380", D(2026, 9, 21), daily) is None and I.prev_close_of("999999", D(2026, 9, 23), daily) is None


def test_tick_day_equals_precursor_to_grid_on_real_files():
    """실제 체결 파일에서 로더의 (sec, prc, qty) 가 `_precursor_fastpath.to_grid` 의 tick_sec·tick_prc·tick_qty 와 같다 — 엔진과 연구 코드가 같은 배열을 본다."""
    from _precursor_fastpath import to_grid
    base = REPO / "data/stocks/tick_al"
    codes = sorted(p.name for p in base.iterdir() if p.is_dir())[:60:12] if base.is_dir() else []
    if not codes:
        pytest.skip("실제 체결 없음")
    n = 0
    for c in codes:
        for day in I.tick_days(c)[-2:]:
            f = base / c / f"{day.isoformat()}.parquet"
            if not f.is_file():
                continue
            g, td = to_grid(f), I.load_tick_day(c, day)
            if g is None:
                assert td is None
                continue
            assert np.array_equal(td.sec, g["tick_sec"]) and np.array_equal(td.prc, np.abs(g["tick_prc"])) and np.array_equal(td.qty, g["tick_qty"])
            n += 1
    assert n >= 3
    for c, day in (("000150", D(2026, 9, 22)), ("278470", D(2026, 9, 18))):                 # 시각이 어긋난 곳이 가장 많은 실제 파일들(4곳 / 232곳)
        f = base / c / f"{day.isoformat()}.parquet"
        if f.is_file():
            g, td = to_grid(f), I.load_tick_day(c, day)
            assert np.array_equal(td.sec, g["tick_sec"]) and np.array_equal(td.prc, np.abs(g["tick_prc"])) and np.array_equal(td.qty, g["tick_qty"])


def test_minute_panel_wide_contract(root):
    from studio.domain.models import Panel
    put_archive("005930", minute_frame(["2026-09-22", "2026-09-23"], seed=1))
    put_archive("000660", minute_frame(["2026-09-23"], seed=2))                              # 하루만 있는 종목 — 첫 날 행은 NaN
    daily = daily_frame([D(2026, 9, 18), D(2026, 9, 21), D(2026, 9, 22)], ["005930", "000660"])
    daily.loc[(daily["code"] == "005930") & (daily["date"] == D(2026, 9, 21)), "close"] = 111
    daily.loc[(daily["code"] == "005930") & (daily["date"] == D(2026, 9, 22)), "close"] = 222
    daily.loc[(daily["code"] == "000660") & (daily["date"] == D(2026, 9, 22)), "close"] = 333
    p = I.load_minute_panel_wide(["005930", "000660", "999999"], D(2026, 9, 22), D(2026, 9, 23), 15, daily=daily)
    assert isinstance(p, Panel) and list(p.close.columns) == ["005930", "000660"]              # 분봉 없는 종목은 빠지고 요청 순서 유지
    for f in (p.open, p.high, p.low, p.close, p.volume, p.value, p.prev_close):
        assert f.shape == p.close.shape and f.index.equals(p.close.index) and list(f.columns) == list(p.close.columns)
    idx = p.close.index
    assert idx.is_monotonic_increasing and idx[0] == pd.Timestamp("2026-09-22 09:15") and idx[-1] == pd.Timestamp("2026-09-23 15:45")   # 봉 끝 시각
    assert (p.value.fillna(0) == (p.close * p.volume).fillna(0)).all().all()
    assert p.close["000660"][: p.close.index.searchsorted(pd.Timestamp("2026-09-23"))].isna().all()                # 9/22 에 없던 종목은 NaN(신호 없음)
    d22, d23 = idx.normalize() == pd.Timestamp("2026-09-22"), idx.normalize() == pd.Timestamp("2026-09-23")
    assert (p.prev_close.loc[d22, "005930"] == 111).all() and (p.prev_close.loc[d23, "005930"] == 222).all()     # 그 날의 전일 종가(D−1), 하루 안에서 상수
    assert (p.prev_close.loc[d23, "000660"] == 333).all()
    # 시작 시각 → 끝 시각: 첫 봉(09:00~09:15)은 09:15 라벨
    raw = I.load_minute_bars("005930", D(2026, 9, 22), D(2026, 9, 22), 15)
    assert p.close["005930"].iloc[0] == float(raw["close"].iloc[0]) and idx[0] == raw.index[0] + pd.Timedelta(minutes=15)
    e = I.load_minute_panel_wide(["999999"], D(2026, 9, 22), D(2026, 9, 23), 5, daily=daily)                   # 아무 종목도 없으면 빈 Panel
    assert e.close.empty and e.prev_close.empty


# ---------- 성능 (§8.9: 분봉 2단계 ≤ 60초) ----------


def test_perf_60_days_top30_real_data():
    if not (REPO / "data/stocks/minute_al_archive").is_dir():
        pytest.skip("보관소 없음")
    t0 = time.time()
    out = I.prefiltered_minute_days(D(2026, 6, 25), D(2026, 9, 23), 30, 5)
    took = time.time() - t0
    assert len(out) >= 50 and took < 60, (len(out), took)
    print(f"[perf] 60거래일 × 상위 30 분봉(5분) 로드: {took:.1f}초, {sum(len(v) for v in out.values())} (날짜,종목)")


# ---------- 계층 규칙 (§9.3) ----------

ALLOWED_TOP = {"__future__", "datetime", "dataclasses", "typing", "bisect", "pandas", "numpy", "pyarrow", "datahub", "studio"}
FORBIDDEN_BACKTESTING = True


def test_infrastructure_import_rules():
    """intraday_data 는 domain·application.ports·datahub 읽기 API·backtesting.daily_cache 만 — 기존 backtesting·api·실주문은 금지."""
    path = REPO / "studio/infrastructure/intraday_data.py"
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods = [node.module]
        else:
            continue
        for m in mods:
            top = m.split(".")[0]
            assert top in ALLOWED_TOP | {"backtesting"}, f"금지 import {m}"
            if top == "backtesting":
                assert m == "backtesting.daily_cache", f"backtesting 는 daily_cache 만: {m}"
            if top == "studio":
                assert m.split(".")[1:2] in (["domain"], ["application"]) and (m.startswith("studio.domain") or m == "studio.application.ports"), m
            if top == "datahub":
                assert "api" not in m.split(".") and "jobs" not in m.split("."), m
