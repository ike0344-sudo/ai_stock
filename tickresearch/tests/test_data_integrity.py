"""무결성 검사 테스트 — 검사기가 실제로 문제를 잡는지 확인한다.

검사기가 아무것도 못 잡으면 검사를 안 하는 것과 같으므로, **일부러 망가진 데이터를
만들어 잡히는지**를 본다.
"""
import polars as pl

from src.data.integrity import check_frame
from src.data.ingest import normalize
from src.data.schema import SIDE_UNKNOWN


def _good():
    raw = pl.DataFrame({"time": ["090003", "090002", "090001"],
                        "cur_prc": [102, 101, 100], "trde_qty": [10, 10, 10],
                        "pred_pre_sig": [2, 2, 2]})
    return normalize(raw, "005930", "2026-08-04", 99)


def test_clean_frame_has_no_issues():
    assert check_frame(_good(), "005930", "2026-08-04") == []


def test_detects_empty():
    issues = check_frame(_good().head(0), "005930", "2026-08-04")
    assert any(i["kind"] == "empty" and i["fatal"] for i in issues)


def test_detects_unsorted_timestamp():
    bad = _good().reverse()                      # 시간 역순으로 뒤집어 놓는다
    issues = check_frame(bad, "005930", "2026-08-04")
    assert any(i["kind"] == "timestamp_not_sorted" and i["fatal"] for i in issues)


def test_detects_trade_value_mismatch():
    bad = _good().with_columns(pl.lit(1).alias("trade_value"))
    issues = check_frame(bad, "005930", "2026-08-04")
    assert any(i["kind"] == "trade_value_mismatch" and i["fatal"] for i in issues)


def test_detects_date_mismatch():
    """파일명 날짜와 데이터 날짜가 다르면 경계일 절단 사고다 — 반드시 잡아야 한다."""
    issues = check_frame(_good(), "005930", "2026-08-05")
    assert any(i["kind"] == "date_mismatch" and i["fatal"] for i in issues)


def test_detects_nonpositive_price():
    bad = _good().with_columns(pl.lit(0).alias("price"))
    issues = check_frame(bad, "005930", "2026-08-04")
    assert any(i["kind"] == "nonpositive_price" and i["fatal"] for i in issues)


def test_detects_all_unknown_side():
    bad = _good().with_columns(pl.lit(SIDE_UNKNOWN).alias("side"))
    issues = check_frame(bad, "005930", "2026-08-04")
    assert any(i["kind"] == "side_all_unknown" for i in issues)


def test_detects_missing_ref_price():
    bad = _good().with_columns(pl.lit(None, dtype=pl.Int64).alias("ref_price"))
    issues = check_frame(bad, "005930", "2026-08-04")
    assert any(i["kind"] == "missing_ref_price" for i in issues)
