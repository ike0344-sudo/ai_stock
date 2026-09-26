"""분봉 출처 krx(기본) | al — 같은 모양 · P8 · 범위 오류 · 파일 신선도 규칙 · 기간 표. (통합 보관소 쪽 테스트는 test_intraday_data.py)"""
import datetime as dt
import os
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


@pytest.fixture(autouse=True)
def _krx_selected(monkeypatch):
    """이 파일은 사용자가 krx 를 고른 경우를 시험한다 — 기본 출처(al)는 test_intraday_data.py 가 확인한다."""
    monkeypatch.setattr(I, "DEFAULT_SOURCE", "krx")


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAHUB_ROOT", str(tmp_path))
    return tmp_path


def krx_day(day, seed=1, base=1000, after_hours=False):
    """KRX 분봉 모양: 09:00~15:19 매분 + 15:30(종가 단일가) + 15:35(소량) [+ NXT 애프터 16:00~19:59]."""
    rng = np.random.default_rng(seed)
    idx = list(pd.date_range(f"{day} 09:00", f"{day} 15:19", freq="min"))
    idx += [pd.Timestamp(f"{day} 15:30"), pd.Timestamp(f"{day} 15:35")]
    if after_hours:
        idx += list(pd.date_range(f"{day} 16:00", f"{day} 19:59", freq="min"))
    close = base + rng.integers(-5, 6, len(idx)).cumsum()
    return pd.DataFrame({"open": close - 1, "high": close + 3, "low": close - 3, "close": close,
                         "volume": rng.integers(1, 100, len(idx))}, index=pd.DatetimeIndex(idx, name="date"))


def put_krx(code, df, parquet=False, mtime=None):
    p = catalog.path("minute_krx", code=code)
    p.parent.mkdir(parents=True, exist_ok=True)
    if parquet:
        df.to_parquet(p.with_suffix(".parquet"))
    else:
        df.to_csv(p)
    if mtime is not None:
        os.utime(p.with_suffix(".parquet") if parquet else p, (mtime, mtime))


def al_day(day, seed=1, base=1000):
    idx = pd.date_range(f"{day} 08:00", f"{day} 19:59", freq="min", name="date")
    close = base + np.random.default_rng(seed).integers(-5, 6, len(idx)).cumsum()
    return pd.DataFrame({"open": close - 1, "high": close + 3, "low": close - 3, "close": close, "volume": 5}, index=idx)


def test_krx_selected_and_shapes_match(root):
    days = ["2026-09-21", "2026-09-22", "2026-09-23"]
    put_krx("005930", pd.concat([krx_day(d, i) for i, d in enumerate(days)]))
    arch.merge("005930", pd.concat([al_day(d, i) for i, d in enumerate(days)]))
    assert I.DEFAULT_SOURCE == "krx"                                                        # (이 파일의 fixture 가 고른 상태)
    k = I.load_minute_bars("005930", D(2026, 9, 21), D(2026, 9, 23), 5)
    k2 = I.load_minute_bars("005930", D(2026, 9, 21), D(2026, 9, 23), 5, source="krx")
    a = I.load_minute_bars("005930", D(2026, 9, 21), D(2026, 9, 23), 5, source="al")
    pd.testing.assert_frame_equal(k, k2)
    for f in (k, a):                                                                        # 두 출처가 같은 모양
        assert list(f.columns) == I.MINUTE_COLS and f.index.name == "date" and f.index.is_monotonic_increasing
        assert f.index[0].time() == dt.time(9, 0) and f.index[-1].time() == dt.time(15, 30)   # 정규장(15:35·시간외 제외)
    assert list(I.load_minute_bars("005930", D(2026, 9, 23), D(2026, 9, 23), 1).columns) == I.MINUTE_COLS
    assert len(I.load_minute_bars("005930", D(2026, 9, 23), D(2026, 9, 23), 1)) == 381       # 09:00~15:19 380봉 + 15:30 종가 단일가 = 381 (15:35 제외)
    p = I.load_minute_panel_wide(["005930"], D(2026, 9, 22), D(2026, 9, 23), 15, daily=pd.DataFrame(
        {"code": ["005930"] * 2, "date": [D(2026, 9, 21), D(2026, 9, 22)], "close": [10, 20], "volume": [1, 1], "open": 1, "high": 1, "low": 1}))
    assert list(p.close.columns) == ["005930"] and p.close.index[0] == pd.Timestamp("2026-09-22 09:15")     # Panel 도 같은 계약(끝 시각 라벨)
    pa = I.load_minute_panel_wide(["005930"], D(2026, 9, 22), D(2026, 9, 23), 15, source="al", daily=pd.DataFrame(
        {"code": ["005930"] * 2, "date": [D(2026, 9, 21), D(2026, 9, 22)], "close": [10, 20], "volume": [1, 1], "open": 1, "high": 1, "low": 1}))
    assert type(pa) is type(p) and list(pa.close.columns) == list(p.close.columns)


