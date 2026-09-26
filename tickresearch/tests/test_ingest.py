"""Phase 1 변환 모듈 테스트.

핵심은 **원본이 시간 역순**이라는 사실을 제대로 뒤집는지, 그리고 side가 추정임을
명확히 표시하는지다. 선행 연구에서 같은 초 안의 순서를 잘못 잡아 45.7%가 틀렸던
사고가 있어 그 지점을 집중적으로 고정한다.
"""
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.data.ingest import ingest_file, normalize, read_ref_price
from src.data.schema import (SESSION_POST, SESSION_PRE, SESSION_REGULAR, SIDE_BUY,
                              SIDE_SELL, SIDE_SOURCE_TICK_RULE, SIDE_UNKNOWN, validate_schema)


def _raw(times, prices, vols=None):
    """원본 관례 그대로: **시간 역순**으로 넣는다."""
    vols = vols or [10] * len(times)
    return pl.DataFrame({"time": times, "cur_prc": prices, "trde_qty": vols,
                         "pred_pre_sig": [2] * len(times)}).reverse()


def test_reverses_raw_into_time_order():
    """원본이 역순이므로 변환 결과는 시간 오름차순이어야 한다."""
    raw = _raw(["090001", "090002", "090003"], [100, 101, 102])
    assert raw["time"][0] == "090003"            # 원본은 역순임을 확인

    out = normalize(raw, "005930", "2026-08-04", 99)

    assert out["timestamp"].is_sorted()
    assert out["price"].to_list() == [100, 101, 102]
    assert out["seq"].to_list() == [0, 1, 2]


def test_same_second_order_is_preserved():
    """같은 초 안에 여러 체결이 있어도 순서가 보존돼야 한다(45.7% 사고 재발 방지)."""
    raw = _raw(["090000", "090000", "090000"], [100, 200, 300])

    out = normalize(raw, "005930", "2026-08-04", 99)

    assert out["price"].to_list() == [100, 200, 300]   # 뒤집힌 채로 남으면 [300,200,100]
    assert out["seq"].to_list() == [0, 1, 2]


def test_tick_rule_side_and_source_marked_as_estimate():
    """상승=BUY, 하락=SELL, 보합=직전계승, 첫 체결=UNKNOWN. 추정임을 반드시 표시."""
    raw = _raw(["090001", "090002", "090003", "090004"], [100, 105, 105, 99])

    out = normalize(raw, "005930", "2026-08-04", 100)

    assert out["side"].to_list() == [SIDE_UNKNOWN, SIDE_BUY, SIDE_BUY, SIDE_SELL]
    assert out["side_source"].unique().to_list() == [SIDE_SOURCE_TICK_RULE]


def test_session_tagged_but_nothing_dropped():
    """정규장 밖도 버리지 않고 표시만 한다 — 자르는 건 소비하는 쪽 책임."""
    raw = _raw(["083000", "090000", "153000", "160000"], [100, 101, 102, 103])

    out = normalize(raw, "005930", "2026-08-04", 100)

    assert len(out) == 4                          # 하나도 안 버렸다
    assert out["session"].to_list() == [SESSION_PRE, SESSION_REGULAR, SESSION_REGULAR, SESSION_POST]


def test_trade_value_and_schema():
    raw = _raw(["090001", "090002"], [1000, 2000], [3, 4])

    out = normalize(raw, "005930", "2026-08-04", 999)

    assert out["trade_value"].to_list() == [3000, 8000]
    assert out["ref_price"].unique().to_list() == [999]
    validate_schema(out)


def test_missing_required_column_raises():
    """원본 스키마가 바뀌면 조용히 틀린 결과를 내지 말고 바로 죽어야 한다."""
    bad = pl.DataFrame({"time": ["090001"], "cur_prc": [100]})   # trde_qty 없음

    with pytest.raises(ValueError, match="원본 컬럼 누락"):
        normalize(bad, "005930", "2026-08-04", 100)


def test_ref_price_read_from_metadata(tmp_path):
    """실측 확인: 원본 파일 메타데이터의 ref_price가 전일 종가다(일봉과 8/8 일치)."""
    src = tmp_path / "005930" / "2026-08-04.parquet"
    src.parent.mkdir(parents=True)
    tbl = pa.table({"time": ["090001"], "cur_prc": [100], "trde_qty": [5], "pred_pre_sig": [2]})
    pq.write_table(tbl.replace_schema_metadata({b"ref_price": b"98000"}), src)

    assert read_ref_price(src) == 98000

    r = ingest_file(src, tmp_path / "out")
    assert r["rows"] == 1 and r["ref_price"] == 98000


def test_ingest_file_skips_existing_unless_overwrite(tmp_path):
    src = tmp_path / "005930" / "2026-08-04.parquet"
    src.parent.mkdir(parents=True)
    _raw(["090001"], [100]).write_parquet(src)
    out = tmp_path / "out"

    assert ingest_file(src, out)["skipped"] is False
    assert ingest_file(src, out)["skipped"] is True
    assert ingest_file(src, out, overwrite=True)["skipped"] is False


def test_handles_out_of_order_raw_page_boundary():
    """[회귀] 실측 발견(2026-09-24): 원본이 완벽한 역순이 아니다.

    24,144행 중 2곳에서 역순이 깨져 있었다(간격 5,700 → API 페이지 경계로 추정).
    `reverse()`만 하면 결과가 시간순이 아니게 되어 이후 모든 창 집계가 틀어진다.
    뒤집은 뒤 **안정 정렬**까지 해야 한다.
    """
    # 역순인데 한 곳이 어긋나 있다 (090030 → 090031, 앞이 더 작다)
    raw = pl.DataFrame({"time": ["090050", "090030", "090031", "090010"],
                        "cur_prc": [104, 102, 103, 101], "trde_qty": [10] * 4,
                        "pred_pre_sig": [2] * 4})

    out = normalize(raw, "005930", "2026-08-04", 100)

    assert out["timestamp"].is_sorted(), "역순 위반이 있는 원본을 시간순으로 못 폈다"
    assert out["price"].to_list() == [101, 102, 103, 104]
    assert out["seq"].to_list() == [0, 1, 2, 3]


def test_stable_sort_preserves_same_second_order_after_fix():
    """정렬을 넣어도 같은 초 안의 순서는 보존돼야 한다(불안정 정렬이면 깨진다)."""
    raw = pl.DataFrame({"time": ["090000", "090000", "090000", "090000"],
                        "cur_prc": [400, 300, 200, 100], "trde_qty": [1, 2, 3, 4],
                        "pred_pre_sig": [2] * 4})   # 역순 → 뒤집으면 100,200,300,400

    out = normalize(raw, "005930", "2026-08-04", 100)

    assert out["price"].to_list() == [100, 200, 300, 400]
