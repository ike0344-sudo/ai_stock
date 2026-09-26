"""틱 모드 B 병목 최적화 — 빠른 체결 읽기(`_fast_tick_day`)·색인 D-1 종가(`_prev_close`)가 공식 로더와 **같은 결과**인지.

합성 파일로 규칙(뒤집기·역시간 검사·같은 초 순서·정규장 필터·폴백)을, 실데이터로 공식 로더(`intraday_data.load_tick_day`)와 배열 동일을 확인한다.
"""
import datetime as dt
import glob
import os
import random

import numpy as np
import pandas as pd
import pytest

from studio.infrastructure import intraday_data as I
from studio.infrastructure.market_data import _FALLBACK, LocalMarketData, _fast_tick_day

DAY = dt.date(2026, 9, 22)


def write_ticks(root, code, rows, day=DAY):
    """rows: [(time 'HHMMSS', price, qty)] **원본 순서(역시간순)** 그대로."""
    d = root / "data" / "stocks" / "tick_al" / code
    d.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({"time": [r[0] for r in rows], "cur_prc": [r[1] for r in rows], "trde_qty": [r[2] for r in rows],
                       "pred_pre_sig": 2})
    df.to_parquet(d / f"{day.isoformat()}.parquet", index=False)


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAHUB_ROOT", str(tmp_path))
    return tmp_path


def same(a, b):
    if a is None or b is None:
        return a is b
    return (all(np.array_equal(x, y) and x.dtype == y.dtype for x, y in ((a.sec, b.sec), (a.prc, b.prc), (a.qty, b.qty)))
            and a.prev_close == b.prev_close and a.code == b.code and a.date == b.date)


def test_fast_equals_official_on_synthetic_files(root):
    # 원본은 역시간순: 뒤집으면 시간순. 같은 초(09:00:02)에 3건 — 뒤집은 순서(실제 체결 순서)가 보존돼야 한다. 08:59(장전)·15:31(장후)은 제외.
    rows = [("153100", 111, 1), ("153000", 110, 5), ("100000", 109, 2), ("090002", 108, 3), ("090002", 107, 4),
            ("090002", 106, 5), ("090000", 105, 6), ("085959", 104, 7)]
    write_ticks(root, "111111", rows)
    a = _fast_tick_day("111111", DAY, 100.0)
    b = I.load_tick_day("111111", DAY, 100.0, strict=False)
    assert a is not _FALLBACK and same(a, b)
    assert list(a.prc) == [105, 106, 107, 108, 109, 110] and list(a.sec) == [0, 2, 2, 2, 3600, 23400]  # 같은 초 순서 보존, 장전·장후 제외
    # 부호(전일 대비 등락 표시)가 붙은 가격·체결량은 절댓값
    write_ticks(root, "222222", [("100000", -500, -3), ("090000", 500, 3)])
    assert same(_fast_tick_day("222222", DAY, None), I.load_tick_day("222222", DAY, None, strict=False))


def test_disordered_rows_are_stably_sorted_like_official(root):
    # 시각이 어긋난 줄이 몇 개(기준 max(5행, 5%) 이하) — 초 단위 안정 정렬(같은 초는 뒤집은 순서 유지)
    n = 200
    times = [f"{9 + (n - i) // 100:02d}{((n - i) % 100) // 2:02d}{(n - i) % 2 * 30:02d}" for i in range(n)]  # 역시간순
    rows = [(t, 1000 + i, 1 + i % 7) for i, t in enumerate(times)]
    rows[50], rows[51] = rows[51], rows[50]  # 어긋남 1곳
    rows[120], rows[122] = rows[122], rows[120]
    write_ticks(root, "333333", rows)
    a = _fast_tick_day("333333", DAY, 5.0)
    assert a is not _FALLBACK and same(a, I.load_tick_day("333333", DAY, 5.0, strict=False))
    assert np.all(np.diff(a.sec) >= 0)


def test_fallback_cases_defer_to_official_loader(root):
    assert _fast_tick_day("444444", DAY, None) is _FALLBACK  # 파일 없음
    ascending = [("090000", 1, 1)] + [(f"09{m:02d}00", 1 + m, 1) for m in range(1, 40)]  # 오름차순 저장 — 역시간순 가정이 깨짐
    write_ticks(root, "555555", ascending)
    assert _fast_tick_day("555555", DAY, None) is _FALLBACK  # 공식 로더가 ValueError 로 거부하도록 넘김
    with pytest.raises(ValueError, match="역시간순이 아니다"):
        I.load_tick_day("555555", DAY, None, strict=False)
    write_ticks(root, "666666", [("085000", 1, 1)])  # 정규장 체결이 하나도 없음 → None (공식과 같음)
    assert _fast_tick_day("666666", DAY, None) is None and I.load_tick_day("666666", DAY, None, strict=False) is None
    # csv 원본(압축 전)은 빠른 길이 안 다루고 공식 로더로
    d = root / "data" / "stocks" / "tick_al" / "777777"
    d.mkdir(parents=True)
    pd.DataFrame({"time": ["090001", "090000"], "cur_prc": [2, 1], "trde_qty": [1, 1], "pred_pre_sig": [2, 2]}).to_csv(
        d / f"{DAY.isoformat()}.csv", index=False)
    assert _fast_tick_day("777777", DAY, None) is _FALLBACK


REAL = sorted(glob.glob("data/stocks/tick_al/*/*.parquet"))


@pytest.mark.parity
@pytest.mark.skipif(not REAL or not os.path.exists("data/cache/daily_all.parquet"), reason="실데이터 없음")
def test_real_files_fast_reader_and_prev_close_equal_official():
    md = LocalMarketData()
    daily = md._all_daily()
    files = random.Random(7).sample(REAL, 150)
    # 시각 어긋남이 많다고 알려진 파일(data-agent 실측)도 넣는다
    files += [f for f in REAL if f.replace("\\", "/").endswith(("000150/2026-09-22.parquet", "278470/2026-09-18.parquet"))]
    n_fast = 0
    for f in files:
        parts = f.replace("\\", "/").split("/")
        code, day = parts[-2], dt.date.fromisoformat(parts[-1][:10])
        prev = md._prev_close(code, day)
        assert prev == I.prev_close_of(code, day, daily), (code, day)
        a = _fast_tick_day(code, day, prev)
        if a is _FALLBACK:
            continue
        n_fast += 1
        assert same(a, I.load_tick_day(code, day, prev, strict=False)), f
    assert n_fast >= len(files) * 0.95  # 폴백이 많으면 최적화가 공허하다
    # 일봉이 없는 종목·이전 날이 없는 날
    assert md._prev_close("ZZZZZZ", dt.date(2026, 9, 1)) is None == I.prev_close_of("ZZZZZZ", dt.date(2026, 9, 1), daily)
    assert md._prev_close("000020", dt.date(2019, 4, 23)) is None