@pytest.mark.parametrize("n", [3, 5, 10, 15, 30, 60])
def test_krx_p8_identical_to_legacy_resample(root, n):
    put_krx("005930", pd.concat([krx_day(d, i, after_hours=(i == 2)) for i, d in enumerate(["2026-09-21", "2026-09-22", "2026-09-23"])]))
    got = I.load_minute_bars("005930", D(2026, 9, 21), D(2026, 9, 23), n, source="krx")
    full = pd.read_csv(catalog.path("minute_krx", code="005930"), index_col=0, parse_dates=True)
    reg = I.session_filter(full, "regular")                                                  # 정규장만 자른 뒤 기존 함수와 비교
    want = _resample_minute(reg, n)[I.MINUTE_COLS]
    want.index = want.index.astype("datetime64[ns]")                                          # CSV 파싱은 pandas 버전에 따라 [us] — 로더는 [ns] 로 고정(보관소와 같게)
    pd.testing.assert_frame_equal(got, want)


def test_krx_session_full_is_refused_and_after_hours_bars_dropped(root):
    put_krx("005930", krx_day("2026-09-23", after_hours=True))
    b = I.load_minute_bars("005930", D(2026, 9, 23), D(2026, 9, 23))
    assert b.index.max() == pd.Timestamp("2026-09-23 15:30") and 16 not in set(b.index.hour)     # 15:35 · NXT 애프터 봉 제외
    with pytest.raises(ValueError, match="krx"):
        I.load_minute_bars("005930", D(2026, 9, 23), D(2026, 9, 23), session="full")
    assert len(I.load_minute_bars("005930", D(2026, 9, 23), D(2026, 9, 23), session="full", source="al", strict=False)) == 0   # al 은 full 허용(보관소엔 없어 빈 표)
    with pytest.raises(ValueError):
        I.load_minute_bars("005930", D(2026, 9, 23), D(2026, 9, 23), source="nxt")


def test_range_error_mentions_source_and_available(root):
    put_krx("005930", pd.concat([krx_day("2026-09-22"), krx_day("2026-09-23")]))
    with pytest.raises(I.DataRangeError) as e:
        I.load_minute_bars("005930", D(2026, 9, 1), D(2026, 9, 23))
    assert e.value.available == (D(2026, 9, 22), D(2026, 9, 23)) and "krx" in str(e.value)
    with pytest.raises(I.DataRangeError) as e:
        I.load_minute_bars("999999", D(2026, 9, 22), D(2026, 9, 23))
    assert e.value.available is None
    with pytest.raises(I.DataRangeError):
        I.load_minute_bars("005930", D(2026, 9, 22), D(2026, 9, 23), source="al")           # krx 에 있어도 al 에 없으면 오류(출처를 섞지 않는다)
    part = I.load_minute_bars("005930", D(2026, 9, 1), D(2026, 9, 30), 5, strict=False)
    assert part.index.min().date() == D(2026, 9, 22)
    assert I.load_minute_bars("999999", D(2026, 9, 1), D(2026, 9, 2), strict=False).empty


def test_krx_parquet_used_only_when_not_older_than_csv(root):
    """갱신기는 CSV 에만 쓴다 — parquet 이 더 오래됐으면 낡은 사본이라 CSV 를 읽는다."""
    old = krx_day("2026-09-22")
    new = pd.concat([krx_day("2026-09-22"), krx_day("2026-09-23", seed=2)])
    now = time.time()
    put_krx("005930", new, mtime=now)                                                        # CSV: 이틀치, 최신
    put_krx("005930", old, parquet=True, mtime=now - 3600)                                   # parquet: 하루치, 낡음
    assert I.minute_coverage("005930").dates == (D(2026, 9, 22), D(2026, 9, 23))
    assert I.load_minute_bars("005930", D(2026, 9, 22), D(2026, 9, 23)).index.max().date() == D(2026, 9, 23)
    os.utime(catalog.path("minute_krx", code="005930").with_suffix(".parquet"), (now + 10, now + 10))   # parquet 이 더 새것
    assert I.minute_coverage("005930").dates == (D(2026, 9, 22), D(2026, 9, 22))
    put_krx("000660", krx_day("2026-09-23"), parquet=True)                                   # parquet 만 있는 종목
    assert I.minute_coverage("000660").dates == (D(2026, 9, 23), D(2026, 9, 23))
    assert I.load_minute_bars("000660", D(2026, 9, 23), D(2026, 9, 23)).index.dtype == "datetime64[ns]"


def test_unsorted_and_duplicated_csv_is_normalized(root):
    d = krx_day("2026-09-23")
    messy = pd.concat([d.iloc[::-1], d.iloc[:5].assign(close=999)])                          # 역순 + 앞 5행 중복(뒤가 이김)
    put_krx("005930", messy)
    b = I.load_minute_bars("005930", D(2026, 9, 23), D(2026, 9, 23))
    assert b.index.is_monotonic_increasing and b.index.is_unique and len(b) == 381 and (b["close"].iloc[:5] == 999).all()


