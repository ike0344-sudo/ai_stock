"""로더 테스트 — 정규장 필터 기본값과 시간순 보장을 고정한다."""
import polars as pl
import pytest

from src.data.ingest import ingest_file
from src.data.loader import available, load_stock_day, scan


def _make(tmp_path, symbol="005930", date="2026-08-04"):
    src = tmp_path / "raw" / symbol / f"{date}.parquet"
    src.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"time": ["160000", "153000", "090000", "083000"],   # 역순
                  "cur_prc": [103, 102, 101, 100], "trde_qty": [1, 2, 3, 4],
                  "pred_pre_sig": [2] * 4}).write_parquet(src)
    ingest_file(src, tmp_path / "proc")
    return tmp_path / "proc"


def test_regular_only_is_the_default(tmp_path):
    """시간외 혼입 사고를 막기 위해 안전한 쪽이 기본값이어야 한다."""
    root = _make(tmp_path)

    assert len(load_stock_day(root, "005930", "2026-08-04")) == 2            # 정규장만
    assert len(load_stock_day(root, "005930", "2026-08-04", regular_only=False)) == 4


def test_sorted_by_seq(tmp_path):
    root = _make(tmp_path)
    df = load_stock_day(root, "005930", "2026-08-04", regular_only=False)
    assert df["seq"].is_sorted() and df["price"].to_list() == [100, 101, 102, 103]


def test_available_lists_symbol_dates(tmp_path):
    root = _make(tmp_path)
    av = available(root)
    assert av.to_dicts() == [{"symbol": "005930", "date": "2026-08-04"}]


def test_scan_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan(tmp_path / "nope")
