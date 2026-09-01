"""일봉 캐시 — 낡은 캐시를 조용히 쓰는 것이 이 모듈의 유일한 위험이라 거기만 조인다."""
import time

import pandas as pd

from backtesting.daily_cache import load_daily_all


def _write(dir_, code, close):
    p = dir_ / f"{code}.csv"
    p.write_text(f"date,open,high,low,close,volume\n2026-01-02,1,1,1,{close},10\n", encoding="utf-8")
    return p


def test_합친다_그리고_code_컬럼이_붙는다(tmp_path):
    d = tmp_path / "daily"; d.mkdir()
    _write(d, "005930", 100); _write(d, "000660", 200)
    df = load_daily_all(str(d), str(tmp_path / "c.parquet"))
    assert sorted(df["code"]) == ["000660", "005930"]
    assert sorted(df["close"]) == [100, 200]


def test_원본이_바뀌면_캐시를_다시_만든다(tmp_path):
    """이게 깨지면 낡은 값으로 백테스트가 돌아도 아무도 모른다."""
    d = tmp_path / "daily"; d.mkdir()
    cache = str(tmp_path / "c.parquet")
    _write(d, "005930", 100)
    assert load_daily_all(str(d), cache)["close"].iloc[0] == 100

    time.sleep(0.01)                      # mtime 해상도가 낮은 파일시스템 대비
    _write(d, "005930", 999)              # 원본만 갱신
    assert load_daily_all(str(d), cache)["close"].iloc[0] == 999


def test_새_종목이_생겨도_잡는다(tmp_path):
    d = tmp_path / "daily"; d.mkdir()
    cache = str(tmp_path / "c.parquet")
    _write(d, "005930", 100)
    load_daily_all(str(d), cache)

    time.sleep(0.01)
    _write(d, "000660", 200)
    assert len(load_daily_all(str(d), cache)) == 2