def test_availability_tables_and_source_summary(root):
    put_krx("005930", pd.concat([krx_day("2026-09-01"), krx_day("2026-09-22"), krx_day("2026-09-23")]))
    put_krx("000660", krx_day("2026-09-23"))
    arch.merge("005930", al_day("2026-09-22"))
    arch.merge("035420", al_day("2026-09-22"))
    k = I.minute_availability("krx")
    assert list(k.index) == ["000660", "005930"] and list(k.columns) == ["first", "last"]
    assert k.loc["005930"].tolist() == [D(2026, 9, 1), D(2026, 9, 23)] and k.loc["000660"].tolist() == [D(2026, 9, 23), D(2026, 9, 23)]
    a = I.minute_availability("al")
    assert list(a.index) == ["005930", "035420"] and a.loc["005930", "first"] == D(2026, 9, 22)
    assert I.minute_availability("krx", codes=["005930", "999999"]).index.tolist() == ["005930"]
    s = I.minute_sources_for_range(D(2026, 9, 1), D(2026, 9, 23))
    assert s == {"krx": {"total": 2, "full": 1, "partial": 1}, "al": {"total": 2, "full": 0, "partial": 2}}
    assert I.minute_sources_for_range(D(2026, 9, 22), D(2026, 9, 22))["al"] == {"total": 2, "full": 2, "partial": 0}
    assert I.minute_availability("krx", codes=[]).empty and I.minute_coverage("999999") is None and I.minute_coverage("999999", "al") is None


def test_prefiltered_days_krx_source(root):
    days = [d.date() for d in pd.bdate_range("2026-09-21", "2026-09-23")]
    codes = [f"{i:06d}" for i in range(4)]
    rng = np.random.default_rng(3)
    daily = pd.DataFrame([{"code": c, "date": d, "open": 1, "high": 1, "low": 1, "close": 10, "volume": int(rng.integers(1, 999))}
                          for d in [D(2026, 9, 18)] + days for c in codes])
    for i, c in enumerate(codes):
        put_krx(c, pd.concat([krx_day(d.isoformat(), i) for d in days]))
    out = I.prefiltered_minute_days(days[0], days[-1], 2, 15, daily=daily)                   # source 생략 = krx
    assert sorted(out) == days and all(len(v) == 2 for v in out.values())
    for d, v in out.items():
        for df in v.values():
            assert df.index[0].time() == dt.time(9, 0) and (df.index.normalize() == pd.Timestamp(d)).all()


# ---------- 실제 데이터 (있을 때만) ----------


def test_real_krx_long_history_and_source_relation():
    if not (REPO / "data/stocks/minute").is_dir():
        pytest.skip("KRX 분봉 없음")
    cov = I.minute_coverage("005930")
    assert cov and cov.dates[0] <= D(2025, 7, 15) and cov.dates[1] >= D(2026, 9, 1)
    t0 = time.time()
    b = I.load_minute_bars("005930", D(2025, 8, 1), D(2026, 8, 31), 5)
    assert len(b) > 20000 and b.index.min().time() == dt.time(9, 0) and time.time() - t0 < 10
    s = I.minute_sources_for_range(D(2025, 8, 14), D(2026, 9, 1))
    assert s["krx"]["full"] > 400 and s["al"]["full"] < s["krx"]["full"]                     # 긴 과거는 krx 가 훨씬 많이 덮는다


def test_real_two_sources_same_closing_auction_and_wider_al_range():
    """같은 종목·같은 분에서: 15:30 종가 단일가 봉은 두 출처가 동일, 통합의 고가·저가 범위가 KRX 를 감싼다(NXT 체결분)."""
    if not (REPO / "data/stocks/minute_al_archive/005930.parquet").is_file() or not (REPO / "data/stocks/minute/005930.csv").is_file():
        pytest.skip("두 출처 없음")
    a = I.load_minute_bars("005930", D(2026, 8, 25), D(2026, 9, 23), 1, source="al", strict=False)
    k = I.load_minute_bars("005930", D(2026, 8, 25), D(2026, 9, 23), 1, source="krx", strict=False)
    j = k.join(a, how="inner", lsuffix="_k", rsuffix="_a")
    assert len(j) > 5000
    close_bar = j[j.index.strftime("%H:%M") == "15:30"]
    assert len(close_bar) >= 15 and (close_bar["volume_k"] == close_bar["volume_a"]).all()
    assert (j["high_a"] >= j["high_k"]).all() and (j["low_a"] <= j["low_k"]).all()
    assert 0.5 < j["volume_k"].sum() / j["volume_a"].sum() < 0.95                             # NXT 체결이 빠져 KRX 거래량이 작다
